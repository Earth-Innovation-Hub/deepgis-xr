"""
Live vehicle poses for the viewers' follow mode (the AI pilot's follow_vehicle).

A vehicle's publisher (for the OpenUAV PX4 twin, dreams_llm_bridge's deepgis_pose
node; later field vehicles) POSTs its latest pose to vehicle_pose with a
bearer token. Only the latest pose per vehicle is kept, in the shared "live" cache;
signed-in viewers poll vehicles_live and fly the camera with it. Nothing here sends
anything to a vehicle.

Tokens are configured as VEHICLE_POSE_TOKENS = "vehicle_id:sha256hex,...": the server
keeps only the hash, and a token may only post for its own vehicle id. Sims started by
the OpenUAV launcher instead hold HMAC-SHA256(VEHICLE_FLEET_SECRET, vehicle id) for an id
starting with VEHICLE_FLEET_PREFIX, so each sim can post only as itself and none needs
configuring here. Field robots enroll themselves the same way: a robot holding
HMAC-SHA256(VEHICLE_ENROLL_SECRET, "field:" + its id) is registered as a field robot on its
first pose (platform, name and site from that pose). That key cannot claim an id used by a
sim, by a VEHICLE_POSE_TOKENS publisher or by the OpenUAV prefix.

Camera frames work the same way: the vehicle POSTs a JPEG to vehicle_frame with the same
token (metadata, including the pose at capture, in the X-Frame-Meta header), only the
latest is kept, vehicles_live says which vehicles have one, and signed-in viewers fetch
it from vehicle_frame_image.

Instrument products are small JSON readings a vehicle posts beside its frames, again with
the same token (vehicle_product): only the latest of each kind is kept, vehicles_live says
which vehicles have one, and signed-in viewers fetch it from vehicle_product_json. The one
kind so far is "spectrum": a point-spectrometer reading reduced on the vehicle, with the
laser range to its target and the patch it averaged over.

Robot identity (one hyphenated id per robot, its name, platform, aliases), last-known
positions and a downsampled track live in the database through views/robots.py;
vehicles_nearby searches them for the AI pilot and, with a ROBOT_READ_TOKENS token, for
the DREAMS Lab MCP's find_robots.
"""

import hashlib
import hmac
import json
import logging
import math
import re
from io import BytesIO
from time import time as now

from django.conf import settings
from django.core.cache import caches
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from PIL import Image

from . import robots

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 4096
POSE_TTL_SEC = 60  # a vehicle silent this long drops off the list
FRAME_TTL_SEC = 60
FRAME_MAX_BYTES = 600 * 1024
FRAME_MAX_SIDE = 4096
CAPTURE_SKEW_SEC = 600  # a capture time further than this from the server's clock is dropped
IDS_KEY = robots.IDS_KEY
VEHICLE_ID = re.compile(r"[a-z0-9_-]{1,40}")
KINDS = ("sim", "field")
# (min, max); out-of-range numbers are dropped, not clamped: a bad pose must not fly the camera
POSE_LIMITS = {
    "up_m": (-500.0, 20000.0),
    "alt_amsl": (-500.0, 20000.0),
    "heading_deg": (-360.0, 720.0),
    "gimbal_pitch_deg": (-90.0, 45.0),
    "hfov_deg": (1.0, 170.0),
    "speed_mps": (0.0, 400.0),
}


def pose_tokens():
    """{sha256 hex: vehicle id} from VEHICLE_POSE_TOKENS."""
    out = {}
    for item in (settings.VEHICLE_POSE_TOKENS or "").split(","):
        vid, _, digest = item.strip().partition(":")
        if VEHICLE_ID.fullmatch(vid) and re.fullmatch(r"[0-9a-f]{64}", digest):
            out[digest] = vid
    return out


def bearer(request):
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    return token or None


def token_vehicle(token, tokens):
    digest = hashlib.sha256(token.encode()).hexdigest()
    found = None
    for known, vid in tokens.items():
        if hmac.compare_digest(known, digest):
            found = vid
    return found


