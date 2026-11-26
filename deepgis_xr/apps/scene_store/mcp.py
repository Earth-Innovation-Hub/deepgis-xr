"""Read-only MCP server over the scene-graph store (streamable HTTP, stateless, JSON replies).

    POST /api/v1/mcp     JSON-RPC 2.0: initialize, ping, tools/list, tools/call
    Authorization: Bearer <token>, whose sha256 is listed in SCENE_MCP_TOKENS ("hex,hex")

The tools wrap the same queries as /webclient/sampler/world/*. Areas are a point and a radius
instead of a bbox, and entities come back as centre points unless outlines are asked for, so
a whole block fits in a model's context.
"""

import hashlib
import hmac
import json
import logging
import math
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.gis.db.models.functions import PointOnSurface
from django.contrib.gis.geos import Polygon
from django.db import connections
from django.db.models import Count, Max, Min
from django.http import HttpResponse, JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from deepgis_xr.apps.web.models import FieldReading

from . import assess, fusion, imagery_watch, layers, priors, traits, views
from .models import BeliefSnapshot, Capture, Detection, Entity, Factor, Feedback, FieldLink

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
SERVER_INFO = {'name': 'deepgis-scene-graph', 'title': 'DeepGIS scene graphs', 'version': '1.0.0'}
ALLOWED_ORIGINS = {'https://deepgis.org', 'https://www.deepgis.org'}
M_PER_DEG = 111320.0
MAX_TEXT = 400_000

INSTRUCTIONS = (
    "DeepGIS world model: objects (entities) fused over time from scene graphs, each built by "
    "segmenting a top-down map capture (SAM 3 and other models) into urban categories. "
    "Find where data exists with world_stats or list_scene_graphs (no location = newest anywhere). "
    "world_summary describes an area, find_entities lists its objects, get_entity explains one "
    "object's evidence, world_changes compares dates, get_scene_graph returns one capture's nodes "
    "and links, trait_map gives per-category statistics and a Gaussian-process map of sizes, "
    "assess_point answers what is at one point and on how much evidence. "
    "field_readings summarises the ground robot's survey (counts and spectra, never where it was), "
    "entity_looks lists the captures that covered one object and whether each found it, "
    "belief_history is that object's stored belief after each capture, and entity_beliefs pages "
    "through every live object's belief. Capture footprints are list_scene_graphs with "
    "include_footprints. Captures of the same "
    "imagery are one look and count once, however many there are (get_entity's support). "
    "confidence = probability of the category; p_exists = probability the object was "
    "there when last seen (pass at= to find_entities, or read get_entity's now, for the belief "
    "decayed to a date). first_seen and last_seen are imagery dates: each capture records the "
    "imagery it showed and when that was acquired (observed_at), separately from when the view "
    "was taken (captured_at). get_entity's layers hold what Sentinel-2 passes, NAIP aerial "
    "photographs and a lidar survey measured over the object (NDVI series, height): a record "
    "with its own dates, not part of the beliefs. Below the low-confidence threshold the category is 'unknown' and candidates hold "
    "the best guesses. Coordinates are WGS84 [lon, lat] degrees, areas square metres, times UTC."
)


class ToolError(Exception):
    pass


# ---- arguments ---------------------------------------------------------------------------------

def _float(args, key, default=None, lo=None, hi=None):
    v = args.get(key, default)
    if v is None:
        raise ToolError(f'{key} is required')
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ToolError(f'{key} must be a number')
    if not math.isfinite(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ToolError(f'{key} must be between {lo} and {hi}')
    return v


def _int(args, key, default, hi):
    return int(min(max(_float(args, key, default), 1), hi))


def _bool(args, key):
    return args.get(key) in (True, 1, 'true', 'True', '1')


def _text(args, key):
    v = args.get(key)
    return str(v).strip() or None if v is not None else None


def _time(args, key):
    raw = _text(args, key)
    if raw is None:
        return None
    t = parse_datetime(raw) or views._day(raw)
    if t is None:
        raise ToolError(f'{key} must be an ISO 8601 time or YYYY[-MM[-DD]]')
    return t if t.tzinfo else t.replace(tzinfo=dt_timezone.utc)


def _area(args, max_deg, default_m):
    """(bbox, area) for the square reaching radius_m each way from lat/lon, kept inside the
    store's ``max_deg`` square-degree limit."""
    lat = _float(args, 'lat', lo=-89.9, hi=89.9)
    lon = _float(args, 'lon', lo=-180, hi=180)
    k = math.cos(math.radians(lat))
    r_max = math.floor(max_deg * M_PER_DEG * math.sqrt(k) / 2 * 0.999)
    r = min(_float(args, 'radius_m', default_m, lo=1), r_max)
    dlat, dlon = r / M_PER_DEG, r / (M_PER_DEG * k)
    area = {'lat': lat, 'lon': lon, 'radius_m': round(r)}
    if r == r_max:
        area['note'] = f'radius limited to {r_max} m here'
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat), area


# ---- shaping -----------------------------------------------------------------------------------

