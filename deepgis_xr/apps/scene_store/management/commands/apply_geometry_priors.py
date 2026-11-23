"""Bring stored evidence under the geometry rules that ingest now applies.

For every detection that is still evidence:
  - a region covering more than half of its capture's footprint is gated ('frame') and its
    perceptual and hit factors are superseded;
  - every other region gets a geometry factor (area and shape against each category).
Miss factors on entities too small to resolve at their capture's ground sample distance are
superseded. Entities left with no live detection are retired. Then beliefs are re-inferred.

Nothing is deleted. Without --apply the whole run is rolled back and only reported.
"""

import math
import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.utils import timezone

from deepgis_xr.apps.scene_store import fusion, priors
from deepgis_xr.apps.scene_store.models import Detection, Entity, Factor
from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import taxonomy_by_name

DB = fusion.DB

DETECTIONS_SQL = """
SELECT d.id, d.capture_id, a.entity_id, e.taxonomy, d.observed_at, d.area_m2,
       ST_Perimeter(d.geom::geography), ST_Area(c.footprint::geography)
  FROM sg_detection d
  JOIN sg_association a ON a.detection_id = d.id
  JOIN sg_entity e ON e.id = a.entity_id
  JOIN sg_capture c ON c.id = d.capture_id
 WHERE d.gate = '' AND e.retired_at IS NULL
   AND ST_XMax(d.geom) <= 180 AND ST_XMin(d.geom) >= -180 AND ST_YMax(d.geom) <= 90 AND ST_YMin(d.geom) >= -90
   AND NOT EXISTS (SELECT 1 FROM sg_factor f WHERE f.detection_id = d.id AND f.kind = 'geometry')
"""

UNRESOLVED_MISSES_SQL = """
SELECT f.id, f.entity_ids[1]
  FROM sg_factor f
  JOIN sg_capture c ON c.id = f.capture_id
  JOIN sg_entity e ON e.id = f.entity_ids[1]
 WHERE f.kind = 'miss' AND f.superseded_at IS NULL AND c.gsd_m IS NOT NULL
   AND e.area_m2 < %s * c.gsd_m * c.gsd_m
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
        parser.add_argument('--apply', action='store_true', help='commit (default: report and roll back)')
        parser.add_argument('--misses-only', action='store_true',
                            help='only supersede unresolvable misses (no geometry factors, no gating)')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        t0 = time.perf_counter()
        live = Entity.objects.filter(retired_at__isnull=True)
        before = Counter(live.values_list('category', flat=True))
        absent_before = live.filter(p_exists__lt=0.5).count()
        try:
            with transaction.atomic(using=DB):
                report = self._run(misses_only=opts['misses_only'])
                after = Counter(live.values_list('category', flat=True))
                report['entities believed absent (p_exists < 0.5)'] = \
                    f'{absent_before} -> {live.filter(p_exists__lt=0.5).count()}'
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

    def _run(self, misses_only=False):
        now = timezone.now()
        rows = []
        if not misses_only:
            with connections[DB].cursor() as cur:
                cur.execute(DETECTIONS_SQL)
                rows = cur.fetchall()
        gated, factors, touched, taxes = [], [], set(), {}
        for det_id, cap_id, eid, tax_name, observed_at, area, perim, fp_area in rows:
            touched.add(eid)
            if fp_area and area and area > priors.GATE_FOOTPRINT_FRAC * fp_area:
                gated.append(det_id)
                continue
            tax = taxes.setdefault(tax_name, taxonomy_by_name(tax_name))
            compact = 4 * math.pi * area / perim ** 2 if area and perim else None
            table = priors.geometry_table(tax, area, compact)
            if table is None:
                continue
            factors.append(fusion._new_factor(
                'geometry', [eid], table, observed_at, variables=[fusion.cvar(eid)],
                capture_id=cap_id, detection_id=det_id,
                metadata={'area_m2': round(area, 2), 'compactness': round(compact, 3) if compact else None}))
        Factor.objects.bulk_create(factors, batch_size=1000)
        n_superseded = Factor.objects.filter(detection_id__in=gated, superseded_at__isnull=True) \
            .update(superseded_at=now)
        Detection.objects.filter(id__in=gated).update(gate='frame')
        gated_ids = set(gated)
        regated = sorted({eid for det_id, _, eid, *_ in rows if det_id in gated_ids})
        with connections[DB].cursor() as cur:
            cur.execute(fusion.ENTITY_AREA_SQL, [regated])
            cur.execute(fusion.ENTITY_GEOM_SQL, [regated])

        with connections[DB].cursor() as cur:
            cur.execute(UNRESOLVED_MISSES_SQL, [priors.MISS_MIN_PIXELS])
            misses = cur.fetchall()
        Factor.objects.filter(id__in=[m[0] for m in misses]).update(superseded_at=now)
        touched |= {m[1] for m in misses}

        with connections[DB].cursor() as cur:
            cur.execute(ORPHANED_SQL, [sorted(touched)])
            orphaned = [r[0] for r in cur.fetchall()]
        retired = fusion.retire_entities(orphaned, 'all detections gated (frame)', infer=False)
        touched -= set(orphaned)
        n_bp = fusion._bp_by_taxonomy(touched, cause='geometry')
        return {
            'detections checked': len(rows),
            'geometry factors added': len(factors),
            'detections gated as frame': len(gated),
            'factors superseded by gating': n_superseded,
            'unresolvable misses superseded': len(misses),
            'entities retired (no live detection)': retired['n_retired'],
            'entities re-inferred': n_bp,
        }
