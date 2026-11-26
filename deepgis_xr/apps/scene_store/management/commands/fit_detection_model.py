"""Fit the chance that a later look finds an entity again, and weigh stored misses with it.

The fit (see ``detection_model``) uses every look in the store: a capture that covered an
entity seen earlier by one of its kernels, and whether a detection was merged into it.
The report compares it, on captures held out of the fit, with the fixed priors.P_DETECT.

With --apply the fit becomes the active model for the taxonomy, and every live miss factor
is replaced by one whose table uses the fitted probability for that look (the old factor
is superseded, not deleted). Then beliefs are re-inferred. Without --apply everything is
rolled back and only reported. --keep-misses stores the fit and leaves stored misses alone.
"""

import json
import time
from collections import Counter

import numpy as np
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.utils import timezone

from deepgis_xr.apps.scene_store import detection_model, fusion, priors
from deepgis_xr.apps.scene_store.models import Entity, Factor

DB = fusion.DB

# Live misses with what was known before each look. Entity area is today's median.
MISSES_SQL = """
SELECT f.id, f.entity_ids[1], f.capture_id, f.observed_at, e.area_m2, c.gsd_m,
       (SELECT c1.gsd_m FROM sg_association a
          JOIN sg_detection d ON d.id = a.detection_id
          JOIN sg_capture c1 ON c1.id = d.capture_id
         WHERE a.entity_id = e.id AND d.gate = '' AND c1.gsd_m IS NOT NULL
         ORDER BY c1.captured_at, d.id LIMIT 1),
       COALESCE((SELECT s.category FROM sg_belief_snapshot s
                  WHERE s.entity_id = e.id AND s.at < c.recorded_at
                  ORDER BY s.at DESC, s.id DESC LIMIT 1),
                (SELECT d.category FROM sg_association a
                   JOIN sg_detection d ON d.id = a.detection_id
                   JOIN sg_capture c1 ON c1.id = d.capture_id
                  WHERE a.entity_id = e.id AND d.gate = ''
                  ORDER BY c1.captured_at, d.id LIMIT 1),
                e.category),
       f.metadata
  FROM sg_factor f
  JOIN sg_capture c ON c.id = f.capture_id
  JOIN sg_entity e ON e.id = f.entity_ids[1]
 WHERE f.kind = 'miss' AND f.superseded_at IS NULL AND e.retired_at IS NULL AND e.taxonomy = %s
"""


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--taxonomy', default='urban_v1')
        parser.add_argument('--l2', type=float, default=3.0, help='penalty on the category offsets')
        parser.add_argument('--apply', action='store_true', help='commit (default: report and roll back)')
        parser.add_argument('--keep-misses', action='store_true', help='do not re-weigh stored miss factors')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        t0 = time.perf_counter()
        taxonomy = opts['taxonomy']
        rows = detection_model.looks(taxonomy)
        try:
            coefficients, metrics = detection_model.fit(rows, l2=opts['l2'])
        except ValueError as exc:
            raise CommandError(str(exc))
        self._report_fit(coefficients, metrics)

        live = Entity.objects.filter(retired_at__isnull=True, taxonomy=taxonomy)
        absent_before = live.filter(p_exists__lt=0.5).count()
        report = {}
        try:
            with transaction.atomic(using=DB):
                row = detection_model.store(taxonomy, coefficients, metrics)
                report['model version'] = row.version
                if not opts['keep_misses']:
                    report.update(self._reweigh(taxonomy, detection_model.Fitted(row.version, coefficients)))
                report['entities believed absent (p_exists < 0.5)'] = \
                    f'{absent_before} -> {live.filter(p_exists__lt=0.5).count()}'
                if not opts['apply']:
                    raise Rollback
        except Rollback:
            pass
        detection_model.forget()
        for k, v in report.items():
            self.stdout.write(f'{k}: {v}')
        self.stdout.write(f"{'applied' if opts['apply'] else 'dry run, rolled back'} "
                          f'in {time.perf_counter() - t0:.1f} s')

    def _report_fit(self, c, m):
        w = self.stdout.write
        w(f"looks: {m['n_looks']} in {m['n_captures']} captures, found again {m['found_rate']:.1%}")
        ll = m['log_loss']
        w(f"log loss on held-out captures ({m['folds']} folds): fitted {ll['fitted']}, "
          f"found rate alone {ll['found_rate']}, fixed {priors.P_DETECT} {ll['fixed']}")
        w(f"log-odds: intercept {c['intercept']:+.2f} (1,024 pixels, same zoom as first seen), "
          f"per doubling of pixels {c['log2_pixels']:+.2f}, per doubling coarser {c['coarser']:+.2f}, "
          f"per doubling finer {c['finer']:+.2f}")
        w('category offsets (looks):')
        for cat, v in sorted(c['category'].items(), key=lambda kv: -kv[1]):
            w(f"  {cat}: {v:+.2f} ({m['looks_by_category'].get(cat, 0)})")
        w('held-out calibration: predicted range, looks, mean predicted, found')
        for b in m['calibration']:
            w(f"  {b['lo']:.1f}-{b['hi']:.1f}  {b['n']:5d}  {b['predicted']:.2f}  {b['found']:.2f}")

    def _reweigh(self, taxonomy, model):
        now = timezone.now()
        with connections[DB].cursor() as cur:
            cur.execute(MISSES_SQL, [taxonomy])
            rows = cur.fetchall()
        factors, touched, ps = [], set(), []
        for fid, eid, cap_id, observed_at, area, gsd, first_gsd, category, old in rows:
            table, why = detection_model.miss_evidence(
                model, area_m2=area, gsd_m=gsd, first_gsd_m=first_gsd, category=category)
            if isinstance(old, str):
                old = json.loads(old)
            if (old or {}).get('retro'):  # a miss a later find put on this capture stays marked as one
                why = dict(why, retro=True, found_by=old.get('found_by'))
            factors.append(fusion._new_factor('miss', [eid], table, observed_at, variables=[fusion.xvar(eid)],
                                              decays=False, capture_id=cap_id, metadata=why))
            touched.add(eid)
            ps.append(why['p_detect'])
        Factor.objects.filter(id__in=[r[0] for r in rows]).update(superseded_at=now)
        Factor.objects.bulk_create(factors, batch_size=1000)
        n_bp = fusion._bp_by_taxonomy(touched, cause='detection_model')
        ps = np.asarray(ps) if ps else np.zeros(1)
        bands = Counter('under 0.2' if p < 0.2 else '0.2 to 0.5' if p < 0.5 else '0.5 to 0.8' if p < 0.8
                        else '0.8 and over' for p in ps)
        return {
            'miss factors re-weighed': len(rows),
            'their chance of a find (was 0.8 for all)': f'median {np.median(ps):.2f}, '
                                                        f'10th to 90th percentile {np.quantile(ps, 0.1):.2f} '
                                                        f'to {np.quantile(ps, 0.9):.2f}',
            'misses by chance of a find': dict(bands),
            'entities re-inferred': n_bp,
        }
