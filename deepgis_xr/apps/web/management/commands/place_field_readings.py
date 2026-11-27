"""Re-place stored field readings: aim, target and target height from the pose each row holds.

Rows with a usable EKF pose (``fcu_pose``) are aimed by it; the others by their stored heading,
which places them where they already were. Only ``aim``, ``target`` and ``target_up_m`` are
written. Run ``register_field_readings`` afterwards to link the new targets to the world model.

Prints counts only, no position. Without --apply nothing is written.
"""

from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from deepgis_xr.apps.web import field_readings
from deepgis_xr.apps.web.models import FieldReading


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--vehicle', default='', help='only this vehicle id')
        parser.add_argument('--apply', action='store_true', help='write (default: report only)')

    def handle(self, *args, **opts):
        if 'observations' not in settings.DATABASES:
            raise CommandError('observations database is not configured')
        rows = FieldReading.objects.using('observations').order_by('id')
        if opts['vehicle']:
            rows = rows.filter(vehicle_id=opts['vehicle'])
        counts = Counter()
        for reading in rows.iterator(chunk_size=500):
            had = reading.target is not None
            field_readings._place(reading)
            source = (reading.aim or {}).get('source', 'none')
            counts[f'aimed by {source}'] += 1
            counts['with a target'] += reading.target is not None
            counts['newly placed'] += reading.target is not None and not had
            counts['with a hit height'] += 'hit_height_m' in (reading.aim or {})
            counts['course kept with no recent move (not used)'] += bool((reading.aim or {}).get('held'))
            counts['course kept since stopping (loose aim)'] += 'since_moving_s' in (reading.aim or {})
            if opts['apply']:
                with transaction.atomic(using='observations'):
                    reading.save(using='observations', update_fields=['aim', 'target', 'target_up_m'])
        for k in sorted(counts):
            self.stdout.write(f'{k}: {counts[k]}')
        self.stdout.write('applied' if opts['apply'] else 'dry run, nothing written')
