"""
Shared SceneGraph visualization helpers.

Renders ``SceneGraph`` rows into PNG figures. Two consumers:

  * ``apps/web/management/commands/visualize_scene_graphs.py`` — the CLI
    batch tool for rendering many rows at once or generating a gallery.
  * ``apps/web/admin.py`` (``SceneGraphAdmin``) — the Django admin's
    detail page embeds the per-scene visualization inline and serves
    the PNG bytes through a custom admin view.

Pulling the rendering out of the management command lets both call
sites share the colour palette, geometry-space picker, alpha
modulation, and edge cap policy without one drifting from the other.
The ``CATEGORY_COLORS`` table here is the single source of truth — it
mirrors ``staticfiles/web/js/world-sampler-ui.js#displaySceneGraph``'s
``colorByCategory`` so the live Cesium overlay, the offline mgmt
output, and the admin thumbnail all agree.

All renderers are pure-functional: they take a SceneGraph-like row
(anything exposing ``nodes``, ``edges``, ``viewport``,
``fusion_metadata``, ``kernels_used``, ``session_id``) and a target
path, and return the path (or ``None`` if the row had no usable
geometry). Matplotlib is imported lazily so the module can be imported
in environments without it (e.g. minimal containers).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple


# ── canonical category palette ──────────────────────────────────────────

# Mirrors world-sampler-ui.js#colorByCategory. Adding a category to the
# kernelcal taxonomy means adding it here too — keep them in sync.
CATEGORY_COLORS: Dict[str, str] = {
    'unknown':           '#94a3b8',  # slate
    'building':          '#3b82f6',  # blue
    'road':              '#facc15',  # yellow
    'vehicle':           '#ef4444',  # red
    'tree':              '#16a34a',  # green
    'vegetation_other':  '#84cc16',  # lime
    'pavement':          '#a3a3a3',  # gray
    'bare_ground':       '#a16207',  # brown
    'water':             '#06b6d4',  # cyan
    'debris':            '#f97316',  # orange
}

# Convention: per-row PNGs land alongside the JSON artifact at
# /app/deepgis_results/scenegraph_results/<session_id>/visualization.png.
# Container path; the host bind-mount lives at
# deepgis-xr/deepgis_results/scenegraph_results/...
DEFAULT_OUT_DIR = Path('/app/deepgis_results') / 'scenegraph_results'


# ── duck-typed row protocol ──────────────────────────────────────────────

class SceneGraphRow(Protocol):
    """Anything that quacks like a ``apps.web.models.SceneGraph`` row.

    Exists only so the admin and the management command can pass either
    a Django model instance or a dict mock without the renderer caring.
    """
    session_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    viewport: Dict[str, Any]
    fusion_metadata: Dict[str, Any]
    kernels_used: List[str]


# ── small geometry helpers ───────────────────────────────────────────────

def _node_geometry(
    node: Dict[str, Any],
) -> Tuple[Optional[List[List[float]]], str]:
    """Return ``(ring, space)`` for a SceneNode.

    Prefers ``region.geo_polygon`` (lon/lat) so multi-scene plots are in
    a shared absolute frame. Falls back to ``region.polygon`` (normalized
    [0, 1] image space) when the kernel didn't carry geographic geometry
    — the resulting plot is still useful, just per-tile-only.
    """
    region = (node or {}).get('region') or {}
    geo = region.get('geo_polygon') or []
    if geo and len(geo) >= 3:
        return [list(p) for p in geo], 'geo'
    norm = region.get('polygon') or []
    if norm and len(norm) >= 3:
        return [list(p) for p in norm], 'norm'
    return None, 'none'


def _node_centroid(ring: Sequence[Sequence[float]]) -> Tuple[float, float]:
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def category_histogram(nodes: Sequence[Dict[str, Any]]) -> Counter:
    """Count nodes by argmax category. Public so the admin can show
    the same histogram in the changelist column without re-rendering
    the figure."""
    return Counter((n.get('category') or 'unknown') for n in nodes)


# ── per-scene + gallery renderers ────────────────────────────────────────

def _draw_scene(
    ax,
    row: SceneGraphRow,
    *,
    draw_edges: bool,
    max_edges: int,
    min_score: float,
) -> int:
    """Plot polygons + (optional) adjacency edges onto ``ax``.

    Returns the number of nodes actually drawn. A scene whose nodes
    carry only normalized coords still renders, but in [0, 1]² instead
    of geographic space. Mixing the two would be misleading, so we pick
    the dominant geometry space for the row and silently drop nodes
    that don't conform.
    """
    import matplotlib  # noqa: F401  — lazy import contract
    from matplotlib.collections import LineCollection, PatchCollection
    from matplotlib.colors import to_rgba
    from matplotlib.patches import Polygon as MplPolygon

    nodes = row.nodes or []
    edges = row.edges or []

    # Pick the dominant geometry space for this scene.
    space_votes: Counter = Counter()
    for n in nodes:
        _, sp = _node_geometry(n)
        space_votes[sp] += 1
    space = space_votes.most_common(1)[0][0] if space_votes else 'none'
    if space == 'none':
        ax.text(0.5, 0.5, 'no usable geometry', ha='center', va='center',
                transform=ax.transAxes, color='#ef4444')
        ax.set_axis_off()
        return 0

    patches: List[Any] = []
    face_rgba: List[Tuple[float, float, float, float]] = []
    edge_colors: List[str] = []
    line_widths: List[float] = []
    centroids: Dict[str, Tuple[float, float]] = {}
    for node in nodes:
        score = float(node.get('score') or 0.0)
        if score < min_score:
            continue
        ring, sp = _node_geometry(node)
        if not ring or sp != space:
            continue
        cat = node.get('category') or 'unknown'
        color = CATEGORY_COLORS.get(cat, CATEGORY_COLORS['unknown'])
        n_sources = len(node.get('sources') or [])
        r, g, b, _ = to_rgba(color)
        patches.append(MplPolygon(ring, closed=True))
        face_rgba.append((r, g, b, 0.20 + 0.55 * max(0.0, min(1.0, score))))
        # Saturated dark outline once a node has multi-source consensus,
        # otherwise outline matches fill — high-confidence multi-kernel
        # agreements pop visually.
        edge_colors.append(color if n_sources <= 1 else '#0f172a')
        line_widths.append(0.5 + 0.4 * min(n_sources, 4))
        centroids[node.get('id', '')] = _node_centroid(ring)

    n_drawn = len(patches)
    if n_drawn == 0:
        ax.text(0.5, 0.5, 'no nodes above min_score',
                ha='center', va='center', transform=ax.transAxes,
                color='#ef4444')
        ax.set_axis_off()
        return 0

    pc = PatchCollection(
        patches,
        facecolors=face_rgba,
        edgecolors=edge_colors,
        linewidths=line_widths,
    )
    ax.add_collection(pc)

    if draw_edges and edges and centroids:
        # Sort by weight desc and cap; some scenes carry 300k edges.
        sorted_edges = sorted(
            edges,
            key=lambda e: float(e.get('weight') or 0.0),
            reverse=True,
        )[:max_edges]
        segs = []
        ws = []
        for e in sorted_edges:
            src = e.get('source')
            tgt = e.get('target')
            if src in centroids and tgt in centroids:
                segs.append([centroids[src], centroids[tgt]])
                ws.append(float(e.get('weight') or 0.0))
        if segs:
            wmax = max(ws) if ws else 1.0
            wmin = min(ws) if ws else 0.0
            colors = [(0.10, 0.13, 0.18,
                       0.10 + 0.25 * ((w - wmin) / (wmax - wmin)
                                       if wmax > wmin else 0.5))
                      for w in ws]
            lc = LineCollection(segs, colors=colors, linewidths=0.4)
            ax.add_collection(lc)

    ax.set_aspect('equal')
    ax.autoscale_view()
    if space == 'geo':
        ax.set_xlabel('longitude')
        ax.set_ylabel('latitude')
    else:
        ax.set_xlabel('u  (normalized image)')
        ax.set_ylabel('v  (normalized image, 1 = bottom)')
        ax.invert_yaxis()
    ax.grid(True, alpha=0.15)
    return n_drawn


def _draw_metadata_panel(ax, row: SceneGraphRow, *, n_drawn: int) -> None:
    """Right-side text panel: category histogram + kernels + lambdas.

    Plain text, no extra axes — keeps it readable when zoomed out in
    the gallery and renders cheaply enough to embed in admin pages.
    """
    ax.set_axis_off()
    nodes = row.nodes or []
    edges = row.edges or []
    hist = category_histogram(nodes)

    meta = row.fusion_metadata or {}
    mixer = meta.get('mixer') or {}
    sources_used = mixer.get('sources') or []
    lambdas = mixer.get('lambdas') or []
    per_kernel = meta.get('per_kernel_claim_counts') or {}
    silent = meta.get('silent_kernels') or []

    lines: List[str] = []
    lines.append(f'nodes drawn   : {n_drawn} / {len(nodes)}')
    lines.append(f'edges (total) : {len(edges)}')
    if meta.get('orchestrator_elapsed_ms'):
        lines.append(f'orchestrator  : {meta["orchestrator_elapsed_ms"]} ms')
    if meta.get('wall_clock_s') is not None:
        lines.append(f'fusion        : {float(meta["wall_clock_s"]):.2f} s')
    lines.append('')
    lines.append('-- category histogram (argmax) --')
    for cat, count in hist.most_common():
        color = CATEGORY_COLORS.get(cat, '#94a3b8')
        lines.append(f'  {cat:<18} {count:>5}    [{color}]')
    lines.append('')
    lines.append('-- kernels & lambdas --')
    if sources_used and lambdas and len(sources_used) == len(lambdas):
        for s, lam in zip(sources_used, lambdas):
            lines.append(f'  λ {s:<18} {float(lam):.3f}')
    else:
        for s in (row.kernels_used or []):
            count = per_kernel.get(s, '?')
            lines.append(f'    {s:<20} claims={count}')
    if silent:
        lines.append('')
        lines.append('-- silent kernels --')
        for s in silent:
            lines.append(f'  · {s}')

    method = mixer.get('method')
    if method:
        lines.append('')
        lines.append(f'mixer method  : {method}')
        tax = mixer.get('taxonomy')
        if tax:
            lines.append(f'taxonomy      : {tax}')

    ax.text(
        0.0, 1.0, '\n'.join(lines),
        transform=ax.transAxes,
        fontsize=8.5, family='monospace',
        verticalalignment='top',
        color='#0f172a',
    )


def render_scene_graph_png(
    row: SceneGraphRow,
    target: Path,
    *,
    draw_edges: bool = True,
    max_edges: int = 2000,
    dpi: int = 140,
    min_score: float = 0.0,
    fig_size: Tuple[float, float] = (15.0, 7.0),
) -> Optional[Path]:
    """Render one SceneGraph row to a PNG and return its path.

    Returns ``None`` if the row had no usable geometry (the figure is
    closed and no file is written). All side effects are confined to
    the ``target`` path; callers control caching by inspecting
    ``target.exists()`` before invoking.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    target.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(
        1, 2, figsize=fig_size,
        gridspec_kw={'width_ratios': [3, 1]},
    )
    ax_map, ax_meta = axes

    n_drawn = _draw_scene(
        ax_map, row,
        draw_edges=draw_edges,
        max_edges=max_edges,
        min_score=min_score,
    )
    if n_drawn == 0:
        plt.close(fig)
        return None

    _draw_metadata_panel(ax_meta, row, n_drawn=n_drawn)

    fig.suptitle(
        f'SceneGraph: {row.session_id}',
        fontsize=11, family='monospace',
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(target, dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    return target


def render_gallery_png(
    rows: Sequence[SceneGraphRow],
    target: Path,
    *,
    draw_edges: bool = True,
    max_edges: int = 2000,
    dpi: int = 140,
    min_score: float = 0.0,
) -> Path:
    """Multi-panel gallery: per-scene thumbnails + stacked-bar summary.

    Returns the target path even if some rows were ungeometric (those
    panels just say "no usable geometry"); callers don't have to
    pre-filter.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    target.parent.mkdir(parents=True, exist_ok=True)

    n = len(rows)
    cols = min(4, max(n, 1))
    rows_grid = (n + cols - 1) // cols

    fig = plt.figure(figsize=(4.6 * cols, 4.0 * rows_grid + 3.0))
    gs = fig.add_gridspec(
        rows_grid + 1, cols,
        height_ratios=[1.0] * rows_grid + [0.45],
        hspace=0.45, wspace=0.25,
    )

    for i, row in enumerate(rows):
        ax = fig.add_subplot(gs[i // cols, i % cols])
        n_drawn = _draw_scene(
            ax, row,
            draw_edges=draw_edges,
            max_edges=max_edges,
            min_score=min_score,
        )
        short = (row.session_id or '').replace('scenegraph_', '')
        ax.set_title(
            f'{short}\nn={len(row.nodes or [])} '
            f'drawn={n_drawn} edges={len(row.edges or [])}',
            fontsize=8.5, family='monospace',
        )

    # Stacked-bar summary across scenes.
    ax_bar = fig.add_subplot(gs[-1, :])
    cat_order = list(CATEGORY_COLORS.keys())
    scene_labels = [
        (r.session_id or '').replace('scenegraph_', '') for r in rows
    ]
    bottoms = [0.0] * n
    for cat in cat_order:
        heights = [
            category_histogram(r.nodes or []).get(cat, 0)
            for r in rows
        ]
        ax_bar.bar(
            scene_labels, heights, bottom=bottoms,
            color=CATEGORY_COLORS[cat], label=cat, edgecolor='white',
            linewidth=0.4,
        )
        bottoms = [b + h for b, h in zip(bottoms, heights)]
    ax_bar.set_ylabel('argmax-category count')
    ax_bar.set_title('per-scene category histogram', fontsize=10)
    ax_bar.tick_params(axis='x', labelsize=7, rotation=30)
    ax_bar.legend(
        ncol=min(len(cat_order), 5),
        fontsize=7, loc='upper center',
        bbox_to_anchor=(0.5, -0.45),
        frameon=False,
    )

    fig.suptitle(
        f'Distinction-Game SceneGraphs · {n} scenes',
        fontsize=12, family='monospace',
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(target, dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    return target


# ── default-target convenience for admin and mgmt callers ────────────────

def default_per_scene_path(session_id: str) -> Path:
    """Where the per-scene PNG lives next to the JSON artifact."""
    return DEFAULT_OUT_DIR / session_id / 'visualization.png'


def default_gallery_path() -> Path:
    """Gallery overview path."""
    return DEFAULT_OUT_DIR / '_gallery.png'
