"""JSON API over the spatiotemporal scene-graph store.

    GET  /webclient/sampler/world/entities?bbox=w,s,e,n[&at=ISO][&taxonomy=][&min_p_exists=]
    GET  /webclient/sampler/world/entities/<id>
    POST /webclient/sampler/world/feedback      {entity_id, kind: confirm|relabel|reject, category?, note?}
    GET  /webclient/sampler/world/preferences
    POST /webclient/sampler/world/preferences   {key: value, ...}
    GET  /webclient/sampler/world/stats[?taxonomy=]
    GET  /webclient/sampler/world/histogram?bbox=w,s,e,n | capture=<session_id>|latest
         [&category=][&label=][&source=][&taxonomy=][&min_p_exists=][&bin_m2=auto][&max_m2=]
         Area histogram. With bbox: world entities (median area over their sightings).
         With capture: that capture's detections, one per region as the models saw it.
    GET  /webclient/sampler/world/captures?bbox=w,s,e,n[&taxonomy=][&limit=20]
         Stored scene graphs whose footprint meets the box, newest first.
    GET  /webclient/sampler/world/captures/<session_id>
         One stored scene graph: its detections (with their world entity) and context / contains links.

Reads are public; feedback and preferences need a signed-in user.
"""

import json

from django.contrib.gis.geos import Polygon
from django.db.models import Count, Max, Min
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from . import fusion, priors
from .models import BeliefSnapshot, Capture, Detection, Entity, Factor, Feedback, UserPreference

MAX_BBOX_DEG = 0.05
MAX_CAPTURE_BBOX_DEG = 0.5
MAX_CAPTURE_DETECTIONS = 3000


def _unavailable():
    return JsonResponse({'status': 'unavailable', 'message': 'observations database is not configured'}, status=503)


def _error(message, status=400):
    return JsonResponse({'status': 'error', 'message': message}, status=status)


def _user_id(request):
    user = getattr(request, 'user', None)
    return user.id if user is not None and user.is_authenticated else None


@require_GET
def entities_view(request):
    if not fusion.enabled():
        return _unavailable()
    try:
        bbox = [float(v) for v in request.GET.get('bbox', '').split(',')]
        west, south, east, north = bbox
    except ValueError:
        return _error('bbox=west,south,east,north is required')
    if not (west < east and south < north) or (east - west) * (north - south) > MAX_BBOX_DEG ** 2:
        return _error(f'bbox must be non-empty and at most {MAX_BBOX_DEG} degrees square')
    at = None
    if request.GET.get('at'):
        at = parse_datetime(request.GET['at'])
        if at is None or at.tzinfo is None:
            return _error('at must be an ISO 8601 time with a zone')
    try:
        min_p = float(request.GET.get('min_p_exists', 0))
    except ValueError:
        return _error('min_p_exists must be a number')
    ents, bp = fusion.entities_in_bbox(bbox, at=at, taxonomy=request.GET.get('taxonomy') or None,
                                       min_p_exists=min_p)
    return JsonResponse({'status': 'success', 'at': at.isoformat() if at else None,
                         'n_entities': len(ents), 'entities': ents, 'bp': bp})


@require_GET
def entity_detail_view(request, entity_id):
    if not fusion.enabled():
        return _unavailable()
    e = Entity.objects.filter(id=entity_id).first()
    if e is None:
        return _error('no such entity', 404)
    snaps = BeliefSnapshot.objects.filter(entity=e).order_by('at')
    dets = Detection.objects.filter(association__entity=e).select_related('capture').order_by('observed_at')
    factors = Factor.objects.filter(entity_ids__contains=[e.id]).values('kind').annotate(n=Count('id'))
    return JsonResponse({
        'status': 'success',
        'entity': fusion.entity_to_dict(e),
        'history': [{'at': s.at.isoformat(), 'category': s.category, 'p_exists': round(s.p_exists, 4),
                     'score': round(max(s.posterior), 4), 'cause': s.cause} for s in snaps],
        'detections': [{'at': d.observed_at.isoformat(), 'session_id': d.capture.session_id,
                        'category': d.category, 'score': round(d.score, 4), 'sources': d.sources,
                        'area_m2': round(d.area_m2, 2) if d.area_m2 is not None else None} for d in dets],
        'feedback': [{'kind': f.kind, 'category': f.category, 'at': f.created_at.isoformat(),
                      'superseded': f.superseded_at is not None}
                     for f in Feedback.objects.filter(entity=e).order_by('created_at')],
        'factor_counts': {f['kind']: f['n'] for f in factors},
    })


