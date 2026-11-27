"""Field readings as evidence on the entity under the laser target.

A ground robot stores a photograph, a spectrum and a laser range, and the readings table
places the end of the laser ray on the map. This module registers that target to a world
entity and lets the spectrum vote on the entity's category.

Registration. The target is uncertain by the robot's position, by its aim (range times the
heading error) and by the patch the spectrometer averages. ``weight`` is the share of that
uncertainty, an isotropic Gaussian, that falls inside the entity's outline. A reading is
linked to the smallest entity holding at least half of it, else to the one holding most,
if that is at least ``priors.FIELD_MIN_WEIGHT``.

When the readings table aimed the target with the flight controller's EKF, it stored that
reading's own 1-sigma ground error (GPS accuracy and attitude) in ``aim``; that replaces the
fixed position and heading errors.

Evidence. The NIR/red index is a ratio of raw counts, not reflectance, so it answers one
question only: does the patch read as green vegetation? Daylight readings with the index
are usable (the instrument leaves the index out when its bands clipped). The usable readings of one vehicle on one entity in one day are views of the
same patch through the same instrument, not independent looks, so together they count as
one: the day's factor is the weight-averaged log-likelihood table, scaled down when the
weights sum to less than one reading. It is a ``field`` factor on the category; existence
is left alone, and so is the source-reliability refit, which counts people's corrections.

Height. An EKF-aimed reading also knows how high above the ground under the rover the laser
hit. A hit well above the ground means the entity has something standing there (a wall, a
car, a canopy). That is a second, separate day factor (``metadata.signal = 'height'``), at
any sun, unless the hit is higher than the entity's lidar height allows, in which case the
beam was on something else and the height is left out.

View. The map is drawn from above and the rover looks along the ground, so a reading speaks
for an entity only when both can be seeing the same thing (``view_of``):

- ``top``: the beam ended on the ground, where the lidar shows nothing over it. Both see
  the same surface.
- ``side``: the beam ended above the ground, where the lidar shows something at least that
  tall. The rover saw the flank of what the map shows the top of.
- ``under``: on the ground, beneath a canopy or cover that the map shows instead.
- ``face``: above the ground where the lidar has nothing that tall, or on what the keyframe
  shows as a fence or wall. Such a thing has no category from above. The reading is linked
  to the entity beside it and votes on nothing.
- ``conflict``: the keyframe and the hit height disagree on ground or standing.
- ``unknown``: no hit height and no label (a heading-aimed reading); it votes as before.

For ``top`` and ``side`` the lidar also narrows where the target can be: only the part of
its position uncertainty where such a hit is possible is shared out among the entities.

Label. What the keyframe shows under the spectrometer's patch (``web/field_surface``) is a
second look at the entity, from another image and another side. In a ``top`` or ``side``
view it is a third day factor (``metadata.signal = 'label'``) on the categories that surface
stands for. The laser hits the middle of the patch, so the view goes by the surface there,
and the label by the surface that fills the patch.

Gates. The index is not used with the sun in or beside the frame, nor when the keyframe
shows the patch to be several surfaces or to have sky in it: sky is far brighter than
anything in shade, and the spectrum is then of no one thing. A reading aimed with a
course the rover kept with no recent move (``aim.held``), and a reading of a reference
panel, are not registered at all. With a panel reading within half an hour the spectrum is reflectance
(``field_spectra``) and green is its NDVI.

Nothing here copies a position out of the readings table.
"""

import logging
import math
from datetime import datetime, time as dt_time, timedelta, timezone as dt_timezone

import numpy as np
import shapely
from django.contrib.gis.geos import Polygon
from django.db import transaction
from django.utils import timezone

from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import taxonomy_by_name

from . import field_spectra, fusion, heights, priors
from .models import Entity, Factor, FieldLink, LayerSample

log = logging.getLogger(__name__)

DB = fusion.DB
TAXONOMY = 'urban_v1'
RINGS, SPOKES = 6, 12
M_PER_DEG = 111320.0
RULE = f'nir_red>{priors.FIELD_GREEN_INDEX}'
HEIGHT_RULE = f'hit>{priors.FIELD_ELEVATED_M}m'
LABEL_RULE = f'keyframe patch>={priors.FIELD_LABEL_MIN_SHARE}'
SIGNALS = ('green', 'height', 'label')
VOTING_VIEWS = ('top', 'side', 'unknown')


