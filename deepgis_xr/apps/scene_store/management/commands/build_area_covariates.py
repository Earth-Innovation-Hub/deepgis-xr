"""Compute an area's covariates for ``contents``: per 100 m cell, from Sentinel-2, lidar and
OpenStreetMap.

    python manage.py build_area_covariates --name tempe --bbox=-111.963,33.3709,-111.9077,33.4345
    python manage.py build_area_covariates --name tempe --bbox=... --sources s2,lidar

Writes ``<OBSERVATIONS_ROOT>/layers/covariates/<name>.npz``, replacing any earlier one. The
OpenStreetMap query goes to the public Overpass server once and is cached beside the file.
"""

from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.scene_store import contents, sampler


def _date(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


class Command(BaseCommand):
    help = "Compute an area's covariates (Sentinel-2, lidar, OpenStreetMap) per 100 m cell."

    def add_arguments(self, parser):
        parser.add_argument('--name', required=True)
        parser.add_argument('--bbox', required=True, help='west,south,east,north')
        parser.add_argument('--sources', default='s2,lidar,osm')
        parser.add_argument('--since', type=_date, help='Sentinel-2 window start (default 2023-04-01)')
        parser.add_argument('--until', type=_date, help='Sentinel-2 window end (default 2023-09-30)')

    def handle(self, *args, name, bbox, sources, since, until, **opts):
        try:
            box = [float(v) for v in bbox.split(',')]
        except ValueError:
            raise CommandError('bbox must be west,south,east,north')
        if len(box) != 4 or not (box[0] < box[2] and box[1] < box[3]) \
                or (box[2] - box[0]) * (box[3] - box[1]) > sampler.MAX_BBOX_DEG ** 2:
            raise CommandError(f'bbox must be non-empty and at most {sampler.MAX_BBOX_DEG} degrees square')
        chosen = [s for s in sources.split(',') if s]
        if not chosen or set(chosen) - {'s2', 'lidar', 'osm'}:
            raise CommandError('sources are s2, lidar and osm')
        if not name.replace('_', '').replace('-', '').isalnum():
            raise CommandError('name: letters, digits, - and _')
        try:
            meta = contents.build(name, box, since=since, until=until, sources=chosen)
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"{name}: grid {meta['grid'][0]} x {meta['grid'][1]} cells, {len(meta['names'])} covariates")
        for key in ('sentinel2_cells_filled', 'lidar_cells', 'osm_features'):
            if key in meta:
                self.stdout.write(f'  {key}: {meta[key]}')
        for scene in meta.get('sentinel2') or []:
            self.stdout.write(f"  Sentinel-2 {scene['item_id']} ({scene['observed_at'][:10]})")