def fleet_token(secret, vid):
    return hmac.new(secret.encode(), vid.encode(), hashlib.sha256).hexdigest()


def fleet_vehicle(token, vid):
    """vid if token is the launcher's token for this sim, else None."""
    secret, prefix = settings.VEHICLE_FLEET_SECRET, settings.VEHICLE_FLEET_PREFIX
    if not (secret and prefix and isinstance(vid, str) and vid.startswith(prefix)
            and VEHICLE_ID.fullmatch(vid)):
        return None
    return vid if hmac.compare_digest(fleet_token(secret, vid), token) else None


def enroll_token(secret, vid):
    return hmac.new(secret.encode(), f"field:{vid}".encode(), hashlib.sha256).hexdigest()


def field_vehicle(token, vid, tokens):
    """vid if token is the enrollment key for this field robot's id, else None."""
    secret, prefix = settings.VEHICLE_ENROLL_SECRET, settings.VEHICLE_FLEET_PREFIX
    if not (secret and isinstance(vid, str) and VEHICLE_ID.fullmatch(vid)):
        return None
    if (prefix and vid.startswith(prefix)) or vid in tokens.values():
        return None
    if not hmac.compare_digest(enroll_token(secret, vid), token):
        return None
    return vid if robots.field_id_free(vid) else None


def ingest_configured(tokens):
    return bool(tokens or settings.VEHICLE_FLEET_SECRET or settings.VEHICLE_ENROLL_SECRET)


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _latlon(lat, lon):
    return _finite(lat) and _finite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def clean_pose(data):
    """The stored pose, or None if the position is missing or invalid."""
    if not _latlon(data.get("lat"), data.get("lon")):
        return None
    pose = {"lat": float(data["lat"]), "lon": float(data["lon"])}
    for field, (lo, hi) in POSE_LIMITS.items():
        v = data.get(field)
        if _finite(v) and lo <= v <= hi:
            pose[field] = float(v)
    ref = data.get("ref")
    if isinstance(ref, dict) and _latlon(ref.get("lat"), ref.get("lon")):
        pose["ref"] = {"lat": float(ref["lat"]), "lon": float(ref["lon"])}
        if _finite(ref.get("alt_amsl")):
            pose["ref"]["alt_amsl"] = float(ref["alt_amsl"])
    for field in ("armed", "landed"):
        if isinstance(data.get(field), bool):
            pose[field] = data[field]
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        pose["name"] = name.strip()[:80]
    if data.get("kind") in KINDS:
        pose["kind"] = data["kind"]
    if data.get("platform") in robots.PLATFORMS:
        pose["platform"] = data["platform"]
    site = data.get("site")
    if isinstance(site, str) and site.strip():
        pose["site"] = site.strip()[:200]
    return pose


def _json_object(raw):
    try:
        data = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _vehicle_for(token, tokens, data):
    """(vehicle id, None) or (None, error response) for a parsed request."""
    vid = token_vehicle(token, tokens) or fleet_vehicle(token, data.get("vehicle"))
    if vid is None:
        vid = field_vehicle(token, data.get("vehicle"), tokens)
        if vid is not None:
            data["kind"] = "field"
    if vid is None:
        return None, JsonResponse({"error": "A valid vehicle token is required"}, status=401)
    if data.get("vehicle", vid) != vid:
        return None, JsonResponse({"error": "This token is for another vehicle"}, status=403)
    return vid, None


@csrf_exempt
@require_POST
def vehicle_pose(request):
    tokens = pose_tokens()
    if not ingest_configured(tokens):
        return JsonResponse({"error": "Vehicle poses are not configured"}, status=503)
    token = bearer(request)
    if token is None:
        return JsonResponse({"error": "A valid vehicle token is required"}, status=401)
    if len(request.body) > MAX_BODY_BYTES:
        return JsonResponse({"error": "Pose too large"}, status=413)
    data = _json_object(request.body)
    if data is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    vid, error = _vehicle_for(token, tokens, data)
    if error:
        return error
    pose = clean_pose(data)
    if pose is None:
        return JsonResponse({"error": "lat and lon are required"}, status=400)
    pose.update(id=vid, received=now())
    live = caches["live"]
    live.set(f"vehicle:{vid}", pose, POSE_TTL_SEC)
    ids = live.get(IDS_KEY) or []
    if vid not in ids:
        live.set(IDS_KEY, sorted({*ids, vid}), None)
    try:
        robots.record_pose(vid, pose)
    except Exception:  # the live pose is what viewers need; the database copy can lag
        log.exception("could not record %s in the database", vid)
    return JsonResponse({"ok": True})


