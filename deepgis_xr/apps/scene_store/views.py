"""JSON API over the spatiotemporal scene-graph store.

    GET  /webclient/sampler/world/entities?bbox=w,s,e,n[&at=ISO][&taxonomy=][&min_p_exists=]
         Beliefs as last seen (at each entity's newest evidence), or decayed to ``at``.
    GET  /webclient/sampler/world/entities/<id>
         One entity: candidates, sightings with their imagery dates, belief history, feedback,
         ``now`` (the belief decayed to this moment) and ``layers`` (what satellite passes, aerial
         photographs and lidar recorded over it). Field readings only for signed-in users.
    GET  /webclient/sampler/world/imagery_checks?bbox=w,s,e,n
         ``flags``: captures whose basemap imagery has since been replaced by a later acquisition.
         For a signed-in page also ``due``: captures to look up again (see ``imagery_watch``).
    POST /webclient/sampler/world/imagery_checks  {checks: [{session_id, imagery: the page's record}]}
         The dates the provider serves now for those captures. Signed-in users.
    POST /webclient/sampler/world/feedback      {entity_id, kind: confirm|relabel|reject, category?, note?,
                                                 imagery?: the page's current imagery record, seen?: 'in_person'}
         Dated by the imagery in view when given, the present for 'in_person', else the entity's last sighting.
    GET  /webclient/sampler/world/review?bbox=w,s,e,n[&taxonomy=][&limit=20]
         Entities whose label a person could settle with the most information, best first.
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
    GET  /webclient/sampler/world/summary?bbox=w,s,e,n[&taxonomy=]
         Counts per category, confidence bins, and the best guesses behind the unknown entities.
    GET  /webclient/sampler/world/changes?bbox=w,s,e,n&since=YYYY-MM[-DD][&until=][&taxonomy=][&basis=imagery|view]
         Entities first seen in the window, and those missed in it that are believed gone. The window
         is read by imagery date (default) or by when the views were taken; ``imagery`` lists what
         the captures showed and ``note`` says when that cannot show change on the ground.
    POST /webclient/sampler/world/retire        {entity_ids: [...], reason}   superusers
    POST /webclient/sampler/world/restore       {entity_ids: [...]}           superusers

Reads are public; feedback and preferences need a signed-in user.
"""

import re
from datetime import datetime, timezone as dt_timezone

import json

from django.contrib.gis.geos import Polygon
from django.db.models import Count, Max, Min
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from django.utils import timezone

from . import fusion, imagery_watch, layers, priors, traits
from .models import (
    BeliefSnapshot, Capture, Detection, DetectionModel, Entity, Factor, Feedback, FieldLink, Pose, UserPreference,
)

MAX_BBOX_DEG = 0.05
MAX_CAPTURE_BBOX_DEG = 0.5
MAX_CAPTURE_DETECTIONS = 3000
MAX_RETIRE_IDS = 50
MAX_IMAGERY_CHECKS = 20
DAY = re.compile(r'(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?')


def _unavailable():
    return JsonResponse({'status': 'unavailable', 'message': 'observations database is not configured'}, status=503)


def _error(message, status=400):
    return JsonResponse({'status': 'error', 'message': message}, status=status)


def _user_id(request):
    user = getattr(request, 'user', None)
    return user.id if user is not None and user.is_authenticated else None


def _bbox(request, max_deg=MAX_BBOX_DEG):
    """(bbox, None) or (None, error response)."""
    try:
        bbox = [float(v) for v in request.GET.get('bbox', '').split(',')]
        west, south, east, north = bbox
    except ValueError:
        return None, _error('bbox=west,south,east,north is required')
    if not (west < east and south < north) or (east - west) * (north - south) > max_deg ** 2:
        return None, _error(f'bbox must be non-empty and at most {max_deg} degrees square')
    return bbox, None


def _day(value):
    """Start of a YYYY, YYYY-MM or YYYY-MM-DD day in UTC, or None."""
    m = DAY.fullmatch((value or '').strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1), tzinfo=dt_timezone.utc)
    except ValueError:
        return None


@require_GET
def entities_view(request):
    if not fusion.enabled():
        return _unavailable()
    bbox, err = _bbox(request)
    if err:
        return err
    at = None
    if request.GET.get('at'):
        at = parse_datetime(request.GET['at'])
        if at is None or at.tzinfo is None:
            return _error('at must be an ISO 8601 time with a zone')
    try:
        min_p = float(request.GET.get('min_p_exists', 0))
        min_score = float(request.GET.get('min_score', 0))
    except ValueError:
        return _error('min_p_exists and min_score must be numbers')
    ents, bp = fusion.entities_in_bbox(bbox, at=at, taxonomy=request.GET.get('taxonomy') or None,
                                       min_p_exists=min_p, min_score=min_score)
    return JsonResponse({'status': 'success', 'at': at.isoformat() if at else None,
                         'n_entities': len(ents), 'entities': ents, 'bp': bp})


