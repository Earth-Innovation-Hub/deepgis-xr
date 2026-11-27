"""Label what stored field readings' keyframes show under the spectrometer's patch.

New readings are labelled as they arrive (field_readings.schedule_surface). This fills in
the ones stored before that, and any dropped from its queue, newest first. A standing
rover's repeated views are segmented once and copied. A segmentation takes the GPU service
some tens of seconds.

    manage.py label_field_surfaces                    # count what is left to do
    manage.py label_field_surfaces --apply            # label, then re-register the labelled readings
    manage.py label_field_surfaces --apply --placed   # only readings that have a target
"""

from django.core.management.base import BaseCommand

from deepgis_xr.apps.scene_store import field_evidence, fusion
from deepgis_xr.apps.web import field_surface
from deepgis_xr.apps.web.models import FieldReading


class Command(BaseCommand):
    help = "Label the surface under the spectrometer's patch in stored field readings' keyframes."

    def add_arguments(self, parser):
        parser.add_argument('--vehicle', default='', help='Only this vehicle id')
        parser.add_argument('--since', default='', help='Only readings captured from this date (YYYY-MM-DD)')
        parser.add_argument('--placed', action='store_true', help='Only readings that have a laser target')
        parser.add_argument('--limit', type=int, default=0, help='Stop after this many readings')
        parser.add_argument('--redo', action='store_true', help='Label again readings that already have a surface')
        parser.add_argument('--apply', action='store_true', help='Write the labels (default: only count)')

    def handle(self, *args, **opts):
        rows = (FieldReading.objects.using('observations')
                .exclude(image_relpath='').filter(spectrum__isnull=False)
                .exclude(spectrum__has_key='reference').order_by('-captured_usec'))
        if not opts['redo']:
            rows = rows.filter(surface__isnull=True)
        if opts['vehicle']:
            rows = rows.filter(vehicle_id=opts['vehicle'])
        if opts['since']:
            rows = rows.filter(captured__date__gte=opts['since'])
        if opts['placed']:
            rows = rows.filter(target__isnull=False)
        ids = list(rows.values_list('pk', flat=True)[:opts['limit'] or None])
        self.stdout.write(f'{len(ids)} readings to label')
        if not opts['apply']:
            return
        if opts['redo']:
            # start from no labels, so a repeated view is again segmented once and copied
            FieldReading.objects.using('observations').filter(pk__in=ids).update(surface=None)
        counts, copied, failed, changed = {}, 0, 0, set()
        for i, pk in enumerate(ids, 1):
            surface = field_surface.write_surface(pk)
            if surface is None:
                failed += 1
            else:
                counts[surface['label']] = counts.get(surface['label'], 0) + 1
                copied += 1 if surface.get('from') else 0
                changed |= field_evidence.register_reading(pk, infer=False)
            if i % 25 == 0:
                self.stdout.write(f'  {i}/{len(ids)}: {copied} copied, {failed} not labelled')
        n_bp = fusion._bp_by_taxonomy(changed, cause='field') if changed else 0
        self.stdout.write(f'labelled {sum(counts.values())} ({copied} copied from an earlier look), '
                          f'{failed} not labelled')
        for label, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f'  {label}: {n}')
        self.stdout.write(f'entities whose evidence changed: {len(changed)}, re-inferred: {n_bp}')
