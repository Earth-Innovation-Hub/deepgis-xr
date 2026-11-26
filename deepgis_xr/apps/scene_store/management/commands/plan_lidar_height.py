"""Plan height-above-ground tiles from a public USGS 3DEP lidar point cloud.

Planetary Computer has no height product everywhere, but the point clouds themselves are
public (the ``usgs-lidar-public`` bucket, one folder per survey). This writes one PDAL
pipeline per 1 km tile that meets the taxonomy's capture areas. Each pipeline reads the
points, drops the noise classes, measures every point's height above the nearest ground
returns and keeps the highest per 1 m cell. PDAL is not part of this app: run the pipelines
with its container, on the host, with the layer directory mounted at /data:

    docker run --rm -v <layers>/usgs_3dep:/data pdal/pdal pdal pipeline \\
        /data/<project>/pipelines/<tile>.json --metadata /data/<project>/pipelines/<tile>.meta.json

(about three minutes and 20 million points per tile in a city). ``watch_layers`` then samples
the tiles onto the entities, dated by the survey's GPS times in the .meta.json files.

Nothing is written without --apply.
"""

import json
import math
import os

from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.scene_store import fusion, layers
from deepgis_xr.apps.scene_store.models import Capture

BUCKET = 'https://s3-us-west-2.amazonaws.com/usgs-lidar-public'


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('project', help='survey folder in the bucket, e.g. AZ_MaricopaPinal_1_2020')
        parser.add_argument('--taxonomy', default='urban_v1')
        parser.add_argument('--epsg', type=int, default=None, help='projection of the tiles (default: the WGS84 UTM zone)')
        parser.add_argument('--tile', type=int, default=1000, help='tile side, metres')
        parser.add_argument('--apply', action='store_true', help='write the pipelines (default: only count the tiles)')

    def handle(self, *args, **opts):
        from pyproj import Transformer
        from shapely.geometry import box
        from shapely.ops import transform as shapely_transform, unary_union

        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        root = layers.layer_root()
        if not root:
            raise CommandError('OBSERVATIONS_ROOT is not set: there is nowhere to keep the tiles')
        project = opts['project']
        if not project.replace('_', '').replace('-', '').isalnum():
            raise CommandError('project must be a folder name')
        feet = [fusion._from_geos(f) for f in
                Capture.objects.filter(taxonomy=opts['taxonomy']).values_list('footprint', flat=True)]
        if not feet:
            raise CommandError(f"no captures of {opts['taxonomy']}")
        centre = unary_union(feet).centroid
        epsg = opts['epsg'] or (32600 if centre.y >= 0 else 32700) + int((centre.x + 180) // 6) + 1
        to_tile = Transformer.from_crs(4326, epsg, always_xy=True).transform
        to_cloud = Transformer.from_crs(epsg, 3857, always_xy=True).transform   # the bucket's clouds are in web mercator
        area = unary_union([shapely_transform(to_tile, f) for f in feet]).buffer(30)
        size, pad = opts['tile'], 25
        x0, y0, x1, y1 = area.bounds
        out = os.path.join(root, 'usgs_3dep', project)
        tiles = []
        for tx in range(int(math.floor(x0 / size)), int(math.floor(x1 / size)) + 1):
            for ty in range(int(math.floor(y0 / size)), int(math.floor(y1 / size)) + 1):
                square = box(tx * size, ty * size, (tx + 1) * size, (ty + 1) * size)
                if not square.intersects(area):
                    continue
                mx0, my0, mx1, my1 = shapely_transform(to_cloud, square.buffer(pad)).bounds
                name = f'hag_{tx * size}_{ty * size}'
                tiles.append((name, [
                    {'type': 'readers.ept', 'filename': f'{BUCKET}/{project}/ept.json', 'requests': 8,
                     'bounds': f'([{mx0:.2f}, {mx1:.2f}], [{my0:.2f}, {my1:.2f}])'},
                    # 7 and 18 are low and high noise
                    {'type': 'filters.expression', 'expression': 'Classification != 7 && Classification != 18'},
                    {'type': 'filters.reprojection', 'out_srs': f'EPSG:{epsg}'},
                    {'type': 'filters.hag_nn', 'count': 3},
                    {'type': 'filters.stats', 'dimensions': 'GpsTime,HeightAboveGround,Classification',
                     'count': 'Classification'},
                    {'type': 'writers.gdal', 'filename': f'/data/{project}/{name}.tif',
                     'dimension': 'HeightAboveGround', 'output_type': 'max', 'resolution': 1.0,
                     'data_type': 'float32', 'nodata': -9999,
                     'bounds': f'([{tx * size}, {(tx + 1) * size}], [{ty * size}, {(ty + 1) * size}])',
                     'gdalopts': 'COMPRESS=DEFLATE,PREDICTOR=3,TILED=YES'},
                ]))
        self.stdout.write(f'{len(tiles)} tiles of {size} m in EPSG:{epsg} over {area.area / 1e6:.2f} km2 of capture area')
        if not opts['apply']:
            self.stdout.write('dry run, nothing written')
            return
        os.makedirs(os.path.join(out, 'pipelines'), exist_ok=True)
        for name, pipeline in tiles:
            with open(os.path.join(out, 'pipelines', f'{name}.json'), 'w') as fh:
                json.dump(pipeline, fh, indent=1)
        self.stdout.write(f"pipelines written under usgs_3dep/{project}/pipelines in the layer directory")