@require_GET
def summary_view(request):
    if not fusion.enabled():
        return _unavailable()
    bbox, err = _bbox(request)
    if err:
        return err
    return JsonResponse({'status': 'success',
                         **fusion.world_summary(bbox, taxonomy=request.GET.get('taxonomy') or None)})


@require_GET
def changes_view(request):
    if not fusion.enabled():
        return _unavailable()
    bbox, err = _bbox(request)
    if err:
        return err
    since = _day(request.GET.get('since'))
    until = _day(request.GET.get('until')) if request.GET.get('until') else None
    if since is None or (request.GET.get('until') and until is None):
        return _error('since (and until, if given) must be YYYY, YYYY-MM or YYYY-MM-DD')
    if until is not None and until <= since:
        return _error('until must be after since')
    basis = request.GET.get('basis') or 'imagery'
    if basis not in ('imagery', 'view'):
        return _error('basis must be imagery or view')
    return JsonResponse({'status': 'success', **fusion.world_changes(
        bbox, since, until, taxonomy=request.GET.get('taxonomy') or None, basis=basis)})


@require_GET
def review_view(request):
    if not fusion.enabled():
        return _unavailable()
    bbox, err = _bbox(request)
    if err:
        return err
    try:
        limit = min(max(int(request.GET.get('limit', 20)), 1), 100)
    except ValueError:
        return _error('limit must be an integer')
    return JsonResponse({'status': 'success', **fusion.review_queue(
        bbox, taxonomy=request.GET.get('taxonomy') or None, limit=limit)})


