"""
SceneGraph orchestrator endpoint — the deepgis-xr surface of the
Distinction-Game (kernelcal §4 / §11.4).

Public API (one route, registered in ``apps/web/urls.py``):

    POST /webclient/sampler/scenegraph/build

Request body (JSON)::

    {
      "viewport": {
        "image_size": [W, H],
        "world_corners": [[lonNW, latNW], [lonNE, latNE],
                          [lonSE, latSE], [lonSW, latSW]],
        "camera": { "lon": ..., "lat": ..., "alt": ... },
        "image_path": "..."     // optional, server-side disk path
      },

      // EITHER (preferred) the per-kernel results that the existing
      // /analyze-viewport endpoint just produced, keyed by kernel id —
      // this is the "client orchestrates" mode where the UI runs each
      // kernel through the existing dropdown and POSTs the bundle here:
      "kernel_results": {
        "mr_rocks":   { ... raw analyze-viewport JSON ... },
        "mr_house":   { ... },
        "grounding_dino": { ... },
        "sam":        { ... }
      },

      // OR, additionally / alternatively, ground-truth sources to fetch
      // server-side. PR-2 supports OSM-buildings + OSM-roads:
      "ground_truth_sources": ["osm_buildings", "osm_roads"],

      // Mixing controls (all optional; defaults are uniform-λ over the
      // sources that ended up contributing claims):
      "min_score":     0.2,
      "iou_threshold": 0.5,
      "edge_proximity": 0.05
    }

Response::

    {
      "status": "success",
      "session_id": "scenegraph_<ts>_<latlon>",
      "scene_graph": <kernelcal SceneGraph.to_dict() output>,
      "saved_to": { "session_dir": "...", "host_path": "..." },
      "report_url": "/label/ai-analysis/report/<session_id>/"   // best-effort
    }

This endpoint is intentionally additive — none of the existing
``/analyze-viewport`` analyzer branches are changed. The orchestrator
is one process boundary above them.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from kernelcal.distinction_game import (
    PHX_URBAN_V0,
    Viewport,
    build_scene_graph,
    default_q_s_table,
    uniform_lambdas,
)

from ..models import SamplingSession, SceneGraph as SceneGraphRow
from .scene_graph_adapters import (
    adapt_kernel_result,
    adapt_osm,
)
from .scenegraph_city_graph import (
    CityGraphUnavailable,
    annotate_nodes_with_cg_idx,
    attach_road_edges,
    build_city_graph_for_bbox,
    city_graph_to_osm_features,
    spectral_block,
)


SCENEGRAPH_RESULTS_DIR = Path('/app/deepgis_results') / 'scenegraph_results'


def _sanitize_json_floats(obj: Any) -> Any:
    """Recursively replace non-finite floats (NaN / +Inf / -Inf) with
    ``None`` so the result is RFC-8259-valid JSON.

    Why this exists. Two downstream consumers reject Python's permissive
    ``json.dumps(allow_nan=True)`` output:

      1. JavaScript ``JSON.parse`` fails the entire document on the first
         bare ``NaN`` / ``Infinity`` token, so the whole SceneGraph never
         reaches the Cesium overlay.
      2. SQLite's ``JSONField`` runs ``json_valid()`` as a column CHECK
         constraint and rejects NaN/Infinity, so the DB persist fails
         with ``CHECK constraint failed: scene_graphs``.

    The dominant source of NaN in our pipeline is OSM tag round-tripping:
    geopandas reports sparsely-populated columns (``traffic_signals``,
    ``maxspeed``, ``bicycle``, …) as ``float('nan')`` when the tag is
    absent on a feature, and those NaNs ride through into
    ``KernelClaim.metadata`` and the final node payload. We chose
    *normalize-then-emit* over ``allow_nan=False`` because the latter
    would 500 the request (a single NaN in a 3 MB payload is enough);
    silently mapping to ``None`` lets the structurally-valid scenes
    still ship while flagging missing tag values exactly as a
    JSON-aware client would expect (``null``).

    Walks dicts, lists, and tuples; leaves int/bool/str/None untouched;
    coerces ``float('nan'|'inf'|'-inf')`` to ``None``.
    """
    if isinstance(obj, float):
        if math.isfinite(obj):
            return obj
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_json_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json_floats(v) for v in obj]
    return obj


def _safe_lat_str(lat: float) -> str:
    return f"lat{lat:.6f}".replace('.', 'p').replace('-', 'n')


def _safe_lon_str(lon: float) -> str:
    return f"lon{lon:.6f}".replace('.', 'p').replace('-', 'n')


def _normalise_corners(world_corners: Any) -> Optional[List[Tuple[float, float]]]:
    """Coerce the frontend's corners payload into ``[NW, NE, SE, SW]``
    ``(lon, lat)`` tuples, or ``None`` if the input is malformed.

    ``world_corners`` is either a 4-element array of ``[lon, lat]``
    pairs (the format ``world-sampler-ui.js#computeViewportCornersGeo``
    uses) or a dict ``{nw: [lon, lat], ne: ..., se: ..., sw: ...}``.
    """
    if not world_corners:
        return None
    try:
        if isinstance(world_corners, dict):
            order = ['nw', 'ne', 'se', 'sw']
            pts = [world_corners[k] for k in order]
        else:
            pts = list(world_corners)
        if len(pts) != 4:
            return None
        out: List[Tuple[float, float]] = []
        for p in pts:
            if isinstance(p, dict):
                lon = float(p.get('lon') or p.get('longitude') or p.get('x'))
                lat = float(p.get('lat') or p.get('latitude') or p.get('y'))
            else:
                lon = float(p[0])
                lat = float(p[1])
            out.append((lon, lat))
        return out
    except Exception:
        return None


def _viewport_bbox_from_corners(
    corners: Sequence[Tuple[float, float]],
) -> Tuple[float, float, float, float]:
    """``[NW, NE, SE, SW]`` → ``(west, south, east, north)``."""
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    return (min(lons), min(lats), max(lons), max(lats))


def _fetch_osm_for_bbox(
    bbox_geo: Tuple[float, float, float, float],
    *,
    sources: Sequence[str],
) -> Dict[str, List[Mapping[str, Any]]]:
    """Run server-side OSM fetches for the requested ground-truth
    sources and return ``{source_id: feature_list}``.

    Lazily imports the existing helpers in :mod:`.http` so we don't
    pull in OSMnx at module-import time.
    """
    if not sources:
        return {}
    out: Dict[str, List[Mapping[str, Any]]] = {}
    try:
        from .http import _fetch_osm_features, _gdf_to_features
    except Exception as exc:
        print(f"[scenegraph] failed to import OSM helpers: {exc}")
        return out
    west, south, east, north = bbox_geo
    if 'osm_buildings' in sources:
        try:
            gdf = _fetch_osm_features(
                south, west, north, east,
                {'building': True},
            )
            out['osm_buildings'] = _gdf_to_features(gdf, limit=400)
        except Exception as exc:
            print(f"[scenegraph] OSM buildings fetch failed: {exc}")
            out['osm_buildings'] = []
    if 'osm_roads' in sources:
        try:
            gdf = _fetch_osm_features(
                south, west, north, east,
                {'highway': True},
            )
            out['osm_roads'] = _gdf_to_features(gdf, limit=400)
        except Exception as exc:
            print(f"[scenegraph] OSM roads fetch failed: {exc}")
            out['osm_roads'] = []
    return out


@require_http_methods(["POST"])
@csrf_exempt
def build_scenegraph_view(request):
    """Build a Distinction-Game SceneGraph from per-kernel analyzer
    results + optional OSM ground truth and persist it.

    See module docstring for the request/response contract.
    """
    t_start = time.perf_counter()
    try:
        data = json.loads(request.body or b'{}')
    except Exception as exc:
        return JsonResponse({
            'status': 'error',
            'message': f'Invalid JSON body: {exc}',
        }, status=400)

    viewport_in = data.get('viewport') or {}
    image_size = viewport_in.get('image_size') or [0, 0]
    world_corners_raw = (
        viewport_in.get('world_corners')
        or data.get('world_corners')
    )
    corners = _normalise_corners(world_corners_raw)

    if not corners:
        return JsonResponse({
            'status': 'error',
            'message': (
                'viewport.world_corners is required '
                '([NW, NE, SE, SW] of [lon, lat])'
            ),
        }, status=400)
    bbox_geo = _viewport_bbox_from_corners(corners)

    try:
        img_w, img_h = int(image_size[0]), int(image_size[1])
    except Exception:
        img_w, img_h = 0, 0

    # 1. Adapt the client-supplied per-kernel results.
    kernel_results = data.get('kernel_results') or {}
    if not isinstance(kernel_results, dict):
        return JsonResponse({
            'status': 'error',
            'message': 'kernel_results must be an object {kernel_kind: result}',
        }, status=400)

    ground_truth_sources = list(data.get('ground_truth_sources') or [])

    all_claims = []
    kernels_queried: List[str] = []
    per_kernel_counts: Dict[str, int] = {}
    silent: List[str] = []

    for kernel_kind, result in kernel_results.items():
        kernels_queried.append(kernel_kind)
        if not isinstance(result, dict) or not result:
            silent.append(kernel_kind)
            per_kernel_counts[kernel_kind] = 0
            continue
        try:
            claims = adapt_kernel_result(
                kernel_kind, result, corners_lonlat=corners
            )
        except Exception as exc:
            print(f"[scenegraph] adapter for {kernel_kind} raised: {exc}")
            silent.append(kernel_kind)
            per_kernel_counts[kernel_kind] = 0
            continue
        per_kernel_counts[kernel_kind] = len(claims)
        if not claims:
            silent.append(kernel_kind)
        all_claims.extend(claims)

    # 2. Fetch + adapt OSM ground truth server-side.
    #
    # Optional Option-A merge with the urban-spectral pipeline: when the
    # caller sets ``use_city_graph_regions=True``, build a kernelcal
    # CityGraph for this bbox first and use *its* OSM-building rows as
    # the source of OSM-building claims (each tagged with its CityGraph
    # node index so we can splice road-aware edges + spectral diagnostics
    # back in after fusion). Buildings from osmnx are otherwise duplicate
    # work, so we elide them from ``_fetch_osm_for_bbox``.
    use_city_graph_regions = bool(data.get('use_city_graph_regions', False))
    cg_obj = None
    cg_warning: Optional[str] = None
    cg_options: Dict[str, Any] = {}
    if use_city_graph_regions:
        cg_options = {
            'graph_mode':   str(data.get('graph_mode', 'road_knn')),
            'k':            int(data.get('cg_k', 8)),
            'n_max':        int(data.get('cg_n_max', 1500)),
            'sigma_frac':   float(data.get('cg_sigma_frac', 0.05)),
            'network_type': str(data.get('cg_network_type', 'drive')),
            'simplify':     bool(data.get('cg_simplify_roads', True)),
            'force_refresh': bool(data.get('cg_force_refresh', False)),
            'timeout':      int(data.get('cg_timeout', 60)),
        }
        max_dist_raw = data.get('cg_max_network_dist')
        if max_dist_raw is not None:
            try:
                cg_options['max_network_dist'] = float(max_dist_raw)
            except (TypeError, ValueError):
                pass
        try:
            cg_obj = build_city_graph_for_bbox(bbox_geo, **cg_options)
        except CityGraphUnavailable as exc:
            cg_warning = (
                'kernelcal.urban not available — falling back to '
                f'standard SceneGraph: {exc}'
            )
            print(f'[scenegraph] {cg_warning}')
            cg_obj = None
        except ValueError as exc:
            cg_warning = f'invalid city-graph option: {exc}'
            print(f'[scenegraph] {cg_warning}')
            cg_obj = None
        except Exception as exc:  # OSM Overpass timeouts, network errors, …
            cg_warning = f'city-graph build failed: {exc}'
            print(f'[scenegraph] {cg_warning}')
            cg_obj = None

    osm_buildings_in_gt = 'osm_buildings' in ground_truth_sources

    # If we got a CityGraph, *force* osm_buildings into the kernel
    # mix (it provides the region backbone) and skip the duplicate
    # osmnx fetch in _fetch_osm_for_bbox.
    if cg_obj is not None:
        cg_features = city_graph_to_osm_features(cg_obj)
        kernels_queried.append('osm_buildings')
        bld_claims = adapt_osm(
            cg_features,
            corners_lonlat=corners,
            image_size=(img_w, img_h) if img_w and img_h else None,
            feature_kind='building',
        )
        per_kernel_counts['osm_buildings'] = len(bld_claims)
        if not bld_claims:
            silent.append('osm_buildings')
        all_claims.extend(bld_claims)

    osm_fetch_sources = [s for s in ground_truth_sources
                         if not (s == 'osm_buildings' and cg_obj is not None)]
    osm_features = _fetch_osm_for_bbox(
        bbox_geo, sources=osm_fetch_sources
    )
    if 'osm_buildings' in osm_features:
        kernels_queried.append('osm_buildings')
        bld_claims = adapt_osm(
            osm_features['osm_buildings'],
            corners_lonlat=corners,
            image_size=(img_w, img_h) if img_w and img_h else None,
            feature_kind='building',
        )
        per_kernel_counts['osm_buildings'] = len(bld_claims)
        if not bld_claims:
            silent.append('osm_buildings')
        all_claims.extend(bld_claims)
    if 'osm_roads' in osm_features:
        kernels_queried.append('osm_roads')
        road_claims = adapt_osm(
            osm_features['osm_roads'],
            corners_lonlat=corners,
            image_size=(img_w, img_h) if img_w and img_h else None,
            feature_kind='road',
        )
        per_kernel_counts['osm_roads'] = len(road_claims)
        if not road_claims:
            silent.append('osm_roads')
        all_claims.extend(road_claims)

    # 3. Build the SceneGraph.
    taxonomy = PHX_URBAN_V0
    q_s_table = default_q_s_table(taxonomy=taxonomy)
    contributing_sources = sorted({c.source_id for c in all_claims})
    fit = uniform_lambdas(
        sources=contributing_sources or list(q_s_table.keys()),
        taxonomy=taxonomy,
    )

    kc_viewport = Viewport(
        image_size=(img_w, img_h) if img_w and img_h else None,
        bbox_geo=bbox_geo,
        capture_metadata={
            'world_corners': [list(c) for c in corners],
            'camera': viewport_in.get('camera') or {},
            'image_path': viewport_in.get('image_path') or '',
            'captured_at': viewport_in.get('captured_at')
                           or timezone.now().isoformat(),
        },
    )

    min_score = float(data.get('min_score', 0.2))
    iou_threshold = float(data.get('iou_threshold', 0.5))
    edge_proximity = float(data.get('edge_proximity', 0.05))

    try:
        graph = build_scene_graph(
            all_claims,
            taxonomy=taxonomy,
            q_s_table=q_s_table,
            fit=fit,
            viewport=kc_viewport,
            iou_threshold=iou_threshold,
            edge_proximity=edge_proximity,
            min_score=min_score,
            kernels_queried=kernels_queried,
        )
    except Exception as exc:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': f'build_scene_graph raised: {exc}',
            'traceback': traceback.format_exc(),
            'n_claims_in': len(all_claims),
            'kernels_queried': kernels_queried,
        }, status=500)

    # Option-A splice: if we built a CityGraph, lift its road-aware
    # adjacency onto graph.edges (alongside the centroid-IoU edges
    # build_scene_graph just produced) and stash the spectral
    # diagnostics under fusion_metadata['city_graph']. Failures here
    # are non-fatal — the un-spliced SceneGraph is still a valid
    # response.
    cg_meta_block: Optional[Dict[str, Any]] = None
    n_road_edges_added = 0
    if cg_obj is not None:
        try:
            n_road_edges_added = attach_road_edges(graph, cg_obj)
        except Exception as exc:
            print(f'[scenegraph] attach_road_edges failed: {exc}')
        try:
            cg_meta_block = spectral_block(cg_obj)
        except CityGraphUnavailable as exc:
            cg_warning = (cg_warning or '') + f' spectral block skipped: {exc}'
            print(f'[scenegraph] spectral_block unavailable: {exc}')
        except Exception as exc:
            print(f'[scenegraph] spectral_block failed: {exc}')

    graph_dict = graph.to_dict()

    # Hoist OSM cg_node_idx tags from claim attributes onto each
    # node['cg_node_idx'] for cheap client-side lookup. No-op when
    # use_city_graph_regions=False.
    n_cg_annotated = annotate_nodes_with_cg_idx(graph_dict)

    graph_dict.setdefault('fusion_metadata', {})
    graph_dict['fusion_metadata'].update({
        'per_kernel_claim_counts': per_kernel_counts,
        'silent_kernels': silent,
        'orchestrator_elapsed_ms': int((time.perf_counter() - t_start) * 1000),
        'min_score': min_score,
        'iou_threshold': iou_threshold,
        'edge_proximity': edge_proximity,
    })
    if use_city_graph_regions:
        graph_dict['fusion_metadata']['use_city_graph_regions'] = True
        graph_dict['fusion_metadata']['city_graph_options'] = cg_options
        graph_dict['fusion_metadata']['n_cg_annotated_nodes'] = n_cg_annotated
        graph_dict['fusion_metadata']['n_road_edges_added'] = n_road_edges_added
        if cg_meta_block is not None:
            graph_dict['fusion_metadata']['city_graph'] = cg_meta_block
        if cg_warning:
            graph_dict['fusion_metadata']['city_graph_warning'] = cg_warning
        if cg_obj is None and cg_warning is None:
            # User asked for it but we silently produced no city-graph.
            graph_dict['fusion_metadata']['city_graph_warning'] = (
                'No buildings in viewport — city-graph build returned None.'
            )

    # Strip NaN / +Inf / -Inf so both the JS client and SQLite's
    # JSONField check are happy. See _sanitize_json_floats() docstring;
    # OSM tag round-trips are the empirically-dominant source.
    graph_dict = _sanitize_json_floats(graph_dict)

    # 4. Persist artifacts.
    location = viewport_in.get('camera') or {}
    try:
        lat = float(location.get('lat', (bbox_geo[1] + bbox_geo[3]) / 2.0))
        lon = float(location.get('lon', (bbox_geo[0] + bbox_geo[2]) / 2.0))
    except Exception:
        lat, lon = 0.0, 0.0

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    session_id = f"scenegraph_{timestamp}_{_safe_lat_str(lat)}_{_safe_lon_str(lon)}"

    artifact_path = ''
    try:
        SCENEGRAPH_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        session_dir = SCENEGRAPH_RESULTS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(session_dir / 'scene_graph.json', 'w') as f:
            json.dump(graph_dict, f, indent=2)
        with open(session_dir / 'request.json', 'w') as f:
            # Strip kernel_results to keep this small; full per-kernel
            # outputs already live under /app/deepgis_results/<kind>_results.
            json.dump({
                'viewport': viewport_in,
                'ground_truth_sources': ground_truth_sources,
                'kernel_kinds': list(kernel_results.keys()),
                'min_score': min_score,
                'iou_threshold': iou_threshold,
                'edge_proximity': edge_proximity,
            }, f, indent=2)
        artifact_path = str(
            session_dir.relative_to('/app/deepgis_results')
        )
    except Exception as exc:
        print(f"[scenegraph] failed to write artifacts: {exc}")

    # 5. Persist DB row.
    try:
        user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        sampling_session_obj = None
        sampling_session_id = data.get('sampling_session_id')
        if sampling_session_id:
            try:
                sampling_session_obj = SamplingSession.objects.filter(
                    session_id=str(sampling_session_id)
                ).first()
            except Exception:
                sampling_session_obj = None

        SceneGraphRow.objects.create(
            session_id=session_id,
            user=user,
            sampling_session=sampling_session_obj,
            taxonomy_name=taxonomy.name,
            kernels_used=kernels_queried,
            viewport=graph_dict.get('viewport') or {},
            nodes=graph_dict.get('nodes') or [],
            edges=graph_dict.get('edges') or [],
            fusion_metadata=graph_dict.get('fusion_metadata') or {},
            artifact_path=artifact_path,
        )
    except Exception as exc:
        # Persisting is best-effort — the SceneGraph itself is the
        # primary deliverable to the frontend.
        print(f"[scenegraph] failed to persist DB row: {exc}")

    return JsonResponse(
        {
            'status': 'success',
            'session_id': session_id,
            'scene_graph': graph_dict,
            'saved_to': {
                'session_dir': artifact_path,
                'host_path': str(SCENEGRAPH_RESULTS_DIR / session_id).replace(
                    '/app/deepgis_results', './deepgis_results'
                ),
            },
        },
        # allow_nan=False makes any future regression (a NaN that
        # _sanitize_json_floats missed) a loud 500 instead of a silent
        # 200 with malformed JSON that JS rejects mid-parse.
        json_dumps_params={'allow_nan': False},
    )
