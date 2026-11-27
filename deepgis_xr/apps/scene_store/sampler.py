"""Choosing the next view: a bandit over 100 m cells and zoom bands.

An arm is a cell of a 100 m grid over an area and a zoom band (a ground pixel size). Pulling it
means capturing the top-down view centred on the cell at that zoom. Its reward is the
capture's ``reward['bits_new']`` (``fusion.capture_reward``): the category information that
earlier captures could not be expected to deliver. Bits the detector gives on a second try at
pixels already read are recorded and not paid.

What a capture returns is modelled from the captures already stored:

    E[bits_new] = place(cell) * content(cell, band) * sum over k of yield[band, k] * share in class k

The classes are those of ``fusion.ground_read``: ground no capture has covered, ground covered
only at a coarser zoom, and ground already read at this zoom. ``yield`` is the bits a capture
of the band returns from a footprint wholly in one class; shares are used, not hectares,
because detections per capture are nearly flat across zoom. The yields have a normal
posterior from a linear regression on the stored captures, with every band shrunk toward the
all-band fit. ``place`` is how much captures near the cell returned against what the yields
predicted, smoothed over ``PLACE_LENGTH_M`` and shrunk toward 1 where there are few.
``content`` is what ``contents`` expects a capture of that footprint and zoom to detect,
against the band's mean, where a fitted model covers the area (1 elsewhere); the yields are
then fitted with each stored capture's own content factor, as the model would have predicted
it without that capture. On a replay of the first Tempe run it raised the correlation of
predicted with realised bits from 0.39 to 0.70 on the sampler's own captures; it predicts too
low by about a fifth.

Thompson sampling draws the yields and the place field from their posteriors and takes the arm
with the largest draw. ``uniform`` takes a cell and a band at random and is the baseline;
``greedy`` takes the largest posterior mean. Every proposal is stored with what it expected
(``SamplerPull``), and the capture's reward is attached when it comes back.
"""

import math

import numpy as np
import shapely
from django.contrib.gis.geos import Point
from django.db import connections
from scipy.ndimage import uniform_filter

from . import contents, fusion, priors
from .models import Capture, SamplerPull

DB = fusion.DB
CELL_M = 100.0
FINE_M = 20.0                         # coverage is rasterised at this size
BAND_EDGES = (0.15, 0.25, 0.40, 0.70)  # ground pixel size (m) between the five zoom bands
BAND_GSD = (0.12, 0.20, 0.32, 0.50, 1.00)  # the pixel size asked for in each band
CLASSES = ('new', 'finer', 'same')
POLICIES = ('thompson', 'uniform', 'greedy')
MAX_BBOX_DEG = 0.12
MIN_PRIOR_SD = 20.0                   # bits: how far a band's yield may sit from the all-band fit, at least
MIN_NOISE_SD = 30.0                   # bits: capture-to-capture scatter, at least
PLACE_LENGTH_M = 500.0
PLACE_PRIOR_N = 2.0                   # captures' worth of weight on place = 1
PLACE_SD = 0.5                        # prior sd of log place
PLACE_OFFSET = 10.0                   # bits added to both sides of the ratio, so empty captures stay finite
DEFAULT_IMAGE = (1909, 974)


def band_of(gsd):
    return int(np.searchsorted(BAND_EDGES, gsd, side='right'))