def _superuser_ids(request):
    """(entity ids, None) for a superuser's JSON body, or (None, error response)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return None, _error('sign in first', 401)
    if not user.is_superuser:
        return None, _error('only superusers can retire or restore world entities', 403)
    try:
        data = json.loads(request.body or b'{}')
        ids = [int(i) for i in data.get('entity_ids') or []]
    except (ValueError, TypeError, AttributeError):
        return None, _error('entity_ids must be a list of integers')
    if not ids or len(ids) > MAX_RETIRE_IDS:
        return None, _error(f'give 1 to {MAX_RETIRE_IDS} entity_ids')
    return (ids, data), None


@require_http_methods(['POST'])
def retire_view(request):
    if not fusion.enabled():
        return _unavailable()
    got, err = _superuser_ids(request)
    if err:
        return err
    ids, data = got
    reason = str(data.get('reason') or '').strip()[:100] or 'retired from the AI pilot'
    out = fusion.retire_entities(ids, f'{reason} (user {request.user.id})')
    return JsonResponse({'status': 'success', **out})


@require_http_methods(['POST'])
def restore_view(request):
    if not fusion.enabled():
        return _unavailable()
    got, err = _superuser_ids(request)
    if err:
        return err
    return JsonResponse({'status': 'success', **fusion.restore_entities(got[0])})


@require_GET
def entity_detail_view(request, entity_id):
    if not fusion.enabled():
        return _unavailable()
    e = Entity.objects.filter(id=entity_id).first()
    if e is None:
        return _error('no such entity', 404)
    return JsonResponse({'status': 'success', **entity_detail(e, include_field=_user_id(request) is not None)})


def _imagery_dict(cap):
    if not (cap.imagery_source or cap.imagery_start):
        return None
    return {'source': cap.imagery_source or None,
            'start': cap.imagery_start.isoformat() if cap.imagery_start else None,
            'end': cap.imagery_end.isoformat() if cap.imagery_end else None}


def entity_detail(e, include_field=False):
    """One entity with its top candidates, belief history, sightings, feedback and factor counts.

    ``entity`` holds the belief as last seen; ``now`` is the same belief decayed to this moment.
    Field readings show where a robot has been, so they are listed only when ``include_field``
    (the readings themselves need a sign-in); their effect on the belief is always there.
    """
    snaps = BeliefSnapshot.objects.filter(entity=e).order_by('at')
    dets = Detection.objects.filter(association__entity=e).select_related('capture').order_by('observed_at')
    tax = fusion.taxonomy_by_name(e.taxonomy)
    ranked = sorted(enumerate(e.posterior), key=lambda kv: -kv[1])[:3]
    factors = Factor.objects.filter(entity_ids__contains=[e.id], superseded_at__isnull=True) \
        .values('kind').annotate(n=Count('id'))
    counts = {f['kind']: f['n'] for f in factors}
    out = {
        'entity': fusion.entity_to_dict(e),
        'candidates': [{'category': tax.name_of(k), 'p': round(float(v), 4)} for k, v in ranked],
        'history': [{'at': s.at.isoformat(), 'category': s.category, 'p_exists': round(s.p_exists, 4),
                     'score': round(max(s.posterior), 4), 'cause': s.cause} for s in snaps],
        'detections': [{'at': d.observed_at.isoformat(), 'viewed_at': d.capture.captured_at.isoformat(),
                        'imagery': _imagery_dict(d.capture), 'session_id': d.capture.session_id,
                        'category': d.category, 'score': round(d.score, 4), 'sources': d.sources,
                        'gate': d.gate or None,
                        'area_m2': round(d.area_m2, 2) if d.area_m2 is not None else None,
                        'gsd_m': round(d.capture.gsd_m, 3) if d.capture.gsd_m else None} for d in dets],
        'feedback': [{'kind': f.kind, 'category': f.category, 'at': f.created_at.isoformat(),
                      'superseded': f.superseded_at is not None}
                     for f in Feedback.objects.filter(entity=e).order_by('created_at')],
        # what remote sensors recorded over it; a record, none of it is in the belief
        'layers': layers.entity_layers(e),
    }
    if not e.retired_at:
        now = fusion.run_local_bp([e.id], at=timezone.now(), write=False).get('beliefs', {}).get(e.id)
        if now:
            out['now'] = {'category': now['category'], 'score': round(now['score'], 4),
                          'p_exists': round(now['p_exists'], 4)}
    if include_field:
        links = list(FieldLink.objects.filter(entity=e).order_by('observed_at'))
        usable = [k for k in links if k.usable]
        out['field'] = {
            'n_readings': len(links), 'n_usable': len(usable),
            'n_green': sum(1 for k in usable if k.signal.get('green')),
            'first': links[0].observed_at.isoformat() if links else None,
            'last': links[-1].observed_at.isoformat() if links else None,
            'vehicles': sorted({k.vehicle_id for k in links}),
        }
    else:
        counts.pop('field', None)
    out['factor_counts'] = counts
    return out


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
    # What the person was looking at dates the correction: the imagery in view when the page
    # sends it, the present for a judgement made on the ground, else the entity's last sighting.
    now = timezone.now()
    seen = now if data.get('seen') == 'in_person' else fusion.imagery_record(data.get('imagery'), now)['observed_at']
    try:
        fb, entity, bp = fusion.apply_feedback(entity_id, str(data.get('kind') or ''),
                                               category=str(data.get('category') or ''),
                                               user_id=user_id, note=str(data.get('note') or '')[:2000],
                                               observed_at=seen)
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
        'detection_models': detection_models(),
        'imagery': fusion.imagery_dates(Capture.objects.filter(taxonomy=taxonomy) if taxonomy
                                        else Capture.objects.all()),
        'layers': layers.layer_stats(),
        'imagery_checks': imagery_watch.summary(taxonomy),
    })


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def imagery_checks_view(request):
    """Which captures' basemap imagery to look up again, and what the look-ups found."""
    if not fusion.enabled():
        return _unavailable()
    user_id = _user_id(request)
    if request.method == 'GET':
        bbox, err = _bbox(request, MAX_CAPTURE_BBOX_DEG)
        if err:
            return err
        return JsonResponse({'status': 'success', 'flags': imagery_watch.flags(bbox),
                             'due': imagery_watch.due(bbox) if user_id is not None else []})
    if user_id is None:
        return _error('sign in to report imagery dates', 401)
    try:
        checks = json.loads(request.body or b'{}').get('checks')
    except (ValueError, AttributeError):
        checks = None
    if not isinstance(checks, list) or not 0 < len(checks) <= MAX_IMAGERY_CHECKS:
        return _error(f'checks must be a list of 1 to {MAX_IMAGERY_CHECKS} look-ups')
    ids = [str(c.get('session_id') or '')[:120] for c in checks if isinstance(c, dict)]
    caps = {c.session_id: c for c in Capture.objects.filter(session_id__in=ids)}
    recorded = 0
    for c in checks:
        cap = caps.get(str(c.get('session_id') or '')[:120]) if isinstance(c, dict) else None
        if cap is not None and imagery_watch.record(cap, c.get('imagery'), user_id) is not None:
            recorded += 1
    wanted = {c.session_id for c in caps.values()}
    return JsonResponse({'status': 'success', 'recorded': recorded,
                         'flags': [f for f in imagery_watch.flags() if f['session_id'] in wanted]})