def target_sigma_m(range_m, patch_m=None):
    """1-sigma position error of the laser target on the ground, metres."""
    aim = (range_m or 0.0) * math.radians(priors.FIELD_HEADING_SIGMA_DEG)
    return math.sqrt(priors.FIELD_POSITION_SIGMA_M ** 2 + aim ** 2 + ((patch_m or 0.0) / 4.0) ** 2)


def reading_sigma_m(reading, patch_m=None):
    """The reading's own target error when its aim carries one, else the fixed assumption."""
    aim = reading.aim if isinstance(getattr(reading, 'aim', None), dict) else {}
    sigma = aim.get('sigma_m')
    if isinstance(sigma, (int, float)) and math.isfinite(sigma) and sigma > 0:
        return math.sqrt(sigma ** 2 + ((patch_m or 0.0) / 4.0) ** 2)
    return target_sigma_m(reading.range_m, patch_m)


def lidar_p90_m(entity):
    """The latest lidar 90th-percentile height above ground over the entity, or None."""
    s = (LayerSample.objects.filter(entity=entity, scene__layer='height').select_related('scene')
         .order_by('-scene__observed_at').first())
    if s is None:
        return None
    names = (s.scene.metadata or {}).get('bands') or []
    if 'p90' in names and len(s.bands) == len(names):
        return float(s.bands[names.index('p90')])
    return float(s.value)


def height_signal(reading, entity):
    """{'hit_height_m', 'p_elevated', 'lidar_p90_m', 'height_ok'} for an EKF-aimed hit, else {}."""
    aim = reading.aim if isinstance(getattr(reading, 'aim', None), dict) else {}
    h, s = aim.get('hit_height_m'), aim.get('sigma_up_m')
    if not (isinstance(h, (int, float)) and isinstance(s, (int, float)) and s > 0):
        return {}
    p = 0.5 * (1.0 + math.erf((h - priors.FIELD_ELEVATED_M) / (s * math.sqrt(2.0))))
    out = {'hit_height_m': round(float(h), 2), 'p_elevated': round(p, 4)}
    p90 = lidar_p90_m(entity)
    ok = True
    if p90 is not None:
        out['lidar_p90_m'] = round(p90, 2)
        ok = h - p90 <= max(priors.FIELD_LIDAR_SLACK_M, 2.0 * s)
    out['height_ok'] = ok
    return out


def _aim(reading):
    aim = getattr(reading, 'aim', None)
    return aim if isinstance(aim, dict) else {}


def hit_kind(reading):
    """'elevated' or 'ground' when the hit's height above the ground settles it, else None."""
    aim = _aim(reading)
    h, s = aim.get('hit_height_m'), aim.get('sigma_up_m')
    if not (isinstance(h, (int, float)) and isinstance(s, (int, float)) and s > 0):
        return None
    p = 0.5 * (1.0 + math.erf((h - priors.FIELD_ELEVATED_M) / (s * math.sqrt(2.0))))
    if p >= priors.FIELD_HIT_SURE:
        return 'elevated'
    return 'ground' if p <= 1.0 - priors.FIELD_HIT_SURE else None


def surface_label(reading):
    """What the keyframe shows under the patch, when one known surface fills enough of it."""
    surface = getattr(reading, 'surface', None)
    if not isinstance(surface, dict):
        return None
    label, share = surface.get('label'), surface.get('share')
    if label in priors.FIELD_SURFACES and isinstance(share, (int, float)) and share >= priors.FIELD_LABEL_MIN_SHARE:
        return label
    return None


def spot_label(reading):
    """What the keyframe shows under the laser's spot, the middle of the patch."""
    surface = getattr(reading, 'surface', None)
    centre = surface.get('centre') if isinstance(surface, dict) else None
    return centre if centre in priors.FIELD_SURFACES else None


