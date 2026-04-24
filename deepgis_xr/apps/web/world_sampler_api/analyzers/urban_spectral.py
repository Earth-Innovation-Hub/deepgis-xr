"""Urban spectral analyzer — viewport → OSM building graph → kernelcal.

Implements the ``model_type="urban_spectral"`` branch of the
``POST /webclient/sampler/analyze-viewport`` endpoint.

Unlike the other analyzers in this package, this one consumes a
geographic bounding box (WGS84 degrees) rather than a rendered image.
The bbox is fetched as OSM building footprints via osmnx, built into a
proximity graph on centroids, eigendecomposed, and fed through the
kernelcal MaxCal fixed-point pipeline to yield an eigenspectrum and a
small set of controller-detection diagnostics (ΔH, Δ′, β₁, Fiedler
eigenvalue).

Graph modes
-----------
``graph_mode='knn'`` (default)
    Euclidean k-NN on building centroids with Gaussian edge weights. Pure
    geometric proximity — buildings across a highway are "neighbours" iff
    their centroids are close in metres.

``graph_mode='road_knn'``
    k-NN on **road-network distance** between snapped building centroids.
    Adds an ``ox.graph_from_bbox`` call (``network_type`` selectable, defaults
    to ``'drive'``), snaps each centroid to the nearest road node, then
    ranks k-nearest neighbours by shortest-path distance along the street
    graph. This is the "option 1" road-aware variant: buildings separated
    by an impassable boundary (rail cut, canal, unpaved informal fabric)
    become spectral-distant even if Euclidean-close, which is usually what
    a planner-controller analysis wants.

The bridge relies on ``kernelcal.urban.buildings_to_graph_from_bbox``
(``'knn'``) or ``buildings_to_graph_via_roads_from_bbox`` (``'road_knn'``),
both exposed from the ``feat/osm-bbox-buildings`` branch of the kernelcal
repo. If kernelcal is not installed, the endpoint returns a structured 503
so the client can show a friendly "spectral analysis unavailable" banner
instead of a 500.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from django.http import JsonResponse


# ---------------------------------------------------------------------------
# defaults (kept loose; everything is overridable from the POST payload)
# ---------------------------------------------------------------------------

DEFAULT_K_NN         = 8
DEFAULT_N_MAX        = 1500
DEFAULT_SIGMA_FRAC   = 0.05
DEFAULT_MU2          = 2.0
DEFAULT_SIGMA2       = 1.0
DEFAULT_TAU          = 1.0
DEFAULT_TIMEOUT      = 60
MAX_LON_DEGREES      = 4.0   # refuse bboxes wider than this (UTM-zone guard)
MAX_LAT_DEGREES      = 2.0

# Road-aware graph defaults (graph_mode='road_knn').
DEFAULT_NETWORK_TYPE = 'drive'
_ALLOWED_NETWORK_TYPES = {
    'drive', 'drive_service', 'walk', 'bike', 'all', 'all_private',
}
_ALLOWED_GRAPH_MODES = {'knn', 'road_knn'}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _validate_bbox(bbox: dict) -> tuple[float, float, float, float] | JsonResponse:
    """Validate and normalise a bbox payload. Returns tuple or error response."""
    required = {'south', 'west', 'north', 'east'}
    missing  = required - set(bbox or {})
    if missing:
        return JsonResponse({
            'status': 'error',
            'message': f'bbox missing keys: {sorted(missing)}',
        }, status=400)

    try:
        south = float(bbox['south']); west = float(bbox['west'])
        north = float(bbox['north']); east = float(bbox['east'])
    except (TypeError, ValueError) as exc:
        return JsonResponse({
            'status': 'error',
            'message': f'bbox values must be numeric: {exc}',
        }, status=400)

    if not (south < north and west < east):
        return JsonResponse({
            'status': 'error',
            'message': (
                f'Degenerate bbox (south<north, west<east required): '
                f'S={south} W={west} N={north} E={east}'
            ),
        }, status=400)

    lon_span = east - west
    lat_span = north - south
    if lon_span > MAX_LON_DEGREES or lat_span > MAX_LAT_DEGREES:
        return JsonResponse({
            'status': 'error',
            'message': (
                f'Viewport too wide for single-UTM-zone spectral analysis '
                f'(Δlon={lon_span:.2f}°, Δlat={lat_span:.2f}°). '
                f'Zoom in until span < {MAX_LON_DEGREES}° × {MAX_LAT_DEGREES}°.'
            ),
            'code': 'bbox_too_wide',
        }, status=400)

    return (south, west, north, east)


def _centroids_to_lonlat(cg) -> list[list[float]]:
    """Reproject the (UTM) CityGraph.positions back to WGS84 for the client."""
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError:
        return []

    utm_crs = cg.raw_gdf.crs if cg.raw_gdf is not None else None
    if utm_crs is None:
        return []

    pts = gpd.GeoSeries(
        [Point(x, y) for x, y in cg.positions], crs=utm_crs,
    ).to_crs('EPSG:4326')
    return [[float(p.x), float(p.y)] for p in pts]


def _edges_and_polylines(
    cg,
    centroids_lonlat: list[list[float]],
    include_polylines: bool,
    max_edges: int | None = None,
) -> tuple[list[dict], list[list[list[float]]]]:
    """Extract the CityGraph adjacency as an edge list for the Cesium client.

    Returns
    -------
    (edges, edge_polylines)
        * ``edges`` — list of ``{'i', 'j', 'w'}`` dicts, one per unique
          undirected edge (i < j) in ``cg.W``. Weights are the Gaussian
          adjacency values kernelcal computed and are already in [0, 1],
          so the client can use them directly as an alpha channel.
        * ``edge_polylines`` — parallel to ``edges``; each entry is a
          list of ``[lon, lat]`` pairs to draw.
            - For ``graph_mode='knn'`` every polyline is a two-point
              straight line between the two building centroids.
            - For ``graph_mode='road_knn'`` polylines trace the actual
              shortest path through the OSM road graph — centroid[i] →
              snap_node[i] → intermediate road nodes → snap_node[j] →
              centroid[j] — so the user can see the edge hugging the
              streets instead of flying through buildings.

    The polyline set is capped at ``max_edges`` (falsy → no cap) to keep
    response size bounded on dense viewports.
    """
    W = cg.W
    n = W.shape[0]

    # Flat (i, j) upper-triangle enumeration. Using numpy here to avoid a
    # ~N²/2 Python loop on medium viewports.
    iu, ju = np.triu_indices(n, k=1)
    mask   = W[iu, ju] > 0.0
    iu, ju = iu[mask], ju[mask]
    wts    = W[iu, ju]

    # If we'd exceed max_edges, keep the strongest ones — they're the
    # ones the Fiedler-difference coloring will highlight anyway.
    if max_edges is not None and max_edges > 0 and len(iu) > max_edges:
        keep = np.argsort(wts)[::-1][:max_edges]
        iu, ju, wts = iu[keep], ju[keep], wts[keep]

    edges: list[dict] = []
    polylines: list[list[list[float]]] = []

    # Road-path reconstruction needs the (optional) raw road graph and
    # the per-building snap-node ids that kernelcal stashed on road_meta.
    G_roads       = getattr(cg, 'raw_road_graph', None)
    snap_node_ids = (cg.road_meta or {}).get('snap_node_ids') if hasattr(cg, 'road_meta') else None
    road_mode     = (
        getattr(cg, 'graph_mode', 'knn') == 'road_knn'
        and G_roads is not None
        and snap_node_ids is not None
        and include_polylines
    )
    if road_mode:
        # Lazy-import networkx only on the path that actually needs it;
        # keeps the knn branch dependency-free.
        import networkx as nx
        # Reproject road-graph node coordinates back to WGS84 once so we
        # don't hit the shapely CRS machinery inside the inner loop. We
        # stashed ``lon``/``lat`` on the nodes inside fetch_road_graph_bbox
        # before projecting; use them directly when present.
        node_lonlat: dict = {}
        missing: list = []
        for nd, data in G_roads.nodes(data=True):
            if 'lon' in data and 'lat' in data:
                node_lonlat[nd] = [float(data['lon']), float(data['lat'])]
            else:
                missing.append(nd)
        if missing:
            # Fallback: reproject the UTM x/y back to WGS84 in one batch.
            try:
                import geopandas as gpd
                from shapely.geometry import Point
                utm_crs = G_roads.graph.get('crs')
                if utm_crs is not None:
                    pts = [Point(G_roads.nodes[n].get('x', 0.0),
                                 G_roads.nodes[n].get('y', 0.0))
                           for n in missing]
                    wgs = gpd.GeoSeries(pts, crs=utm_crs).to_crs('EPSG:4326')
                    for nd, p in zip(missing, wgs):
                        node_lonlat[nd] = [float(p.x), float(p.y)]
            except Exception:
                # Missing coords → that edge falls back to a straight line.
                pass

    for idx in range(len(iu)):
        i, j, w = int(iu[idx]), int(ju[idx]), float(wts[idx])
        edges.append({'i': i, 'j': j, 'w': w})
        if not include_polylines:
            continue

        # Defensive bounds check — centroids_lonlat might be empty if the
        # caller passed include_centroids=false while still asking for edges.
        ci = centroids_lonlat[i] if i < len(centroids_lonlat) else None
        cj = centroids_lonlat[j] if j < len(centroids_lonlat) else None
        if ci is None or cj is None:
            polylines.append([])
            continue

        if not road_mode:
            polylines.append([list(ci), list(cj)])
            continue

        si = snap_node_ids[i] if i < len(snap_node_ids) else None
        sj = snap_node_ids[j] if j < len(snap_node_ids) else None
        coords: list[list[float]] = [list(ci)]
        if si is not None and sj is not None and si in node_lonlat and sj in node_lonlat:
            try:
                path = nx.shortest_path(G_roads, si, sj, weight='length')
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                path = [si, sj]
            for nd in path:
                p = node_lonlat.get(nd)
                if p is not None:
                    coords.append(p)
        coords.append(list(cj))
        polylines.append(coords)

    return edges, polylines


def _run_spectral_diagnostics(
    cg,
    mu2: float,
    sigma2: float,
    tau: float,
    k_nn: int,
) -> dict[str, Any]:
    """Compute kernelcal diagnostics for a CityGraph.

    Mirrors the ``run_kernelcal`` helper from
    ``examples/urban/osm_urban_kernelcal.py`` but trimmed to what the
    viewport client actually plots (eigvals, h0/h*, ΔH, Δ′, β₁, λ_fiedler).
    """
    from kernelcal.terrain.diagnostics import (
        fiedler_mode_gap,
        fixed_point_kernel,
        spectral_entropy,
    )
    from kernelcal.spectral.graph import SpectralGraph

    eigvals = cg.eigvals.copy()
    n       = int(eigvals.size)

    # kernelcal convention: shift degenerate zero modes to avoid ÷0 in the
    # fixed-point iteration
    w_modes    = eigvals.copy()
    n_zero     = int(np.sum(eigvals < 1e-6))
    if n_zero < n:
        w_modes[:n_zero] = eigvals[n_zero]
    else:
        w_modes[:] = 1e-3

    # heat-kernel vacuum (τ chosen to normalise across viewport sizes if τ<=0)
    if tau <= 0:
        lam_max = float(eigvals[-1]) if eigvals[-1] > 0 else 1.0
        tau = 1.0 / lam_max
    h0 = np.maximum(np.exp(-eigvals * tau), 1e-10)

    # fixed-point kernel (the controller signature)
    h_star, info = fixed_point_kernel(
        cg.L, h0=h0, mu2=mu2, sigma2=sigma2, w=w_modes,
    )
    h_star = np.maximum(h_star, 1e-8)

    H_obs   = float(spectral_entropy(h_star))
    H_vac   = float(spectral_entropy(h0))
    delta_p = float(fiedler_mode_gap(h_star, cg.L, mu2=mu2, sigma2=sigma2, w=w_modes))

    # β₁ vs a k-NN null
    n_edges     = int((cg.W > 0).sum()) // 2
    beta0       = n_zero
    beta1       = max(0, n_edges - (n - beta0))
    e_null      = k_nn * n // 2
    beta1_null  = max(0, e_null - (n - 1))
    delta_beta1 = beta1 - beta1_null

    # Fiedler eigenvector = lowest-freq non-trivial mode; useful for UI overlay
    fiedler_idx = n_zero if n_zero < n else 1
    fiedler_vec = cg.eigvecs[:, fiedler_idx].astype(float).tolist()
    lam_fiedler = float(eigvals[fiedler_idx]) if fiedler_idx < n else 0.0

    # expose the SpectralGraph wrapper only to derive heat weights for
    # clients that want an alternative baseline than exp(-λτ)
    sg = SpectralGraph(cg.L)

    return {
        'eigvals':      eigvals.astype(float).tolist(),
        'h0':           h0.astype(float).tolist(),
        'h_star':       h_star.astype(float).tolist(),
        'fiedler_vec':  fiedler_vec,
        'fiedler_value': float(sg.fiedler_value),
        'diagnostics': {
            'H_obs':       H_obs,
            'H_vac':       H_vac,
            'delta_H':     H_obs - H_vac,
            'delta_prime': delta_p,
            'beta0':       int(beta0),
            'beta1':       int(beta1),
            'beta1_null':  int(beta1_null),
            'delta_beta1': int(delta_beta1),
            'lam_fiedler': lam_fiedler,
            'n_edges':     int(n_edges),
            'n_zero_modes': int(n_zero),
            'converged':   bool(info.get('converged', False)),
            'n_iter':      int(info.get('n_iter', 0)),
            'tau':         float(tau),
            'mu2':         float(mu2),
            'sigma2':      float(sigma2),
        },
    }


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def _analyze_viewport_urban_spectral(data: dict) -> JsonResponse:
    """Handle ``model_type="urban_spectral"``.

    Expected POST body (additions beyond the shared envelope are flagged †):

    ```
    {
      "model_type": "urban_spectral",
      "bbox": { "south": 37.77, "west": -122.43,           †
                "north": 37.78, "east":  -122.41 },
      "k":            8,            // optional, default 8
      "n_max":        1500,         // optional, default 1500
      "sigma_frac":   0.05,         // optional
      "tau":          1.0,          // optional; <=0 ⇒ auto 1/λ_max
      "mu2":          2.0,          // optional
      "sigma2":       1.0,          // optional
      "graph_mode":   "knn",        // reserved — only "knn" wired today
      "force_refresh": false,        // bypass on-disk osmnx cache
      "timeout":      60,           // osmnx Overpass timeout (s)
      "include_fiedler_vec": true,   // strip from response if false
      "include_centroids":   true
    }
    ```

    Response JSON ``{status, n_buildings, bbox_m, eigvals, h0, h_star,
    fiedler_vec, fiedler_value, diagnostics, centroids_lonlat, timings}``.
    """
    t0 = time.perf_counter()

    bbox_or_err = _validate_bbox(data.get('bbox', {}))
    if isinstance(bbox_or_err, JsonResponse):
        return bbox_or_err
    south, west, north, east = bbox_or_err

    # Params (validated via type coercion; defaults match kernelcal examples).
    try:
        k_nn       = int(data.get('k',          DEFAULT_K_NN))
        n_max      = int(data.get('n_max',      DEFAULT_N_MAX))
        sigma_frac = float(data.get('sigma_frac', DEFAULT_SIGMA_FRAC))
        mu2        = float(data.get('mu2',       DEFAULT_MU2))
        sigma2     = float(data.get('sigma2',    DEFAULT_SIGMA2))
        tau        = float(data.get('tau',       DEFAULT_TAU))
        timeout    = int(data.get('timeout',    DEFAULT_TIMEOUT))
    except (TypeError, ValueError) as exc:
        return JsonResponse({
            'status': 'error',
            'message': f'Invalid numeric parameter: {exc}',
        }, status=400)

    graph_mode = str(data.get('graph_mode', 'knn'))
    if graph_mode not in _ALLOWED_GRAPH_MODES:
        return JsonResponse({
            'status': 'error',
            'message': f'graph_mode={graph_mode!r} not supported. '
                       f'Allowed: {sorted(_ALLOWED_GRAPH_MODES)}.',
            'code': 'graph_mode_unsupported',
        }, status=400)

    # Road-aware mode takes an extra `network_type` selector plus an
    # optional Dijkstra cutoff. Defaults keep the endpoint callable with
    # just `graph_mode="road_knn"`.
    network_type = str(data.get('network_type', DEFAULT_NETWORK_TYPE))
    if graph_mode == 'road_knn' and network_type not in _ALLOWED_NETWORK_TYPES:
        return JsonResponse({
            'status': 'error',
            'message': f'network_type={network_type!r} not supported. '
                       f'Allowed: {sorted(_ALLOWED_NETWORK_TYPES)}.',
            'code': 'network_type_unsupported',
        }, status=400)
    try:
        max_network_dist = data.get('max_network_dist', None)
        if max_network_dist is not None:
            max_network_dist = float(max_network_dist)
    except (TypeError, ValueError) as exc:
        return JsonResponse({
            'status': 'error',
            'message': f'Invalid max_network_dist: {exc}',
        }, status=400)
    simplify_roads = bool(data.get('simplify_roads', True))

    force_refresh        = bool(data.get('force_refresh', False))
    include_fiedler_vec  = bool(data.get('include_fiedler_vec', True))
    include_centroids    = bool(data.get('include_centroids',   True))
    # Edge rendering toggles. ``include_edges`` switches on the (i, j, w)
    # adjacency list; ``include_edge_polylines`` additionally emits a
    # ``[[lon, lat], …]`` polyline per edge (road-aware in ``road_knn``
    # mode). ``max_edges`` caps the response size on dense viewports.
    include_edges          = bool(data.get('include_edges',          True))
    include_edge_polylines = bool(data.get('include_edge_polylines', True))
    try:
        max_edges_raw = data.get('max_edges', 6000)
        max_edges = int(max_edges_raw) if max_edges_raw is not None else None
        if max_edges is not None and max_edges <= 0:
            max_edges = None
    except (TypeError, ValueError):
        max_edges = 6000

    # Import kernelcal lazily: the server should still answer other
    # analyzer routes if kernelcal is missing.
    try:
        if graph_mode == 'road_knn':
            from kernelcal.urban import buildings_to_graph_via_roads_from_bbox
        else:
            from kernelcal.urban import buildings_to_graph_from_bbox
    except ImportError as exc:
        return JsonResponse({
            'status': 'error',
            'message': (
                'kernelcal is not installed on this server (or is missing '
                'the road-aware helpers from kernelcal.urban). Install/upgrade '
                'with "pip install -U git+https://github.com/darknight-007/'
                'kernelcal@feat/osm-bbox-buildings" or follow '
                '../../INTEGRATION.md.'
            ),
            'code': 'kernelcal_unavailable',
            'detail': str(exc),
        }, status=503)

    # Build the graph (fetch + k-NN + eigendecomp).
    t_build = time.perf_counter()
    try:
        if graph_mode == 'road_knn':
            cg = buildings_to_graph_via_roads_from_bbox(
                south=south, west=west, north=north, east=east,
                k=k_nn, n_max=n_max, sigma_frac=sigma_frac,
                network_type=network_type,
                simplify=simplify_roads,
                max_network_dist=max_network_dist,
                force_refresh=force_refresh,
                timeout=timeout,
            )
        else:
            cg = buildings_to_graph_from_bbox(
                south=south, west=west, north=north, east=east,
                k=k_nn, n_max=n_max, sigma_frac=sigma_frac,
                force_refresh=force_refresh,
                timeout=timeout,
            )
    except RuntimeError as exc:  # e.g., Overpass timeout
        return JsonResponse({
            'status': 'error',
            'message': f'OSM fetch failed: {exc}',
            'code':    'osm_fetch_failed',
        }, status=503)
    except Exception as exc:
        import traceback
        return JsonResponse({
            'status':    'error',
            'message':   str(exc),
            'traceback': traceback.format_exc(),
            'code':      'graph_build_failed',
        }, status=500)
    dt_build = time.perf_counter() - t_build

    if cg is None:
        return JsonResponse({
            'status':      'ok',
            'n_buildings': 0,
            'message':     'No buildings in viewport.',
            'bbox':        {'south': south, 'west': west,
                            'north': north, 'east': east},
        })

    # Run kernelcal diagnostics on the graph.
    t_spec = time.perf_counter()
    try:
        payload = _run_spectral_diagnostics(
            cg, mu2=mu2, sigma2=sigma2, tau=tau, k_nn=k_nn,
        )
    except Exception as exc:
        import traceback
        return JsonResponse({
            'status':    'error',
            'message':   f'Spectral diagnostics failed: {exc}',
            'traceback': traceback.format_exc(),
            'code':      'spectral_failed',
        }, status=500)
    dt_spec = time.perf_counter() - t_spec

    if not include_fiedler_vec:
        payload.pop('fiedler_vec', None)

    centroids = _centroids_to_lonlat(cg) if include_centroids else []

    # Edge list + (optionally) per-edge WGS84 polylines. We always need the
    # centroids to anchor the polylines, so if the caller disabled
    # ``include_centroids`` but asked for edges we still reproject them
    # locally — the centroids just aren't echoed in the top-level payload.
    edges: list[dict] = []
    edge_polylines: list[list[list[float]]] = []
    if include_edges:
        centroids_for_edges = centroids or _centroids_to_lonlat(cg)
        try:
            edges, edge_polylines = _edges_and_polylines(
                cg,
                centroids_for_edges,
                include_polylines=include_edge_polylines,
                max_edges=max_edges,
            )
        except Exception as exc:
            # Edge rendering is a visualization aid — never 500 the whole
            # analysis because a networkx path lookup hiccupped. Log
            # structurally and keep going.
            import traceback
            edges = []
            edge_polylines = []
            payload.setdefault('warnings', []).append({
                'where':     'edges_and_polylines',
                'message':   str(exc),
                'traceback': traceback.format_exc().splitlines()[-3:],
            })

    # Surface road-aware diagnostics on the response so the Cesium client
    # can render snap/reachability warnings without a second round-trip.
    # `effective_graph_mode` differs from the requested one when the road
    # fetcher degraded to Euclidean k-NN (e.g. viewport with buildings but
    # no drivable roads).
    effective_graph_mode = getattr(cg, 'graph_mode', 'knn')
    road_meta            = dict(getattr(cg, 'road_meta', {}) or {})
    # snap_node_ids is a server-internal handle for _edges_and_polylines;
    # the client doesn't need it (edge_polylines already carries the
    # reconstructed geometry) and it can be ~1500 entries wide.
    road_meta.pop('snap_node_ids', None)

    return JsonResponse({
        'status':       'ok',
        'n_buildings':  int(cg.positions.shape[0]),
        'n_buildings_total': int(cg.n_buildings),
        'bbox_wgs84':   {'south': south, 'west': west,
                         'north': north, 'east': east},
        'bbox_m':       [float(v) for v in cg.bounds_m],
        'centroids_lonlat': centroids,
        'graph_mode':   effective_graph_mode,
        'road_meta':    road_meta,
        'edges':        edges,
        'edge_polylines': edge_polylines,
        **payload,
        'timings': {
            'graph_build_s':  round(dt_build, 3),
            'spectral_s':     round(dt_spec, 3),
            'total_s':        round(time.perf_counter() - t0, 3),
        },
        'params': {
            'k_nn': k_nn, 'n_max': n_max, 'sigma_frac': sigma_frac,
            'mu2':  mu2,  'sigma2': sigma2, 'tau': tau,
            'graph_mode':       graph_mode,
            'network_type':     network_type if graph_mode == 'road_knn' else None,
            'simplify_roads':   simplify_roads if graph_mode == 'road_knn' else None,
            'max_network_dist': max_network_dist,
        },
    })