def detection_models():
    """The fitted chance of finding an entity again that is in use, per taxonomy."""
    return {m.taxonomy: {'version': m.version, 'fitted_at': m.fitted_at.isoformat(), 'n_looks': m.n_looks,
                         'coefficients': m.coefficients, 'log_loss': (m.metrics or {}).get('log_loss')}
            for m in DetectionModel.objects.filter(active=True)}


@require_GET
def trait_map_view(request):
    """Per-category statistics of one trait in bbox and its Gaussian-process map for one category."""
    if not fusion.enabled():
        return _unavailable()
    bbox, err = _bbox(request)
    if err:
        return err
    q = request.GET
    trait = q.get('trait', 'area')
    if trait not in traits.TRAITS:
        return _error(f'trait must be one of {", ".join(traits.TRAITS)}')
    category = q.get('category', '').strip()
    if category and not re.fullmatch(r'[a-z_]{1,40}', category):
        return _error('category must be a taxonomy category, e.g. house')
    try:
        min_p = min(max(float(q.get('min_p_exists', 0.5)), 0.0), 1.0)
    except ValueError:
        return _error('min_p_exists must be a number')
    return JsonResponse({'status': 'success', **traits.trait_map(
        bbox, trait=trait, category=category, taxonomy=q.get('taxonomy') or 'urban_v1', min_p_exists=min_p)})


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


def _capture_dict(cap, categories, pose=None):
    gsd = cap.gsd_m
    return {
        'session_id': cap.session_id,
        'captured_at': cap.captured_at.isoformat(),
        # when the ground looked like this: the imagery's date when known, else the view time
        'observed_at': cap.world_time.isoformat(),
        'imagery': _imagery_dict(cap),
        'taxonomy': cap.taxonomy,
        'sources': cap.sources,
        'n_detections': sum(categories.values()),
        'categories': dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        'footprint': _lonlat_ring(cap.footprint),
        'camera': list(cap.camera.coords) if cap.camera else None,
        'camera_alt_m': cap.camera_alt_m,
        'gsd_m': round(gsd, 3) if gsd else None,
        # the smallest object a miss can be counted for at this resolution
        'min_object_m2': round(priors.MISS_MIN_PIXELS * gsd ** 2, 1) if gsd else None,
        'pose': {'source': pose.source, 'sigma_h_m': pose.sigma_h_m, 'sigma_v_m': pose.sigma_v_m,
                 'pitch_deg': pose.pitch_deg} if pose else None,
    }


def _poses(caps):
    return {p.capture_id: p for p in Pose.objects.filter(capture__in=caps, superseded_at__isnull=True)
            .order_by('capture_id', 'recorded_at')}  # the newest estimate wins


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
    return JsonResponse({'status': 'success', **captures_in((west, south, east, north),
                                                            taxonomy=q.get('taxonomy') or None, limit=limit)})


def captures_in(bbox, *, taxonomy=None, limit=20):
    """Stored scene graphs whose footprint meets ``bbox`` (anywhere when it is None), newest first."""
    caps = Capture.objects.all()
    if bbox is not None:
        caps = caps.filter(footprint__intersects=Polygon.from_bbox(bbox))
    if taxonomy:
        caps = caps.filter(taxonomy=taxonomy)
    span = caps.aggregate(n=Count('id'), first=Min('captured_at'), last=Max('captured_at'))
    rows = list(caps.order_by('-captured_at')[:limit])
    cats = {}
    for cap_id, category, n in (Detection.objects.filter(capture__in=rows)
                                .values_list('capture_id', 'category').annotate(n=Count('id')).order_by()):
        cats.setdefault(cap_id, {})[category] = n
    poses = _poses(rows)
    return {
        'n_captures': span['n'],
        'first': span['first'].isoformat() if span['first'] else None,
        'last': span['last'].isoformat() if span['last'] else None,
        'captures': [_capture_dict(c, cats.get(c.id, {}), poses.get(c.id)) for c in rows],
    }


@require_GET
def capture_detail_view(request, session_id):
    if not fusion.enabled():
        return _unavailable()
    cap = Capture.objects.filter(session_id=session_id).first()
    if cap is None:
        return _error('no such capture', 404)
    return JsonResponse({'status': 'success', **capture_detail(cap)})


def capture_detail(cap):
    """One stored scene graph: its detections with their world entity, and the context / contains links."""
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
                                   superseded_at__isnull=True, valid__contains=cap.world_time)
             .values_list('kind', 'entity_ids') if set(ids) <= entity_ids]
    return {'capture': _capture_dict(cap, cats, _poses([cap]).get(cap.id)),
            'n_skipped': len(dets) - len(out) - n_gated - n_retired, 'n_gated': n_gated,
            'n_retired': n_retired, 'detections': out, 'links': links}
