"""POST /api/v1/observe + GET /api/v1/scene-graph (PR-6).

This module is the server-side counterpart of the
``kernelcal.distinction_game.geometry`` superquadric pipeline.  An
upstream producer (typically the **earth_rover** running on a Pixhawk
PX4 / Velodyne VLP-16 / MicaSense Altum / OceanOptics UV-VIS-NIR /
USB3 Coral TPU stack) emits packed superquadric bytes via
:func:`kernelcal.distinction_game.geometry.codec.pack_superquadric`,
batches them into a single payload, and POSTs them here.

The endpoint:

1. Parses an envelope describing the producer frame
   (:class:`kernelcal.distinction_game.geometry.FrameSpec`) and the
   payload byte length.
2. Decodes each superquadric packet
   (:func:`kernelcal.distinction_game.geometry.codec.unpack_superquadric`).
3. Transforms each SQ pose from the producer frame to **ECEF** (the
   canonical server-side frame) via
   :func:`kernelcal.distinction_game.geometry.transform_superquadric`.
4. Computes an axis-aligned WGS84 bbox of the centroids for fast
   spatial filtering.
5. Persists the raw payload + the decoded ECEF view as an
   :class:`deepgis_xr.apps.web.models.Observation`.
6. Returns an ack with ingest stats.

The companion ``GET /api/v1/scene-graph`` endpoint pulls the most
recent observations whose centroids intersect a user-supplied bbox,
optionally re-projects them into a requested frame
(WGS84-LLA / ECEF / UTM / ENU local), and returns either a JSON
SceneGraph view or a re-packed binary blob for ultra-low-bandwidth
clients.

Frame negotiation
-----------------
Both endpoints accept a frame in JSON form
``{"kind": "...", "params": {...}}`` matching :meth:`FrameSpec.to_dict`.
Allowed ``kind`` values (per the kernelcal frame registry):
``wgs84_lla``, ``ecef``, ``utm``, ``enu_local``, ``ned_local``.

Error contract
--------------
* 400 -- envelope missing required fields, frame invalid, payload
  size mismatch, or bbox malformed.
* 401 -- unauthenticated when the deployment requires login.
* 413 -- payload exceeds :data:`MAX_OBSERVATION_BYTES`.
* 415 -- unsupported content type.
* 422 -- payload bytes failed to decode as superquadric packets.

All success responses are ``application/json`` with a stable
``status`` field (``"ok"`` on success).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from deepgis_xr.apps.web.models import Observation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration knobs (settings overrides allowed)
# ---------------------------------------------------------------------------

#: Hard upper bound on POST body size.  At 100 SQs/window with the full
#: 147-byte appearance trailer this is ~14.7 kB; we allow a generous 4 MB
#: to accommodate batch replays.  Tunable via
#: ``DEEPGIS_MAX_OBSERVATION_BYTES`` in Django settings.
MAX_OBSERVATION_BYTES: int = int(
    getattr(settings, "DEEPGIS_MAX_OBSERVATION_BYTES", 4 * 1024 * 1024)
)

#: Default cap on superquadrics returned by ``GET /api/v1/scene-graph``
#: when the client does not supply ``limit``.
DEFAULT_SCENE_GRAPH_LIMIT: int = 1000

#: Hard cap on superquadrics returned by ``GET /api/v1/scene-graph``.
MAX_SCENE_GRAPH_LIMIT: int = 10_000


# ---------------------------------------------------------------------------
# Helpers: lazy kernelcal imports + envelope parsing
# ---------------------------------------------------------------------------


def _import_kernelcal_geometry():
    """Lazy import to keep Django boot fast and to avoid coupling the
    web layer to kernelcal at import time (eases test isolation)."""
    from kernelcal.distinction_game.geometry import (  # noqa: PLC0415
        FrameSpec,
        Superquadric,
        ecef_to_geodetic,
        pack_superquadric,
        packed_size,
        transform_superquadric,
        unpack_superquadric,
    )

    return {
        "FrameSpec": FrameSpec,
        "Superquadric": Superquadric,
        "ecef_to_geodetic": ecef_to_geodetic,
        "pack_superquadric": pack_superquadric,
        "packed_size": packed_size,
        "transform_superquadric": transform_superquadric,
        "unpack_superquadric": unpack_superquadric,
    }


#: The kernelcal codec quantizes translation as int32 millimetres,
#: which gives a +/- 2,147,483 m (~2,000 km) range per axis.  Producers
#: that pack in a frame whose origin is far from the SQ centroids
#: (e.g. raw UTM with northing ~3.7e6 m) will silently clip on the
#: wire.  We reject any frame whose unpacked SQ falls outside this
#: band on the server so the operator sees the misuse explicitly.
_MAX_LOCAL_TRANSLATION_M: float = 2_100_000.0


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"status": "error", "message": msg}, status=status)


def _parse_envelope(request) -> Tuple[Dict[str, Any], bytes]:
    """Return ``(envelope_dict, payload_bytes)`` for a POST /observe call.

    Two transports are supported:

    * ``Content-Type: application/json`` -- the body is a single JSON
      object with a base64 payload field (``payload_b64``).
    * ``Content-Type: application/octet-stream`` -- the JSON envelope
      lives in the ``X-Observation-Envelope`` header and the body is
      the raw bytes.

    The latter is what the earth_rover ROS2 publisher will use because
    base64 inflates a tight 30-120 kbps link by 33 %.
    """
    ctype = (request.content_type or "").lower()
    if "application/octet-stream" in ctype:
        env_header = request.META.get("HTTP_X_OBSERVATION_ENVELOPE")
        if not env_header:
            raise ValueError(
                "octet-stream POST requires X-Observation-Envelope header"
            )
        try:
            envelope = json.loads(env_header)
        except json.JSONDecodeError as exc:
            raise ValueError(f"X-Observation-Envelope is not valid JSON: {exc}")
        payload = bytes(request.body or b"")
        return envelope, payload

    if "application/json" in ctype:
        try:
            envelope = json.loads(request.body or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"request body is not valid JSON: {exc}")
        b64 = envelope.pop("payload_b64", "")
        try:
            payload = base64.b64decode(b64) if b64 else b""
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError(f"payload_b64 is not valid base64: {exc}")
        return envelope, payload

    raise ValueError(
        f"unsupported content_type {ctype!r}; "
        f"use application/json or application/octet-stream"
    )


def _validate_envelope(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(envelope, Mapping):
        raise ValueError("envelope must be a JSON object")
    out: Dict[str, Any] = {}
    out["source_id"] = str(envelope.get("source_id") or "").strip()
    if not out["source_id"]:
        raise ValueError("envelope.source_id is required")
    out["session_id"] = str(envelope.get("session_id") or out["source_id"])
    out["frame"] = envelope.get("frame") or {}
    if not isinstance(out["frame"], Mapping) or "kind" not in out["frame"]:
        raise ValueError(
            "envelope.frame must be a FrameSpec dict (e.g. "
            "{'kind': 'utm', 'params': {'zone': 12, 'hemisphere': 'N'}})"
        )
    ts_raw = envelope.get("sensor_timestamp")
    if ts_raw:
        ts = parse_datetime(str(ts_raw))
        if ts is None:
            raise ValueError(
                "envelope.sensor_timestamp must be ISO-8601 if provided"
            )
        out["sensor_timestamp"] = ts
    else:
        out["sensor_timestamp"] = None
    out["n_superquadrics"] = int(envelope.get("n_superquadrics") or 0)
    out["payload_size"] = int(envelope.get("payload_size") or 0)
    attrs = envelope.get("attributes") or {}
    if not isinstance(attrs, Mapping):
        raise ValueError("envelope.attributes must be a JSON object")
    out["attributes"] = dict(attrs)
    return out


# ---------------------------------------------------------------------------
# Payload decoding + ECEF re-expression
# ---------------------------------------------------------------------------


def _decode_payload(payload: bytes, geom: Mapping[str, Any]) -> List[Tuple[Any, Dict[str, Any]]]:
    """Walk the payload buffer, decoding consecutive packed SQs.

    Returns a list of ``(Superquadric, meta)`` tuples in the order they
    appear on the wire.  Raises ``ValueError`` if any packet fails to
    decode -- partial ingestion is rejected to keep the stream
    auditable.
    """
    unpack = geom["unpack_superquadric"]
    out: List[Tuple[Any, Dict[str, Any]]] = []
    cursor = 0
    n = len(payload)
    while cursor < n:
        try:
            sq, meta = unpack(payload[cursor:])
        except Exception as exc:
            raise ValueError(
                f"failed to decode SQ at byte offset {cursor}/{n}: {exc}"
            )
        consumed = int(meta.get("bytes_consumed", 0))
        if consumed <= 0:
            raise ValueError(
                f"unpack_superquadric reported bytes_consumed={consumed} "
                f"at offset {cursor}"
            )
        out.append((sq, meta))
        cursor += consumed
    return out


def _superquadric_to_server_view(
    sq: Any,
    meta: Mapping[str, Any],
    *,
    geom: Mapping[str, Any],
    src_frame: Any,
) -> Dict[str, Any]:
    """Return a JSON-friendly server-side view of an SQ in ECEF."""
    ecef_frame = geom["FrameSpec"].ecef()
    sq_ecef = geom["transform_superquadric"](sq, src_frame, ecef_frame)
    view: Dict[str, Any] = {
        "id": sq_ecef.id,
        "class_idx": int(meta.get("class_idx", 0)),
        "t_ecef": [float(x) for x in sq_ecef.t.tolist()],
        "R": [[float(x) for x in row] for row in sq_ecef.R.tolist()],
        "scale": [float(x) for x in sq_ecef.scale.tolist()],
        "epsilon": [float(x) for x in sq_ecef.epsilon.tolist()],
    }
    if sq_ecef.parent_id is not None:
        view["parent_id"] = sq_ecef.parent_id
    parent_hash = meta.get("parent_hash")
    if parent_hash is not None:
        view["parent_hash"] = int(parent_hash)
    properties = meta.get("properties")
    if properties:
        view["properties"] = {
            (k.name if hasattr(k, "name") else str(k)): float(v)
            for k, v in dict(properties).items()
        }
    spectrum = meta.get("spectrum")
    if spectrum is not None:
        view["spectrum"] = {
            "n_samples": int(getattr(spectrum, "n_samples", 0)),
            "lambda_lo_nm": float(getattr(spectrum, "lambda_lo_nm", 0.0)),
            "lambda_hi_nm": float(getattr(spectrum, "lambda_hi_nm", 0.0)),
            "n_channels": int(getattr(spectrum, "n_channels", 0)),
            "quality_score": float(getattr(spectrum, "quality_score", 0.0)),
        }
    return view


def _bbox_wgs84_for(views: Iterable[Mapping[str, Any]], geom: Mapping[str, Any]) -> Dict[str, float]:
    """Compute an axis-aligned WGS84 bbox over a list of ECEF views."""
    points = np.array(
        [v["t_ecef"] for v in views if "t_ecef" in v],
        dtype=float,
    )
    if points.size == 0:
        return {}
    lla = geom["ecef_to_geodetic"](points)
    if lla.ndim == 1:
        lla = lla.reshape(1, 3)
    return {
        "lat_min": float(lla[:, 0].min()),
        "lat_max": float(lla[:, 0].max()),
        "lon_min": float(lla[:, 1].min()),
        "lon_max": float(lla[:, 1].max()),
        "alt_min": float(lla[:, 2].min()),
        "alt_max": float(lla[:, 2].max()),
    }


# ---------------------------------------------------------------------------
# POST /api/v1/observe
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
def post_observation(request) -> JsonResponse:
    """Ingest a packed-superquadric payload from a streaming client."""
    try:
        envelope, payload = _parse_envelope(request)
    except ValueError as exc:
        return _err(str(exc), status=400)

    try:
        env = _validate_envelope(envelope)
    except ValueError as exc:
        return _err(str(exc), status=400)

    if len(payload) > MAX_OBSERVATION_BYTES:
        return _err(
            f"payload too large: {len(payload)} > {MAX_OBSERVATION_BYTES}",
            status=413,
        )
    if env["payload_size"] and env["payload_size"] != len(payload):
        return _err(
            f"payload_size mismatch: envelope={env['payload_size']} bytes != "
            f"received={len(payload)} bytes",
            status=400,
        )

    geom = _import_kernelcal_geometry()
    try:
        src_frame = geom["FrameSpec"].from_dict(env["frame"])
    except Exception as exc:
        return _err(f"invalid frame: {exc}", status=400)

    try:
        decoded = _decode_payload(payload, geom)
    except ValueError as exc:
        return _err(str(exc), status=422)

    if (
        env["n_superquadrics"]
        and env["n_superquadrics"] != len(decoded)
    ):
        return _err(
            f"n_superquadrics mismatch: envelope={env['n_superquadrics']} != "
            f"decoded={len(decoded)}",
            status=400,
        )

    server_views: List[Dict[str, Any]] = []
    for sq, meta in decoded:
        # Reject obvious wire-budget abuse: any SQ that decoded to a
        # translation near the codec's int32 mm clip is almost
        # certainly the result of packing in a frame with an offset
        # too far from the centroid (e.g. raw UTM).  Producers should
        # use enu_local at a station origin instead.
        if (
            float(abs(sq.t).max() if sq.t.size else 0.0)
            > _MAX_LOCAL_TRANSLATION_M
        ):
            return _err(
                f"SQ {sq.id!r} translation exceeds codec budget "
                f"(|t|_inf > {_MAX_LOCAL_TRANSLATION_M:.0f} m); the "
                f"producer should pack in an ENU local frame at a "
                f"station origin instead of {src_frame.kind!r}.",
                status=422,
            )
        try:
            server_views.append(
                _superquadric_to_server_view(
                    sq, meta, geom=geom, src_frame=src_frame
                )
            )
        except Exception as exc:
            log.exception("transform_superquadric failed: %s", exc)
            return _err(
                f"frame transform failed for SQ {sq.id!r}: {exc}",
                status=422,
            )

    bbox = _bbox_wgs84_for(server_views, geom)

    user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
    obs = Observation.objects.create(
        session_id=env["session_id"],
        source_id=env["source_id"],
        user=user,
        sensor_timestamp=env["sensor_timestamp"],
        n_superquadrics=len(decoded),
        src_frame=dict(env["frame"]),
        bbox_wgs84=bbox,
        payload=bytes(payload),
        payload_size=len(payload),
        superquadrics_ecef=server_views,
        attributes=env["attributes"],
    )

    return JsonResponse(
        {
            "status": "ok",
            "observation_id": obs.id,
            "received_at": obs.received_at.isoformat(),
            "n_superquadrics": int(obs.n_superquadrics),
            "bbox_wgs84": bbox,
            "src_frame": dict(env["frame"]),
        },
        status=201,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/scene-graph
# ---------------------------------------------------------------------------


def _parse_bbox(raw: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    if not raw:
        return None
    try:
        parts = [float(p) for p in raw.split(",")]
    except ValueError as exc:
        raise ValueError(f"bbox is not a comma-separated float list: {exc}")
    if len(parts) != 4:
        raise ValueError(
            "bbox must be 'lon_min,lat_min,lon_max,lat_max' (4 floats)"
        )
    lon_min, lat_min, lon_max, lat_max = parts
    if lon_min >= lon_max or lat_min >= lat_max:
        raise ValueError("bbox must satisfy lon_min<lon_max and lat_min<lat_max")
    if not (-180.0 <= lon_min <= 180.0 and -180.0 <= lon_max <= 180.0):
        raise ValueError("bbox longitudes must be in [-180, 180]")
    if not (-90.0 <= lat_min <= 90.0 and -90.0 <= lat_max <= 90.0):
        raise ValueError("bbox latitudes must be in [-90, 90]")
    return lon_min, lat_min, lon_max, lat_max


def _parse_frame_query(raw: Optional[str], geom: Mapping[str, Any]) -> Any:
    """Accept either a JSON FrameSpec or a compact shorthand.

    Shorthand examples:

    * ``wgs84_lla``
    * ``ecef``
    * ``utm:12N`` or ``utm:54S``
    * ``enu_local:33.42,-111.94,350``
    """
    FrameSpec = geom["FrameSpec"]
    if not raw:
        return FrameSpec.wgs84_lla()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, Mapping):
            return FrameSpec.from_dict(parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    raw = raw.strip()
    if raw == "wgs84_lla":
        return FrameSpec.wgs84_lla()
    if raw == "ecef":
        return FrameSpec.ecef()
    if raw.startswith("utm:"):
        body = raw.split(":", 1)[1]
        if body[-1] in ("N", "S"):
            zone = int(body[:-1])
            hemi = body[-1]
        else:
            zone = int(body)
            hemi = "N"
        return FrameSpec.utm(zone=zone, hemisphere=hemi)
    if raw.startswith("enu_local:"):
        body = raw.split(":", 1)[1]
        triple = [float(c) for c in body.split(",")]
        if len(triple) != 3:
            raise ValueError(
                "enu_local frame requires lat,lon,alt as 3 comma-separated floats"
            )
        return FrameSpec.enu_local(origin_lla=tuple(triple))
    raise ValueError(f"unrecognised frame shorthand: {raw!r}")


def _filter_observations_in_bbox(
    bbox: Tuple[float, float, float, float],
    *,
    source_ids: Optional[List[str]] = None,
    since: Optional[Any] = None,
    max_observations: int = 64,
) -> List[Observation]:
    lon_min, lat_min, lon_max, lat_max = bbox
    qs = Observation.objects.all()
    if source_ids:
        qs = qs.filter(source_id__in=source_ids)
    if since is not None:
        qs = qs.filter(received_at__gte=since)
    qs = qs.order_by("-received_at")
    out: List[Observation] = []
    # Iterate; observations without a bbox (n_superquadrics=0) are
    # skipped.  We accept the python-side filter because Django's
    # JSONField doesn't have a portable bbox-overlap operator.
    for obs in qs.iterator(chunk_size=128):
        b = obs.bbox_wgs84 or {}
        if not b:
            continue
        if (
            b.get("lon_max", -181.0) < lon_min
            or b.get("lon_min", 181.0) > lon_max
            or b.get("lat_max", -91.0) < lat_min
            or b.get("lat_min", 91.0) > lat_max
        ):
            continue
        out.append(obs)
        if len(out) >= max_observations:
            break
    return out


def _gather_sqs_in_bbox(
    obs_list: Iterable[Observation],
    bbox: Tuple[float, float, float, float],
    *,
    geom: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Collect SQ server-views from a list of observations whose centroids
    fall inside ``bbox`` (WGS84).

    Uses the persisted ECEF view + ECEF -> LLA conversion to filter
    centroid by centroid.  Multiple observations may report the same
    SQ id; we keep the *most recent* observation's view per id.
    """
    lon_min, lat_min, lon_max, lat_max = bbox
    seen: Dict[str, Dict[str, Any]] = {}
    ecef_to_geo = geom["ecef_to_geodetic"]
    for obs in obs_list:  # already ordered newest -> oldest
        for view in obs.superquadrics_ecef or []:
            t_ecef = view.get("t_ecef")
            if not t_ecef or len(t_ecef) != 3:
                continue
            lla = ecef_to_geo(np.array(t_ecef, dtype=float))
            lat, lon, _ = lla
            if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
                continue
            sid = str(view.get("id") or f"obs{obs.id}-{len(seen)}")
            if sid in seen:
                continue
            enriched = dict(view)
            enriched["observation_id"] = obs.id
            enriched["source_id"] = obs.source_id
            enriched["received_at"] = obs.received_at.isoformat()
            seen[sid] = enriched
    return list(seen.values())