class Grid:
    """A 100 m grid over a bbox, with a 20 m grid inside it for coverage."""

    def __init__(self, bbox):
        self.west, self.south, self.east, self.north = bbox
        self.lat0 = (self.south + self.north) / 2
        self.mx = 111320.0 * math.cos(math.radians(self.lat0))
        self.my = 110920.0
        self.nx = max(1, int(round((self.east - self.west) * self.mx / CELL_M)))
        self.ny = max(1, int(round((self.north - self.south) * self.my / CELL_M)))
        self.k = int(round(CELL_M / FINE_M))
        self.dx = (self.east - self.west) / (self.nx * self.k)
        self.dy = (self.north - self.south) / (self.ny * self.k)

    def centre(self, ix, iy):
        return (self.west + (ix + 0.5) * self.k * self.dx, self.south + (iy + 0.5) * self.k * self.dy)

    def centres_m(self):
        """(x, y) of every cell centre in metres from the south-west corner, each shaped (ny, nx)."""
        x = (np.arange(self.nx) + 0.5) * CELL_M
        y = (np.arange(self.ny) + 0.5) * CELL_M
        return np.meshgrid(x, y)

    def metres(self, lon, lat):
        return (lon - self.west) * self.mx, (lat - self.south) * self.my

    def raster(self, shapes):
        """Fine cells whose centre is inside any of ``shapes``, as a (ny*k, nx*k) boolean array."""
        out = np.zeros((self.ny * self.k, self.nx * self.k), dtype=bool)
        for shp in shapes:
            w, s, e, n = shp.bounds
            i0, i1 = max(0, int((w - self.west) / self.dx)), min(out.shape[1], int((e - self.west) / self.dx) + 1)
            j0, j1 = max(0, int((s - self.south) / self.dy)), min(out.shape[0], int((n - self.south) / self.dy) + 1)
            if i0 >= i1 or j0 >= j1:
                continue
            xs = self.west + (np.arange(i0, i1) + 0.5) * self.dx
            ys = self.south + (np.arange(j0, j1) + 0.5) * self.dy
            gx, gy = np.meshgrid(xs, ys)
            out[j0:j1, i0:i1] |= shapely.contains_xy(shp, gx, gy)
        return out

    def window_share(self, mask, width_m, height_m):
        """For each 100 m cell, the share of a width x height window centred on it that ``mask``
        covers. Ground outside the grid counts as not covered."""
        size = (max(1, int(round(height_m / FINE_M))), max(1, int(round(width_m / FINE_M))))
        mean = uniform_filter(mask.astype(np.float32), size=size, mode='constant', cval=0.0)
        return mean[self.k // 2::self.k, self.k // 2::self.k][:self.ny, :self.nx]


def default_bbox(taxonomy):
    """The box around the taxonomy's capture footprints, or None when there are none."""
    with connections[DB].cursor() as cur:
        cur.execute("SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
                    "(SELECT ST_Extent(footprint) AS e FROM sg_capture WHERE taxonomy = %s) q", [taxonomy])
        row = cur.fetchone()
    return [float(v) for v in row] if row and row[0] is not None else None


def records(taxonomy, bbox=None):
    """Stored captures that carry a reward: one dict per capture, oldest first."""
    caps = Capture.objects.filter(taxonomy=taxonomy, gsd_m__isnull=False).order_by('id')
    out = []
    for c in caps.only('id', 'gsd_m', 'footprint', 'camera', 'sources', 'summary'):
        reward = (c.summary.get('ingest') or {}).get('reward') or {}
        ground = reward.get('ground_ha') or {}
        total = sum(ground.get(k) or 0.0 for k in CLASSES)
        row = {'id': c.id, 'gsd': c.gsd_m, 'band': band_of(c.gsd_m), 'shape': fusion._from_geos(c.footprint),
               'sources': set(c.sources), 'bits_new': reward.get('bits_new'),
               'share': [(ground.get(k) or 0.0) / total for k in CLASSES] if total > 0 else None}
        centre = row['shape'].centroid
        row['lon'], row['lat'] = centre.x, centre.y
        out.append(row)
    return out


def fit_yields(rows):
    """Posterior over yield[band, class] from captures with a reward: (mean, covariance, info).

    A Bayesian linear regression with known noise. The prior mean of every band is the all-band
    least-squares fit; its sd is that value or ``MIN_PRIOR_SD``, whichever is larger."""
    n_b, n_k = len(BAND_GSD), len(CLASSES)
    data = [r for r in rows if r['bits_new'] is not None and r['share']]
    shares = np.array([r['share'] for r in data], dtype=float).reshape(-1, n_k)
    y = np.array([r['bits_new'] for r in data], dtype=float)
    if len(data) >= n_k + 2:
        pooled = np.clip(np.linalg.lstsq(shares, y, rcond=None)[0], 0.0, None)
    else:
        pooled = np.array([100.0, 50.0, 10.0])
    x = np.zeros((len(data), n_b * n_k))
    for i, r in enumerate(data):
        x[i, r['band'] * n_k:(r['band'] + 1) * n_k] = r['share']
    prior_mean = np.tile(pooled, n_b)
    prior_sd = np.maximum(prior_mean, MIN_PRIOR_SD)
    noise = MIN_NOISE_SD
    if len(data) > n_b * n_k:
        ridge = np.linalg.solve(x.T @ x + np.diag((MIN_NOISE_SD / prior_sd) ** 2),
                                x.T @ y + prior_mean * (MIN_NOISE_SD / prior_sd) ** 2)
        noise = max(MIN_NOISE_SD, float(np.sqrt(np.mean((y - x @ ridge) ** 2))))
    precision = x.T @ x / noise ** 2 + np.diag(1.0 / prior_sd ** 2)
    cov = np.linalg.inv(precision)
    mean = cov @ (x.T @ y / noise ** 2 + prior_mean / prior_sd ** 2)
    info = {'n_captures': len(data), 'noise_sd': round(noise, 1),
            'pooled': {k: round(float(v), 1) for k, v in zip(CLASSES, pooled)},
            'by_band': [{'gsd_m': g, 'n': int(sum(r['band'] == b for r in data)),
                         **{k: round(float(mean[b * n_k + j]), 1) for j, k in enumerate(CLASSES)}}
                        for b, g in enumerate(BAND_GSD)]}
    return mean, cov, info


def place_field(grid, rows, mean):
    """(mean, sd) of log place for every cell, each shaped (ny, nx)."""
    n_k = len(CLASSES)
    gx, gy = grid.centres_m()
    num, den = np.zeros_like(gx), np.zeros_like(gx)
    for r in rows:
        if r['bits_new'] is None or not r['share']:
            continue
        expected = float(np.dot(mean[r['band'] * n_k:(r['band'] + 1) * n_k], r['share']))
        ratio = math.log((max(r['bits_new'], 0.0) + PLACE_OFFSET) / (max(expected, 0.0) + PLACE_OFFSET))
        cx, cy = grid.metres(r['lon'], r['lat'])
        w = np.exp(-((gx - cx) ** 2 + (gy - cy) ** 2) / (2 * PLACE_LENGTH_M ** 2))
        num += w * ratio
        den += w
    return num / (den + PLACE_PRIOR_N), PLACE_SD * np.sqrt(PLACE_PRIOR_N / (den + PLACE_PRIOR_N))


def shares(grid, rows, image_size, sources):
    """Share of each arm's footprint in each ground class: an array (bands, classes, ny, nx)."""
    cover = [r for r in rows if r['sources'] & set(sources)]
    seen = grid.raster([r['shape'] for r in cover])
    out = np.zeros((len(BAND_GSD), len(CLASSES), grid.ny, grid.nx), dtype=np.float32)
    for b, gsd in enumerate(BAND_GSD):
        w, h = image_size[0] * gsd, image_size[1] * gsd
        repeat = grid.raster([r['shape'] for r in cover if not gsd < priors.RELOOK_FINER_RATIO * r['gsd']])
        any_share = grid.window_share(seen, w, h)
        same_share = grid.window_share(repeat, w, h)
        out[b, 0] = 1.0 - any_share
        out[b, 1] = np.clip(any_share - same_share, 0.0, 1.0)
        out[b, 2] = same_share
    return out


def propose(taxonomy, *, policy='thompson', bbox=None, image_size=None, sources=('sam3',), run='', user_id=None,
            seed=None, record=True):
    """Pick the next view and (unless ``record`` is False) store the proposal.

    Returns a dict with the view to capture (``lon``, ``lat``, ``gsd_m``, ``footprint_m``) and
    what the model expects of it (``predicted``)."""
    if policy not in POLICIES:
        raise ValueError(f'policy must be one of {", ".join(POLICIES)}')
    bbox = [float(v) for v in bbox] if bbox else default_bbox(taxonomy)
    if not bbox:
        raise ValueError('bbox is required: there are no captures to take an area from')
    west, south, east, north = bbox
    if not (west < east and south < north) or (east - west) * (north - south) > MAX_BBOX_DEG ** 2:
        raise ValueError(f'bbox must be non-empty and at most {MAX_BBOX_DEG} degrees square')
    image_size = [int(v) for v in (image_size or DEFAULT_IMAGE)][:2]
    if len(image_size) != 2 or not all(64 <= v <= 8192 for v in image_size):
        raise ValueError('image_size must be [width, height] in pixels')
    rng = np.random.default_rng(seed)
    grid = Grid(bbox)
    rows = records(taxonomy)
    n_b, n_k = len(BAND_GSD), len(CLASSES)
    ground = shares(grid, rows, image_size, sources)
    share = ground
    content = contents.for_sampler(taxonomy, grid, image_size)
    if content:
        rows = [dict(r, share=[v * content['ratio'](r) for v in r['share']]) if r['share'] else r for r in rows]
        share = ground * content['maps'][:, None].astype(np.float32)
    mean, cov, info = fit_yields(rows)
    place_mean, place_sd = place_field(grid, rows, mean)
    expected = np.einsum('bk,bkyx->byx', np.clip(mean, 0.0, None).reshape(n_b, n_k), share) * np.exp(place_mean)

    draw = None
    if policy == 'uniform':
        b, iy, ix = int(rng.integers(n_b)), int(rng.integers(grid.ny)), int(rng.integers(grid.nx))
    else:
        if policy == 'thompson':
            theta = np.clip(rng.multivariate_normal(mean, cov), 0.0, None).reshape(n_b, n_k)
            # one draw per block of about PLACE_LENGTH_M, so neighbouring cells move together
            step = max(1, int(round(PLACE_LENGTH_M / CELL_M)))
            blocks = rng.standard_normal((grid.ny // step + 1, grid.nx // step + 1))
            noise = np.kron(blocks, np.ones((step, step)))[:grid.ny, :grid.nx]
            value = np.einsum('bk,bkyx->byx', theta, share) * np.exp(place_mean + place_sd * noise)
        else:
            value = expected
        value = value + rng.random(value.shape) * 1e-6  # ties are broken at random
        b, iy, ix = (int(v) for v in np.unravel_index(int(np.argmax(value)), value.shape))
        draw = float(value[b, iy, ix])
    lon, lat = grid.centre(ix, iy)
    gsd = BAND_GSD[b]
    predicted = {
        'bits_new': round(float(expected[b, iy, ix]), 1),
        'draw': round(draw, 1) if draw is not None else None,
        'share': {k: round(float(ground[b, j, iy, ix]), 3) for j, k in enumerate(CLASSES)},
        'place': round(float(math.exp(place_mean[iy, ix])), 3),
        'content': round(float(content['maps'][b, iy, ix]), 3) if content else None,
        'content_model': {'name': content['name'], 'fitted_at': content['fitted_at']} if content else None,
        'yield': {k: round(float(mean[b * n_k + j]), 1) for j, k in enumerate(CLASSES)},
        'n_captures': info['n_captures'],
    }
    out = {'policy': policy, 'run': run, 'taxonomy': taxonomy, 'bbox': [round(v, 6) for v in bbox],
           'cell': [ix, iy], 'grid': [grid.nx, grid.ny], 'band': b, 'gsd_m': gsd,
           'lon': round(lon, 6), 'lat': round(lat, 6), 'image_size': image_size,
           'footprint_m': [round(image_size[0] * gsd, 1), round(image_size[1] * gsd, 1)],
           'predicted': predicted}
    if record:
        pull = SamplerPull.objects.create(
            policy=policy, run=run[:40], taxonomy=taxonomy, centre=Point(lon, lat, srid=4326), band=b, gsd_m=gsd,
            image_size=image_size, predicted=dict(predicted, cell=[ix, iy], bbox=out['bbox']), user_id=user_id)
        out['pull_id'] = pull.id
    return out


def model_summary(taxonomy):
    """The fitted yields (before any content factor), and the content models, for display."""
    return dict(fit_yields(records(taxonomy))[2], contents=contents.summary(taxonomy))


def report(pull_id, session_id=None, error=None):
    """Attach the capture a proposal led to, or say why there is none. Returns the pull as a dict."""
    pull = SamplerPull.objects.get(id=pull_id)
    if pull.capture_id or pull.realised:
        return pull_dict(pull)
    if not session_id:
        pull.realised = {'error': str(error or 'no capture')[:200]}
        pull.save(update_fields=['realised'])
        return pull_dict(pull)
    cap = Capture.objects.filter(session_id=session_id, taxonomy=pull.taxonomy).first()
    if cap is None:
        raise ValueError('no such capture')
    if SamplerPull.objects.filter(capture=cap).exists():
        raise ValueError('that capture already answers another proposal')
    if cap.recorded_at < pull.created_at:
        raise ValueError('that capture was stored before the proposal was made')
    # The capture must be the view that was asked for: its footprint has to hold the proposed centre.
    if not cap.footprint.contains(pull.centre):
        raise ValueError('that capture does not cover the proposed view')
    reward = (cap.summary.get('ingest') or {}).get('reward') or {}
    ground = reward.get('ground_ha') or {}
    total = sum(ground.get(k) or 0.0 for k in CLASSES)
    pull.capture = cap
    pull.realised = {
        'bits_new': reward.get('bits_new'), 'bits': reward.get('bits'), 'bits_reread': reward.get('bits_reread'),
        'n_first_sightings': reward.get('n_first_sightings'), 'share_new_ground': reward.get('share_new_ground'),
        'n': {c: r['n'] for c, r in (reward.get('by_cause') or {}).items()},
        'share': {k: round((ground.get(k) or 0.0) / total, 3) for k in CLASSES} if total > 0 else None,
        'gsd_m': round(cap.gsd_m, 3) if cap.gsd_m else None,
    }
    pull.save(update_fields=['capture', 'realised'])
    return pull_dict(pull)


def pull_dict(pull):
    return {'pull_id': pull.id, 'created_at': pull.created_at.isoformat(), 'policy': pull.policy, 'run': pull.run,
            'band': pull.band, 'gsd_m': pull.gsd_m, 'lon': round(pull.centre.x, 6), 'lat': round(pull.centre.y, 6),
            'predicted': pull.predicted, 'realised': pull.realised,
            'session_id': pull.capture.session_id if pull.capture_id else None}


def pulls(taxonomy, *, run=None, limit=200):
    """Stored proposals, newest first, with a per-policy comparison of what was expected and returned."""
    qs = SamplerPull.objects.filter(taxonomy=taxonomy).select_related('capture')
    if run:
        qs = qs.filter(run=run)
    rows = [pull_dict(p) for p in qs.order_by('-id')[:limit]]
    by_policy = {}
    for policy in sorted({r['policy'] for r in rows}):
        done = [r for r in rows if r['policy'] == policy and r['session_id'] and r['realised']
                and r['realised'].get('bits_new') is not None]
        row = {'n_proposed': sum(r['policy'] == policy for r in rows), 'n_captured': len(done)}
        if done:
            got = np.array([r['realised']['bits_new'] for r in done], dtype=float)
            want = np.array([r['predicted']['bits_new'] for r in done], dtype=float)
            counts = {}
            for r in done:
                for cause, n in (r['realised'].get('n') or {}).items():
                    counts[cause] = counts.get(cause, 0) + n
            first = sum(counts.get(c, 0) for c in fusion.FIRST_SIGHTINGS)
            row.update(
                predicted_bits_new=round(float(want.mean()), 1), realised_bits_new=round(float(got.mean()), 1),
                realised_sd=round(float(got.std(ddof=1)), 1) if len(got) > 1 else None,
                mean_abs_error=round(float(np.abs(got - want).mean()), 1),
                correlation=round(float(np.corrcoef(want, got)[0, 1]), 3)
                if len(got) > 2 and want.std() > 0 and got.std() > 0 else None,
                realised_bits_reread=round(float(np.mean([r['realised'].get('bits_reread') or 0.0 for r in done])), 1),
                objects=counts,
                share_new_ground=round(counts.get('new_ground', 0) / first, 3) if first else None,
                share_re_found=round(counts.get('re_found', 0) / first, 3) if first else None,
                by_band={str(BAND_GSD[b]): sum(r['band'] == b for r in done) for b in range(len(BAND_GSD))})
        by_policy[policy] = row
    return {'n': len(rows), 'by_policy': by_policy, 'pulls': rows}