def jpeg_size(data):
    """(width, height) of a JPEG within FRAME_MAX_SIDE, else None. Reads only the header."""
    if not data.startswith(b"\xff\xd8\xff"):
        return None
    try:
        with Image.open(BytesIO(data)) as im:
            if im.format != "JPEG":
                return None
            w, h = im.size
    except Exception:
        return None
    return (w, h) if 0 < w <= FRAME_MAX_SIDE and 0 < h <= FRAME_MAX_SIDE else None


@csrf_exempt
@require_POST
def vehicle_frame(request):
    """One camera frame (image/jpeg body) from a vehicle; the optional X-Frame-Meta header
    carries the JSON {vehicle, captured (unix s), pose fields at capture}."""
    tokens = pose_tokens()
    if not ingest_configured(tokens):
        return JsonResponse({"error": "Vehicle frames are not configured"}, status=503)
    token = bearer(request)
    if token is None:
        return JsonResponse({"error": "A valid vehicle token is required"}, status=401)
    if len(request.body) > FRAME_MAX_BYTES:
        return JsonResponse({"error": "Frame too large"}, status=413)
    raw_meta = request.headers.get("X-Frame-Meta", "")
    meta = _json_object(raw_meta.encode()) if len(raw_meta) <= MAX_BODY_BYTES else None
    if meta is None:
        return JsonResponse({"error": "X-Frame-Meta must be a JSON object"}, status=400)
    vid, error = _vehicle_for(token, tokens, meta)
    if error:
        return error
    size = jpeg_size(request.body)
    if size is None:
        return JsonResponse({"error": "The body must be a JPEG"}, status=400)
    t = now()
    info = {"w": size[0], "h": size[1], "bytes": len(request.body), "received": t}
    pose = clean_pose(meta)
    if pose:
        info["pose"] = pose
    captured = meta.get("captured")
    if _finite(captured) and abs(captured - t) <= CAPTURE_SKEW_SEC:
        info["captured"] = float(captured)
    live = caches["live"]
    info["seq"] = (live.get(f"frame_info:{vid}") or {}).get("seq", 0) + 1
    live.set(f"frame:{vid}", bytes(request.body), FRAME_TTL_SEC)
    live.set(f"frame_info:{vid}", info, FRAME_TTL_SEC)
    return JsonResponse({"ok": True, "seq": info["seq"]})


@require_GET
def vehicle_frame_image(request, vid):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to see vehicle cameras"}, status=401)
    jpeg = caches["live"].get(f"frame:{vid}") if VEHICLE_ID.fullmatch(vid) else None
    if jpeg is None:
        return JsonResponse({"error": "No recent frame from this vehicle"}, status=404)
    resp = HttpResponse(jpeg, content_type="image/jpeg")
    resp["Cache-Control"] = "private, no-store"
    return resp


PRODUCT_MAX_BYTES = 16 * 1024
PRODUCT_TTL_SEC = 120
SPECTRUM_MAX_BINS = 2048
SPECTRUM_MAX_NOTES = 6
# (min, max) per field; as with poses, an out-of-range optional number is dropped
SPECTRUM_LIMITS = {
    "baseline": (-1e7, 1e7),
    "integration_ms": (0.0, 600000.0),
    "clipped_pct": (0.0, 100.0),
    "peak_frac": (0.0, 1.0),
}
SPECTRUM_INDEX_LIMITS = {k: (-1000.0, 1000.0) for k in robots.SPECTRUM_INDICES}
LASER_LIMITS = {"valid": (0.0, 1.0), "range_m": (0.0, 5000.0), "min_m": (0.0, 5000.0), "max_m": (0.0, 5000.0)}
FOOTPRINT_LIMITS = {"u": (0.0, 1.0), "v": (0.0, 1.0), "fov_deg": (0.01, 180.0), "frac_w": (0.0, 20.0),
                    "diameter_m": (0.0, 5000.0)}


