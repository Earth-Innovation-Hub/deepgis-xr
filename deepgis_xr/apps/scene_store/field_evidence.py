"""Field readings as evidence on the entity under the laser target.

A ground robot stores a photograph, a spectrum and a laser range, and the readings table
places the end of the laser ray on the map. This module registers that target to a world
entity and lets the spectrum vote on the entity's category.

Registration. The target is uncertain by the robot's position, by its aim (range times the
heading error) and by the patch the spectrometer averages. ``weight`` is the share of that
uncertainty, an isotropic Gaussian, that falls inside the entity's outline. A reading is
linked to the smallest entity holding at least half of it, else to the one holding most,
if that is at least ``priors.FIELD_MIN_WEIGHT``.

Evidence. The NIR/red index is a ratio of raw counts, not reflectance, so it answers one
question only: does the patch read as green vegetation? Daylight readings with the index
are usable (the instrument leaves the index out when its bands clipped). The usable readings of one vehicle on one entity in one day are views of the
same patch through the same instrument, not independent looks, so together they count as
one: the day's factor is the weight-averaged log-likelihood table, scaled down when the
weights sum to less than one reading. It is a ``field`` factor on the category; existence
is left alone, and so is the source-reliability refit, which counts people's corrections.

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

from . import fusion, priors
from .models import Entity, Factor, FieldLink

log = logging.getLogger(__name__)

DB = fusion.DB
TAXONOMY = 'urban_v1'
RINGS, SPOKES = 6, 12
M_PER_DEG = 111320.0
RULE = f'nir_red>{priors.FIELD_GREEN_INDEX}'


def target_sigma_m(range_m, patch_m=None):
    """1-sigma position error of the laser target on the ground, metres."""
    aim = (range_m or 0.0) * math.radians(priors.FIELD_HEADING_SIGMA_DEG)
    return math.sqrt(priors.FIELD_POSITION_SIGMA_M ** 2 + aim ** 2 + ((patch_m or 0.0) / 4.0) ** 2)


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


def entity_under(lon, lat, sigma_m):
    """(entity, weight) for a target, or (None, best weight seen)."""
    pad = 3.0 * sigma_m / M_PER_DEG
    pad_x = pad / max(math.cos(math.radians(lat)), 0.05)
    box = Polygon.from_bbox((lon - pad_x, lat - pad, lon + pad_x, lat + pad))
    box.srid = 4326
    scored = []
    for e in Entity.objects.filter(taxonomy=TAXONOMY, retired_at__isnull=True, geom__intersects=box):
        w = registration_weight(fusion._from_geos(e.geom), lon, lat, sigma_m)
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


def signal_of(reading):
    """(signal, usable): what the spectrum says, and whether it may count as evidence."""
    from deepgis_xr.apps.web.field_readings import sun_position

    _, sun = sun_position(reading.target.y, reading.target.x, reading.captured)
    signal = {'sun_deg': round(sun, 1)}
    spec = reading.spectrum if isinstance(reading.spectrum, dict) else {}
    indices = spec.get('indices') if isinstance(spec.get('indices'), dict) else {}
    index = indices.get('nir_red')
    if isinstance(index, (int, float)) and math.isfinite(index):
        signal['nir_red'] = round(float(index), 4)
        signal['green'] = bool(index > priors.FIELD_GREEN_INDEX)
    usable = 'green' in signal and sun >= priors.FIELD_MIN_SUN_DEG
    return signal, usable


def _day_span(when):
    start = datetime.combine(when.astimezone(dt_timezone.utc).date(), dt_time.min, tzinfo=dt_timezone.utc)
    return start, start + timedelta(days=1)


def refresh_day(entity_id, vehicle_id, when):
    """Rebuild the one ``field`` factor for an entity, a vehicle and the UTC day of ``when``.

    Returns True when the stored evidence changed."""
    start, end = _day_span(when)
    day = start.date().isoformat()
    links = list(FieldLink.objects.filter(entity_id=entity_id, vehicle_id=vehicle_id, usable=True,
                                          observed_at__gte=start, observed_at__lt=end))
    live = list(Factor.objects.filter(kind='field', entity_ids=[entity_id], superseded_at__isnull=True,
                                      metadata__vehicle=vehicle_id, metadata__day=day))
    table, meta = None, None
    if links:
        entity = Entity.objects.get(id=entity_id)
        tax = taxonomy_by_name(entity.taxonomy)
        total = sum(k.weight for k in links)
        table = sum(k.weight * priors.field_green_table(tax, bool(k.signal.get('green'))) for k in links)
        table = table / max(total, 1.0)
        meta = {'vehicle': vehicle_id, 'day': day, 'n_readings': len(links), 'weight': round(total, 3),
                'n_green': sum(1 for k in links if k.signal.get('green')), 'rule': RULE}
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
        entity, weight = None, 0.0
        placed = reading.target is not None and reading.range_m is not None and \
            0 <= reading.range_m <= priors.FIELD_MAX_RANGE_M
        if placed:
            spec = reading.spectrum if isinstance(reading.spectrum, dict) else {}
            foot = spec.get('footprint') if isinstance(spec.get('footprint'), dict) else {}
            patch = foot.get('diameter_m') if isinstance(foot.get('diameter_m'), (int, float)) else None
            entity, weight = entity_under(reading.target.x, reading.target.y,
                                          target_sigma_m(reading.range_m, patch))
        if entity is None:
            if old is not None:
                old.delete()
                if refresh_day(old.entity_id, old.vehicle_id, old.observed_at):
                    changed.add(old.entity_id)
        else:
            signal, usable = signal_of(reading)
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
    changed, n = set(), 0
    for reading in rows.iterator(chunk_size=200):
        changed |= register_reading(reading, infer=False)
        n += 1
    links = FieldLink.objects.all()
    if vehicle_id:
        links = links.filter(vehicle_id=vehicle_id)
    n_bp = fusion._bp_by_taxonomy(changed, cause='field') if infer and changed else 0
    return {
        'readings with a target': n,
        'registered to an entity': links.count(),
        'usable as evidence (daylight, index present)': links.filter(usable=True).count(),
        'entities with a registered reading': links.values('entity_id').distinct().count(),
        'field factors live': Factor.objects.filter(kind='field', superseded_at__isnull=True).count(),
        'entities whose evidence changed': len(changed),
        'entities re-inferred': n_bp,
    }, changed
