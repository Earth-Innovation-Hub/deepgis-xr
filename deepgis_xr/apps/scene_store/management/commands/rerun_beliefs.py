"""Recompute every live entity's belief from its stored factors.

    python manage.py rerun_beliefs --taxonomy urban_v1            # dry run: what would move
    python manage.py rerun_beliefs --taxonomy urban_v1 --apply

Needed when the way evidence is combined changes (looks: the captures of one image count
once) and nothing new was stored. Factors are not touched; entities whose belief moves get a
snapshot with cause ``looks``. The dry run also recomputes with the rule before looks, every
detection its own observation, so the report separates what the new rule changes from what a
plain recomputation would.
"""

import json
from collections import Counter

import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction

from deepgis_xr.apps.scene_store import fusion, looks, priors
from deepgis_xr.apps.scene_store.models import Entity

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)


def _describe(rows):
    """rows: [(category, score, p_exists)]"""
    score = np.asarray([r[1] for r in rows], dtype=float)
    p = np.asarray([r[2] for r in rows], dtype=float)
    return {
        'score_quantiles': [round(float(v), 3) for v in np.quantile(score, QUANTILES)],
        'p_exists_quantiles': [round(float(v), 3) for v in np.quantile(p, QUANTILES)],
        'n_unknown': sum(r[0] == 'unknown' for r in rows),
        'n_score_above_0.95': int((score > 0.95).sum()),
        'n_p_exists_above_0.99': int((p > 0.99).sum()),
        'n_believed_absent': int((p < 0.5).sum()),
    }


class Command(BaseCommand):
    help = "Recompute live entities' beliefs from their stored factors (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument('--taxonomy', default='urban_v1')
        parser.add_argument('--chunk', type=int, default=1500)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--json', action='store_true')

    def _stored(self, taxonomy):
        return {eid: (cat, score, p) for eid, cat, score, p in
                Entity.objects.filter(taxonomy=taxonomy, retired_at__isnull=True)
                .values_list('id', 'category', 'score', 'p_exists')}

    def _compute(self, ids, chunk, **kw):
        out = {}
        for i in range(0, len(ids), chunk):
            beliefs = fusion.run_local_bp(ids[i:i + chunk], write=False, **kw).get('beliefs', {})
            for eid, b in beliefs.items():
                out[eid] = (b['category'], b['score'], b['p_exists'])
        return out

    def handle(self, *args, taxonomy, chunk, apply, **opts):
        before = self._stored(taxonomy)
        ids = sorted(before)
        if not ids:
            self.stdout.write(f'no live {taxonomy} entities')
            return
        product = self._compute(ids, chunk, pool_looks=False)
        pooled = self._compute(ids, chunk)
        keep = [i for i in ids if i in pooled and i in product]
        moves = Counter((product[i][0], pooled[i][0]) for i in keep if product[i][0] != pooled[i][0])
        lo, hi = looks.exists_limits()
        report = {
            'taxonomy': taxonomy, 'n_entities': len(ids),
            'one_look_p_exists': [round(lo, 3), round(hi, 3)],
            'stored': _describe([before[i] for i in keep]),
            'every_detection_counts': _describe([product[i] for i in keep]),
            'looks': _describe([pooled[i] for i in keep]),
            'n_label_changes': sum(moves.values()),
            'label_changes': [{'from': a, 'to': b, 'n': n} for (a, b), n in moves.most_common(12)],
            'n_moved': sum(abs(product[i][1] - pooled[i][1]) > fusion.SNAPSHOT_DELTA
                           or abs(product[i][2] - pooled[i][2]) > fusion.SNAPSHOT_DELTA for i in keep),
            'low_confidence': priors.LOW_CONFIDENCE,
            'applied': False,
        }
        if apply:
            n_snapshots = 0
            with transaction.atomic(using=fusion.DB):
                for i in range(0, len(ids), chunk):
                    n_snapshots += fusion.run_local_bp(ids[i:i + chunk], cause='looks').get('n_snapshots', 0)
            after = self._stored(taxonomy)
            report.update(applied=True, n_snapshots=n_snapshots, after=_describe([after[i] for i in ids if i in after]))
        if opts.get('json'):
            self.stdout.write(json.dumps(report))
            return
        self.stdout.write(f"{taxonomy}: {report['n_entities']} live entities; one look alone can give "
                          f"P(exists) between {report['one_look_p_exists'][0]} and {report['one_look_p_exists'][1]}")
        for key, title in (('stored', 'stored now'), ('every_detection_counts', 'recomputed, every detection counts'),
                           ('looks', 'recomputed, one message per look'), ('after', 'stored after --apply')):
            if key in report:
                r = report[key]
                self.stdout.write(
                    f"  {title}:\n    score {r['score_quantiles']}  p_exists {r['p_exists_quantiles']}\n"
                    f"    unknown {r['n_unknown']}, score > 0.95: {r['n_score_above_0.95']}, "
                    f"p_exists > 0.99: {r['n_p_exists_above_0.99']}, believed absent: {r['n_believed_absent']}")
        self.stdout.write(f"  beliefs moved by more than {fusion.SNAPSHOT_DELTA}: {report['n_moved']}; "
                          f"labels changed: {report['n_label_changes']}")
        for m in report['label_changes']:
            self.stdout.write(f"    {m['from']} -> {m['to']}: {m['n']}")
        self.stdout.write(f"  {report['n_snapshots']} snapshots written" if apply
                          else '  dry run: nothing written (use --apply)')
