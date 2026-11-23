"""Retire (or restore) world-model entities without deleting them.

Select by id or by rule; every condition given must hold. Retiring supersedes every factor
that touches the entity at one instant and re-infers its neighbours; --restore revives
exactly those factors. Without --apply the selection is only reported.

  retire_entities --category road --min-area 5000 --min-compactness 0.35 \\
      --first-seen-from 2026-04-01 --first-seen-to 2026-05-01 --reason "April road blobs" --apply
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from deepgis_xr.apps.scene_store import fusion

AREA = 'ST_Area(e.geom::geography)'
COMPACTNESS = f'4 * pi() * {AREA} / nullif(power(ST_Perimeter(e.geom::geography), 2), 0)'


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--ids', help='comma-separated entity ids')
        parser.add_argument('--taxonomy')
        parser.add_argument('--category')
        parser.add_argument('--only-source', help='entities whose only source is this one')
        parser.add_argument('--min-area', type=float, help='m²')
        parser.add_argument('--max-area', type=float, help='m²')
        parser.add_argument('--min-compactness', type=float, help='4πA/P²: 1 disc, 0.785 square, ~0 line')
        parser.add_argument('--first-seen-from', help='ISO date or time, inclusive')
        parser.add_argument('--first-seen-to', help='ISO date or time, exclusive')
        parser.add_argument('--reason', default='', help='stored on each entity (required to retire)')
        parser.add_argument('--restore', action='store_true', help='restore retired entities instead')
        parser.add_argument('--apply', action='store_true', help='act (default: report only)')

    def handle(self, *args, **o):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        where = ['e.retired_at IS NOT NULL' if o['restore'] else 'e.retired_at IS NULL',
                 'ST_XMax(e.geom) <= 180 AND ST_XMin(e.geom) >= -180']
        params = []
        for opt, sql in (('taxonomy', 'e.taxonomy = %s'), ('category', 'e.category = %s'),
                         ('min_area', f'{AREA} >= %s'), ('max_area', f'{AREA} < %s'),
                         ('min_compactness', f'{COMPACTNESS} >= %s'),
                         ('first_seen_from', 'e.first_seen >= %s'), ('first_seen_to', 'e.first_seen < %s')):
            if o[opt] is not None:
                where.append(sql)
                params.append(o[opt])
        if o['only_source']:
            where.append('e.sources = ARRAY[%s]::varchar[]')
            params.append(o['only_source'])
        if o['ids']:
            try:
                ids = [int(i) for i in o['ids'].split(',') if i.strip()]
            except ValueError:
                raise CommandError('--ids must be integers')
            where.append('e.id = ANY(%s)')
            params.append(ids)
        if len(where) == 2:
            raise CommandError('give --ids or at least one selection rule')
        sql = (f'SELECT e.id, e.category, {AREA} FROM sg_entity e WHERE {" AND ".join(where)}')
        with connections[fusion.DB].cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        by_cat = {}
        for _, cat, area in rows:
            n, a = by_cat.get(cat, (0, 0.0))
            by_cat[cat] = (n + 1, a + (area or 0.0))
        self.stdout.write(f"{'retired, to restore' if o['restore'] else 'selected'}: {len(rows)}")
        for cat, (n, a) in sorted(by_cat.items(), key=lambda kv: -kv[1][0]):
            self.stdout.write(f'  {cat}: {n} ({a / 1e6:.3f} km²)')
        if not o['apply'] or not rows:
            self.stdout.write('report only; add --apply to act' if rows else 'nothing to do')
            return
        ids = [r[0] for r in rows]
        if o['restore']:
            out = fusion.restore_entities(ids)
        else:
            if not o['reason'].strip():
                raise CommandError('--reason is required to retire')
            out = fusion.retire_entities(ids, o['reason'].strip())
        self.stdout.write(str(out))