def _numbers(src, limits):
    """{field: float} for the fields of src that are finite and within their limits."""
    if not isinstance(src, dict):
        return {}
    return {k: float(src[k]) for k, (lo, hi) in limits.items() if _finite(src.get(k)) and lo <= src[k] <= hi}


def _pair(v, lo, hi):
    """[a, b] if v is two finite numbers within [lo, hi] with a <= b, else None."""
    if not (isinstance(v, list) and len(v) == 2 and all(_finite(x) and lo <= x <= hi for x in v) and v[0] <= v[1]):
        return None
    return [float(v[0]), float(v[1])]


def clean_spectrum(d):
    """The stored spectrum product, or None if the spectrum itself is missing or invalid.

    counts[i] is the reading (counts above the instrument's baseline) for the band starting
    at wl0 + i * dwl nm; full_scale is the count at which the detector clips. The rest is
    optional and dropped if malformed: clipped ([lo, hi] nm spans), indices (band ratios),
    laser (range to the target during the reading), footprint (where the instrument points
    in the vehicle's camera frame, u and v from the left and top, and how wide it sees),
    t_rel (when it was integrated, seconds relative to the frame) and the instrument's own
    notes on what the numbers mean."""
    if not isinstance(d, dict):
        return None
    counts = d.get("counts")
    grid = _numbers(d, {"wl0": (100.0, 30000.0), "dwl": (0.01, 100.0), "full_scale": (1.0, 1e7)})
    if len(grid) < 3 or not isinstance(counts, list) or not 16 <= len(counts) <= SPECTRUM_MAX_BINS:
        return None
    if not all(_finite(c) and abs(c) <= 1e7 for c in counts):
        return None
    out = {**grid, "counts": [round(c) for c in counts], **_numbers(d, SPECTRUM_LIMITS)}
    spans = d.get("clipped")
    out["clipped"] = [s for s in (_pair(x, 0.0, 30000.0) for x in (spans if isinstance(spans, list) else [])[:64]) if s]
    out["indices"] = _numbers(d.get("indices"), SPECTRUM_INDEX_LIMITS)
    laser = _numbers(d.get("laser"), LASER_LIMITS)
    if laser:
        out["laser"] = laser
    footprint = _numbers(d.get("footprint"), FOOTPRINT_LIMITS)
    if footprint:
        out["footprint"] = footprint
    t_rel = _pair(d.get("t_rel"), -60.0, 60.0)
    if t_rel:
        out["t_rel"] = t_rel
    notes = d.get("notes")
    out["notes"] = [" ".join(n.split())[:300] for n in (notes if isinstance(notes, list) else [])
                    if isinstance(n, str) and n.strip()][:SPECTRUM_MAX_NOTES]
    return out


PRODUCT_CLEANERS = {"spectrum": clean_spectrum}  # one per kind in robots.PRODUCT_KINDS


@csrf_exempt
@require_POST
def vehicle_product(request):
    """One instrument product from a vehicle: the JSON {vehicle, product, captured (unix s), data},
    where product names its kind ("spectrum")."""
    tokens = pose_tokens()
    if not ingest_configured(tokens):
        return JsonResponse({"error": "Vehicle products are not configured"}, status=503)
    token = bearer(request)
    if token is None:
        return JsonResponse({"error": "A valid vehicle token is required"}, status=401)
    if len(request.body) > PRODUCT_MAX_BYTES:
        return JsonResponse({"error": "Product too large"}, status=413)
    body = _json_object(request.body)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    vid, error = _vehicle_for(token, tokens, body)
    if error:
        return error
    kind = body.get("product")
    clean = PRODUCT_CLEANERS.get(kind) if isinstance(kind, str) else None
    if clean is None:
        return JsonResponse({"error": f"product must be one of: {', '.join(PRODUCT_CLEANERS)}"}, status=400)
    data = clean(body.get("data"))
    if data is None:
        return JsonResponse({"error": f"Invalid {kind} product"}, status=400)
    t = now()
    live = caches["live"]
    key = robots.product_key(vid, kind)
    product = {"product": kind, "data": data, "received": t, "seq": (live.get(key) or {}).get("seq", 0) + 1}
    captured = body.get("captured")
    if _finite(captured) and abs(captured - t) <= CAPTURE_SKEW_SEC:
        product["captured"] = float(captured)
    live.set(key, product, PRODUCT_TTL_SEC)
    return JsonResponse({"ok": True, "seq": product["seq"]})


