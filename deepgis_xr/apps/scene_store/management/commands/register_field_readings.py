"""Register stored field readings to the world entities under their laser targets.

Each reading with a target is linked to an entity (see ``field_evidence``) and the usable
ones become one weak ``field`` factor per entity, vehicle and day. Running it again is
safe: links and factors are rebuilt only where something changed.

Prints counts and how the linked entities' categories moved. No position is printed.
Without --apply the whole run is rolled back and only reported.
"""

import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from deepgis_xr.apps.scene_store import field_evidence, fusion
from deepgis_xr.apps.scene_store.models import Entity, FieldLink

DB = fusion.DB


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--vehicle', default='', help='only this vehicle id')
        parser.add_argument('--apply', action='store_true', help='commit (default: report and roll back)')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        t0 = time.perf_counter()
        lines = []
        try:
            with transaction.atomic(using=DB):
                before = {e.id: (e.category, e.score) for e in Entity.objects.filter(retired_at__isnull=True)
                          .only('id', 'category', 'score')}
                report, changed = field_evidence.register_all(vehicle_id=opts['vehicle'] or None)
                links = FieldLink.objects.filter(usable=True)
                per = Counter(links.values_list('entity_id', flat=True))
                green = Counter(links.filter(signal__green=True).values_list('entity_id', flat=True))
                for e in Entity.objects.filter(id__in=changed).order_by('id'):
                    was = before.get(e.id, ('?', 0.0))
                    lines.append(f'  entity {e.id}: {per[e.id]} usable readings, {green[e.id]} green; '
                                 f'{was[0]} {was[1]:.2f} -> {e.category} {e.score:.2f}')
                if not opts['apply']:
                    raise Rollback
        except Rollback:
            pass
        for k, v in report.items():
            self.stdout.write(f'{k}: {v}')
        self.stdout.write('entities whose category evidence changed:')
        for line in lines:
            self.stdout.write(line)
        self.stdout.write(f"{'applied' if opts['apply'] else 'dry run, rolled back'} "
                          f'in {time.perf_counter() - t0:.1f} s')