@csrf_exempt
@require_http_methods(['POST'])
def feedback_view(request):
    if not fusion.enabled():
        return _unavailable()
    user_id = _user_id(request)
    if user_id is None:
        return _error('sign in to give feedback', 401)
    try:
        data = json.loads(request.body or b'{}')
        entity_id = int(data['entity_id'])
    except (ValueError, KeyError, TypeError):
        return _error('entity_id is required')
    try:
        fb, entity, bp = fusion.apply_feedback(entity_id, str(data.get('kind') or ''),
                                               category=str(data.get('category') or ''),
                                               user_id=user_id, note=str(data.get('note') or '')[:2000])
    except Entity.DoesNotExist:
        return _error('no such entity', 404)
    except ValueError as exc:
        return _error(str(exc))
    return JsonResponse({'status': 'success', 'feedback_id': fb.id,
                         'entity': fusion.entity_to_dict(entity), 'bp': bp})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def preferences_view(request):
    if not fusion.enabled():
        return _unavailable()
    user_id = _user_id(request)
    if user_id is None:
        return _error('sign in to use preferences', 401)
    if request.method == 'POST':
        try:
            data = json.loads(request.body or b'{}')
        except ValueError:
            return _error('body must be a JSON object')
        if not isinstance(data, dict) or not all(isinstance(k, str) and 0 < len(k) <= 60 for k in data):
            return _error('body must be a JSON object of short string keys')
        for key, value in data.items():
            if value is None:
                UserPreference.objects.filter(user_id=user_id, key=key).delete()
            else:
                UserPreference.objects.update_or_create(user_id=user_id, key=key, defaults={'value': value})
    prefs = {p.key: p.value for p in UserPreference.objects.filter(user_id=user_id)}
    return JsonResponse({'status': 'success', 'preferences': prefs})


@require_GET
def stats_view(request):
    if not fusion.enabled():
        return _unavailable()
    taxonomy = request.GET.get('taxonomy') or None
    ents = Entity.objects.filter(retired_at__isnull=True)
    if taxonomy:
        ents = ents.filter(taxonomy=taxonomy)
    return JsonResponse({
        'status': 'success',
        'n_captures': Capture.objects.count(),
        'n_entities': ents.count(),
        'entities_by_category': dict(ents.values_list('category').annotate(n=Count('id')).order_by()),
        'factors_by_kind': dict(Factor.objects.filter(superseded_at__isnull=True)
                                .values_list('kind').annotate(n=Count('id')).order_by()),
        'n_feedback': Feedback.objects.filter(superseded_at__isnull=True).count(),
        'source_reliability': fusion.source_reliability(taxonomy) if taxonomy else None,
    })


@require_GET
def histogram_view(request):
    if not fusion.enabled():
        return _unavailable()
    q = request.GET
    try:
        bin_m2 = float(q['bin_m2']) if q.get('bin_m2', 'auto') != 'auto' else None
        max_m2 = float(q['max_m2']) if q.get('max_m2') else None
        min_p = float(q.get('min_p_exists', 0))
    except ValueError:
        return _error('bin_m2, max_m2 and min_p_exists must be numbers')
    if (bin_m2 is not None and not 0 < bin_m2 <= 1e6) or (max_m2 is not None and max_m2 <= 0):
        return _error('bin_m2 and max_m2 must be positive')
    category, label, source = q.get('category'), q.get('label'), q.get('source')
    filters = {k: v for k, v in (('category', category), ('label', label), ('source', source)) if v}

    if q.get('capture'):
        caps = Capture.objects.order_by('-captured_at')
        if source:
            caps = caps.filter(sources__contains=[source])
        cap = caps.first() if q['capture'] == 'latest' else caps.filter(session_id=q['capture']).first()
        if cap is None:
            return _error('no such capture', 404)
        rows = Detection.objects.filter(capture=cap)
        if category:
            rows = rows.filter(category=category)
        if source:
            rows = rows.filter(sources__contains=[source])
        if label:
            rows = rows.filter(claims__native_label=label).distinct()
        hist = fusion.area_histogram(rows.values_list('area_m2', flat=True), bin_m2=bin_m2, max_m2=max_m2)
        return JsonResponse({'status': 'success', 'level': 'detection', 'filters': filters,
                             'capture': {'session_id': cap.session_id, 'captured_at': cap.captured_at.isoformat(),
                                         'taxonomy': cap.taxonomy, 'sources': cap.sources},
                             **hist})

    try:
        west, south, east, north = [float(v) for v in q.get('bbox', '').split(',')]
    except ValueError:
        return _error('bbox=west,south,east,north or capture=<session_id>|latest is required')
    if not (west < east and south < north) or (east - west) * (north - south) > MAX_BBOX_DEG ** 2:
        return _error(f'bbox must be non-empty and at most {MAX_BBOX_DEG} degrees square')
    rows = Entity.objects.filter(geom__intersects=Polygon.from_bbox((west, south, east, north)),
                                 p_exists__gte=min_p, retired_at__isnull=True)
    if q.get('taxonomy'):
        rows = rows.filter(taxonomy=q['taxonomy'])
    if category:
        rows = rows.filter(category=category)
    if source:
        rows = rows.filter(sources__contains=[source])
    if label:
        rows = rows.filter(associations__detection__claims__native_label=label).distinct()
    hist = fusion.area_histogram(rows.values_list('area_m2', flat=True), bin_m2=bin_m2, max_m2=max_m2)
    return JsonResponse({'status': 'success', 'level': 'entity', 'filters': filters,
                         'min_p_exists': min_p, **hist})