def _centre(ring):
    if not ring:
        return None
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    return [round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6)]


def _dist_m(a, b):
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * k, a[1] - b[1]) * M_PER_DEG


def _entity(d, origin=None, polygon=False):
    """An entity_to_dict row without the posterior vector and outline."""
    tax = fusion.taxonomy_by_name(d['taxonomy'])
    ranked = sorted(enumerate(d['posterior']), key=lambda kv: -kv[1])[:3]
    centre = _centre(d['geo_polygon'])
    out = {'id': d['id'], 'category': d['category'], 'confidence': d['score'],
           'candidates': [{'category': tax.name_of(i), 'p': p} for i, p in ranked],
           'p_exists': d['p_exists'], 'area_m2': d['area_m2'], 'centre': centre,
           'first_seen': d['first_seen'], 'last_seen': d['last_seen'],
           'n_hits': d['n_hits'], 'n_misses': d['n_misses'], 'sources': d['sources']}
    if origin and centre:
        out['distance_m'] = round(_dist_m(origin, centre), 1)
    if d.get('retired'):
        out['retired'] = d['retired']
    if polygon:
        out['polygon'] = d['geo_polygon']
    return out


def _counts(rows, key='category'):
    c = {}
    for r in rows:
        c[r[key]] = c.get(r[key], 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


# ---- tools -------------------------------------------------------------------------------------

def world_stats(args):
    ents = Entity.objects.filter(retired_at__isnull=True)
    span = Capture.objects.aggregate(n=Count('id'), first=Min('captured_at'), last=Max('captured_at'))
    taxonomies = {}
    for name in Capture.objects.values_list('taxonomy', flat=True).distinct():
        try:
            taxonomies[name] = list(fusion.taxonomy_by_name(name).categories)
        except Exception:
            taxonomies[name] = None
    return {
        'n_captures': span['n'],
        'first_capture': span['first'].isoformat() if span['first'] else None,
        'last_capture': span['last'].isoformat() if span['last'] else None,
        'n_entities': ents.count(),
        'entities_by_category': dict(sorted(ents.values_list('category').annotate(n=Count('id')).order_by(),
                                            key=lambda kv: -kv[1])),
        'n_feedback': Feedback.objects.filter(superseded_at__isnull=True).count(),
        'taxonomies': taxonomies,
        'low_confidence': priors.LOW_CONFIDENCE,
        'imagery': fusion.imagery_dates(Capture.objects.all()),
        'detection_models': views.detection_models(),
        'layers': layers.layer_stats(),
        'imagery_checks': imagery_watch.summary(),
    }


def list_scene_graphs(args):
    if args.get('lat') is None and args.get('lon') is None:
        bbox, area = None, None
    else:
        bbox, area = _area(args, views.MAX_CAPTURE_BBOX_DEG, 5000)
    out = views.captures_in(bbox, taxonomy=_text(args, 'taxonomy'), limit=_int(args, 'limit', 10, 100))
    footprints = _bool(args, 'include_footprints')
    for c in out['captures']:
        c['centre'] = _centre(c['footprint'])
        if not footprints:
            c.pop('footprint')
    return {'area': area, **out}


def get_scene_graph(args):
    session_id = _text(args, 'session_id')
    if not session_id:
        raise ToolError('session_id is required (see list_scene_graphs)')
    cap = Capture.objects.filter(session_id=session_id).first()
    if cap is None:
        raise ToolError(f'no stored scene graph {session_id}')
    d = views.capture_detail(cap)
    category = _text(args, 'category')
    dets = [x for x in d['detections'] if not category or category in (x['category'], x['best_guess'])]
    keep = dets[:_int(args, 'max_nodes', 150, views.MAX_CAPTURE_DETECTIONS)]
    polygons = _bool(args, 'include_polygons')
    nodes = []
    for x in keep:
        n = {'id': x['id'], 'entity_id': x['entity_id'], 'category': x['category'], 'best_guess': x['best_guess'],
             'confidence': x['score'], 'area_m2': x['area_m2'], 'centre': _centre(x['geo_polygon'])}
        if polygons:
            n['polygon'] = x['geo_polygon']
        nodes.append(n)
    ids = {n['entity_id'] for n in nodes if n['entity_id']}
    links = [link for link in d['links'] if set(link['entities']) <= ids]
    return {'capture': d['capture'], 'n_nodes': len(dets), 'n_returned': len(nodes),
            'by_category': _counts(dets), 'n_gated': d['n_gated'], 'n_retired': d['n_retired'],
            'nodes': nodes, 'n_links': len(d['links']), 'links': links,
            'link_kinds': {'context': 'two entities seen next to each other',
                           'contains': 'the first entity lies inside the second'}}


def get_entity(args):
    entity_id = int(_float(args, 'entity_id', lo=1))
    e = Entity.objects.filter(id=entity_id).first()
    if e is None:
        raise ToolError(f'no entity {entity_id}')
    d = views.entity_detail(e, include_field=True)
    n = _int(args, 'max_sightings', 20, 500)
    return {'entity': _entity(d['entity'], polygon=_bool(args, 'include_polygon')),
            'now': d.get('now'),
            'n_sightings': len(d['detections']), 'sightings': d['detections'][::-1][:n],
            'n_history': len(d['history']), 'history': d['history'][-10:],
            'feedback': d['feedback'], 'field_readings': d.get('field'),
            'factor_counts': d['factor_counts'], 'support': d['support'], 'layers': d['layers']}


def assess_point(args):
    lat = _float(args, 'lat', lo=-89.9, hi=89.9)
    lon = _float(args, 'lon', lo=-180, hi=180)
    sigma = _float(args, 'sigma_m', lo=assess.MIN_SIGMA_M, hi=assess.MAX_SIGMA_M) \
        if args.get('sigma_m') is not None else None
    taxonomy = _text(args, 'taxonomy') or 'urban_v1'
    try:
        fusion.taxonomy_by_name(taxonomy)
    except Exception:
        raise ToolError(f'unknown taxonomy {taxonomy}')
    return assess.assess_point(lon, lat, at=_time(args, 'at'), taxonomy=taxonomy, sigma_m=sigma)


def world_summary(args):
    bbox, area = _area(args, views.MAX_BBOX_DEG, 300)
    return {'area': area, **fusion.world_summary(bbox, taxonomy=_text(args, 'taxonomy'))}


SORTS = {
    'distance': lambda e: e.get('distance_m', 0),
    'confidence': lambda e: -e['confidence'],
    'uncertain': lambda e: e['confidence'],
    'area': lambda e: -(e['area_m2'] or 0),
    'recent': lambda e: e['last_seen'],
}


def find_entities(args):
    bbox, area = _area(args, views.MAX_BBOX_DEG, 200)
    sort = _text(args, 'sort') or 'distance'
    if sort not in SORTS:
        raise ToolError(f'sort must be one of {", ".join(SORTS)}')
    at = _time(args, 'at')
    rows, _ = fusion.entities_in_bbox(bbox, at=at, taxonomy=_text(args, 'taxonomy'),
                                      min_p_exists=_float(args, 'min_p_exists', 0, 0, 1),
                                      min_score=_float(args, 'min_confidence', 0, 0, 1))
    category = _text(args, 'category')
    origin = [area['lon'], area['lat']]
    polygons = _bool(args, 'include_polygons')
    ents = [_entity(d, origin, polygons) for d in rows if not category or d['category'] == category]
    ents.sort(key=SORTS[sort], reverse=sort == 'recent')
    limit = _int(args, 'limit', 50, 500)
    return {'area': area, 'at': at.isoformat() if at else None, 'n_matched': len(ents),
            'n_returned': min(limit, len(ents)), 'store_limit_reached': len(rows) >= 2000,
            'by_category': _counts(ents), 'entities': ents[:limit]}


def world_changes(args):
    bbox, area = _area(args, views.MAX_BBOX_DEG, 300)
    since = views._day(_text(args, 'since') or '')
    until = views._day(_text(args, 'until') or '') if _text(args, 'until') else None
    if since is None or (_text(args, 'until') and until is None):
        raise ToolError('since (and until, if given) must be YYYY, YYYY-MM or YYYY-MM-DD')
    if until is not None and until <= since:
        raise ToolError('until must be after since')
    limit = _int(args, 'limit', 25, 200)
    basis = _text(args, 'basis') or 'imagery'
    if basis not in ('imagery', 'view'):
        raise ToolError('basis must be imagery or view')
    out = fusion.world_changes(bbox, since, until, taxonomy=_text(args, 'taxonomy'), limit=limit, basis=basis)
    origin = [area['lon'], area['lat']]
    for k in ('appeared', 'gone'):
        out[k]['entities'] = [_entity(d, origin) for d in out[k]['entities']]
    return {'area': area, **out}


def area_histogram(args):
    bbox, area = _area(args, views.MAX_BBOX_DEG, 300)
    rows = Entity.objects.filter(geom__intersects=Polygon.from_bbox(bbox), retired_at__isnull=True,
                                 p_exists__gte=_float(args, 'min_p_exists', 0, 0, 1))
    if _text(args, 'taxonomy'):
        rows = rows.filter(taxonomy=_text(args, 'taxonomy'))
    if _text(args, 'category'):
        rows = rows.filter(category=_text(args, 'category'))
    max_m2 = _float(args, 'max_m2', lo=0.01) if args.get('max_m2') is not None else None
    return {'area': area, 'category': _text(args, 'category'),
            **fusion.area_histogram(rows.values_list('area_m2', flat=True), max_m2=max_m2)}


NOTE_GROUPS = (('hedge or shrub', ('hedge', 'shrub')), ('paved', ('paved', 'pavement')),
               ('wall or fence', ('wall', 'fence')), ('roof or house', ('roof', 'house')),
               ('tree', ('tree',)), ('grass', ('grass',)), ('vehicle', ('vehicle', 'car')),
               ('pool', ('pool',)), ('road', ('road',)))

DAY_SQL = """
SELECT (captured AT TIME ZONE 'America/Phoenix')::date,
       count(*), count(camera), count(target), count(*) FILTER (WHERE range_valid),
       count(*) FILTER (WHERE jsonb_typeof(spectrum->'indices'->'nir_red') = 'number'),
       count(*) FILTER (WHERE jsonb_typeof(spectrum->'indices'->'nir_red') = 'number'
                        AND (spectrum->'indices'->>'nir_red')::float > %s),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (spectrum->'indices'->>'nir_red')::float)
         FILTER (WHERE jsonb_typeof(spectrum->'indices'->'nir_red') = 'number'),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (spectrum->>'integration_ms')::float)
         FILTER (WHERE jsonb_typeof(spectrum->'integration_ms') = 'number'),
       count(*) FILTER (WHERE jsonb_typeof(spectrum->'clipped_pct') = 'number'
                        AND (spectrum->>'clipped_pct')::float > 0)
  FROM field_readings
 WHERE (%s IS NULL OR captured >= %s) AND (%s IS NULL OR captured < %s)
 GROUP BY 1 ORDER BY 1
"""
SOURCE_SQL = """
SELECT coalesce(spectrum->'acquisition'->>'source', ''), count(*)
  FROM field_readings
 WHERE (%s IS NULL OR captured >= %s) AND (%s IS NULL OR captured < %s)
 GROUP BY 1 ORDER BY 2 DESC
"""


def _round(v, n=3):
    return None if v is None else round(float(v), n)


def _reading_window(args):
    """(since, until) as aware datetimes, until exclusive. Both optional."""
    since, until = _time(args, 'since'), _time(args, 'until')
    if until and len(_text(args, 'until') or '') == 10:
        until += timedelta(days=1)
    if since and until and until <= since:
        raise ToolError('until must be after since')
    return since, until


def field_readings(args):
    """The ground survey as counts. Camera and target coordinates are never selected."""
    since, until = _reading_window(args)
    bounds = (since, since, until, until)
    with connections[FieldReading.objects.db].cursor() as cur:
        cur.execute(DAY_SQL, [priors.FIELD_GREEN_INDEX, *bounds])
        days = cur.fetchall()
        cur.execute(SOURCE_SQL, bounds)
        sources = cur.fetchall()
    by_day = []
    for day, n, n_pos, n_target, n_range, n_index, n_green, nir, integ, n_clip in days:
        by_day.append({
            'day': day.isoformat(), 'n': n, 'n_with_position': n_pos, 'n_with_target': n_target,
            'n_with_range': n_range, 'n_with_index': n_index,
            'green_share': _round(n_green / n_index) if n_index else None,
            'nir_red_median': _round(nir), 'integration_ms_median': _round(integ, 0),
            'clipping_share': _round(n_clip / n_index) if n_index else None,
        })
    notes = {name: 0 for name, _ in NOTE_GROUPS}
    n_notes = 0
    qs = FieldReading.objects.all()
    if since:
        qs = qs.filter(captured__gte=since)
    if until:
        qs = qs.filter(captured__lt=until)
    for analysis in qs.values_list('analysis', flat=True).iterator(chunk_size=500):
        text = analysis.get('image') if isinstance(analysis, dict) else None
        if not isinstance(text, str) or not text.strip():
            continue
        n_notes += 1
        low = text.lower()
        for name, words in NOTE_GROUPS:
            if any(w in low for w in words):
                notes[name] += 1
    links = FieldLink.objects.all()
    if since:
        links = links.filter(observed_at__gte=since)
    if until:
        links = links.filter(observed_at__lt=until)
    linked = {}
    for category, n in links.values_list('entity__category').annotate(n=Count('id')).order_by():
        linked[category] = n
    totals = {k: sum(d[k] for d in by_day) for k in ('n', 'n_with_position', 'n_with_target', 'n_with_range',
                                                     'n_with_index')}
    return {
        'n_readings': totals.get('n', 0), 'n_with_position': totals.get('n_with_position', 0),
        'n_with_target': totals.get('n_with_target', 0), 'n_with_range': totals.get('n_with_range', 0),
        'n_with_index': totals.get('n_with_index', 0), 'n_image_notes': n_notes,
        'n_registered': sum(linked.values()),
        'green_rule': f'nir_red > {priors.FIELD_GREEN_INDEX}',
        'by_day': by_day, 'acquisition': {name or 'unknown': n for name, n in sources},
        'image_notes': notes, 'registered_by_category': dict(sorted(linked.items(), key=lambda kv: -kv[1])),
        'positions': 'not returned; camera and target coordinates stay in the readings table',
    }


def entity_looks(args):
    """Every capture whose footprint covers an object, and whether that capture found it."""
    e = Entity.objects.filter(id=int(_float(args, 'entity_id', lo=1))).first()
    if e is None:
        raise ToolError(f"no entity {args.get('entity_id')}")
    caps = list(Capture.objects.filter(taxonomy=e.taxonomy, footprint__covers=e.geom.envelope)
                .order_by('captured_at'))
    found = set(Detection.objects.filter(association__entity=e, capture__in=caps)
                .values_list('capture_id', flat=True))
    missed = set(Factor.objects.filter(kind='miss', entity_ids__contains=[e.id], superseded_at__isnull=True,
                                       capture__in=caps).values_list('capture_id', flat=True))
    rows = []
    for c in caps:
        pixels = (e.area_m2 / c.gsd_m ** 2) if e.area_m2 and c.gsd_m else None
        rows.append({
            'session_id': c.session_id, 'captured_at': c.captured_at.isoformat(),
            'imagery': views._imagery_dict(c), 'gsd_m': round(c.gsd_m, 3) if c.gsd_m else None,
            'pixels': round(pixels) if pixels is not None else None,
            'resolvable': pixels is not None and pixels >= priors.MISS_MIN_PIXELS,
            'found': c.id in found, 'missed': c.id in missed,
        })
    return {'entity_id': e.id, 'category': e.category, 'n_captures': len(rows),
            'n_found': sum(r['found'] for r in rows), 'n_missed': sum(r['missed'] for r in rows),
            'captures': rows}


def belief_history(args):
    """The stored belief after each thing that changed it, oldest first, one page at a time."""
    e = Entity.objects.filter(id=int(_float(args, 'entity_id', lo=1))).first()
    if e is None:
        raise ToolError(f"no entity {args.get('entity_id')}")
    qs = BeliefSnapshot.objects.filter(entity=e).select_related('capture').order_by('at', 'id')
    n = qs.count()
    after = int(_float(args, 'after_id', 0, lo=0))
    if after:
        qs = qs.filter(id__gt=after)
    limit = _int(args, 'limit', 50, 200)
    rows = list(qs[:limit])
    more = bool(rows) and BeliefSnapshot.objects.filter(entity=e, id__gt=rows[-1].id).exists()
    return {'entity_id': e.id, 'n': n, 'n_returned': len(rows),
            'next_after_id': rows[-1].id if more else None,
            'history': [{'id': s.id, 'at': s.at.isoformat(), 'category': s.category,
                         'p_exists': round(s.p_exists, 4), 'score': round(max(s.posterior), 4),
                         'cause': s.cause, 'session_id': s.capture.session_id if s.capture_id else None}
                        for s in rows]}


def entity_beliefs(args):
    """Live objects and their beliefs, in id order, so a whole taxonomy can be read a page at a time."""
    taxonomy = _text(args, 'taxonomy')
    after = int(_float(args, 'after_id', 0, lo=0))
    limit = _int(args, 'limit', 200, 500)
    qs = Entity.objects.filter(retired_at__isnull=True)
    if taxonomy:
        try:
            fusion.taxonomy_by_name(taxonomy)
        except Exception:
            raise ToolError(f'unknown taxonomy {taxonomy}')
        qs = qs.filter(taxonomy=taxonomy)
    n = qs.count()
    rows = list(qs.filter(id__gt=after).annotate(pt=PointOnSurface('geom')).order_by('id').defer('geom')[:limit])
    ents = []
    for e in rows:
        pt = e.pt
        post = e.posterior or []
        ranked = sorted(enumerate(post), key=lambda kv: -kv[1])[:3]
        tax = fusion.taxonomy_by_name(e.taxonomy)
        ents.append({
            'id': e.id, 'taxonomy': e.taxonomy, 'category': e.category, 'confidence': round(e.score, 4),
            'candidates': [{'category': tax.name_of(i), 'p': round(float(p), 4)} for i, p in ranked],
            'p_exists': round(e.p_exists, 4),
            'area_m2': round(e.area_m2, 2) if e.area_m2 is not None else None,
            'centre': [round(pt.x, 6), round(pt.y, 6)] if pt else None,
            'n_hits': e.n_hits, 'n_misses': e.n_misses,
            'first_seen': e.first_seen.isoformat(), 'last_seen': e.last_seen.isoformat(),
        })
    return {'taxonomy': taxonomy, 'n_entities': n, 'n_returned': len(ents),
            'next_after_id': ents[-1]['id'] if len(ents) == limit else None, 'entities': ents}


def trait_map(args):
    bbox, area = _area(args, views.MAX_BBOX_DEG, 250)
    trait = _text(args, 'trait') or 'area'
    if trait not in traits.TRAITS:
        raise ToolError(f'trait must be one of {", ".join(traits.TRAITS)}')
    cells = _int(args, 'grid_cells', 24, 48) if args.get('grid_cells') is not None else None
    out = traits.trait_map(bbox, trait=trait, category=_text(args, 'category') or '',
                           taxonomy=_text(args, 'taxonomy') or 'urban_v1',
                           min_p_exists=_float(args, 'min_p_exists', 0.5, 0, 1),
                           grid_cells=cells or traits.GRID_CELLS, with_grid=cells is not None)
    for c in out['categories']:
        c['hist'] = {'bins': c['hist']['bins'], 'log': c['hist']['log']}
    return {'area': area, **out}


# ---- tool list ---------------------------------------------------------------------------------

def _num(desc):
    return {'type': 'number', 'description': desc}


def _str(desc):
    return {'type': 'string', 'description': desc}


def _flag(desc):
    return {'type': 'boolean', 'description': desc}


LAT = _num('Latitude, WGS84 degrees')
LON = _num('Longitude, WGS84 degrees')
TAXONOMY = _str("Category set, e.g. 'urban_v1' (default: all)")
RADIUS = 'Metres from the point to each side of the square searched'

TOOLS = [
    ('world_stats', 'World model totals',
     'Totals for the whole store: captures, live entities per category, the category sets, the '
     'low-confidence threshold below which an entity is called unknown, the imagery the captures '
     'showed with its acquisition dates, and the fitted chance that a later look finds an object '
     'again (detection_models: per doubling of pixels, per doubling coarser or finer than the '
     'first sighting, and per category, in log-odds). layers lists the remote-sensing record per '
     'source (scenes, dates, samples, entities sampled); imagery_checks says how recently the '
     "basemap's dates were looked up again and which captures show imagery the provider has since "
     'replaced (to_recapture).',
     {}, [], world_stats),
    ('list_scene_graphs', 'List stored scene graphs',
     'Stored scene graphs (one per map capture), newest first, with the time of the view (captured_at), '
     'the imagery shown and its acquisition dates (imagery, observed_at), category counts, centre, '
     'ground resolution (gsd_m) and the smallest object a miss can count for (min_object_m2). Without '
     'lat/lon, lists the newest anywhere: use this to find where data exists.',
     {'lat': LAT, 'lon': LON, 'radius_m': _num(f'{RADIUS} (default 5000, at most ~25 km)'),
      'taxonomy': TAXONOMY, 'limit': _num('At most this many (default 10, max 100)'),
      'include_footprints': _flag('Include each capture footprint polygon')},
     [], list_scene_graphs),
    ('get_scene_graph', 'Get one scene graph',
     "One capture's graph: nodes (detections, highest confidence first, each with the world entity it "
     "was merged into) and links between those entities ('context' = seen together, 'contains' = "
     'first inside second).',
     {'session_id': _str('Capture id from list_scene_graphs'),
      'category': _str('Only nodes of this category or best guess'),
      'max_nodes': _num('At most this many nodes (default 150)'),
      'include_polygons': _flag('Include node outlines as [lon, lat] rings')},
     ['session_id'], get_scene_graph),
    ('world_summary', 'Summarise an area',
     'What the world model holds around a point: counts per category, confidence spread, and what the '
     'unknown objects most likely are.',
     {'lat': LAT, 'lon': LON, 'radius_m': _num(f'{RADIUS} (default 300, at most ~2,500; less at high latitudes)'),
      'taxonomy': TAXONOMY},
     ['lat', 'lon'], world_summary),
    ('find_entities', 'Find objects in an area',
     'Objects around a point with category, confidence, top three candidates, p_exists, area, centre, '
     'distance and sighting counts. Beliefs are as last seen; at= gives them for a date instead '
     '(evidence imaged up to then, decayed to then; today answers "is it still there").',
     {'lat': LAT, 'lon': LON, 'radius_m': _num(f'{RADIUS} (default 200, at most ~2,500; less at high latitudes)'),
      'category': _str("Only this category (e.g. 'pool', 'building', 'unknown')"),
      'min_confidence': _num('Minimum category probability, 0-1'),
      'min_p_exists': _num('Minimum probability the object still exists, 0-1'),
      'at': _str('Beliefs for this date (ISO 8601 or YYYY-MM-DD); default: as last seen'),
      'sort': {'type': 'string', 'enum': list(SORTS), 'description': 'Order (default distance)'},
      'limit': _num('At most this many (default 50, max 500)'),
      'taxonomy': TAXONOMY, 'include_polygons': _flag('Include outlines as [lon, lat] rings')},
     ['lat', 'lon'], find_entities),
    ('get_entity', 'Explain one object',
     "One object's full record: candidates, every sighting (imagery date, when it was viewed, capture, "
     'label, score, area, image ground resolution), the belief as last seen and decayed to now, '
     'belief history, feedback, field readings a ground robot aimed at it, and factor counts. '
     'support lists the looks the belief rests on, one per image: how many captures showed it, '
     'how often the object was found and missed, and what that image says on its own (exists.p, '
     'category). Captures of one image share its mistakes and count once: one_look_p_exists is '
     'the range a single image can give, and only another image, a correction or a field reading '
     'moves the belief beyond it. '
     'layers is the remote-sensing record over the object, one row per source: number of samples, '
     'first and last date, latest value, the value around the imagery date (at_last_seen), min / '
     'median / max, a series (monthly medians [month, value, n] when long) and purity, the share '
     'of the sampled signal that comes from inside the outline (the rest is its surroundings). '
     'Sentinel-2 NDVI is from surface reflectance; NAIP NDVI is from uncalibrated photograph '
     'numbers; lidar height is metres above ground (value = median, p90 = top). Objects too '
     'small for a sensor have no row for it. None of this is in the beliefs.',
     {'entity_id': _num('Entity id'), 'max_sightings': _num('Newest sightings to include (default 20)'),
      'include_polygon': _flag('Include the outline')},
     ['entity_id'], get_entity),
    ('assess_point', 'What is at a point',
     'The fused assessment at one point: what is there and on how much evidence. Stored objects '
     'that cover the point are composed front to back, smallest on top: each counts by weight (the '
     "share of the point's position uncertainty inside its outline) times p_exists, giving its "
     'share of the answer. fused is the resulting category distribution (candidates) and '
     'no_object, the chance that no stored object accounts for the point; fused.category is null '
     'when that is the likeliest. looked_at says how many captures and distinct images cover the '
     'point, so "nothing found" can be told from "never looked". Each object lists its support '
     '(independent looks, times found and missed, corrections). remote_sensing holds the latest '
     'satellite, aerial and lidar values over the object with the largest share; they are a '
     'record, not part of the beliefs. Beliefs are as last seen unless at is given.',
     {'lat': LAT, 'lon': LON,
      'at': _str('Beliefs for this date (ISO 8601 or YYYY-MM-DD); today answers what is likely still there'),
      'sigma_m': _num('How well the point is located, metres 1-sigma (default 2.5, the imagery registration)'),
      'taxonomy': _str("Category set (default 'urban_v1')")},
     ['lat', 'lon'], assess_point),
    ('world_changes', 'What changed in an area',
     'Objects first seen between two dates, and objects missed then that are believed gone. The dates '
     'are imagery acquisition dates by default, so two looks at the same imagery are not a change; '
     "imagery lists what the captures showed and note says when no change on the ground can be read. "
     "basis='view' compares by when the views were taken instead (detector runs). Misses only count "
     'where the capture could resolve the object, weighted by the fitted chance of finding it.',
     {'lat': LAT, 'lon': LON, 'radius_m': _num(f'{RADIUS} (default 300, at most ~2,500; less at high latitudes)'),
      'since': _str('YYYY, YYYY-MM or YYYY-MM-DD (UTC)'), 'until': _str('Same format; default now'),
      'basis': {'type': 'string', 'enum': ['imagery', 'view'], 'description': 'Which clock the dates are on (default imagery)'},
      'limit': _num('Objects listed per side (default 25, max 200)'), 'taxonomy': TAXONOMY},
     ['lat', 'lon', 'since'], world_changes),
    ('area_histogram', 'Object sizes in an area',
     'Histogram of object areas (median over sightings) around a point, with min / p10 / median / mean / '
     'p90 / max.',
     {'lat': LAT, 'lon': LON, 'radius_m': _num(f'{RADIUS} (default 300, at most ~2,500; less at high latitudes)'),
      'category': _str('Only this category'), 'min_p_exists': _num('Minimum p_exists, 0-1'),
      'max_m2': _num('Upper edge of the last bin (default: 99th percentile)'), 'taxonomy': TAXONOMY},
     ['lat', 'lon'], area_histogram),
    ('trait_map', 'Map a trait with a Gaussian process',
     'Statistics of one trait (area, confidence or p_exists) for every category around a point (n, mean, sd, '
     'cv, quantiles; for area also the log10 mean and sd, as areas are near log-normal), and a Gaussian '
     'process fitted to one category over space (exact GP on the GPU, Matern 5/2 + noise, log10 area or '
     'logit): lengthscale_m (how far sizes stay alike), signal_sd vs noise_sd (spatial pattern vs '
     'object-to-object scatter), and on request a grid of the predicted median, its sd and the share '
     'of prior variance explained (0 = no data nearby).',
     {'lat': LAT, 'lon': LON, 'radius_m': _num(f'{RADIUS} (default 250, at most ~2,500; less at high latitudes)'),
      'category': _str("Category to map (e.g. 'house'); default all named categories"),
      'trait': {'type': 'string', 'enum': list(traits.TRAITS), 'description': 'Trait (default area)'},
      'min_p_exists': _num('Minimum p_exists, 0-1 (default 0.5)'),
      'grid_cells': _num('Include the map as a grid this many cells across (max 48; default: no grid)'),
      'taxonomy': _str("Category set (default 'urban_v1')")},
     ['lat', 'lon'], trait_map),
    ('field_readings', 'Summarise the ground survey',
     'What the ground robot recorded, as counts: readings per local day, how many have a position, a '
     'spectrum, a laser range or a laser target, the median NIR/red index, the share that reads as green '
     'vegetation, the median integration time and the share with clipping, where the exposure settings '
     'came from, and how often fixed words appear in the image notes. registered_by_category counts the '
     'readings the store has linked to a world object. No coordinate, heading or image is returned.',
     {'since': _str('Readings from this time on (ISO 8601 or YYYY-MM-DD)'),
      'until': _str('Readings up to the end of this date')},
     [], field_readings),
    ('entity_looks', 'Which captures covered an object',
     'Every capture whose footprint covers an object, whether the object was large enough to resolve '
     'there, whether the capture found it, and whether the store counted a miss. This is the list behind '
     "an object's found and missed counts.",
     {'entity_id': _num('Entity id')}, ['entity_id'], entity_looks),
    ('belief_history', 'Belief after each change',
     "An object's stored belief after each capture or correction, oldest first: category, confidence, "
     'p_exists, what caused the row, and the capture. Pass after_id from next_after_id for the next page.',
     {'entity_id': _num('Entity id'), 'after_id': _num('Return rows after this snapshot id'),
      'limit': _num('At most this many (default 50, max 200)')},
     ['entity_id'], belief_history),
    ('entity_beliefs', 'Page through every object',
     'Live objects and their beliefs in id order: category, top candidates, p_exists, area, centre, '
     'hits and misses. A page is at most 500, and next_after_id asks for the next one, so a whole '
     'taxonomy can be read. Capture footprints are list_scene_graphs with include_footprints.',
     {'taxonomy': TAXONOMY, 'after_id': _num('Return objects with a higher id'),
      'limit': _num('At most this many (default 200, max 500)')},
     [], entity_beliefs),
]
TOOL_FNS = {name: fn for name, *_, fn in TOOLS}
TOOL_LIST = [{'name': name, 'title': title, 'description': desc,
              'inputSchema': {'type': 'object', 'properties': props, 'required': req},
              'annotations': {'readOnlyHint': True, 'openWorldHint': False}}
             for name, title, desc, props, req, _ in TOOLS]


# ---- JSON-RPC ----------------------------------------------------------------------------------

def _ok(mid, result):
    return {'jsonrpc': '2.0', 'id': mid, 'result': result}


def _err(mid, code, message):
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': message}}


def _tool_error(message):
    return {'content': [{'type': 'text', 'text': message}], 'isError': True}


def _call(name, args):
    if not fusion.enabled():
        return _tool_error('the observations database is not configured')
    try:
        out = TOOL_FNS[name](args if isinstance(args, dict) else {})
    except ToolError as exc:
        return _tool_error(str(exc))
    except Exception:
        log.exception('mcp tool %s failed', name)
        return _tool_error('internal error; see the deepgis-xr log')
    text = json.dumps(out, separators=(',', ':'), default=str)
    if len(text) > MAX_TEXT:
        return _tool_error(f'the answer is {len(text) // 1000} kB; ask for fewer items or a smaller radius')
    return {'content': [{'type': 'text', 'text': text}], 'isError': False}


def _handle(m):
    if isinstance(m, dict) and 'method' not in m and ('result' in m or 'error' in m):
        return None
    if not isinstance(m, dict) or m.get('jsonrpc') != '2.0' or not isinstance(m.get('method'), str):
        return _err(m.get('id') if isinstance(m, dict) else None, -32600, 'invalid request')
    if 'id' not in m:
        return None
    mid, method = m['id'], m['method']
    params = m.get('params') if isinstance(m.get('params'), dict) else {}
    if method == 'initialize':
        asked = params.get('protocolVersion')
        return _ok(mid, {'protocolVersion': asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                         'capabilities': {'tools': {'listChanged': False}},
                         'serverInfo': SERVER_INFO, 'instructions': INSTRUCTIONS})
    if method == 'ping':
        return _ok(mid, {})
    if method == 'tools/list':
        return _ok(mid, {'tools': TOOL_LIST})
    if method == 'tools/call':
        name = params.get('name')
        if name not in TOOL_FNS:
            return _err(mid, -32602, f'unknown tool: {name}')
        log.info('mcp %s %s', name, json.dumps(params.get('arguments'), default=str)[:300])
        return _ok(mid, _call(name, params.get('arguments') or {}))
    return _err(mid, -32601, f'method not found: {method}')


def _token_ok(request):
    auth = request.headers.get('Authorization', '')
    token = auth[7:].strip() if auth[:7].lower() == 'bearer ' else ''
    if not token:
        return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    known = [d.strip() for d in (settings.SCENE_MCP_TOKENS or '').split(',') if d.strip()]
    return any(hmac.compare_digest(d, digest) for d in known)


@csrf_exempt
def mcp_view(request):
    if request.method != 'POST':
        r = HttpResponse(status=405)
        r['Allow'] = 'POST'
        return r
    origin = request.headers.get('Origin')
    if origin and origin not in ALLOWED_ORIGINS:
        return JsonResponse(_err(None, -32000, 'origin not allowed'), status=403)
    if not _token_ok(request):
        return JsonResponse(_err(None, -32001, 'a valid bearer token is required'), status=401)
    try:
        msg = json.loads(request.body)
    except ValueError:
        return JsonResponse(_err(None, -32700, 'parse error'), status=400)
    batch = isinstance(msg, list)
    replies = [r for r in (_handle(m) for m in (msg if batch else [msg])) if r is not None]
    if not replies:
        return HttpResponse(status=202)
    return JsonResponse(replies if batch else replies[0], safe=False)