def patch_state(reading):
    """(labelled, clean, sky share): whether the keyframe was segmented, and whether the
    spectrum is of one surface: one that fills the patch, with no more than a sliver of sky."""
    surface = getattr(reading, 'surface', None)
    if not (isinstance(surface, dict) and surface.get('label')):
        return False, True, 0.0
    shares = surface.get('shares') if isinstance(surface.get('shares'), dict) else {}
    sky = shares.get('sky')
    sky = float(sky) if isinstance(sky, (int, float)) and math.isfinite(sky) else 0.0
    label = surface_label(reading)
    return True, label is not None and (label == 'sky' or sky < priors.FIELD_MAX_SKY_SHARE), sky


def view_of(reading, sigma_m):
    """(view, keep): which view the rover had of what the map shows at the target, and the
    part of the target's position uncertainty where the lidar allows such a hit.

    ``view`` is {'view', 'view_by'} plus, when the lidar was consulted, 'lidar_m' (its height
    at the target) and 'lidar_share' (the share of the uncertainty where the hit fits).
    ``keep`` is a mask over ``_sample`` for ``entity_under``, or None for all of it.
    The view is about what the laser hit, so the keyframe's word on it is the surface under
    the laser's spot, else the one that fills the patch.
    """
    kind = hit_kind(reading)
    label = spot_label(reading) or surface_label(reading)
    seen = priors.FIELD_SURFACES[label][0] if label else None
    view = {}
    fits, share = None, None
    if kind is not None:
        lon, lat = reading.target.x, reading.target.y
        xs, ys = _sample(lon, lat, sigma_m)
        hag = heights.sample(xs, ys)
        if np.isfinite(hag).mean() >= 0.5:
            if kind == 'elevated':
                aim = _aim(reading)
                tol = max(priors.FIELD_HEIGHT_TOL_M, 2.0 * aim['sigma_up_m'])
                fits = hag >= max(aim['hit_height_m'] - tol, priors.FIELD_ELEVATED_M)
            else:
                fits = hag <= priors.FIELD_GROUND_TOP_M
            share = float(fits.mean())
            view['lidar_share'] = round(share, 3)
            at = heights.sample([lon], [lat])[0]
            if math.isfinite(at):
                view['lidar_m'] = round(float(at), 2)
    allowed = share is not None and share >= priors.FIELD_MIN_COMPATIBLE
    keep = None
    if seen in ('face', 'none'):
        relation, by = seen, 'image'
    elif seen == 'top':
        if kind == 'elevated':
            relation, by = 'conflict', 'image'
        elif kind == 'ground' and share is not None and not allowed:
            relation, by = 'under', 'lidar'
        else:
            relation, by, keep = 'top', 'image', (fits if kind == 'ground' and allowed else None)
    elif seen == 'side':
        if kind == 'ground':
            relation, by = 'conflict', 'image'
        else:
            relation, by, keep = 'side', 'image', (fits if kind == 'elevated' and allowed else None)
    elif kind is None:
        relation, by = 'unknown', None
    elif share is None:
        relation, by = ('side' if kind == 'elevated' else 'top'), 'aim'
    elif kind == 'elevated':
        relation, by, keep = ('side', 'lidar', fits) if allowed else ('face', 'lidar', None)
    else:
        relation, by, keep = ('top', 'lidar', fits) if allowed else ('under', 'lidar', None)
    view['view'] = relation
    if by:
        view['view_by'] = by
    return view, keep


def _sample(lon, lat, sigma_m):
    """Equal-probability points of an isotropic Gaussian around (lon, lat)."""
    kx = M_PER_DEG * math.cos(math.radians(lat))
    xs, ys = [], []
    for i in range(RINGS):
        r = sigma_m * math.sqrt(-2.0 * math.log(1.0 - (i + 0.5) / RINGS))
        for j in range(SPOKES):
            a = 2 * math.pi * (j + 0.5 * (i % 2)) / SPOKES
            xs.append(lon + r * math.sin(a) / kx)
            ys.append(lat + r * math.cos(a) / M_PER_DEG)
    return np.asarray(xs), np.asarray(ys)


def registration_weight(shape, lon, lat, sigma_m):
    """Share of the target's position uncertainty inside ``shape`` (a lon/lat shapely polygon)."""
    xs, ys = _sample(lon, lat, sigma_m)
    return float(shapely.contains_xy(shape, xs, ys).mean())


