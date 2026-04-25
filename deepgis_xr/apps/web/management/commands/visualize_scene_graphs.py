"""
Visualize Distinction-Game SceneGraph rows from the database.

Reads ``SceneGraph`` rows persisted by the orchestrator
(:mod:`deepgis_xr.apps.web.world_sampler_api.scenegraph`) and renders
each one as a PNG showing fused polygons coloured by argmax category,
with optional adjacency edges.

Usage::

    # Render every SceneGraph row, one PNG per row + a gallery overview.
    python manage.py visualize_scene_graphs

    # One specific session.
    python manage.py visualize_scene_graphs --session-id scenegraph_20260425_194346_lat33p407641_lonn111p925631

    # Latest N only.
    python manage.py visualize_scene_graphs --latest 3

    # Custom output directory (defaults to <artifact_dir>/visualization.png
    # for per-scene plots and <out-dir>/_gallery.png for the overview).
    python manage.py visualize_scene_graphs --out-dir /tmp/sg_viz

    # Skip edge overlay (useful when a graph has tens of thousands of
    # adjacency edges that just paint over the polygons).
    python manage.py visualize_scene_graphs --no-edges

The colour palette mirrors the Cesium overlay in
``staticfiles/web/js/world-sampler-ui.js#displaySceneGraph``; argmax
posterior drives hue and ``score`` drives alpha so confident,
high-mass nodes pop visually.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.web.models import SceneGraph


# Mirror world-sampler-ui.js#colorByCategory so visualization and the
# live Cesium overlay agree at a glance. Anything outside this map
# falls back to the unknown-grey shade.
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

DEFAULT_OUT_DIR = Path('/app/deepgis_results') / 'scenegraph_results'


def _ring_to_xy(ring: Sequence[Sequence[float]]) -> Tuple[List[float], List[float]]:
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    return xs, ys


def _node_geometry(node: Dict[str, Any]) -> Tuple[Optional[List[List[float]]], str]:
    """Return ``(ring, space)`` for a SceneNode.

    Prefers ``region.geo_polygon`` (lon/lat) so multiple scenes are
    plotted in absolute coordinates and the gallery is geographically
    meaningful. Falls back to ``region.polygon`` (normalized [0,1] image
    space) if the kernel didn't carry geographic geometry — the resulting
    plot is still useful, just per-tile-only.
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


def _category_histogram(nodes: Sequence[Dict[str, Any]]) -> Counter:
    return Counter((n.get('category') or 'unknown') for n in nodes)


