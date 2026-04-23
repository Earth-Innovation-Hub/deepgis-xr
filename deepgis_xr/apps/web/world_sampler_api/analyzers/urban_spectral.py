"""Urban spectral analyzer — viewport → OSM building graph → kernelcal.

Implements the ``model_type="urban_spectral"`` branch of the
``POST /webclient/sampler/analyze-viewport`` endpoint.

Unlike the other analyzers in this package, this one consumes a
geographic bounding box (WGS84 degrees) rather than a rendered image.
The bbox is fetched as OSM building footprints via osmnx, built into a
k-NN Gaussian proximity graph on centroids, eigendecomposed, and fed
through the kernelcal MaxCal fixed-point pipeline to yield an
eigenspectrum and a small set of controller-detection diagnostics
(ΔH, Δ′, β₁, Fiedler eigenvalue).

The bridge relies on ``kernelcal.urban.buildings_to_graph_from_bbox``
which in turn calls ``fetch_buildings_bbox`` — both added in the
``feat/osm-bbox-buildings`` branch of the kernelcal repo. If kernelcal
is not installed, the endpoint returns a structured 503 so the client
can show a friendly "spectral analysis unavailable" banner instead of
a 500.
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
    if graph_mode != 'knn':
        return JsonResponse({
            'status': 'error',
            'message': f'graph_mode={graph_mode!r} not implemented yet '
                       f'(only "knn" is wired).',
            'code': 'graph_mode_unsupported',
        }, status=400)

    force_refresh        = bool(data.get('force_refresh', False))
    include_fiedler_vec  = bool(data.get('include_fiedler_vec', True))
    include_centroids    = bool(data.get('include_centroids',   True))

    # Import kernelcal lazily: the server should still answer other
    # analyzer routes if kernelcal is missing.
    try:
        from kernelcal.urban import buildings_to_graph_from_bbox
    except ImportError as exc:
        return JsonResponse({
            'status': 'error',
            'message': (
                'kernelcal is not installed on this server. Install with '
                '"pip install git+https://github.com/darknight-007/kernelcal'
                '@feat/osm-bbox-buildings" or follow ../../INTEGRATION.md.'
            ),
            'code': 'kernelcal_unavailable',
            'detail': str(exc),
        }, status=503)

    # Build the graph (fetch + k-NN + eigendecomp).
    t_build = time.perf_counter()
    try:
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

    return JsonResponse({
        'status':       'ok',
        'n_buildings':  int(cg.positions.shape[0]),
        'n_buildings_total': int(cg.n_buildings),
        'bbox_wgs84':   {'south': south, 'west': west,
                         'north': north, 'east': east},
        'bbox_m':       [float(v) for v in cg.bounds_m],
        'centroids_lonlat': centroids,
        **payload,
        'timings': {
            'graph_build_s':  round(dt_build, 3),
            'spectral_s':     round(dt_spec, 3),
            'total_s':        round(time.perf_counter() - t0, 3),
        },
        'params': {
            'k_nn': k_nn, 'n_max': n_max, 'sigma_frac': sigma_frac,
            'mu2':  mu2,  'sigma2': sigma2, 'tau': tau,
            'graph_mode': graph_mode,
        },
    })
