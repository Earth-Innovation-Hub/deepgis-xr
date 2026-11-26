"""Bring stored detections under the fragment rule that ingest now applies.

A detection smaller than priors.FRAGMENT_MIN_PIXELS pixels of its own capture is gated
('fragment'): it stays stored, its perceptual, geometry and hit factors are superseded, and
it no longer counts toward its entity's sightings, area or outline. Entities left with no
live detection are retired, which ``restore_entities`` can undo. Then beliefs are re-inferred.

Nothing is deleted. Without --apply the whole run is rolled back and only reported.
"""

import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.utils import timezone

from deepgis_xr.apps.scene_store import fusion, priors
from deepgis_xr.apps.scene_store.models import Detection, Entity, Factor

DB = fusion.DB

FRAGMENTS_SQL = """
SELECT d.id, a.entity_id, d.category
  FROM sg_detection d
  JOIN sg_capture c ON c.id = d.capture_id
  LEFT JOIN sg_association a ON a.detection_id = d.id
 WHERE d.gate = '' AND c.taxonomy = %s AND c.gsd_m IS NOT NULL AND d.area_m2 IS NOT NULL
   AND d.area_m2 < %s * c.gsd_m * c.gsd_m
   AND ST_XMax(d.geom) <= 180 AND ST_XMin(d.geom) >= -180 AND ST_YMax(d.geom) <= 90 AND ST_YMin(d.geom) >= -90
"""

ORPHANED_SQL = """
SELECT e.id FROM sg_entity e
 WHERE e.retired_at IS NULL AND e.id = ANY(%s)
   AND NOT EXISTS (SELECT 1 FROM sg_association a JOIN sg_detection d ON d.id = a.detection_id
                    WHERE a.entity_id = e.id AND d.gate = '')
"""


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--taxonomy', default='urban_v1')
        parser.add_argument('--apply', action='store_true', help='commit (default: report and roll back)')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        t0 = time.perf_counter()
        live = Entity.objects.filter(retired_at__isnull=True, taxonomy=opts['taxonomy'])
        before = Counter(live.values_list('category', flat=True))
        try:
            with transaction.atomic(using=DB):
                report = self._run(opts['taxonomy'])
                after = Counter(live.values_list('category', flat=True))
                if not opts['apply']:
                    raise Rollback
        except Rollback:
            pass
        for k, v in report.items():
            self.stdout.write(f'{k}: {v}')
        self.stdout.write('category: before -> after')
        for cat in sorted(set(before) | set(after)):
            self.stdout.write(f'  {cat}: {before[cat]} -> {after[cat]}')
        self.stdout.write(f"{'applied' if opts['apply'] else 'dry run, rolled back'} "
                          f'in {time.perf_counter() - t0:.1f} s')

    def _run(self, taxonomy):
        now = timezone.now()
        with connections[DB].cursor() as cur:
            cur.execute(FRAGMENTS_SQL, [taxonomy, priors.FRAGMENT_MIN_PIXELS])
            rows = cur.fetchall()
        gated = [r[0] for r in rows]
        touched = sorted({r[1] for r in rows if r[1] is not None})
        n_superseded = Factor.objects.filter(detection_id__in=gated, superseded_at__isnull=True) \
            .update(superseded_at=now)
        Detection.objects.filter(id__in=gated).update(gate='fragment')
        with connections[DB].cursor() as cur:
            cur.execute(ORPHANED_SQL, [touched])
            orphaned = [r[0] for r in cur.fetchall()]
        retired = fusion.retire_entities(
            orphaned, f'all detections gated (fragment under {priors.FRAGMENT_MIN_PIXELS} px)', infer=False)
        kept = sorted(set(touched) - set(orphaned))
        with connections[DB].cursor() as cur:
            cur.execute(fusion.ENTITY_SPAN_SQL, [kept])
            cur.execute(fusion.ENTITY_AREA_SQL, [kept])
            cur.execute(fusion.ENTITY_GEOM_SQL, [kept])
        neighbours = fusion._neighbours(orphaned, Factor.objects.filter(
            entity_ids__overlap=orphaned, superseded_at=retired.get('at')).only('entity_ids')) if orphaned else set()
        n_bp = fusion._bp_by_taxonomy(set(kept) | neighbours, cause='fragment')
        return {
            'taxonomy': taxonomy,
            'pixel floor': priors.FRAGMENT_MIN_PIXELS,
            'detections gated as fragment': len(gated),
            'by category': dict(Counter(r[2] for r in rows).most_common()),
            'factors superseded by gating': n_superseded,
            'entities retired (no live detection)': retired['n_retired'],
            'entities kept with fewer sightings': len(kept),
            'entities re-inferred': n_bp,
        }
