"""Draw the fused map of every zone whose store content changed since its map was drawn.

The maps are served at /world-model/zones/<slug> (see ``zonemap``). A zone is drawn again only
when the entities, captures or corrections it is made from differ from those of the files on
disk, so this is cheap to run often: every few minutes keeps the published map the latest.

    render_zone_maps                   every zone that is due
    render_zone_maps --zone az/tempe   one zone
    render_zone_maps --force           draw even when nothing changed
"""

import json
import os
import time
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.scene_store import fusion, zonemap
from deepgis_xr.apps.scene_store.models import Zone


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--zone', default='', help='slug of one zone (default: all)')
        parser.add_argument('--force', action='store_true', help='draw even when the store has not changed')
        parser.add_argument('--no-backdrop', action='store_true', help='leave out the aerial photograph under the map')
        parser.add_argument('--json', action='store_true', help='one line of JSON, and only when something was drawn')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        try:
            os.nice(10)   # the web workers of this container come first
        except OSError:
            pass
        zones = Zone.objects.all()
        if opts['zone']:
            zones = zones.filter(slug=opts['zone'].strip('/'))
            if not zones.exists():
                raise CommandError(f"no zone {opts['zone']}")
        quiet = opts['json']
        say = (lambda text: None) if quiet else self.stdout.write
        photo = not opts['no_backdrop']
        report, failed = [], 0
        for zone in zones:
            why = 'asked to' if opts['force'] else zonemap.due(zone, with_backdrop=photo)
            if not why:
                say(f'{zone.slug}: current')
                continue
            t0 = time.perf_counter()
            try:
                out = zonemap.render(zone, with_backdrop=photo, say=say)
            except Exception as exc:
                failed += 1
                report.append({'zone': zone.slug, 'why': why, 'error': f'{type(exc).__name__}: {exc}'[:300]})
                self.stderr.write(f'{zone.slug}: not drawn: {type(exc).__name__}: {exc}')
                continue
            if out is None:
                say(f'{zone.slug}: another process is drawing it')
                continue
            report.append({'zone': zone.slug, 'why': why, 'state': out['state'], 'objects': out['objects']['n'],
                           'captures': out['looked_at']['n_captures'], 'photograph': bool(out['backdrop']),
                           'bytes': out['files'], 'seconds': round(time.perf_counter() - t0, 1)})
            say(f"{zone.slug}: drawn ({why}); {out['objects']['n']} objects, state {out['state']}")
        if quiet and report:
            self.stdout.write(json.dumps({'at': datetime.now(dt_timezone.utc).isoformat(timespec='seconds'),
                                          'drawn': report}))
        if failed:
            raise CommandError(f'{failed} zone{"s" if failed != 1 else ""} could not be drawn')