def entity_under(lon, lat, sigma_m, keep=None):
    """(entity, weight) for a target, or (None, best weight seen).

    ``keep`` limits the target's uncertainty to the sample points where it can be (``view_of``);
    the weight is then the entity's share of that part."""
    pad = 3.0 * sigma_m / M_PER_DEG
    pad_x = pad / max(math.cos(math.radians(lat)), 0.05)
    box = Polygon.from_bbox((lon - pad_x, lat - pad, lon + pad_x, lat + pad))
    box.srid = 4326
    xs, ys = _sample(lon, lat, sigma_m)
    if keep is not None and keep.any():
        xs, ys = xs[keep], ys[keep]
    scored = []
    for e in Entity.objects.filter(taxonomy=TAXONOMY, retired_at__isnull=True, geom__intersects=box):
        w = float(shapely.contains_xy(fusion._from_geos(e.geom), xs, ys).mean())
        if w > 0:
            scored.append((w, e))
    if not scored:
        return None, 0.0
    inside = [(w, e) for w, e in scored if w >= 0.5]
    if inside:
        w, e = min(inside, key=lambda we: (we[1].area_m2 if we[1].area_m2 is not None else float('inf'), -we[0]))
        return e, w
    w, e = max(scored, key=lambda we: we[0])
    return (e, w) if w >= priors.FIELD_MIN_WEIGHT else (None, w)


def sun_separation_deg(aim, sun_azimuth_deg, sun_elevation_deg):
    """Angle between the camera axis and the sun, or None when the reading carries no axis."""
    az, el = aim.get('azimuth_deg'), aim.get('elevation_deg')
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (az, el)):
        return None
    a, b = math.radians(el), math.radians(sun_elevation_deg)
    c = math.sin(a) * math.sin(b) + math.cos(a) * math.cos(b) * math.cos(math.radians(az - sun_azimuth_deg))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def signal_of(reading):
    """(signal, usable): what the spectrum says, and whether the light lets it count as evidence."""
    from deepgis_xr.apps.web.field_readings import sun_position

    sun_az, sun = sun_position(reading.target.y, reading.target.x, reading.captured)
    signal = {'sun_deg': round(sun, 1)}
    sep = sun_separation_deg(_aim(reading), sun_az, sun)
    if sep is not None:
        signal['sun_sep_deg'] = round(sep, 1)
    spec = reading.spectrum if isinstance(reading.spectrum, dict) else {}
    indices = spec.get('indices') if isinstance(spec.get('indices'), dict) else {}
    index = indices.get('nir_red')
    if isinstance(index, (int, float)) and math.isfinite(index):
        signal['nir_red'] = round(float(index), 4)
        signal['green'] = bool(index > priors.FIELD_GREEN_INDEX)
    ratios = field_spectra.band_ratios(spec)
    if ratios:
        signal['bands'] = ratios
    reflect = field_spectra.reflectance_of(reading)
    if reflect is not None:
        signal['reflectance'] = reflect['bands']
        signal['reference_dt_s'] = reflect['reference_dt_s']
        if 'ndvi' in reflect:
            signal['ndvi'] = reflect['ndvi']
            signal['green'] = bool(reflect['ndvi'] > priors.FIELD_GREEN_NDVI)
            signal['green_by'] = 'ndvi'
    in_frame = sep is not None and sun > 0 and sep < priors.FIELD_MIN_SUN_SEP_DEG
    usable = 'green' in signal and sun >= priors.FIELD_MIN_SUN_DEG and not in_frame
    return signal, usable


def _day_span(when):
    start = datetime.combine(when.astimezone(dt_timezone.utc).date(), dt_time.min, tzinfo=dt_timezone.utc)
    return start, start + timedelta(days=1)


def refresh_day(entity_id, vehicle_id, when):
    """Rebuild the ``field`` factors (green, height, label) for an entity, a vehicle and the UTC day of ``when``.

    Returns True when the stored evidence changed."""
    changed = [_refresh_signal(entity_id, vehicle_id, when, signal) for signal in SIGNALS]
    return any(changed)


