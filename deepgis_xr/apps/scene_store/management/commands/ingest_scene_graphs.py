"""Replay stored SceneGraph rows into the spatiotemporal factor graph, oldest first."""

import time

from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.scene_store import fusion
from deepgis_xr.apps.scene_store.models import Capture, Entity, Potential
from deepgis_xr.apps.web.models import SceneGraph


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--taxonomy', help='only rows built under this taxonomy')
        parser.add_argument('--limit', type=int, help='stop after this many rows')
        parser.add_argument('--reset', action='store_true', help='delete every capture and entity first')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        if opts['reset']:
            Capture.objects.all().delete()
            Entity.objects.all().delete()
            Potential.objects.all().delete()
            self.stdout.write('cleared the scene store')
        rows = SceneGraph.objects.order_by('created_at')
        if opts['taxonomy']:
            rows = rows.filter(taxonomy_name=opts['taxonomy'])
        if opts['limit']:
            rows = rows[:opts['limit']]
        t0, n = time.perf_counter(), 0
        done = set(Capture.objects.values_list('session_id', flat=True))
        # The registry is SQLite in rollback-journal mode: a cursor held open across the
        # whole replay blocks every writer (robot poses, field readings) until it ends.
        pks = [pk for pk, sid in rows.values_list('pk', 'session_id') if sid not in done]
        for pk in pks:
            row = SceneGraph.objects.filter(pk=pk).first()
            if row is None:
                continue
            sg = {'viewport': row.viewport, 'nodes': row.nodes, 'edges': row.edges,
                  'fusion_metadata': row.fusion_metadata}
            out = fusion.ingest_scene_graph(sg, session_id=row.session_id, taxonomy_name=row.taxonomy_name,
                                            user_id=row.user_id, artifact_path=row.artifact_path,
                                            captured_at=row.created_at)
            if out.get('status') != 'ok':
                continue
            n += 1
            bp = out.get('bp') or {}
            self.stdout.write(
                f"{row.session_id}: {out['n_detections']} det, {out['n_new_entities']} new, "
                f"{out['n_matched']} matched, {out['n_missed']} missed, {out['n_factors']} factors, "
                f"BP {bp.get('n_iter')} it / {bp.get('n_factors')} f, {out['elapsed_ms']} ms")
        self.stdout.write(f'ingested {n} captures in {time.perf_counter() - t0:.1f} s; '
                          f'{Entity.objects.count()} entities')