def _reproject_view(
    view: Mapping[str, Any],
    *,
    dst_frame: Any,
    geom: Mapping[str, Any],
) -> Dict[str, Any]:
    """Re-express an ECEF view in ``dst_frame``."""
    Superquadric = geom["Superquadric"]
    ecef_frame = geom["FrameSpec"].ecef()
    sq = Superquadric(
        scale=np.array(view["scale"], dtype=float),
        epsilon=np.array(view["epsilon"], dtype=float),
        R=np.array(view["R"], dtype=float),
        t=np.array(view["t_ecef"], dtype=float),
        id=str(view.get("id") or "sq"),
        parent_id=view.get("parent_id"),
    )
    sq_dst = geom["transform_superquadric"](sq, ecef_frame, dst_frame)
    out = dict(view)
    out.pop("t_ecef", None)
    out["t"] = [float(x) for x in sq_dst.t.tolist()]
    out["R"] = [[float(x) for x in row] for row in sq_dst.R.tolist()]
    out["frame"] = dst_frame.to_dict()
    return out


@csrf_exempt
@require_GET
def get_scene_graph(request) -> HttpResponse:
    """Publish fused superquadrics within a bbox, in a chosen frame.

    Query parameters
    ----------------
    bbox:
        ``lon_min,lat_min,lon_max,lat_max`` (WGS84, required).
    frame:
        Destination frame (default ``wgs84_lla``).  Accepts JSON
        FrameSpec or shorthand (see :func:`_parse_frame_query`).
    sources:
        Optional comma-separated ``source_id`` filter.
    since:
        Optional ISO-8601 timestamp; only observations received after
        this are considered.
    limit:
        Cap on returned superquadrics
        (default :data:`DEFAULT_SCENE_GRAPH_LIMIT`,
        max :data:`MAX_SCENE_GRAPH_LIMIT`).
    format:
        ``json`` (default) or ``binary``.  The binary form re-packs
        each SQ via :func:`pack_superquadric` and concatenates -- the
        same wire format the earth_rover speaks for ``POST /observe``,
        which lets the same client codec be used in both directions.
    """
    geom = _import_kernelcal_geometry()

    # -- bbox
    try:
        bbox = _parse_bbox(request.GET.get("bbox"))
    except ValueError as exc:
        return _err(str(exc), status=400)
    if bbox is None:
        return _err("bbox query parameter is required", status=400)

    # -- frame
    try:
        dst_frame = _parse_frame_query(request.GET.get("frame"), geom)
    except Exception as exc:
        return _err(f"invalid frame: {exc}", status=400)

    # -- sources
    sources_raw = request.GET.get("sources") or ""
    source_ids = [s.strip() for s in sources_raw.split(",") if s.strip()] or None

    # -- since
    since_raw = request.GET.get("since")
    since = None
    if since_raw:
        since = parse_datetime(since_raw)
        if since is None:
            return _err("since must be ISO-8601", status=400)

    # -- limit
    try:
        limit = int(request.GET.get("limit") or DEFAULT_SCENE_GRAPH_LIMIT)
    except ValueError:
        return _err("limit must be an integer", status=400)
    limit = max(1, min(limit, MAX_SCENE_GRAPH_LIMIT))

    # -- format
    fmt = (request.GET.get("format") or "json").lower()
    if fmt not in ("json", "binary"):
        return _err("format must be 'json' or 'binary'", status=400)

    obs_list = _filter_observations_in_bbox(
        bbox, source_ids=source_ids, since=since, max_observations=512
    )
    sqs = _gather_sqs_in_bbox(obs_list, bbox, geom=geom)
    sqs = sqs[:limit]

    if fmt == "binary":
        out_bytes = bytearray()
        Superquadric = geom["Superquadric"]
        ecef_frame = geom["FrameSpec"].ecef()
        for view in sqs:
            sq = Superquadric(
                scale=np.array(view["scale"], dtype=float),
                epsilon=np.array(view["epsilon"], dtype=float),
                R=np.array(view["R"], dtype=float),
                t=np.array(view["t_ecef"], dtype=float),
                id=str(view.get("id") or "sq"),
                parent_id=view.get("parent_id"),
            )
            sq_dst = geom["transform_superquadric"](sq, ecef_frame, dst_frame)
            parent_hash: Optional[int] = view.get("parent_hash")
            if parent_hash is None and view.get("parent_id"):
                # Recompute a stable 63-bit hash so receivers can do
                # data-association without a global id table.
                parent_hash = hash(str(view["parent_id"])) & 0x7FFFFFFFFFFFFFFF
            out_bytes += geom["pack_superquadric"](
                sq_dst,
                class_idx=int(view.get("class_idx", 0)),
                parent_hash=parent_hash,
            )
        resp = HttpResponse(bytes(out_bytes), content_type="application/octet-stream")
        resp["X-SceneGraph-Count"] = str(len(sqs))
        resp["X-SceneGraph-Frame"] = json.dumps(dst_frame.to_dict())
        return resp

    payload = {
        "status": "ok",
        "frame": dst_frame.to_dict(),
        "bbox_wgs84": {
            "lon_min": bbox[0],
            "lat_min": bbox[1],
            "lon_max": bbox[2],
            "lat_max": bbox[3],
        },
        "n_observations": len(obs_list),
        "n_superquadrics": len(sqs),
        "superquadrics": [
            _reproject_view(v, dst_frame=dst_frame, geom=geom) for v in sqs
        ],
        "generated_at": timezone.now().isoformat(),
    }
    return JsonResponse(payload)
