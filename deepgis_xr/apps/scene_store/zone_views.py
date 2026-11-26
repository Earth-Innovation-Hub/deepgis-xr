"""The published fused maps: a page and four files for every zone.

    GET /world-model/                     the zones
    GET /world-model/zones/<slug>         the page: the latest map, its legend, the downloads
    GET /world-model/zones/<slug>.pdf     the map as one PDF page (17 x 11 in, every cell kept)
    GET /world-model/zones/<slug>.png     the same page as an image
    GET /world-model/zones/<slug>.jpg     a small preview of it
    GET /world-model/zones/<slug>.json    the numbers on the page, and whether the files are the latest

Add ?download=1 to a file to have the browser save it under a dated name. Public and read-only.
No request draws anything: the files are those ``render_zone_maps`` last wrote (see ``zonemap``),
and ``latest`` says whether the store has changed since.
"""

import os
import time
from datetime import datetime

from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.utils.cache import get_conditional_response
from django.utils.http import http_date
from django.views.decorators.http import require_safe

from . import fusion, zonemap
from .models import Zone

TYPES = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg'}
LATEST_KEEP_S = 30          # how long one worker trusts its last comparison with the store
_latest = {}


def _unavailable():
    return JsonResponse({'status': 'unavailable', 'message': 'observations database is not configured'}, status=503)


def is_latest(zone, info):
    """Whether the files on disk were drawn from the store as it is now."""
    now = time.monotonic()
    kept = _latest.get(zone.id)
    if kept is None or now - kept[0] > LATEST_KEEP_S or kept[1] != info.get('state'):
        kept = _latest[zone.id] = (now, info.get('state'), zonemap.fingerprint(zone) == info.get('state'))
    return kept[2]


def _size(n):
    return f'{n / 1e6:.1f} MB' if n >= 1e6 else f'{max(1, round(n / 1e3))} kB'


def _drawn(info):
    try:
        at = datetime.fromisoformat(info['rendered_at'])
    except (KeyError, TypeError, ValueError):
        return ''
    return f'{at.day} {at:%b %Y, %H:%M} UTC'


def _base(zone):
    return f'/world-model/zones/{zone.slug}'


def _card(zone, info):
    """What the pages show of one zone."""
    base = _base(zone)
    card = {'slug': zone.slug, 'name': zone.name, 'url': base, 'has_map': info is not None}
    if info is None:
        return card
    ground = info['ground']
    card.update({
        'headline': info['headline'], 'drawn': _drawn(info), 'state': info['state'],
        'preview': f"{base}.jpg?v={info['state']}",
        'n_objects': f"{info['objects']['n']:,}",
        'viewed_km2': f"{ground['viewed_km2_in_zone']:,.1f}",
        'viewed_share': f"{ground['viewed_share_of_zone']:.0%}",
    })
    return card


@require_safe
def zones_view(request):
    if not fusion.enabled():
        return _unavailable()
    cards = [_card(zone, zonemap.current(zone)) for zone in Zone.objects.all()]
    return render(request, 'scene_store/zones.html', {'zones': cards})


@require_safe
def zone_view(request, slug, ext=None):
    if not fusion.enabled():
        return _unavailable()
    zone = Zone.objects.filter(slug=slug).first()
    if zone is None:
        raise Http404('no such zone')
    info = zonemap.current(zone)
    base = _base(zone)
    if ext in TYPES:
        if info is None:
            raise Http404('the first map of this zone is still being drawn')
        return _file(request, zone, info, ext)
    links = {'page': base, **{kind: f'{base}.{kind}' for kind in (*TYPES, 'json')}}
    if ext == 'json':
        if info is None:
            return JsonResponse({'status': 'pending', 'zone': {'slug': zone.slug, 'name': zone.name},
                                 'message': 'the first map of this zone is still being drawn', 'links': links})
        resp = JsonResponse({'status': 'success', 'latest': is_latest(zone, info), **info, 'links': links})
        resp['Cache-Control'] = 'no-cache'
        return resp

    ctx = {'zone': _card(zone, info), 'source': zone.source, 'base': base, 'latest': True,
           'image_url': request.build_absolute_uri(f'{base}.jpg')}
    if info is not None:
        ground = info['ground']
        ctx.update({
            'latest': is_latest(zone, info),
            'downloads': [
                {'url': f'{base}.pdf?download=1', 'label': 'PDF', 'note': f"one page, {_size(info['files']['pdf'])}"},
                {'url': f'{base}.png?download=1', 'label': 'PNG image', 'note': _size(info['files']['png'])},
                {'url': f'{base}.json', 'label': 'Numbers (JSON)', 'note': ''},
            ],
            'rows': [{'colour': row['colour'], 'name': zonemap._name(row['category']), 'n': f"{row['n']:,}",
                      'area': zonemap._num(row['area_ha']) if row['area_ha'] >= 0.05 or not row['area_ha'] else '<0.1',
                      'sure': f"{row['confidence']:.0%}" if row['confidence'] is not None else ''}
                     for row in info['objects']['by_category']],
            'no_object_ha': zonemap._num(ground['no_object_ha']),
            'never_viewed_ha': zonemap._num(ground['never_viewed_ha']),
            'has_photo': bool(info.get('backdrop')),
            'facts': info['facts'], 'reading': info['reading'][:2], 'footer': info['footer'],
        })
    resp = render(request, 'scene_store/zone.html', ctx)
    resp['Cache-Control'] = 'no-cache'
    return resp


def _file(request, zone, info, ext):
    try:
        fh = open(zonemap.file_path(zone, ext), 'rb')
    except OSError:
        raise Http404('no such file')
    st = os.fstat(fh.fileno())
    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
    resp = get_conditional_response(request, etag=etag, last_modified=int(st.st_mtime))
    if resp is not None:
        fh.close()
    else:
        day = str(info.get('rendered_at', ''))[:10].replace('-', '')
        name = f"deepgis-world-model-{zone.slug.replace('/', '-')}-{day}.{ext}"
        resp = FileResponse(fh, content_type=TYPES[ext], as_attachment=bool(request.GET.get('download')),
                            filename=name)
    resp['ETag'] = etag
    resp['Last-Modified'] = http_date(st.st_mtime)
    resp['Cache-Control'] = 'no-cache'
    return resp
