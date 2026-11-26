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
from datetime import timezone as dt_timezone

from django.conf import settings
from django.contrib.gis.geos import Polygon
from django.db.models import Count, Max, Min
from django.http import HttpResponse, JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from . import fusion, priors, traits, views
from .models import Capture, Entity, Feedback

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
    "and links, trait_map gives per-category statistics and a Gaussian-process map of sizes. confidence = probability of the category; p_exists = probability the object was "
    "there when last seen (pass at= to find_entities, or read get_entity's now, for the belief "
    "decayed to a date). first_seen and last_seen are imagery dates: each capture records the "
    "imagery it showed and when that was acquired (observed_at), separately from when the view "
    "was taken (captured_at). Below the low-confidence threshold the category is 'unknown' and candidates hold "
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
            'factor_counts': d['factor_counts']}


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
     'first sighting, and per category, in log-odds).',
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
     'belief history, feedback, field readings a ground robot aimed at it, and factor counts.',
     {'entity_id': _num('Entity id'), 'max_sightings': _num('Newest sightings to include (default 20)'),
      'include_polygon': _flag('Include the outline')},
     ['entity_id'], get_entity),
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
