"""
City-graph bridge between the urban-spectral pipeline and the
Distinction-Game SceneGraph orchestrator.

Until now the two halves of the deepgis-xr / kernelcal stack ran in
separate tabs:

  * **Urban spectral** (``world_sampler_api/analyzers/urban_spectral.py``)
    builds a road-aware OSM building graph and emits its eigenspectrum
    + Fiedler structure. Topology-rich, semantics-poor (every node is
    "building").
  * **SceneGraph** (``world_sampler_api/scenegraph.py``) fuses
    multi-kernel claims into a category posterior over PHX_URBAN_V0
    via :func:`kernelcal.distinction_game.build_scene_graph`, but
    invents its own (centroid-IoU) adjacency.

This module is the merge surface (Option A from the design doc):

  * Use a :class:`kernelcal.urban.CityGraph` as the **region partition
    backbone** for the SceneGraph build — every OSM building becomes
    one persistent node identified by its CityGraph index, surviving
    the orchestrator's IoU clustering through a stamped attribute.
  * Use the CityGraph's **road-aware adjacency** as additional
    ``relation='road_adjacent'`` :class:`SceneEdge`s on the
    SceneGraph, alongside (not replacing) the centroid-proximity
    edges. Edge weight = the kernelcal Gaussian similarity already on
    ``cg.W``; ``cg_i`` / ``cg_j`` end up in ``attributes`` so the
    Cesium overlay can re-trace road polylines if it has the raw
    road graph.
  * Compute spectral diagnostics on the CityGraph (eigenvals, Fiedler
    eigenvalue + vector, ΔH, β₁, …) and stash them in
    ``fusion_metadata['city_graph']`` so any consumer — admin
    detail page, mgmt-command renderer, future PR-3 analytics —
    can colour/score nodes by spectral mode in addition to argmax
    category.

The module is additive: when the orchestrator is called without
``use_city_graph_regions=True`` nothing here runs and behaviour is
identical to the pre-merge endpoint.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ── error contract ──────────────────────────────────────────────────────


class CityGraphUnavailable(RuntimeError):
    """Raised when kernelcal.urban (or osmnx) is missing on this server.

    The orchestrator catches this and falls back to the standard
    bbox-IoU scene graph, returning a structured warning to the client
    so the UI can flip the checkbox off and surface a banner.
    """


# ── (1) build a CityGraph for a viewport bbox ───────────────────────────

# Mirrors the defaults in urban_spectral.py so the merged pipeline
# behaves identically to the standalone tab when called with the same
# viewport. Loose by design — every value is overridable from the
# orchestrator request payload.
DEFAULT_K_NN          = 8
DEFAULT_N_MAX         = 1500
DEFAULT_SIGMA_FRAC    = 0.05
DEFAULT_NETWORK_TYPE  = 'drive'
DEFAULT_TIMEOUT       = 60

_ALLOWED_NETWORK_TYPES = {
    'drive', 'drive_service', 'walk', 'bike', 'all', 'all_private',
}
_ALLOWED_GRAPH_MODES = {'knn', 'road_knn'}


def build_city_graph_for_bbox(
    bbox_geo: Tuple[float, float, float, float],
    *,
    graph_mode: str = 'road_knn',
    k: int = DEFAULT_K_NN,
    n_max: int = DEFAULT_N_MAX,
    sigma_frac: float = DEFAULT_SIGMA_FRAC,
    network_type: str = DEFAULT_NETWORK_TYPE,
    simplify: bool = True,
    max_network_dist: Optional[float] = None,
    force_refresh: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[Any]:
    """Fetch OSM buildings (and optionally roads) for ``bbox_geo`` and
    build a kernelcal :class:`CityGraph` on top of them.

    ``bbox_geo`` is ``(west, south, east, north)`` — same convention
    the orchestrator uses for its viewport corner reduction.

    Returns the ``CityGraph`` (or ``None`` if the bbox holds no
    buildings, mirroring the urban-spectral analyzer's contract).
    Raises :class:`CityGraphUnavailable` if kernelcal isn't installed
    (orchestrator catches this).
    """
    if graph_mode not in _ALLOWED_GRAPH_MODES:
        raise ValueError(
            f'graph_mode={graph_mode!r} not supported. '
            f'Allowed: {sorted(_ALLOWED_GRAPH_MODES)}'
        )
    if graph_mode == 'road_knn' and network_type not in _ALLOWED_NETWORK_TYPES:
        raise ValueError(
            f'network_type={network_type!r} not supported. '
            f'Allowed: {sorted(_ALLOWED_NETWORK_TYPES)}'
        )

    try:
        if graph_mode == 'road_knn':
            from kernelcal.urban import buildings_to_graph_via_roads_from_bbox
        else:
            from kernelcal.urban import buildings_to_graph_from_bbox
    except ImportError as exc:
        raise CityGraphUnavailable(
            'kernelcal.urban is not available on this server. '
            'Install/upgrade with the editable bind-mount or '
            f'pip install -U kernelcal[urban]. ({exc})'
        ) from exc

    west, south, east, north = bbox_geo
    if graph_mode == 'road_knn':
        return buildings_to_graph_via_roads_from_bbox(
            south=south, west=west, north=north, east=east,
            k=k, n_max=n_max, sigma_frac=sigma_frac,
            network_type=network_type,
            simplify=simplify,
            max_network_dist=max_network_dist,
            force_refresh=force_refresh,
            timeout=timeout,
        )
    return buildings_to_graph_from_bbox(
        south=south, west=west, north=north, east=east,
        k=k, n_max=n_max, sigma_frac=sigma_frac,
        force_refresh=force_refresh,
        timeout=timeout,
    )


# ── (2) project a CityGraph back into OSM-feature dicts ─────────────────


def city_graph_to_osm_features(cg: Any, *, limit: int = 1500) -> List[Dict[str, Any]]:
    """Convert ``cg.raw_gdf`` into the same OSM-feature dict shape
    :func:`adapt_osm` expects (``{osm_id, geometry, centroid, tags}``),
    **with ``tags['cg_node_idx']`` stamped** so downstream code can
    map fused SceneNodes back to CityGraph nodes after fusion.

    Why we don't just call :func:`http._gdf_to_features` and post-stamp:
    the order of ``cg.raw_gdf.iterrows()`` is the order of ``cg.positions``
    (kernelcal builds the graph from that gdf one-to-one), so the row
    index *is* the CityGraph node index. Doing the conversion here
    keeps that invariant local to this module.
    """
    try:
        from shapely.geometry import mapping
    except ImportError as exc:  # pragma: no cover — shapely is a kernelcal dep
        raise CityGraphUnavailable(
            f'shapely missing while converting CityGraph features: {exc}'
        ) from exc

    out: List[Dict[str, Any]] = []
    gdf = getattr(cg, 'raw_gdf', None)
    if gdf is None or getattr(gdf, 'empty', True):
        return out

    # cg.positions and cg.raw_gdf are zipped 1:1 by construction in
    # buildings_to_graph_*; iterating rows gives us the right cg index.
    for cg_idx, (_, row) in enumerate(gdf.head(limit).iterrows()):
        if cg_idx >= len(cg.positions):
            # Defensive: head(limit) shouldn't truncate below positions
            # but if a future kernelcal change introduces filtering we
            # stop here so cg_idx stays consistent with cg.W.
            break
        geom = row.get('geometry')
        if geom is None or getattr(geom, 'is_empty', False):
            continue
        centroid = geom.centroid
        tags: Dict[str, Any] = {'cg_node_idx': int(cg_idx)}
        for key, value in row.items():
            if key == 'geometry' or value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                tags[key] = value
        out.append({
            'osm_id': str(row.get('osmid', cg_idx)),
            'geometry': mapping(geom),
            'centroid': {'lon': float(centroid.x), 'lat': float(centroid.y)},
            'tags': tags,
        })
    return out


# ── (3) splice CityGraph regions/edges into a built SceneGraph ──────────


def _scene_node_to_cg_idx(node: Any) -> Optional[int]:
    """Return the CityGraph node index this SceneNode originated from,
    or ``None`` if no contributing claim carried one.

    The :func:`adapt_osm` adapter forwards feature ``tags`` straight
    through into ``KernelClaim.attributes['tags']``; we stash
    ``cg_node_idx`` there in step (2). One scene-node can absorb
    multiple OSM-building claims after IoU association — pick the
    *first* such index we see, which corresponds to the highest-IoU
    OSM match (kernelcal's association is greedy by IoU).
    """
    for claim in (node.claims or []):
        attrs = getattr(claim, 'attributes', None) or {}
        tags = attrs.get('tags') if isinstance(attrs, Mapping) else None
        if isinstance(tags, Mapping):
            idx = tags.get('cg_node_idx')
            if isinstance(idx, int):
                return idx
    return None


def _build_scenenode_index(graph: Any) -> Dict[int, str]:
    """Map ``cg_idx → scene_node.id`` for every node that absorbed an
    OSM-building claim with a stamped CityGraph index. Used to
    translate CityGraph edges into :class:`SceneEdge`s."""
    out: Dict[int, str] = {}
    for n in (graph.nodes or []):
        idx = _scene_node_to_cg_idx(n)
        if idx is None:
            continue
        # Last-write-wins is fine here: if two scene-nodes both claim
        # the same cg index (rare; they'd have to be near-duplicate
        # IoU clusters), we pick the later one. The first-write-wins
        # alternative biases toward whichever came out of build_scene_graph
        # first, which is implementation detail; either is acceptable
        # because the spectral analytics treat both the same.
        out[idx] = n.id
    return out


def attach_road_edges(graph: Any, cg: Any) -> int:
    """Append road-aware :class:`SceneEdge`s derived from ``cg.W``
    onto ``graph.edges``. Returns the number of edges added.

    The CityGraph stores symmetric Gaussian similarity in ``cg.W``;
    we walk the upper triangle, look up which scene-node each end
    landed in, and emit an undirected ``relation='road_adjacent'``
    edge with weight = ``cg.W[i, j]`` and ``cg_i`` / ``cg_j`` in
    attributes. Only emits edges where *both* endpoints survived
    the SceneGraph fusion (i.e. an OSM-building claim landed in a
    final scene-node, which excludes regions whose claims were
    out-shouted by other kernels with very different bboxes).
    """
    import numpy as np
    from kernelcal.distinction_game import SceneEdge  # type: ignore

    W = getattr(cg, 'W', None)
    if W is None or W.size == 0:
        return 0
    cg_to_node = _build_scenenode_index(graph)
    if not cg_to_node:
        return 0

    iu, ju = np.triu_indices(W.shape[0], k=1)
    mask = W[iu, ju] > 0.0
    iu, ju = iu[mask], ju[mask]
    wts = W[iu, ju]

    n_added = 0
    for k in range(len(iu)):
        ci, cj = int(iu[k]), int(ju[k])
        ni = cg_to_node.get(ci)
        nj = cg_to_node.get(cj)
        if not ni or not nj or ni == nj:
            continue
        graph.edges.append(
            SceneEdge(
                source=ni,
                target=nj,
                relation='road_adjacent',
                weight=float(wts[k]),
                attributes={
                    'cg_i': ci,
                    'cg_j': cj,
                    'edge_source': 'city_graph',
                    'graph_mode': getattr(cg, 'graph_mode', 'knn'),
                },
            )
        )
        n_added += 1
    return n_added


# ── (4) spectral diagnostics block ──────────────────────────────────────


def spectral_block(
    cg: Any,
    *,
    mu2: float = 2.0,
    sigma2: float = 1.0,
    tau: float = 1.0,
    k_nn: int = DEFAULT_K_NN,
) -> Dict[str, Any]:
    """Compute the kernelcal spectral diagnostics on a CityGraph and
    return a JSON-serialisable dict suitable for stashing under
    ``fusion_metadata['city_graph']``.

    Mirrors the body of :func:`urban_spectral._run_spectral_diagnostics`
    but trimmed for orchestrator persistence: we skip ``h0``/``h_star``
    full vectors (they bloat the JSON to MBs at viewport scale) and keep
    just eigvals + Fiedler + scalar diagnostics.
    """
    import numpy as np

    try:
        from kernelcal.terrain.diagnostics import (
            fiedler_mode_gap,
            fixed_point_kernel,
            spectral_entropy,
        )
        from kernelcal.spectral.graph import SpectralGraph
    except ImportError as exc:
        raise CityGraphUnavailable(
            f'kernelcal diagnostics unavailable: {exc}'
        ) from exc

    eigvals = cg.eigvals.copy()
    n = int(eigvals.size)
    w_modes = eigvals.copy()
    n_zero = int(np.sum(eigvals < 1e-6))
    if n_zero < n:
        w_modes[:n_zero] = eigvals[n_zero]
    else:
        w_modes[:] = 1e-3

    if tau <= 0:
        lam_max = float(eigvals[-1]) if eigvals[-1] > 0 else 1.0
        tau = 1.0 / lam_max
    h0 = np.maximum(np.exp(-eigvals * tau), 1e-10)

    h_star, info = fixed_point_kernel(
        cg.L, h0=h0, mu2=mu2, sigma2=sigma2, w=w_modes,
    )
    h_star = np.maximum(h_star, 1e-8)

    H_obs = float(spectral_entropy(h_star))
    H_vac = float(spectral_entropy(h0))
    delta_p = float(fiedler_mode_gap(
        h_star, cg.L, mu2=mu2, sigma2=sigma2, w=w_modes,
    ))

    n_edges = int((cg.W > 0).sum()) // 2
    beta0 = n_zero
    beta1 = max(0, n_edges - (n - beta0))
    e_null = k_nn * n // 2
    beta1_null = max(0, e_null - (n - 1))
    delta_beta1 = beta1 - beta1_null

    fiedler_idx = n_zero if n_zero < n else 1
    fiedler_vec = cg.eigvecs[:, fiedler_idx].astype(float).tolist() \
        if fiedler_idx < n else []
    lam_fiedler = float(eigvals[fiedler_idx]) if fiedler_idx < n else 0.0

    sg = SpectralGraph(cg.L)

    return {
        'graph_mode':   getattr(cg, 'graph_mode', 'knn'),
        'n_nodes':      n,
        'n_edges':      n_edges,
        # Top eigenvalues only — the full spectrum lives on the
        # standalone urban-spectral endpoint if the user wants it.
        'eigvals_low':  eigvals[: min(64, n)].astype(float).tolist(),
        'fiedler_value': float(sg.fiedler_value),
        'fiedler_vec':  fiedler_vec,  # length n; used by overlays
        'lam_fiedler':  lam_fiedler,
        'diagnostics': {
            'H_obs':        H_obs,
            'H_vac':        H_vac,
            'delta_H':      H_obs - H_vac,
            'delta_prime':  delta_p,
            'beta0':        int(beta0),
            'beta1':        int(beta1),
            'beta1_null':   int(beta1_null),
            'delta_beta1':  int(delta_beta1),
            'n_zero_modes': int(n_zero),
            'converged':    bool(info.get('converged', False)),
            'n_iter':       int(info.get('n_iter', 0)),
            'tau':          float(tau),
            'mu2':          float(mu2),
            'sigma2':       float(sigma2),
        },
    }


# ── (5) per-node cg-index annotation for the response ───────────────────


def annotate_nodes_with_cg_idx(graph_dict: Dict[str, Any]) -> int:
    """After ``graph.to_dict()``, walk each node's claims and lift the
    ``cg_node_idx`` stamped in ``adapt_osm`` up to a top-level
    ``node['cg_node_idx']`` field for easy lookup by clients.

    Returns the count of annotated nodes. Mutates ``graph_dict`` in
    place.
    """
    n = 0
    for node in graph_dict.get('nodes') or []:
        for claim in node.get('claims') or []:
            attrs = claim.get('attributes') or {}
            tags = attrs.get('tags') or {}
            idx = tags.get('cg_node_idx')
            if isinstance(idx, int):
                node['cg_node_idx'] = idx
                n += 1
                break
    return n
