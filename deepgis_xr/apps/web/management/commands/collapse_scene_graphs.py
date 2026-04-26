"""
Collapse multiple persisted SceneGraph rows into one fused semantic graph.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from deepgis_xr.apps.web.models import SceneGraph
from deepgis_xr.apps.web.world_sampler_api.scene_graph_collapse import (
    FUSED_SCENE_GRAPH_DIR,
    run_collapse_for_rows,
)


def _parse_date(s: str) -> datetime:
    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            naive = datetime.strptime(s, fmt)
            return timezone.make_aware(naive, timezone.get_current_timezone())
        except ValueError:
            continue
    raise CommandError(
        f'Could not parse date {s!r}; use YYYY-MM-DD or ISO-8601.'
    )


class Command(BaseCommand):
    help = 'Collapse selected SceneGraph rows into one factor-graph fused graph.'

    def add_arguments(self, parser):
        parser.add_argument('--latest', type=int, default=None)
        parser.add_argument('--since', default=None)
        parser.add_argument('--until', default=None)
        parser.add_argument('--session-ids', nargs='+', default=None)
        parser.add_argument('--taxonomy', default=None)
        parser.add_argument('--fit-artifact', default=None)
        parser.add_argument('--iou-thresh', type=float, default=0.5)
        parser.add_argument('--osm-id-match', dest='osm_id_match', action='store_true', default=True)
        parser.add_argument('--no-osm-id-match', dest='osm_id_match', action='store_false')
        parser.add_argument(
            '--centroid-eps',
            type=float,
            default=0.0002,
            help='Geographic centroid threshold in lon/lat degrees for cross-row association.',
        )
        parser.add_argument('--beta-spatial', type=float, default=1.0)
        parser.add_argument(
            '--spatial-degree-cap',
            type=int,
            default=8,
            help='Maximum number of spatial pairwise factors attached to any fused node.',
        )
        parser.add_argument(
            '--persistence-alpha',
            type=float,
            default=0.95,
            help='Same-entity temporal persistence probability for repeated observations.',
        )
        parser.add_argument('--bp-max-iter', type=int, default=30)
        parser.add_argument('--bp-damping', type=float, default=0.5)
        parser.add_argument('--bp-tol', type=float, default=1e-4)
        parser.add_argument('--label', default=None)
        parser.add_argument('--dry-run', action='store_true')

    def _select_rows(self, options) -> List[SceneGraph]:
        qs = SceneGraph.objects.all()
        if options['session_ids']:
            qs = qs.filter(session_id__in=options['session_ids'])
        if options['since']:
            qs = qs.filter(created_at__gte=_parse_date(options['since']))
        if options['until']:
            qs = qs.filter(created_at__lt=_parse_date(options['until']))
        if options['taxonomy']:
            qs = qs.filter(taxonomy_name=options['taxonomy'])
        qs = qs.order_by('-created_at')
        if options['latest']:
            qs = qs[: options['latest']]
        return list(qs)

    def handle(self, *args, **options):
        rows = self._select_rows(options)
        if not rows:
            raise CommandError('No SceneGraph rows matched the given filters.')

        self.stdout.write(self.style.NOTICE(
            f'Selected {len(rows)} SceneGraph row(s) for collapse.'
        ))
        for r in rows[:10]:
            self.stdout.write(
                f'  - {r.session_id} '
                f'({r.created_at.isoformat()}, n_nodes={len(r.nodes or [])})'
            )
        if len(rows) > 10:
            self.stdout.write(f'  ... (+{len(rows) - 10} more)')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                'Dry run requested — exiting without running collapse.'
            ))
            return

        FUSED_SCENE_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        try:
            artifact = run_collapse_for_rows(
                rows,
                fit_artifact_dir=Path(options['fit_artifact']) if options['fit_artifact'] else None,
                iou_thresh=options['iou_thresh'],
                osm_id_match=options['osm_id_match'],
                centroid_eps=options['centroid_eps'],
                persistence_alpha=options['persistence_alpha'],
                beta_spatial=options['beta_spatial'],
                spatial_degree_cap=options['spatial_degree_cap'],
                bp_max_iter=options['bp_max_iter'],
                bp_damping=options['bp_damping'],
                bp_tol=options['bp_tol'],
                label=options['label'],
            )
        except Exception as exc:
            raise CommandError(f'Collapse failed: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(
            f'Collapse complete — artifact at {artifact.artifact_dir}'
        ))
        self.stdout.write(
            f'  input nodes: {artifact.n_input_nodes}; '
            f'fused nodes: {artifact.n_fused_nodes}; edges: {artifact.n_edges}'
        )
        self.stdout.write(f'  BP converged: {artifact.converged}')
        self.stdout.write('')
        self.stdout.write(f'Inspect: {artifact.artifact_dir / "fused.summary.txt"}')
        self.stdout.write(f'JSON   : {artifact.artifact_dir / "fused.json"}')
