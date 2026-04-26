"""
Run the Distinction-Game MaxCal Q_s + λ fit on persisted SceneGraph rows.

Loads ``SceneGraph`` rows from the database (filtered by date range,
session ids, or "latest N"), feeds them into the kernelcal
``fit_distinction_game`` pipeline, and writes a versioned artifact
under ``/app/deepgis_results/distinction_game_fits/<timestamp>/``
containing:

- ``fit.json`` — the full :class:`DistinctionGameFit` payload.
- ``fit.summary.txt`` — one-page human-readable summary (lambdas,
  per-source Q_s diagonal peaks, EM trajectory, contributing rows).
- ``contributing_rows.json`` — index back to the SceneGraph PKs
  consumed in this fit, useful for replay and provenance.

Usage::

    # Fit on every row.
    python manage.py fit_distinction_game

    # Latest 10.
    python manage.py fit_distinction_game --latest 10

    # Date-range slice.
    python manage.py fit_distinction_game --since 2026-04-25 --until 2026-04-27

    # Specific sessions.
    python manage.py fit_distinction_game --session-ids scenegraph_a scenegraph_b

    # Bootstrap mode (use fused argmax as anchor everywhere).
    python manage.py fit_distinction_game --use-consensus-fallback

    # Fit only λ (keep Q_s frozen at the prior).
    python manage.py fit_distinction_game --no-fit-q-s

    # Smaller pseudo-count strength so data dominates the prior.
    python manage.py fit_distinction_game --alpha 1.0
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from deepgis_xr.apps.web.models import SceneGraph
from deepgis_xr.apps.web.world_sampler_api.distinction_game_fit import (
    DISTINCTION_GAME_FIT_DIR,
    run_fit_for_rows,
)


def _parse_date(s: str) -> datetime:
    """Accept either ``YYYY-MM-DD`` or full ISO-8601 timestamps."""
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
    help = 'Run the Distinction-Game MaxCal Q_s + λ fit on persisted SceneGraph rows.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--latest',
            type=int,
            default=None,
            help='Use only the most-recent N SceneGraph rows.',
        )
        parser.add_argument(
            '--since',
            default=None,
            help='Only include rows created on/after this date (YYYY-MM-DD or ISO-8601).',
        )
        parser.add_argument(
            '--until',
            default=None,
            help='Only include rows created strictly before this date.',
        )
        parser.add_argument(
            '--session-ids',
            nargs='+',
            default=None,
            help='Restrict to these session_id values (overrides date filters).',
        )
        parser.add_argument(
            '--taxonomy',
            default=None,
            help='Only include rows that used this taxonomy_name.',
        )

        parser.add_argument(
            '--use-consensus-fallback',
            action='store_true',
            help=(
                'Treat the fused argmax as the anchor for every node, not just '
                'OSM-anchored ones. Bootstrapping mode — biased toward the prior '
                'but useful when no OSM coverage is present.'
            ),
        )
        parser.add_argument(
            '--include-anchor-source-claims',
            action='store_true',
            help=(
                'Keep anchor-source (e.g. OSM) claims as features in the EM fit. '
                'Default is to exclude them so the fitted λ describes how much '
                'each non-anchor kernel agrees with the anchor — without this, '
                'the EM collapses onto λ_OSM=1 by trivial circularity.'
            ),
        )
        parser.add_argument(
            '--no-fit-q-s',
            action='store_true',
            help='Fit only λ (keep Q_s frozen at the prior).',
        )
        parser.add_argument(
            '--alpha',
            type=float,
            default=10.0,
            help='Dirichlet pseudo-count strength for the Q_s update (default 10).',
        )
        parser.add_argument(
            '--max-iter',
            type=int,
            default=20,
            help='Maximum EM outer iterations (default 20).',
        )
        parser.add_argument(
            '--tol',
            type=float,
            default=1e-5,
            help='EM convergence tolerance on log-likelihood improvement (default 1e-5).',
        )
        parser.add_argument(
            '--min-score',
            type=float,
            default=0.0,
            help='Drop claims with score below this floor before fitting (default 0).',
        )
        parser.add_argument(
            '--osm-anchor-sources',
            nargs='+',
            default=['osm'],
            help=(
                'Source ids that anchor a node to its fused argmax category. '
                'Default ("osm") is the canonical kernelcal id assigned by '
                'adapt_osm, which is what every OSM-claim node carries '
                'regardless of whether it came from the buildings or roads '
                'layer.'
            ),
        )
        parser.add_argument(
            '--label',
            default=None,
            help='Optional human-friendly suffix on the artifact directory name.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the row selection without running the fit.',
        )

    # ----------------------------------------------------------------

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
        rows = list(qs)
        return rows

    # ----------------------------------------------------------------

    def handle(self, *args, **options):
        rows = self._select_rows(options)
        if not rows:
            raise CommandError(
                'No SceneGraph rows matched the given filters.'
            )

        self.stdout.write(self.style.NOTICE(
            f'Selected {len(rows)} SceneGraph row(s) for fitting.'
        ))
        for r in rows[:10]:
            self.stdout.write(
                f'  - {r.session_id} '
                f'({r.created_at.isoformat()}, '
                f'n_nodes={len(r.nodes or [])}, '
                f'kernels={list(r.kernels_used or [])})'
            )
        if len(rows) > 10:
            self.stdout.write(f'  … (+{len(rows) - 10} more)')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                'Dry run requested — exiting without running the fit.'
            ))
            return

        DISTINCTION_GAME_FIT_DIR.mkdir(parents=True, exist_ok=True)

        try:
            artifact = run_fit_for_rows(
                rows,
                osm_anchor_sources=tuple(options['osm_anchor_sources']),
                use_consensus_fallback=options['use_consensus_fallback'],
                exclude_anchor_sources_from_fit=(
                    not options['include_anchor_source_claims']
                ),
                fit_q_s=not options['no_fit_q_s'],
                alpha_q_s=options['alpha'],
                max_iter=options['max_iter'],
                tol=options['tol'],
                min_score=options['min_score'],
                label=options['label'],
            )
        except Exception as exc:
            raise CommandError(f'Fit failed: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(
            f'Fit complete — artifact at {artifact.artifact_dir}'
        ))
        self.stdout.write(
            f'  regions: {artifact.n_regions} '
            f'(anchored={artifact.n_anchored_regions}, '
            f'unsupervised={artifact.n_unsupervised_regions})'
        )
        self.stdout.write(f'  converged: {artifact.converged}')
        self.stdout.write('  lambdas:')
        for src, lam in artifact.lambdas.items():
            self.stdout.write(f'    {src:24s}  {lam:.4f}')
        # Print a peek at the EM history.
        history = (artifact.payload.get('log_likelihood_history') or [])
        if history:
            tail = history[-min(5, len(history)):]
            self.stdout.write(
                '  EM ll trajectory (last few): '
                + ', '.join(f'{v:.3f}' for v in tail)
            )

        # Final hint for plumbing back into the orchestrator.
        self.stdout.write('')
        self.stdout.write(
            'Inspect: '
            f'{artifact.artifact_dir / "fit.summary.txt"}'
        )
        self.stdout.write(
            'JSON   : '
            f'{artifact.artifact_dir / "fit.json"}'
        )
