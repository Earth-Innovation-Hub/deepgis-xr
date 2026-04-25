"""
Adapters that turn each existing analyzer's output (or an OSM bbox
fetch) into a flat list of :class:`kernelcal.distinction_game.KernelClaim`.

The Distinction-Game SceneGraph orchestrator is the only consumer.
Each adapter here is intentionally narrow:

  * its input is exactly what the corresponding analyzer/OSM fetch
    already produces today (so we don't break the world-sampler UI's
    per-kernel rendering), and
  * its output is a list of :class:`KernelClaim` whose ``source_id``
    matches a key in :func:`kernelcal.distinction_game.default_q_s_table`,
    so the fusion math just works.

Geometry contract (matches kernelcal's expectation):

  * ``polygon`` is a closed ring of normalised image coordinates
    ``[0, 1]`` (origin top-left, x→right, y→down). This is the same
    basis the Mask R-CNN service emits in
    ``predictions.masks_polygons_norm`` and is what
    :func:`kernelcal.distinction_game.scene_graph.build_scene_graph`
    expects.
  * ``geo_polygon`` is the matching ``[(lon, lat), ...]`` ring,
    obtained by bilinearly interpolating the four ``viewport`` corners.
    This stays optional (``None``) for analyzers/sources that didn't
    have geographic context — but for ground-truth sources like OSM,
    geographic coordinates are the *only* native basis, and we
    forward-project them into the normalised-image basis using the
    same bilinear corners.

Note on naming vs function (kernelcal §3.0): the ``source_id`` here is
``"mr_house"`` for MaskRCNN-House regardless of whether it's actually
firing on undamaged roofs, damaged roofs, or generic structures. That
distinction-vs-label discipline lives in ``Q_s``, not in the adapter.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# kernelcal lives next to this repo on the dev box and is installed
# editable inside the deepgis-xr containers.
from kernelcal.distinction_game import KernelClaim


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _bilinear_lonlat(
    u: float,
    v: float,
    corners_lonlat: Sequence[Tuple[float, float]],
) -> Tuple[float, float]:
    """Project a normalised image coordinate ``(u, v) ∈ [0, 1]²`` to
    ``(lon, lat)`` using bilinear interpolation over four viewport
    corners.

    ``corners_lonlat`` is ``[NW, NE, SE, SW]`` — the convention emitted
    by ``world-sampler-ui.js#computeViewportCornersGeo()``. Each entry
    is ``(lon, lat)``.

    The Cesium frontend uses image-coords with origin top-left, so:
      * (u=0, v=0) → NW
      * (u=1, v=0) → NE
      * (u=1, v=1) → SE
      * (u=0, v=1) → SW
    """
    nw, ne, se, sw = corners_lonlat
    lon = (
        (1 - u) * (1 - v) * nw[0]
        + u * (1 - v) * ne[0]
        + u * v * se[0]
        + (1 - u) * v * sw[0]
    )
    lat = (
        (1 - u) * (1 - v) * nw[1]
        + u * (1 - v) * ne[1]
        + u * v * se[1]
        + (1 - u) * v * sw[1]
    )
    return (lon, lat)


def _bilinear_uv(
    lon: float,
    lat: float,
    corners_lonlat: Sequence[Tuple[float, float]],
) -> Tuple[float, float]:
    """Inverse of :func:`_bilinear_lonlat`: project ``(lon, lat)`` to
    normalised image coordinates ``(u, v) ∈ [0, 1]²`` using a
    plate-carrée approximation of the viewport extent.

    For small viewports (PHX-scale tiles) this is well within
    sub-pixel of a true bilinear inverse. We deliberately *don't*
    invert the bilinear map analytically (which would require solving
    a quadratic) because the viewports we care about are small and
    near-axis-aligned.
    """
    nw, ne, se, sw = corners_lonlat
    lon_min = min(nw[0], sw[0])
    lon_max = max(ne[0], se[0])
    lat_min = min(sw[1], se[1])
    lat_max = max(nw[1], ne[1])
    if lon_max <= lon_min or lat_max <= lat_min:
        return (0.5, 0.5)
    u = (lon - lon_min) / (lon_max - lon_min)
    v = 1.0 - (lat - lat_min) / (lat_max - lat_min)
    return (max(0.0, min(1.0, u)), max(0.0, min(1.0, v)))


def _polygon_from_bbox_norm(
    bbox_norm: Sequence[float],
) -> List[List[float]]:
    """Closed ring around an axis-aligned bbox in normalised image coords.

    ``bbox_norm`` is ``[x1, y1, x2, y2]`` in [0, 1].
    """
    x1, y1, x2, y2 = (float(v) for v in bbox_norm[:4])
    return [
        [x1, y1],
        [x2, y1],
        [x2, y2],
        [x1, y2],
        [x1, y1],
    ]


def _attach_geo_polygon(
    polygon_norm: Sequence[Sequence[float]],
    corners_lonlat: Optional[Sequence[Tuple[float, float]]],
) -> Optional[List[List[float]]]:
    """Project a normalised polygon into ``[lon, lat]`` if corners are known."""
    if not corners_lonlat:
        return None
    return [list(_bilinear_lonlat(p[0], p[1], corners_lonlat)) for p in polygon_norm]


# ---------------------------------------------------------------------------
# Per-source adapters
# ---------------------------------------------------------------------------

def adapt_osm(
    osm_features: Iterable[Mapping[str, Any]],
    *,
    corners_lonlat: Optional[Sequence[Tuple[float, float]]] = None,
    image_size: Optional[Tuple[int, int]] = None,
    feature_kind: str = "building",
    score: float = 0.95,
) -> List[KernelClaim]:
    """OSM features → :class:`KernelClaim` list with ``source_id='osm'``.

    ``osm_features`` is the structure already emitted by
    ``http._gdf_to_features``: each item has ``geometry`` (GeoJSON
    Polygon/MultiPolygon mapping) and ``tags`` (OSM tags dict).

    We forward-project each feature's outer ring into normalised image
    coordinates using ``corners_lonlat`` (the four viewport corners
    captured at the same time as the JPEG). Features without a usable
    geometry are skipped silently.

    ``feature_kind`` becomes the kernel's :attr:`native_label` (so
    ``Q_s["osm"]`` knows whether to read the building / road / tree /
    parking column). The orchestrator should call this adapter once
    per OSM tag query (e.g. ``{'building': True}`` →
    ``feature_kind='building'``, ``{'highway': True}`` →
    ``feature_kind='road'``).

    Note: OSM is treated as a near-truthful kernel by ``Q_s["osm"]``,
    not as a perfect oracle (footprints lag construction, OSM tag
    coverage is patchy in some PHX neighbourhoods). The Q_s prior
    encodes that.
    """
    claims: List[KernelClaim] = []
    if not corners_lonlat:
        # Without corners we cannot build normalised geometry; OSM
        # features are useless without that, so skip.
        return claims

    for f in osm_features:
        geom = f.get('geometry') or {}
        gtype = geom.get('type', '')
        if gtype == 'Polygon':
            rings = geom.get('coordinates') or []
        elif gtype == 'MultiPolygon':
            polys = geom.get('coordinates') or []
            rings = [p[0] for p in polys if p]
        else:
            # Linestrings (roads), points (POIs) come through here.
            # PR-1 buffers them as bbox squares so they participate
            # in spatial association.
            coords = geom.get('coordinates') or []
            if not coords:
                continue
            try:
                if gtype == 'LineString':
                    pts = coords
                elif gtype == 'Point':
                    pts = [coords]
                else:
                    continue
                if not pts:
                    continue
                lon_min = min(p[0] for p in pts)
                lon_max = max(p[0] for p in pts)
                lat_min = min(p[1] for p in pts)
                lat_max = max(p[1] for p in pts)
                # Pad zero-area features by 1m so they have a finite bbox.
                if lon_max == lon_min:
                    lon_min -= 1e-6
                    lon_max += 1e-6
                if lat_max == lat_min:
                    lat_min -= 1e-6
                    lat_max += 1e-6
                rings = [[
                    [lon_min, lat_min],
                    [lon_max, lat_min],
                    [lon_max, lat_max],
                    [lon_min, lat_max],
                    [lon_min, lat_min],
                ]]
            except Exception:
                continue

        for ring in rings:
            try:
                ring_uv = [
                    list(_bilinear_uv(pt[0], pt[1], corners_lonlat))
                    for pt in ring
                ]
                if len(ring_uv) < 3:
                    continue
                geo_ring = [[float(p[0]), float(p[1])] for p in ring]
                # OSM tag dump from geopandas spreads sparsely-populated
                # columns across every feature with ``float('nan')`` for
                # the empties (e.g. ``traffic_signals``, ``maxspeed``,
                # ``bicycle`` on roads). Those NaNs are RFC-8259-invalid
                # and bloat the payload to MBs of ``null`` keys; drop
                # them at the source. The orchestrator's
                # ``_sanitize_json_floats`` is still the safety net for
                # any other adapter that forgets, but trimming here is
                # what keeps the response compact.
                tags_raw = f.get('tags') or {}
                tags = {
                    k: v for k, v in tags_raw.items()
                    if v is not None
                    and not (isinstance(v, float) and not math.isfinite(v))
                    and v != ''
                }
                claims.append(
                    KernelClaim.from_polygon(
                        source_id='osm',
                        native_label=feature_kind,
                        score=float(score),
                        points=ring_uv,
                        geo_polygon=geo_ring,
                        image_size=image_size,
                        attributes={
                            'osm_id': f.get('osm_id'),
                            'tags': tags,
                            'feature_kind': feature_kind,
                        },
                    )
                )
            except Exception:
                # Skip degenerate rings without breaking the adapter.
                continue

    return claims


def _adapt_maskrcnn_family(
    detections: Iterable[Mapping[str, Any]],
    *,
    source_id: str,
    fallback_label: str,
    image_size: Tuple[int, int],
    corners_lonlat: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[KernelClaim]:
    """Internal: shared adapter for MaskRCNN-Rocks and MaskRCNN-House.

    Both branches share an output schema (vector contours via
    ``mask_polygons_norm``, plus ``bbox`` in pixel coords as fallback)
    because they're served by the same Docker image. The kernel id
    discipline is what's different (``mr_rocks`` vs ``mr_house``), and
    that is captured by the explicit ``source_id`` argument so the
    fused posterior gets the right ``Q_s`` row.
    """
    claims: List[KernelClaim] = []
    w, h = float(image_size[0]), float(image_size[1])
    if w <= 0 or h <= 0:
        return claims

    for det in detections:
        score = float(det.get('confidence') or det.get('score') or 0.0)
        if score <= 0.0:
            continue
        label = det.get('class_name') or det.get('label') or fallback_label

        polygons_norm = det.get('mask_polygons_norm') or []
        if polygons_norm:
            for poly in polygons_norm:
                if not poly or len(poly) < 3:
                    continue
                try:
                    geo_ring = _attach_geo_polygon(poly, corners_lonlat)
                    claims.append(
                        KernelClaim.from_polygon(
                            source_id=source_id,
                            native_label=label,
                            score=score,
                            points=[list(p) for p in poly],
                            geo_polygon=geo_ring,
                            image_size=image_size,
                            attributes={
                                'detection_id': det.get('detection_id'),
                                'has_mask': True,
                                'area_px': det.get('area'),
                            },
                        )
                    )
                except Exception:
                    continue
            continue

        # Fallback: bbox-only claim.
        bbox_px = det.get('bbox') or []
        if len(bbox_px) >= 4:
            x1, y1, x2, y2 = (float(v) for v in bbox_px[:4])
            bbox_norm = [x1 / w, y1 / h, x2 / w, y2 / h]
            ring = _polygon_from_bbox_norm(bbox_norm)
            try:
                geo_ring = _attach_geo_polygon(ring, corners_lonlat)
                claims.append(
                    KernelClaim.from_polygon(
                        source_id=source_id,
                        native_label=label,
                        score=score,
                        points=ring,
                        geo_polygon=geo_ring,
                        image_size=image_size,
                        attributes={
                            'detection_id': det.get('detection_id'),
                            'has_mask': False,
                            'area_px': det.get('area'),
                        },
                    )
                )
            except Exception:
                continue
    return claims


def adapt_maskrcnn_rocks(
    result: Mapping[str, Any],
    *,
    corners_lonlat: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[KernelClaim]:
    """``maskrcnn_rocks`` analyzer JSON → claims with ``source_id='mr_rocks'``.

    Accepts the JSON returned by ``/webclient/sampler/analyze-viewport``
    when ``analysis_type=maskrcnn_rocks``: it has top-level
    ``detections`` and ``image_size``.
    """
    img_size = tuple(result.get('image_size') or (0, 0))[:2]
    if img_size == (0, 0):
        return []
    return _adapt_maskrcnn_family(
        result.get('detections') or [],
        source_id='mr_rocks',
        fallback_label='rock',
        image_size=img_size,
        corners_lonlat=corners_lonlat,
    )


def adapt_maskrcnn_house(
    result: Mapping[str, Any],
    *,
    corners_lonlat: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[KernelClaim]:
    """``maskrcnn_house`` analyzer JSON → claims with ``source_id='mr_house'``.

    Native labels here are ``house``, ``house_undamaged``,
    ``house_damage_{0..3}`` (or whatever ``DEFAULT_LABEL_NAME`` is set
    to on the upstream container). The downstream Q_s prior collapses
    them into a binary ``[fired, no_fire]`` vocabulary anchored on
    ``building`` — see ``kernelcal.distinction_game.q_s._q_mr_house``.
    """
    img_size = tuple(result.get('image_size') or (0, 0))[:2]
    if img_size == (0, 0):
        return []
    return _adapt_maskrcnn_family(
        result.get('detections') or [],
        source_id='mr_house',
        fallback_label='house',
        image_size=img_size,
        corners_lonlat=corners_lonlat,
    )


def adapt_grounding_dino(
    result: Mapping[str, Any],
    *,
    corners_lonlat: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[KernelClaim]:
    """``grounding_dino`` analyzer JSON → claims with ``source_id='grounding_dino'``.

    Grounding DINO returns text-conditioned boxes only; we synthesise
    rectangular polygons from each box. ``native_label`` is the matched
    text phrase (the user's query token), so the Q_s prior decides
    how trustworthy each query word is per category.
    """
    img_size = tuple(result.get('image_size') or (0, 0))[:2]
    if img_size == (0, 0):
        return []
    w, h = float(img_size[0]), float(img_size[1])
    claims: List[KernelClaim] = []
    for det in result.get('detections') or []:
        score = float(det.get('confidence') or det.get('score') or 0.0)
        if score <= 0.0:
            continue
        label = det.get('class_name') or det.get('label') or 'object'
        bbox_px = det.get('bbox') or []
        if len(bbox_px) < 4:
            continue
        x1, y1, x2, y2 = (float(v) for v in bbox_px[:4])
        bbox_norm = [x1 / w, y1 / h, x2 / w, y2 / h]
        ring = _polygon_from_bbox_norm(bbox_norm)
        try:
            geo_ring = _attach_geo_polygon(ring, corners_lonlat)
            claims.append(
                KernelClaim.from_polygon(
                    source_id='grounding_dino',
                    native_label=label,
                    score=score,
                    points=ring,
                    geo_polygon=geo_ring,
                    image_size=img_size,
                    attributes={
                        'detection_id': det.get('detection_id'),
                        'phrase': label,
                    },
                )
            )
        except Exception:
            continue
    return claims


def adapt_grounded_sam(
    result: Mapping[str, Any],
    *,
    corners_lonlat: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[KernelClaim]:
    """``grounded_sam`` analyzer JSON → claims with ``source_id='grounded_sam2'``.

    Grounded-SAM-2 emits text-conditioned masks. The remote service
    returns mask polygons in its GeoJSON output; if normalised vector
    contours are present we use them, otherwise we fall back to the
    bbox-rectangle path used by Grounding-DINO above.
    """
    img_size = tuple(result.get('image_size') or (0, 0))[:2]
    if img_size == (0, 0):
        return []
    w, h = float(img_size[0]), float(img_size[1])
    claims: List[KernelClaim] = []
    for det in result.get('detections') or []:
        score = float(det.get('confidence') or det.get('score') or 0.0)
        if score <= 0.0:
            continue
        label = det.get('class_name') or det.get('label') or 'object'

        polygons_norm = det.get('mask_polygons_norm') or []
        if polygons_norm:
            for poly in polygons_norm:
                if not poly or len(poly) < 3:
                    continue
                try:
                    geo_ring = _attach_geo_polygon(poly, corners_lonlat)
                    claims.append(
                        KernelClaim.from_polygon(
                            source_id='grounded_sam2',
                            native_label=label,
                            score=score,
                            points=[list(p) for p in poly],
                            geo_polygon=geo_ring,
                            image_size=img_size,
                            attributes={
                                'detection_id': det.get('detection_id'),
                                'phrase': label,
                                'has_mask': True,
                            },
                        )
                    )
                except Exception:
                    continue
            continue

        bbox_px = det.get('bbox') or []
        if len(bbox_px) < 4:
            continue
        x1, y1, x2, y2 = (float(v) for v in bbox_px[:4])
        bbox_norm = [x1 / w, y1 / h, x2 / w, y2 / h]
        ring = _polygon_from_bbox_norm(bbox_norm)
        try:
            geo_ring = _attach_geo_polygon(ring, corners_lonlat)
            claims.append(
                KernelClaim.from_polygon(
                    source_id='grounded_sam2',
                    native_label=label,
                    score=score,
                    points=ring,
                    geo_polygon=geo_ring,
                    image_size=img_size,
                    attributes={
                        'detection_id': det.get('detection_id'),
                        'phrase': label,
                        'has_mask': False,
                    },
                )
            )
        except Exception:
            continue
    return claims


def adapt_sam(
    result: Mapping[str, Any],
    *,
    corners_lonlat: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[KernelClaim]:
    """SAM analyzer JSON → claims with ``source_id='sam2'``.

    SAM is class-agnostic; every mask gets the literal native label
    ``"<sam_segment>"`` (which is what
    :mod:`kernelcal.distinction_game.q_s` ``_q_sam2`` is keyed on).

    The world-sampler SAM analyzer currently returns ``segments`` with
    polygon outlines in the ``geojson`` payload; we tap that GeoJSON
    directly so we don't have to round-trip through pixel rasters.
    """
    img_size = tuple(result.get('image_size') or (0, 0))[:2]
    if img_size == (0, 0):
        return []
    w, h = float(img_size[0]), float(img_size[1])
    claims: List[KernelClaim] = []
    geojson = result.get('geojson') or {}
    features = geojson.get('features') or []
    for feat in features:
        props = feat.get('properties') or {}
        score = float(props.get('confidence') or props.get('predicted_iou') or props.get('score') or 0.5)
        geom = feat.get('geometry') or {}
        gtype = geom.get('type', '')
        if gtype != 'Polygon':
            continue
        rings = geom.get('coordinates') or []
        if not rings:
            continue
        ring_pixels = rings[0]
        try:
            ring_norm = [[float(p[0]) / w, float(p[1]) / h] for p in ring_pixels]
            if len(ring_norm) < 3:
                continue
            geo_ring = _attach_geo_polygon(ring_norm, corners_lonlat)
            claims.append(
                KernelClaim.from_polygon(
                    source_id='sam2',
                    native_label='<sam_segment>',
                    score=score,
                    points=ring_norm,
                    geo_polygon=geo_ring,
                    image_size=img_size,
                    attributes={
                        'segment_id': props.get('segment_id'),
                        'predicted_iou': props.get('predicted_iou'),
                    },
                )
            )
        except Exception:
            continue
    return claims


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

ADAPTERS = {
    'maskrcnn_rocks':  adapt_maskrcnn_rocks,
    'mr_rocks':        adapt_maskrcnn_rocks,
    'maskrcnn_house':  adapt_maskrcnn_house,
    'mr_house':        adapt_maskrcnn_house,
    'grounding_dino':  adapt_grounding_dino,
    'grounded_sam':    adapt_grounded_sam,
    'grounded_sam2':   adapt_grounded_sam,
    'sam':             adapt_sam,
    'sam2':            adapt_sam,
}


def adapt_kernel_result(
    kernel_kind: str,
    result: Mapping[str, Any],
    *,
    corners_lonlat: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[KernelClaim]:
    """Look up the adapter for an analyzer kind and run it.

    Unknown ``kernel_kind`` returns ``[]`` (silent kernel) — the
    orchestrator will record the kind in ``kernels_queried`` so the
    frontend can still tell silent vs. unimplemented apart.
    """
    fn = ADAPTERS.get(kernel_kind)
    if fn is None:
        return []
    return fn(result, corners_lonlat=corners_lonlat)