@require_GET
def vehicle_product_json(request, vid, kind):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to see vehicle instruments"}, status=401)
    product = robots.live_product(vid, kind, now()) if VEHICLE_ID.fullmatch(vid) else None
    if product is None:
        return JsonResponse({"error": "No recent reading of this kind from this vehicle"}, status=404)
    resp = JsonResponse(product)
    resp["Cache-Control"] = "private, no-store"
    return resp


@require_GET
def vehicles_live(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to follow vehicles"}, status=401)
    reg = robots.registry()
    return JsonResponse({"vehicles": [robots.enrich(p, reg) for p in robots.live_poses(now())]})


def read_token_ok(request):
    """A bearer token whose sha256 is listed in ROBOT_READ_TOKENS ("hex,hex")."""
    token = bearer(request)
    if not token:
        return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    known = [d.strip() for d in (settings.ROBOT_READ_TOKENS or "").split(",") if d.strip()]
    return any(hmac.compare_digest(d, digest) for d in known)


def _query_float(q, key):
    try:
        v = float(q.get(key, ""))
    except ValueError:
        return None
    return v if math.isfinite(v) else None


NEARBY_MAX_RADIUS_M = 20_000_000
NEARBY_MAX_LIMIT = 200


@require_GET
def vehicles_nearby(request):
    """Robots near a point or another robot, of a platform, or matching a name.

    GET lat, lon (or near=<robot id or name>), radius_m (0 = any distance), platform
    ("rover", "drones", "boat"...), q (a name, alias or platform word), offline=1 to include
    known robots that are not reporting (at their last-known position), limit.
    """
    if not (request.user.is_authenticated or read_token_ok(request)):
        return JsonResponse({"error": "Sign in or present a robot read token"}, status=401)
    q = request.GET
    lat, lon = _query_float(q, "lat"), _query_float(q, "lon")
    if (lat is None) != (lon is None) or (lat is not None and not _latlon(lat, lon)):
        return JsonResponse({"error": "lat and lon must be given together and be valid"}, status=400)
    center = {"lat": lat, "lon": lon} if lat is not None else None
    near = q.get("near", "").strip()
    if near:
        everyone = robots.nearby(include_offline=True, limit=NEARBY_MAX_LIMIT)
        vid = robots.resolve(near, [r["id"] for r in everyone])
        anchor = next((r for r in everyone if r["id"] == vid and "lat" in r), None)
        if anchor is None:
            return JsonResponse({"error": f"No robot called {near!r} with a known position"}, status=404)
        lat, lon = anchor["lat"], anchor["lon"]
        center = {"lat": lat, "lon": lon, "robot": vid}
    radius = min(max(_query_float(q, "radius_m") or 0.0, 0.0), NEARBY_MAX_RADIUS_M)
    try:
        limit = min(max(int(q.get("limit", 50)), 1), NEARBY_MAX_LIMIT)
    except ValueError:
        limit = 50
    rows = robots.nearby(lat, lon, radius, q.get("platform", ""), q.get("q", ""),
                         include_offline=q.get("offline", "") in ("1", "true", "yes"), limit=limit)
    if center and center.get("robot"):
        rows = [r for r in rows if r["id"] != center["robot"]]
    return JsonResponse({"center": center, "radius_m": radius or None, "robots": rows})