def _counts(link, signal):
    """Whether a link carries a vote for this signal."""
    if signal == 'green':
        return link.usable
    if signal == 'height':
        return 'p_elevated' in link.signal and bool(link.signal.get('height_ok'))
    return bool(link.signal.get('label_ok'))


def _refresh_signal(entity_id, vehicle_id, when, signal):
    start, end = _day_span(when)
    day = start.date().isoformat()
    links = [k for k in FieldLink.objects.filter(entity_id=entity_id, vehicle_id=vehicle_id,
                                                 observed_at__gte=start, observed_at__lt=end)
             if _counts(k, signal)]
    live = [f for f in Factor.objects.filter(kind='field', entity_ids=[entity_id], superseded_at__isnull=True,
                                             metadata__vehicle=vehicle_id, metadata__day=day)
            if (f.metadata or {}).get('signal', 'green') == signal]
    table, meta = None, None
    if links:
        entity = Entity.objects.get(id=entity_id)
        tax = taxonomy_by_name(entity.taxonomy)
        total = sum(k.weight for k in links)
        if signal == 'green':
            table = sum(k.weight * priors.field_green_table(tax, bool(k.signal.get('green'))) for k in links)
            meta = {'vehicle': vehicle_id, 'day': day, 'n_readings': len(links), 'weight': round(total, 3),
                    'n_green': sum(1 for k in links if k.signal.get('green')), 'rule': RULE}
        elif signal == 'height':
            table = sum(k.weight * priors.field_height_table(tax, k.signal['p_elevated']) for k in links)
            meta = {'vehicle': vehicle_id, 'day': day, 'signal': 'height', 'n_readings': len(links),
                    'weight': round(total, 3), 'n_elevated': sum(1 for k in links if k.signal['p_elevated'] > 0.5),
                    'rule': HEIGHT_RULE}
        else:
            table = sum(k.weight * priors.field_label_table(tax, k.signal['surface']) for k in links)
            labels = {}
            for k in links:
                labels[k.signal['surface']] = labels.get(k.signal['surface'], 0) + 1
            meta = {'vehicle': vehicle_id, 'day': day, 'signal': 'label', 'n_readings': len(links),
                    'weight': round(total, 3), 'labels': dict(sorted(labels.items())), 'rule': LABEL_RULE}
        table = table / max(total, 1.0)
    if len(live) == 1 and table is not None and live[0].metadata == meta and \
            np.allclose(np.asarray(live[0].log_table, dtype=float), table, atol=1e-9):
        return False
    if not live and table is None:
        return False
    Factor.objects.filter(id__in=[f.id for f in live]).update(superseded_at=timezone.now())
    if table is not None:
        fusion._new_factor('field', [entity_id], table, max(k.observed_at for k in links),
                           variables=[fusion.cvar(entity_id)], metadata=meta).save()
    return True