class Command(BaseCommand):
    help = "Render fused SceneGraph rows from the DB as polygon-coloured PNGs."

    def add_arguments(self, parser):
        parser.add_argument(
            '--session-id',
            default=None,
            help='Render exactly this session_id (overrides --latest and --all).',
        )
        parser.add_argument(
            '--latest',
            type=int,
            default=None,
            help='Render only the most recent N rows (by created_at).',
        )
        parser.add_argument(
            '--out-dir',
            default=None,
            help=(
                'Directory for output PNGs. Defaults to the per-row artifact '
                'directory under /app/deepgis_results/scenegraph_results/. '
                'When set, all PNGs land in this directory and the gallery '
                'is named <out_dir>/_gallery.png.'
            ),
        )
        parser.add_argument(
            '--no-edges',
            action='store_true',
            help='Skip the centroid-adjacency edge overlay.',
        )
        parser.add_argument(
            '--no-gallery',
            action='store_true',
            help='Skip the multi-panel _gallery.png overview.',
        )
        parser.add_argument(
            '--max-edges',
            type=int,
            default=2000,
            help=(
                'Cap edges drawn per scene (default 2000). Top-weighted '
                'edges win. Keeps dense graphs (300k edges) legible.'
            ),
        )
        parser.add_argument(
            '--dpi',
            type=int,
            default=140,
            help='PNG dpi (default 140).',
        )
        parser.add_argument(
            '--min-score',
            type=float,
            default=0.0,
            help='Drop nodes whose argmax score is below this threshold.',
        )

    def handle(self, *args, **options):
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            from matplotlib.patches import Polygon as MplPolygon
            from matplotlib.collections import PatchCollection, LineCollection
        except ImportError as exc:
            raise CommandError(
                f'matplotlib is required for visualization: {exc}. '
                'Install with `pip install matplotlib`.'
            )

        # Hand the imported handles to the renderer functions to keep
        # signatures clean.
        self._plt = plt
        self._MplPolygon = MplPolygon
        self._PatchCollection = PatchCollection
        self._LineCollection = LineCollection

        qs = SceneGraph.objects.all().order_by('-created_at')
        if options['session_id']:
            qs = qs.filter(session_id=options['session_id'])
        elif options['latest']:
            qs = qs[: options['latest']]

        rows = list(qs)
        if not rows:
            self.stdout.write(self.style.WARNING('No SceneGraph rows match.'))
            return

        out_dir_arg = options['out_dir']
        out_dir: Optional[Path] = Path(out_dir_arg) if out_dir_arg else None
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)

        rendered: List[Tuple[SceneGraph, Path]] = []
        for row in rows:
            try:
                target = self._render_one(
                    row,
                    out_dir=out_dir,
                    draw_edges=not options['no_edges'],
                    max_edges=options['max_edges'],
                    dpi=options['dpi'],
                    min_score=options['min_score'],
                )
            except Exception as exc:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ {row.session_id}: {exc}'
                ))
                continue
            if target is None:
                self.stdout.write(self.style.WARNING(
                    f'  · {row.session_id}: no usable geometry, skipped'
                ))
                continue
            rendered.append((row, target))
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ {row.session_id}: {len(row.nodes)} nodes → {target}'
            ))

        if not options['no_gallery'] and len(rendered) >= 1:
            gallery_dir = out_dir if out_dir is not None else DEFAULT_OUT_DIR
            gallery_dir.mkdir(parents=True, exist_ok=True)
            gallery_path = gallery_dir / '_gallery.png'
            self._render_gallery(
                [r for (r, _) in rendered],
                gallery_path,
                draw_edges=not options['no_edges'],
                max_edges=options['max_edges'],
                dpi=options['dpi'],
                min_score=options['min_score'],
            )
            self.stdout.write(self.style.SUCCESS(
                f'  ★ gallery: {gallery_path}'
            ))

    # ── per-scene rendering ────────────────────────────────────────────

    def _render_one(
        self,
        row: SceneGraph,
        *,
        out_dir: Optional[Path],
        draw_edges: bool,
        max_edges: int,
        dpi: int,
        min_score: float,
    ) -> Optional[Path]:
        """Render one SceneGraph row to a PNG and return its path."""
        plt = self._plt

        if out_dir is None:
            artifact_dir = DEFAULT_OUT_DIR / row.session_id
            artifact_dir.mkdir(parents=True, exist_ok=True)
            target = artifact_dir / 'visualization.png'
        else:
            target = out_dir / f'{row.session_id}.png'

        fig, axes = plt.subplots(
            1, 2, figsize=(15, 7),
            gridspec_kw={'width_ratios': [3, 1]},
        )
        ax_map, ax_meta = axes

        n_drawn = self._draw_scene(
            ax_map, row,
            draw_edges=draw_edges,
            max_edges=max_edges,
            min_score=min_score,
        )
        if n_drawn == 0:
            plt.close(fig)
            return None

        self._draw_metadata_panel(ax_meta, row, n_drawn=n_drawn)

        fig.suptitle(
            f'SceneGraph: {row.session_id}',
            fontsize=11, family='monospace',
        )
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        fig.savefig(target, dpi=dpi, bbox_inches='tight')
        plt.close(fig)
        return target

    def _draw_scene(
        self,
        ax,
        row: SceneGraph,
        *,
        draw_edges: bool,
        max_edges: int,
        min_score: float,
    ) -> int:
        """Plot polygons + edges onto ``ax``. Returns number of nodes drawn.

        Geographic geometry is preferred, but a scene whose nodes carry
        only normalized coords still renders (just in a [0,1] frame).
        Mixing the two would produce nonsense, so we pick whichever
        space the majority of nodes use and silently drop the others.
        """
        MplPolygon = self._MplPolygon
        PatchCollection = self._PatchCollection
        LineCollection = self._LineCollection

        nodes = row.nodes or []
        edges = row.edges or []

        # Pick the dominant geometry space for this scene.
        space_votes = Counter()
        for n in nodes:
            _, sp = _node_geometry(n)
            space_votes[sp] += 1
        space = space_votes.most_common(1)[0][0] if space_votes else 'none'
        if space == 'none':
            ax.text(0.5, 0.5, 'no usable geometry', ha='center', va='center',
                    transform=ax.transAxes, color='#ef4444')
            ax.set_axis_off()
            return 0

        # Single pass: build patches, per-node face RGBA (alpha folded
        # in because PatchCollection wants a constant alpha per call),
        # edge colours, and a centroid map for the edge overlay.
        from matplotlib.colors import to_rgba

        patches = []
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
            # Saturated dark outline once a node has multi-source
            # consensus, otherwise the outline matches the fill — this
            # makes high-confidence multi-kernel agreements pop visually.
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
            # Sort by weight desc and cap; some scenes carry 300k edges
            # which obliterate the polygons.
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
                # Faint, dark grey; weight modulates alpha mildly so
                # strong adjacencies are slightly more visible.
                wmax = max(ws) if ws else 1.0
                wmin = min(ws) if ws else 0.0
                colors = [(0.10, 0.13, 0.18,
                           0.10 + 0.25 * ((w - wmin) / (wmax - wmin) if wmax > wmin else 0.5))
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

    def _draw_metadata_panel(
        self, ax, row: SceneGraph, *, n_drawn: int,
    ) -> None:
        """Side panel: category histogram + kernel sources + mixer info.

        Plain-text rendering keeps this readable when zoomed out in the
        gallery; matplotlib axes are turned off and we lay the text out
        in a single column.
        """
        ax.set_axis_off()
        nodes = row.nodes or []
        edges = row.edges or []
        hist = _category_histogram(nodes)

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

    # ── multi-scene gallery ────────────────────────────────────────────

    def _render_gallery(
        self,
        rows: Sequence[SceneGraph],
        target: Path,
        *,
        draw_edges: bool,
        max_edges: int,
        dpi: int,
        min_score: float,
    ) -> None:
        """One PNG with a thumbnail per scene + a stacked-bar summary.

        Top half: small per-scene polygon plots (no metadata panel) so
        the human eye can compare argmax-category distributions across
        many fused readings at once.
        Bottom strip: stacked-bar of category counts per scene.
        """
        plt = self._plt

        n = len(rows)
        cols = min(4, n)
        rows_grid = (n + cols - 1) // cols

        fig = plt.figure(figsize=(4.6 * cols, 4.0 * rows_grid + 3.0))
        gs = fig.add_gridspec(
            rows_grid + 1, cols,
            height_ratios=[1.0] * rows_grid + [0.45],
            hspace=0.45, wspace=0.25,
        )

        for i, row in enumerate(rows):
            ax = fig.add_subplot(gs[i // cols, i % cols])
            n_drawn = self._draw_scene(
                ax, row,
                draw_edges=draw_edges,
                max_edges=max_edges,
                min_score=min_score,
            )
            short = row.session_id.replace('scenegraph_', '')
            ax.set_title(
                f'{short}\nn={len(row.nodes)} drawn={n_drawn} edges={len(row.edges)}',
                fontsize=8.5, family='monospace',
            )

        # Stacked-bar summary across scenes.
        ax_bar = fig.add_subplot(gs[-1, :])
        cat_order = [c for c in CATEGORY_COLORS.keys()]
        scene_labels = [r.session_id.replace('scenegraph_', '') for r in rows]
        bottoms = [0.0] * n
        for cat in cat_order:
            heights = [
                _category_histogram(r.nodes or []).get(cat, 0)
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
