"""
Visualize Distinction-Game SceneGraph rows from the database.

Reads ``SceneGraph`` rows persisted by the orchestrator
(:mod:`deepgis_xr.apps.web.world_sampler_api.scenegraph`) and renders
each one as a PNG showing fused polygons coloured by argmax category,
with optional adjacency edges.

This command is a thin wrapper around
:mod:`deepgis_xr.apps.web.world_sampler_api.scenegraph_viz`, which is
also used by the Django admin's ``SceneGraphAdmin`` to render the
inline thumbnail on each row's detail page. Keeping the rendering in
that shared module guarantees the CLI batch outputs and the admin
inline previews remain pixel-identical.

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
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.web.models import SceneGraph
from deepgis_xr.apps.web.world_sampler_api.scenegraph_viz import (
    DEFAULT_OUT_DIR,
    default_per_scene_path,
    render_gallery_png,
    render_scene_graph_png,
)


class Command(BaseCommand):
    help = "Render fused SceneGraph rows from the DB as polygon-coloured PNGs."

    def add_arguments(self, parser):
        parser.add_argument(
            '--session-id',
            default=None,
            help='Render exactly this session_id (overrides --latest).',
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
            import matplotlib  # noqa: F401  — fail fast with a clear msg
        except ImportError as exc:
            raise CommandError(
                f'matplotlib is required for visualization: {exc}. '
                'Install with `pip install matplotlib`.'
            )

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
            target = (
                out_dir / f'{row.session_id}.png'
                if out_dir is not None
                else default_per_scene_path(row.session_id)
            )
            try:
                result = render_scene_graph_png(
                    row, target,
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
            if result is None:
                self.stdout.write(self.style.WARNING(
                    f'  · {row.session_id}: no usable geometry, skipped'
                ))
                continue
            rendered.append((row, result))
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ {row.session_id}: {len(row.nodes)} nodes → {result}'
            ))

        if not options['no_gallery'] and rendered:
            gallery_dir = out_dir if out_dir is not None else DEFAULT_OUT_DIR
            gallery_dir.mkdir(parents=True, exist_ok=True)
            gallery_path = gallery_dir / '_gallery.png'
            render_gallery_png(
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
