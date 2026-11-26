"""Sample new remote-sensing scenes onto the world entities, and report what is due a re-capture.

For every area that has captures of the taxonomy this looks for Sentinel-2 passes and NAIP
aerial photographs not yet sampled (Planetary Computer, no key needed), for lidar
height-above-ground tiles prepared with ``plan_lidar_height``, and for entities added since a
known scene was sampled, and stores one sample per entity and scene (see ``layers``). It is
a record: no factor is written and no belief changes.

It then reports how current the basemap look-ups are and which captures show imagery the
provider has since replaced. Those look-ups are made by signed-in pages, not here: they need
the provider key the page holds (see ``imagery_watch``).

Meant to run once a day. Without --apply it reads one scene per source to show what a scene
yields and stores nothing.
"""

import json
import time
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.scene_store import fusion, imagery_watch, layers


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--taxonomy', default='urban_v1')
        parser.add_argument('--sources', default=','.join(layers.SOURCES),
                            help=f"comma-separated, of {', '.join(layers.SOURCES)}")
        parser.add_argument('--since', default='', help='YYYY-MM-DD (default: the earliest imagery date of the captures)')
        parser.add_argument('--max-cloud', type=float, default=20.0, help='Sentinel-2 scenes under this cloud cover, percent')
        parser.add_argument('--limit', type=int, default=None, help='read at most this many scenes per source')
        parser.add_argument('--full', action='store_true', help='search the whole period again, not just the recent weeks')
        parser.add_argument('--json', action='store_true', help='print the report as one line of JSON')
        parser.add_argument('--apply', action='store_true', help='store the samples (default: read one scene, store nothing)')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        sources = [s.strip() for s in opts['sources'].split(',') if s.strip()]
        unknown = [s for s in sources if s not in layers.SOURCES]
        if unknown:
            raise CommandError(f"unknown source {', '.join(unknown)}")
        since = None
        if opts['since']:
            try:
                since = datetime.strptime(opts['since'], '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
            except ValueError:
                raise CommandError('--since must be YYYY-MM-DD')
        quiet = opts['json']
        say = (lambda text: None) if quiet else self.stdout.write
        t0 = time.perf_counter()
        report = layers.watch(opts['taxonomy'], sources=sources, since=since, max_cloud=opts['max_cloud'],
                              apply=opts['apply'], limit=opts['limit'], full=opts['full'], say=say)
        basemap = imagery_watch.summary(opts['taxonomy'])
        report['basemap'] = basemap
        report['seconds'] = round(time.perf_counter() - t0, 1)
        if quiet:
            self.stdout.write(json.dumps({'at': datetime.now(dt_timezone.utc).isoformat(timespec='seconds'), **report}))
            return
        for name, rep in report['sources'].items():
            if rep.get('samples_by_category'):
                say(f"{name} samples by category: "
                    + ', '.join(f'{k} {v}' for k, v in rep['samples_by_category'].items()))
            if rep.get('purity_p10_p50_p90'):
                say(f"{name} purity p10 / median / p90: {' / '.join(str(x) for x in rep['purity_p10_p50_p90'])}")
        say(f"basemap: {basemap['n_dated_captures']} dated captures; {basemap['n_checked_recently']} looked up in the "
            f"last {basemap['recheck_days']} days, {basemap['n_never_checked']} never; "
            f"{basemap['n_to_recapture']} show imagery that has since been replaced")
        for flag in basemap['to_recapture']:
            say(f"  re-capture {flag['session_id']}: stored {flag['stored']['start']} to {flag['stored']['end']}, "
                f"now {flag['now']['start']} to {flag['now']['end']}")
        say(f"{'applied' if opts['apply'] else 'dry run, nothing stored'} in {report['seconds']} s")