def register_reading(reading, *, infer=True):
    """Link one reading to the entity under its target and refresh that day's evidence.

    ``reading`` is a FieldReading or its id. Returns the entity ids whose evidence changed.
    Safe to call again when the reading's pose or spectrum is updated.
    """
    from deepgis_xr.apps.web.models import FieldReading

    if not isinstance(reading, FieldReading):
        reading = FieldReading.objects.using(DB).filter(pk=reading).first()
    if reading is None:
        return set()
    changed = set()
    with transaction.atomic(using=DB):
        old = FieldLink.objects.select_for_update().filter(reading_id=reading.pk).first()
        entity, weight, view = None, 0.0, {}
        # a course kept with no recent move does not say where the rover points, and a look
        # at the reference panel is not a look at the map
        placed = reading.target is not None and reading.range_m is not None and \
            0 <= reading.range_m <= priors.FIELD_MAX_RANGE_M and not _aim(reading).get('held') and \
            field_spectra.is_reference(reading.spectrum) is None
        if placed:
            spec = reading.spectrum if isinstance(reading.spectrum, dict) else {}
            foot = spec.get('footprint') if isinstance(spec.get('footprint'), dict) else {}
            patch = foot.get('diameter_m') if isinstance(foot.get('diameter_m'), (int, float)) else None
            sigma = reading_sigma_m(reading, patch)
            view, keep = view_of(reading, sigma)
            entity, weight = entity_under(reading.target.x, reading.target.y, sigma, keep)
        if entity is None:
            if old is not None:
                old.delete()
                if refresh_day(old.entity_id, old.vehicle_id, old.observed_at):
                    changed.add(old.entity_id)
        else:
            signal, usable = signal_of(reading)
            signal.update(height_signal(reading, entity))
            signal.update(view)
            votes = view['view'] in VOTING_VIEWS
            usable = usable and votes
            if 'height_ok' in signal:
                signal['height_ok'] = signal['height_ok'] and votes
            labelled, clean, sky = patch_state(reading)
            if labelled:
                # a patch of several surfaces, or with sky in it, gives a spectrum of none of them
                signal['patch'] = 'one surface' if clean else 'sky in it' if surface_label(reading) else 'mixed'
                if sky:
                    signal['sky_share'] = round(sky, 3)
                if spot_label(reading):
                    signal['spot'] = spot_label(reading)
                usable = usable and clean
            label = surface_label(reading)
            if label:
                kind, stands_for = priors.FIELD_SURFACES[label]
                signal['surface'] = label
                signal['label_ok'] = bool(stands_for) and view['view'] == kind
            fields = {'entity': entity, 'vehicle_id': reading.vehicle_id, 'observed_at': reading.captured,
                      'weight': round(weight, 4), 'range_m': reading.range_m, 'usable': usable, 'signal': signal}
            moved = old is not None and (old.entity_id != entity.id or old.vehicle_id != reading.vehicle_id
                                         or _day_span(old.observed_at) != _day_span(reading.captured))
            if old is None:
                FieldLink.objects.create(reading_id=reading.pk, **fields)
            else:
                was = (old.entity_id, old.vehicle_id, old.observed_at)
                for name, value in fields.items():
                    setattr(old, name, value)
                old.save()
                if moved and refresh_day(*was):
                    changed.add(was[0])
            if refresh_day(entity.id, reading.vehicle_id, reading.captured):
                changed.add(entity.id)
        if infer and changed:
            fusion._bp_by_taxonomy(changed, cause='field')
    return changed


def register_all(*, vehicle_id=None, infer=True):
    """Register every stored reading that has a target. Returns counts; one inference pass at the end."""
    from deepgis_xr.apps.web.models import FieldReading

    rows = FieldReading.objects.using(DB).filter(target__isnull=False).order_by('captured')
    if vehicle_id:
        rows = rows.filter(vehicle_id=vehicle_id)
    changed, n, seen = set(), 0, set()
    for reading in rows.iterator(chunk_size=200):
        changed |= register_reading(reading, infer=False)
        seen.add(reading.pk)
        n += 1
    links = FieldLink.objects.all()
    if vehicle_id:
        links = links.filter(vehicle_id=vehicle_id)
    # a reading that lost its target, or was deleted, keeps no link
    for old in list(links.exclude(reading_id__in=seen)):
        old.delete()
        if refresh_day(old.entity_id, old.vehicle_id, old.observed_at):
            changed.add(old.entity_id)
    n_bp = fusion._bp_by_taxonomy(changed, cause='field') if infer and changed else 0
    views = {}
    for signal in links.values_list('signal', flat=True):
        name = (signal or {}).get('view', 'not set')
        views[name] = views.get(name, 0) + 1
    return {
        'readings with a target': n,
        'registered to an entity': links.count(),
        'by view': dict(sorted(views.items(), key=lambda kv: -kv[1])),
        'usable as evidence (daylight, index present)': links.filter(usable=True).count(),
        'entities with a registered reading': links.values('entity_id').distinct().count(),
        'field factors live': Factor.objects.filter(kind='field', superseded_at__isnull=True).count(),
        'of which height': Factor.objects.filter(kind='field', superseded_at__isnull=True,
                                                 metadata__signal='height').count(),
        'of which label': Factor.objects.filter(kind='field', superseded_at__isnull=True,
                                                metadata__signal='label').count(),
        'entities whose evidence changed': len(changed),
        'entities re-inferred': n_bp,
    }, changed