def _lonlat_ring(geom):
    """Exterior ring as [[lon, lat], ...], or None for rows stored in projected metres."""
    ring = [list(p) for p in geom.coords[0]]
    return ring if all(abs(x) <= 180 and abs(y) <= 90 for x, y in ring) else None


def _capture_dict(cap, categories):
    return {
        'session_id': cap.session_id,
        'captured_at': cap.captured_at.isoformat(),
        'taxonomy': cap.taxonomy,
        'sources': cap.sources,
        'n_detections': sum(categories.values()),
        'categories': dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        'footprint': _lonlat_ring(cap.footprint),
        'camera': list(cap.camera.coords) if cap.camera else None,
        'camera_alt_m': cap.camera_alt_m,
    }


@require_GET
def captures_view(request):
    if not fusion.enabled():
        return _unavailable()
    q = request.GET
    try:
        west, south, east, north = [float(v) for v in q.get('bbox', '').split(',')]
        limit = min(max(int(q.get('limit', 20)), 1), 100)
    except ValueError:
        return _error('bbox=west,south,east,north is required and limit must be an integer')
    if not (west < east and south < north) or (east - west) * (north - south) > MAX_CAPTURE_BBOX_DEG ** 2:
        return _error(f'bbox must be non-empty and at most {MAX_CAPTURE_BBOX_DEG} degrees square')
    caps = Capture.objects.filter(footprint__intersects=Polygon.from_bbox((west, south, east, north)))
    if q.get('taxonomy'):
        caps = caps.filter(taxonomy=q['taxonomy'])
    span = caps.aggregate(n=Count('id'), first=Min('captured_at'), last=Max('captured_at'))
    rows = list(caps.order_by('-captured_at')[:limit])
    cats = {}
    for cap_id, category, n in (Detection.objects.filter(capture__in=rows)
                                .values_list('capture_id', 'category').annotate(n=Count('id')).order_by()):
        cats.setdefault(cap_id, {})[category] = n
    return JsonResponse({
        'status': 'success',
        'n_captures': span['n'],
        'first': span['first'].isoformat() if span['first'] else None,
        'last': span['last'].isoformat() if span['last'] else None,
        'captures': [_capture_dict(c, cats.get(c.id, {})) for c in rows],
    })


@require_GET
def capture_detail_view(request, session_id):
    if not fusion.enabled():
        return _unavailable()
    cap = Capture.objects.filter(session_id=session_id).first()
    if cap is None:
        return _error('no such capture', 404)
    dets = list(Detection.objects.filter(capture=cap).select_related('association__entity')
                .order_by('-score')[:MAX_CAPTURE_DETECTIONS])
    out, cats, n_gated, n_retired = [], {}, 0, 0
    for d in dets:
        assoc = getattr(d, 'association', None)
        if d.gate:
            n_gated += 1
            continue
        if assoc and assoc.entity.retired_at:
            n_retired += 1
            continue
        category = 'unknown' if d.score < priors.LOW_CONFIDENCE else d.category
        cats[category] = cats.get(category, 0) + 1
        ring = _lonlat_ring(d.geom)
        if ring is None:
            continue
        out.append({'id': d.id, 'node_id': d.node_id, 'category': category, 'best_guess': d.category,
                    'score': round(d.score, 4),
                    'area_m2': round(d.area_m2, 2) if d.area_m2 is not None else None,
                    'entity_id': assoc.entity_id if assoc else None, 'geo_polygon': ring})
    # A pair's link is stored once, by the capture that first saw both; list every link among these entities
    entity_ids = {d['entity_id'] for d in out if d['entity_id']}
    links = [{'kind': kind, 'entities': ids} for kind, ids in
             Factor.objects.filter(entity_ids__overlap=list(entity_ids), kind__in=('context', 'contains'),
                                   superseded_at__isnull=True, valid__contains=cap.captured_at)
             .values_list('kind', 'entity_ids') if set(ids) <= entity_ids]
    return JsonResponse({'status': 'success', 'capture': _capture_dict(cap, cats),
                         'n_skipped': len(dets) - len(out) - n_gated - n_retired, 'n_gated': n_gated,
                         'n_retired': n_retired, 'detections': out, 'links': links})
