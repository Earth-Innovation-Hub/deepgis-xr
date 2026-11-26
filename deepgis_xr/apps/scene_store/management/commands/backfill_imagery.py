"""Give stored captures the imagery they showed and move their evidence to its date.

--file is JSON, {session_id: {"source": "bing:Aerial", "start": "2023-03-01", "end":
"2023-09-01", "zoom": 19, "points": 5, "uniform": true, "method": "backfill", ...}}, as
looked up from the imagery provider for each capture's footprint and zoom.

For each capture named there the imagery fields are set and ``observed_at`` becomes the
middle of the acquisition window. Its detections and all its factors are re-dated to that
instant, entity first_seen / last_seen are recomputed, and beliefs are re-inferred.
``captured_at`` (when the view was taken) and the belief history are left alone.

Without --apply the whole run is rolled back and only reported.
"""

import json
import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from deepgis_xr.apps.scene_store import fusion
from deepgis_xr.apps.scene_store.models import Capture, Entity

DB = fusion.DB

# Entities whose detections are all gated keep a span too (they are retired, not erased).
GATED_SPAN_SQL = """
UPDATE sg_entity e SET first_seen = s.first, last_seen = s.last
FROM (SELECT a.entity_id, min(d.observed_at) AS first, max(d.observed_at) AS last
      FROM sg_association a JOIN sg_detection d ON d.id = a.detection_id
      WHERE a.entity_id = ANY(%s)
      GROUP BY a.entity_id HAVING bool_and(d.gate <> '')) s
WHERE e.id = s.entity_id
"""


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True)
        parser.add_argument('--apply', action='store_true', help='commit (default: report and roll back)')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        with open(opts['file'], encoding='utf-8') as fh:
            records = json.load(fh)
        if not isinstance(records, dict):
            raise CommandError('the file must hold one JSON object keyed by session_id')
        t0 = time.perf_counter()
        try:
            with transaction.atomic(using=DB):
                report = self._run(records)
                if not opts['apply']:
                    raise Rollback
        except Rollback:
            pass
        for k, v in report.items():
            self.stdout.write(f'{k}: {v}')
        self.stdout.write(f"{'applied' if opts['apply'] else 'dry run, rolled back'} "
                          f'in {time.perf_counter() - t0:.1f} s')

    def _run(self, records):
        caps = {c.session_id: c for c in Capture.objects.filter(session_id__in=list(records))}
        dated, undated, windows, touched = 0, 0, Counter(), set()
        with connections[DB].cursor() as cur:
            for session_id, raw in records.items():
                cap = caps.get(session_id)
                if cap is None or not isinstance(raw, dict):
                    continue
                dates = {k: raw.get(k) for k in ('start', 'end', 'zoom', 'points', 'method',
                                                 'looked_up_at', 'uniform') if raw.get(k) is not None}
                rec = fusion.imagery_record({'source': raw.get('source'), 'layers': raw.get('layers') or [],
                                             'dates': dates}, cap.captured_at)
                cap.imagery_source, cap.imagery = rec['source'], rec['detail']
                cap.imagery_start, cap.imagery_end, cap.observed_at = rec['start'], rec['end'], rec['observed_at']
                cap.save(update_fields=['imagery_source', 'imagery', 'imagery_start', 'imagery_end', 'observed_at'])
                obs = cap.world_time
                if rec['observed_at'] is None:
                    undated += 1
                else:
                    dated += 1
                    windows[(rec['source'], rec['start'].date().isoformat(), rec['end'].date().isoformat())] += 1
                cur.execute('UPDATE sg_detection SET observed_at = %s WHERE capture_id = %s', [obs, cap.id])
                cur.execute('UPDATE sg_factor SET observed_at = %s, valid = tstzrange(%s, upper(valid)) '
                            'WHERE capture_id = %s', [obs, obs, cap.id])
                cur.execute('SELECT DISTINCT a.entity_id FROM sg_association a JOIN sg_detection d '
                            'ON d.id = a.detection_id WHERE d.capture_id = %s', [cap.id])
                touched.update(r[0] for r in cur.fetchall())
                cur.execute("SELECT DISTINCT unnest(entity_ids) FROM sg_factor WHERE capture_id = %s", [cap.id])
                touched.update(r[0] for r in cur.fetchall())
            ids = sorted(touched)
            cur.execute(fusion.ENTITY_SPAN_SQL, [ids])
            cur.execute(GATED_SPAN_SQL, [ids])
        live = Entity.objects.filter(id__in=ids, retired_at__isnull=True)
        absent_before = live.filter(p_exists__lt=0.5).count()
        n_bp = fusion._bp_by_taxonomy(ids, cause='imagery')
        return {
            'captures in the file': len(records),
            'captures found': len(caps),
            'captures dated': dated,
            'captures left at their view time (no usable dates)': undated,
            'imagery windows': {f'{s} {a} to {b}': n for (s, a, b), n in windows.items()},
            'entities touched': len(ids),
            'entities re-inferred': n_bp,
            'entities believed absent (p_exists < 0.5)':
                f'{absent_before} -> {live.filter(p_exists__lt=0.5).count()}',
        }
