"""Name an area whose fused map is kept drawn at /world-model/zones/<slug>.

    add_zone az/tempe --name "Tempe, Arizona" --census-place 0473000
    add_zone az/asu-poly --name "ASU Polytechnic" --bbox=-111.69,33.30,-111.67,33.31
    add_zone ca/santa-cruz --name "Santa Cruz" --geojson limits.geojson

--census-place takes the outline of a US incorporated place from the Census Bureau's TIGERweb
service by its seven-digit GEOID (state FIPS + place FIPS). The map itself is drawn by
``render_zone_maps``.
"""

import json
import re
import urllib.parse
import urllib.request

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError

from deepgis_xr.apps.scene_store import fusion
from deepgis_xr.apps.scene_store.models import Zone

SLUG = re.compile(r'[a-z0-9-]+(/[a-z0-9-]+)*')
TIGERWEB = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query'


def census_place(geoid):
    """(geometry as GeoJSON, name) of an incorporated place."""
    query = urllib.parse.urlencode({'where': f"GEOID='{geoid}'", 'outFields': 'NAME,GEOID', 'outSR': 4326,
                                    'f': 'geojson'})
    with urllib.request.urlopen(f'{TIGERWEB}?{query}', timeout=60) as resp:
        features = json.load(resp).get('features') or []
    if not features:
        raise CommandError(f'the Census Bureau lists no incorporated place {geoid}')
    return features[0]['geometry'], features[0]['properties'].get('NAME', '')


def as_area(geojson):
    geom = GEOSGeometry(json.dumps(geojson), srid=4326)
    if geom.geom_type == 'Polygon':
        geom = MultiPolygon(geom, srid=4326)
    if geom.geom_type != 'MultiPolygon' or geom.empty:
        raise CommandError(f'the outline must be a polygon, not {geom.geom_type}')
    if not geom.valid:
        geom = geom.buffer(0)
        if geom.geom_type == 'Polygon':
            geom = MultiPolygon(geom, srid=4326)
    return geom


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('slug', help="path under /world-model/zones/, lower case: 'az/tempe'")
        parser.add_argument('--name', required=True, help='as printed on the map')
        parser.add_argument('--census-place', default='', help='seven-digit GEOID of a US incorporated place')
        parser.add_argument('--bbox', default='', help='west,south,east,north in degrees; write --bbox=... when west is negative')
        parser.add_argument('--geojson', default='', help='file holding a Polygon or MultiPolygon, a Feature or a FeatureCollection')
        parser.add_argument('--taxonomy', default='urban_v1')
        parser.add_argument('--source', default='', help='where the outline comes from, in words')
        parser.add_argument('--replace', action='store_true', help='change a zone that already exists')

    def handle(self, *args, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        slug = opts['slug'].strip('/')
        if not SLUG.fullmatch(slug) or len(slug) > 80:
            raise CommandError("the slug is lower-case letters, digits and hyphens, in parts joined by '/'")
        given = [k for k in ('census_place', 'bbox', 'geojson') if opts[k]]
        if len(given) != 1:
            raise CommandError('give exactly one of --census-place, --bbox, --geojson')
        if opts['census_place']:
            if not re.fullmatch(r'\d{7}', opts['census_place']):
                raise CommandError('--census-place is a seven-digit GEOID')
            geojson, listed = census_place(opts['census_place'])
            source = f"US Census Bureau TIGERweb, incorporated place {opts['census_place']} ({listed})"
        elif opts['bbox']:
            try:
                w, s, e, n = (float(v) for v in opts['bbox'].split(','))
            except ValueError:
                raise CommandError('--bbox is west,south,east,north')
            if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
                raise CommandError('--bbox must be a non-empty box in degrees')
            geojson, source = json.loads(Polygon.from_bbox((w, s, e, n)).geojson), 'a box given by hand'
        else:
            try:
                with open(opts['geojson']) as fh:
                    doc = json.load(fh)
            except (OSError, ValueError) as exc:
                raise CommandError(f'could not read {opts["geojson"]}: {exc}')
            if doc.get('type') == 'FeatureCollection':
                doc = (doc.get('features') or [{}])[0]
            geojson, source = doc.get('geometry', doc), 'an outline given as GeoJSON'
        area = as_area(geojson)
        fields = {'name': opts['name'], 'taxonomy': opts['taxonomy'], 'area': area, 'source': (opts['source'] or source)[:200]}
        zone = Zone.objects.filter(slug=slug).first()
        if zone is not None and not opts['replace']:
            raise CommandError(f'zone {slug} exists; use --replace to change it')
        if zone is None:
            zone = Zone.objects.create(slug=slug, **fields)
        else:
            for key, value in fields.items():
                setattr(zone, key, value)
            zone.save()
        self.stdout.write(f'zone {zone.slug}: {zone.name}, {area.num_geom} part{"s" if area.num_geom != 1 else ""}, '
                          f'{area.num_coords} points; {zone.source}')
