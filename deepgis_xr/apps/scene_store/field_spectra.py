"""A field spectrum in the bands the overhead sensors use, and as reflectance.

The readings table stores counts above the instrument's baseline on a 1 nm grid, for one scan
of ``integration_ms``. Dividing by that time gives a rate that readings taken at different
exposures share. The rate is still light times instrument response, not a property of the
surface, so two things are offered:

- ``band_ratios``: each band's mean rate over the red band's. The instrument's response is in
  every ratio, so they compare readings of this instrument with each other, by surface and by
  light, and nothing else.
- ``reflectance``: the rate over the rate of a reference panel read in the same light, times
  the panel's reflectance. That is a property of the surface, and its NDVI is the same
  quantity as Sentinel-2's (and close to NAIP's, whose photograph numbers are uncalibrated).

``BANDS`` are an aerial photograph's blue, green, red and near infrared and the Sentinel-2
red-edge bands the spectrometer reaches. Its range ends at about 873 nm, so the near-infrared
band is the short half of Sentinel-2's band 8 and band 11 is out of reach.
"""

import math
from datetime import timedelta

import numpy as np

from . import priors

BANDS = {
    'blue': (458.0, 523.0), 'green': (543.0, 578.0), 'red': (650.0, 680.0),
    're705': (698.0, 713.0), 're740': (733.0, 748.0), 're783': (773.0, 793.0),
    'nir': (785.0, 873.0),
}
MIN_BINS = 8            # of a band that must be on the grid
MIN_REFERENCE_RATE = 1.0  # counts per ms: a darker panel reading is noise


def rates(spectrum):
    """(wavelengths nm, counts per ms) on the stored grid, clipped bins NaN; None if unusable."""
    if not isinstance(spectrum, dict):
        return None
    counts, wl0, dwl, t = (spectrum.get(k) for k in ('counts', 'wl0', 'dwl', 'integration_ms'))
    if not isinstance(counts, list) or len(counts) < 16:
        return None
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (wl0, dwl, t)) or dwl <= 0 or t <= 0:
        return None
    rate = np.asarray(counts, dtype=float) / float(t)
    wl = float(wl0) + float(dwl) * np.arange(rate.size)
    for span in spectrum.get('clipped') or []:
        if isinstance(span, (list, tuple)) and len(span) == 2:
            rate[(wl + dwl > span[0]) & (wl < span[1])] = np.nan
    return wl, rate


def band_means(spectrum):
    """{band: mean rate, or None when the band is off the grid or holds a clipped bin}."""
    got = rates(spectrum)
    if got is None:
        return {}
    wl, rate = got
    out = {}
    for name, (lo, hi) in BANDS.items():
        sel = rate[(wl >= lo) & (wl < hi)]
        out[name] = float(sel.mean()) if sel.size >= MIN_BINS and np.isfinite(sel).all() else None
    return out


def band_ratios(spectrum):
    """{band: mean rate / red band's}, for the bands that have one; {} without a usable red band."""
    b = band_means(spectrum)
    red = b.get('red')
    if red is None or red <= 0:
        return {}
    return {name: round(v / red, 4) for name, v in b.items() if v is not None and name != 'red'}


def is_reference(spectrum):
    """The panel's reflectance if this reading was marked as a look at a reference panel, else None."""
    ref = spectrum.get('reference') if isinstance(spectrum, dict) else None
    rho = ref.get('reflectance') if isinstance(ref, dict) else None
    return float(rho) if isinstance(rho, (int, float)) and 0 < rho <= 1.5 else None


def reflectance(spectrum, reference):
    """{'bands': {band: reflectance}, 'ndvi': ...} of a reading against a panel reading, or None."""
    rho = is_reference(reference)
    target, panel = band_means(spectrum), band_means(reference)
    if rho is None or not target or not panel:
        return None
    bands = {}
    for name in BANDS:
        t, p = target.get(name), panel.get(name)
        if t is not None and p is not None and p >= MIN_REFERENCE_RATE:
            bands[name] = round(rho * t / p, 4)
    if not bands:
        return None
    out = {'bands': bands}
    red, nir = bands.get('red'), bands.get('nir')
    if red is not None and nir is not None and nir + red > 1e-3:
        out['ndvi'] = round((nir - red) / (nir + red), 4)
    return out


def reference_for(reading):
    """The panel reading nearest in time to ``reading`` from the same vehicle, or None."""
    from deepgis_xr.apps.web.models import FieldReading

    span = timedelta(minutes=priors.FIELD_REFERENCE_MAX_MIN)
    near = (FieldReading.objects
            .filter(vehicle_id=reading.vehicle_id, spectrum__has_key='reference',
                    captured__gte=reading.captured - span, captured__lte=reading.captured + span)
            .exclude(pk=reading.pk).only('captured', 'spectrum'))
    best = min(near, key=lambda r: abs((r.captured - reading.captured).total_seconds()), default=None)
    return best if best is not None and is_reference(best.spectrum) is not None else None


def reflectance_of(reading):
    """Reflectance of a stored reading against its nearest panel reading, with how far apart
    in time the two were; None without a panel reading within ``FIELD_REFERENCE_MAX_MIN``."""
    if is_reference(reading.spectrum) is not None:
        return None
    ref = reference_for(reading)
    out = reflectance(reading.spectrum, ref.spectrum) if ref is not None else None
    if out is not None:
        out['reference_dt_s'] = round(abs((ref.captured - reading.captured).total_seconds()), 1)
    return out
