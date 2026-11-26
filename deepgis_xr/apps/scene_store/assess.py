"""The fused assessment at a point: what is here, and on how much evidence.

Every stored object is treated as a patch on the ground with an opacity. A point's position is
known only to ``sigma_m`` (the imagery's georegistration by default; pass a robot's own), so
an object covers the point by the share of that uncertainty inside its outline (``weight``,
the same registration used for field readings), and it is there at all with ``p_exists``.
The opacity is the product. Objects are laid over each other smallest first, as an aerial
view shows them (the car on the parking lot, the panel on the roof), and the answer is
composed front to back:

    share_i = weight_i p_exists_i  prod_{j above i} (1 - weight_j p_exists_j)

``fused`` is the category distribution sum_i share_i posterior_i; what is left over
(``no_object``) is the chance that no stored object accounts for the point. There is always
an answer: where nothing is stored it is ``no_object`` = 1, and ``looked_at`` says whether
that is because no capture covers the point or because captures do and found nothing.

Beliefs are as last seen, or decayed to ``at`` (today answers "what is likely still here").
Each object carries its ``support``: how many independent looks its belief rests on.
"""

import math

import numpy as np
from django.contrib.gis.geos import Point, Polygon

from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import taxonomy_by_name

from . import field_evidence, fusion, layers, looks, priors
from .models import Capture, Entity

M_PER_DEG = 111320.0
MIN_SIGMA_M, MAX_SIGMA_M = 0.5, 50.0
MIN_WEIGHT = 0.02
MAX_OBJECTS = 12


def assess_point(lon, lat, *, at=None, taxonomy='urban_v1', sigma_m=None):
    lon, lat = float(lon), float(lat)
    tax = taxonomy_by_name(taxonomy)
    sigma = min(max(float(sigma_m or priors.VIRTUAL_CAMERA_SIGMA_H_M), MIN_SIGMA_M), MAX_SIGMA_M)
    point = Point(lon, lat, srid=4326)

    caps = Capture.objects.filter(taxonomy=tax.name, footprint__contains=point)
    seen = list(caps.values_list('id', 'imagery_source', 'imagery_start', 'imagery_end', 'gsd_m', 'captured_at'))
    gsds = [r[4] for r in seen if r[4]]
    looked = {
        'n_captures': len(seen),
        'n_looks': len({looks.key_of(*r[:4]) for r in seen}),
        'imagery': fusion.imagery_dates(caps),
        'finest_gsd_m': round(min(gsds), 3) if gsds else None,
        'last_viewed': max(r[5] for r in seen).isoformat() if seen else None,
    }

    pad = 3.0 * sigma / M_PER_DEG
    pad_x = pad / max(math.cos(math.radians(lat)), 0.05)
    box = Polygon.from_bbox((lon - pad_x, lat - pad, lon + pad_x, lat + pad))
    box.srid = 4326
    near = Entity.objects.filter(taxonomy=tax.name, retired_at__isnull=True, geom__intersects=box)
    if at is not None:
        near = near.filter(first_seen__lte=at)
    scored = []
    for e in near:
        w = field_evidence.registration_weight(fusion._from_geos(e.geom), lon, lat, sigma)
        if w >= MIN_WEIGHT:
            scored.append((w, e))
    scored = sorted(scored, key=lambda we: -we[0])[:MAX_OBJECTS]
    ents = [e for _, e in scored]
    beliefs = {}
    if at is not None and ents:
        beliefs = fusion.run_local_bp([e.id for e in ents], at=at, write=False).get('beliefs', {})
    support = fusion.support_many(ents, include_field=False)

    def area_of(e):
        return e.area_m2 if e.area_m2 is not None else float('inf')

    remaining, mix, objects = 1.0, np.zeros(tax.n), []
    for w, e in sorted(scored, key=lambda we: (area_of(we[1]), -we[0])):
        b = beliefs.get(e.id, {})
        post = np.asarray(b.get('posterior', e.posterior), dtype=float)
        p_exists = float(b.get('p_exists', e.p_exists))
        share = remaining * w * p_exists
        remaining -= share
        mix += share * post
        s = support[e.id]
        objects.append({
            'id': e.id, 'category': b.get('category', e.category), 'confidence': round(float(post.max()), 4),
            'p_exists': round(p_exists, 4), 'weight': round(w, 3), 'share': round(share, 4),
            'area_m2': round(e.area_m2, 2) if e.area_m2 is not None else None,
            'last_seen': e.last_seen.isoformat(),
            'support': {'n_looks': s['n_looks'],
                        'n_found': sum(r['n_found'] for r in s['looks']),
                        'n_missed': sum(r['n_missed'] for r in s['looks']),
                        'n_corrections': s['other'].get('feedback', 0)},
        })
    objects.sort(key=lambda o: -o['share'])

    ranked = sorted(enumerate(mix), key=lambda kv: -kv[1])[:3]
    fused = {
        'category': tax.name_of(ranked[0][0]) if ranked[0][1] > remaining else None,
        'p': round(float(max(ranked[0][1], remaining)), 4),
        'candidates': [{'category': tax.name_of(k), 'p': round(float(v), 4)} for k, v in ranked if v >= 0.005],
        'no_object': round(float(remaining), 4),
    }
    out = {
        'point': [round(float(lon), 7), round(float(lat), 7)], 'taxonomy': tax.name, 'sigma_m': round(sigma, 2),
        'at': at.isoformat() if at else None,
        'beliefs': 'as last seen' if at is None else 'decayed to at',
        'looked_at': looked, 'fused': fused, 'objects': objects,
    }
    if objects:
        top = next(e for e in ents if e.id == objects[0]['id'])
        # what remote sensors recorded over the object that most accounts for the point; not in the belief
        out['remote_sensing'] = {'entity_id': top.id, 'layers': [
            {'source': row.get('source'), 'label': row.get('label'), 'unit': row.get('unit'),
             'latest': row.get('latest'), 'purity': row.get('purity')} for row in layers.entity_layers(top)]}
    if not seen:
        out['note'] = 'No capture covers this point: nothing is known here.'
    elif not objects:
        n, k = looked['n_captures'], looked['n_looks']
        out['note'] = (f"{n} capture{'s' if n != 1 else ''} of {k} image{'s' if k != 1 else ''} "
                       f"cover{'s' if n == 1 else ''} this point and no object was found on it.")
    elif looked['n_looks'] == 1:
        out['note'] = ('Everything known here comes from one image: more captures of it cannot make '
                       'this more certain, a different image, a correction or a field reading can.')
    return out
