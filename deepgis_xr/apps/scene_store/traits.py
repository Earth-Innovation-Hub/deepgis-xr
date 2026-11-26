"""Traits of world entities: per-category statistics and a probabilistic map of one trait.

A trait is one scalar per live entity: its area (the median over its sightings), its category
confidence or its probability of still existing. ``trait_map`` summarises the trait for every
category in a box and fits a Gaussian process to one category's values over space, so the map
says both what the trait is likely to be at each point and how sure that is.

The GP is exact: y = f(x) + e, with f ~ GP(0, s^2 Matern-5/2(|x - x'| / l)) and e ~ N(0, n^2),
x in metres from the box centre and y standardised. Areas are close to log-normal, so they are
modelled as log10(area) and mapped back as the median; 0-1 traits are modelled as logits.
l, s and n maximise the log marginal likelihood (Adam, float64, on the GPU when there is one).
"""

import math
import time

import numpy as np
from django.contrib.gis.db.models.functions import Centroid
from django.contrib.gis.geos import Polygon

from .models import Entity

M_PER_DEG = 111320.0
TRAITS = {
    'area': {'field': 'area_m2', 'unit': 'm²', 'log': True},
    'confidence': {'field': 'score', 'unit': 'p', 'log': False},
    'p_exists': {'field': 'p_exists', 'unit': 'p', 'log': False},
}
MIN_GP_POINTS = 8
MAX_GP_POINTS = 4000
GRID_CELLS = 96  # along the longer side of the box
MIN_AREA_M2 = 0.01


def _sig(v, digits=4):
    return float(f'{float(v):.{digits}g}')


def _forward(trait, v):
    if TRAITS[trait]['log']:
        return np.log10(np.maximum(v, MIN_AREA_M2))
    p = np.clip(v, 0.01, 0.99)
    return np.log(p / (1 - p))


def _backward(trait, z):
    if TRAITS[trait]['log']:
        return 10.0 ** z
    return 1 / (1 + np.exp(-z))


def summary(values, trait):
    """n, mean, sd, cv, median, p10, p90, min and max; for areas also the log10 mean and sd."""
    a = np.asarray(values, dtype=float)
    out = {'n': int(a.size)}
    if not a.size:
        return out
    mean, sd = a.mean(), a.std(ddof=1) if a.size > 1 else 0.0
    out.update({k: _sig(v) for k, v in (
        ('mean', mean), ('sd', sd), ('median', np.median(a)), ('p10', np.percentile(a, 10)),
        ('p90', np.percentile(a, 90)), ('min', a.min()), ('max', a.max()))})
    out['cv'] = _sig(sd / mean) if mean > 0 else None
    if TRAITS[trait]['log']:
        z = _forward(trait, a)
        out.update({'geo_mean': _sig(10 ** z.mean()), 'log10_mean': _sig(z.mean()),
                    'log10_sd': _sig(z.std(ddof=1) if a.size > 1 else 0.0)})
    return out


def histogram(values, trait, per_decade=4):
    """Areas in bins a quarter decade wide; 0-1 traits in 20 bins. Same shape as fusion.area_histogram."""
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    log = TRAITS[trait]['log']
    if log:
        a = a[a > 0]
    if not a.size:
        return {'n': 0, 'bins': [], 'overflow': 0, 'stats': None, 'log': log, 'unit': TRAITS[trait]['unit']}
    if log:
        lo = math.floor(math.log10(a.min()) * per_decade) / per_decade
        hi = math.ceil(math.log10(a.max()) * per_decade) / per_decade
        n_bins = max(1, round((hi - lo) * per_decade))
        edges = 10.0 ** np.linspace(lo, lo + n_bins / per_decade, n_bins + 1)
    else:
        edges = np.linspace(0.0, 1.0, 21)
    counts, edges = np.histogram(a, bins=edges)
    return {
        'n': int(a.size), 'log': log, 'unit': TRAITS[trait]['unit'],
        'bin_m2': None if log else 0.05,
        'bins': [{'lo': _sig(lo, 6), 'hi': _sig(hi, 6), 'n': int(c)} for lo, hi, c in zip(edges[:-1], edges[1:], counts)],
        'overflow': 0,
        'stats': {k: _sig(v, 6) for k, v in (
            ('min', a.min()), ('p10', np.percentile(a, 10)), ('median', np.median(a)), ('mean', a.mean()),
            ('p90', np.percentile(a, 90)), ('max', a.max()))},
    }


def _matern52(d, l):
    import torch
    r = math.sqrt(5.0) * d / l
    return (1 + r + r * r / 3) * torch.exp(-r)


def fit_gp(xy, z, grid_xy, *, iters=150, lr=0.08, seed=0):
    """Exact GP on (xy metres, z) predicted at grid_xy: latent mean and sd in z units, and the share
    of the prior variance the data explain at each point (0 far from data, near 1 at dense data)."""
    import torch

    t0 = time.time()
    dev = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    n_all = len(z)
    if n_all > MAX_GP_POINTS:
        keep = np.random.default_rng(seed).choice(n_all, MAX_GP_POINTS, replace=False)
        xy, z = xy[keep], z[keep]
    dt = torch.float64
    X = torch.as_tensor(xy, dtype=dt, device=dev)
    Z = torch.as_tensor(z, dtype=dt, device=dev)
    zm, zs = Z.mean(), Z.std().clamp_min(1e-6)
    Y = ((Z - zm) / zs)[:, None]
    n = len(z)
    D = torch.cdist(X, X)
    eye = torch.eye(n, dtype=dt, device=dev)
    span = float((X.max(0).values - X.min(0).values).max().clamp_min(1.0))
    nn = float((D + eye * 1e12).min(1).values.median())
    min_l, max_l = 5.0, max(50.0, 2 * span)
    l0 = min(max(4 * nn, min_l * 1.5), max_l * 0.5)
    logit = lambda p: math.log(p / (1 - p))  # noqa: E731
    raw_l = torch.tensor(logit((l0 - min_l) / (max_l - min_l)), dtype=dt, device=dev, requires_grad=True)
    raw_s = torch.tensor(math.log(math.expm1(0.5)), dtype=dt, device=dev, requires_grad=True)
    raw_n = torch.tensor(math.log(math.expm1(0.5)), dtype=dt, device=dev, requires_grad=True)
    sp = torch.nn.functional.softplus

    def hyper():
        return (min_l + (max_l - min_l) * torch.sigmoid(raw_l), sp(raw_s) + 1e-4, sp(raw_n) + 1e-4)

    def factor(l, s2, n2):
        return torch.linalg.cholesky(s2 * _matern52(D, l) + (n2 + 1e-6) * eye)

    opt = torch.optim.Adam([raw_l, raw_s, raw_n], lr=lr)
    for _ in range(iters):
        opt.zero_grad()
        l, s2, n2 = hyper()
        try:
            L = factor(l, s2, n2)
        except RuntimeError:  # not positive definite at this step; keep the last good one
            break
        alpha = torch.cholesky_solve(Y, L)
        nll = 0.5 * (Y * alpha).sum() + torch.log(torch.diagonal(L)).sum()
        (nll / n).backward()
        opt.step()
    with torch.no_grad():
        l, s2, n2 = hyper()
        L = factor(l, s2, n2)
        alpha = torch.cholesky_solve(Y, L)
        nll = float(0.5 * (Y * alpha).sum() + torch.log(torch.diagonal(L)).sum() + 0.5 * n * math.log(2 * math.pi))
        G = torch.as_tensor(grid_xy, dtype=dt, device=dev)
        mean, var = [], []
        for chunk in torch.split(G, 4096):
            Ks = s2 * _matern52(torch.cdist(chunk, X), l)
            mean.append((Ks @ alpha)[:, 0])
            v = torch.linalg.solve_triangular(L, Ks.T, upper=False)
            var.append((s2 - (v * v).sum(0)).clamp_min(0))
        mean, var = torch.cat(mean), torch.cat(var)
        explained = (1 - var / s2).clamp(0, 1)
        out = {
            'mean': (mean * zs + zm).cpu().numpy(), 'sd': (var.sqrt() * zs).cpu().numpy(),
            'explained': explained.cpu().numpy(),
            'lengthscale_m': float(l), 'signal_sd': float(s2.sqrt() * zs), 'noise_sd': float(n2.sqrt() * zs),
            'noise_share': float(n2 / (s2 + n2)), 'mean_z': float(zm), 'nll_per_point': nll / n,
            'n_used': n, 'n': n_all,
            'device': torch.cuda.get_device_name(dev) if dev.type == 'cuda' else 'cpu',
        }
    out['fit_ms'] = round((time.time() - t0) * 1000)
    return out


def _local_m(lon, lat, lon0, lat0):
    k = math.cos(math.radians(lat0)) * M_PER_DEG
    return np.column_stack([(np.asarray(lon) - lon0) * k, (np.asarray(lat) - lat0) * M_PER_DEG])


def trait_map(bbox, *, trait='area', category='', taxonomy='urban_v1', min_p_exists=0.5,
              grid_cells=GRID_CELLS, with_grid=True):
    """Statistics of ``trait`` per category of the live entities in ``bbox`` and, when ``category``
    has enough of them, the GP map of the trait for that category (all named categories if empty)."""
    west, south, east, north = bbox
    field = TRAITS[trait]['field']
    rows = (Entity.objects
            .filter(geom__intersects=Polygon.from_bbox(bbox), retired_at__isnull=True,
                    taxonomy=taxonomy, p_exists__gte=min_p_exists)
            .annotate(c=Centroid('geom'))
            .values_list('category', field, 'c'))
    by_cat, pts = {}, []
    for cat, v, c in rows:
        if v is None or not math.isfinite(v):
            continue
        by_cat.setdefault(cat, []).append(v)
        if (cat == category if category else cat != 'unknown'):
            pts.append((c.x, c.y, v))
    categories = sorted(({'category': cat, 'stats': summary(vals, trait), 'hist': histogram(vals, trait)}
                         for cat, vals in by_cat.items()), key=lambda d: -d['stats']['n'])
    out = {'trait': trait, 'unit': TRAITS[trait]['unit'], 'log': TRAITS[trait]['log'],
           'category': category or 'all named categories', 'taxonomy': taxonomy,
           'bbox': [round(v, 6) for v in bbox], 'min_p_exists': min_p_exists,
           'categories': categories, 'n_points': len(pts), 'gp': None, 'grid': None}
    if len(pts) < MIN_GP_POINTS:
        out['gp_skipped'] = f'{len(pts)} {category or "objects"} in the area; the map needs at least {MIN_GP_POINTS}'
        return out
    p = np.asarray(pts, dtype=float)
    lon0, lat0 = (west + east) / 2, (south + north) / 2
    xy = _local_m(p[:, 0], p[:, 1], lon0, lat0)
    z = _forward(trait, p[:, 2])
    width_m = (east - west) * math.cos(math.radians(lat0)) * M_PER_DEG
    height_m = (north - south) * M_PER_DEG
    nx = max(2, round(grid_cells * min(1.0, width_m / height_m)))
    ny = max(2, round(grid_cells * min(1.0, height_m / width_m)))
    # Cell centres, north row first, west to east
    lons = west + (np.arange(nx) + 0.5) * (east - west) / nx
    lats = north - (np.arange(ny) + 0.5) * (north - south) / ny
    glon, glat = np.meshgrid(lons, lats)
    gp = fit_gp(xy, z, _local_m(glon.ravel(), glat.ravel(), lon0, lat0))
    value = _backward(trait, gp['mean'])
    lo, hi = _backward(trait, np.percentile(z, [5, 95]))
    out['gp'] = {
        'kernel': 'Matern 5/2 + noise', 'model': 'log10' if TRAITS[trait]['log'] else 'logit',
        'lengthscale_m': _sig(gp['lengthscale_m']), 'signal_sd': _sig(gp['signal_sd']),
        'noise_sd': _sig(gp['noise_sd']), 'noise_share': _sig(gp['noise_share']),
        'prior_median': _sig(_backward(trait, gp['mean_z'])), 'nll_per_point': _sig(gp['nll_per_point']),
        'n': gp['n'], 'n_used': gp['n_used'], 'device': gp['device'], 'fit_ms': gp['fit_ms'],
        'value_range': [_sig(lo), _sig(hi)],
        'map_range': [_sig(value.min()), _sig(value.max())],
        'mean_explained': _sig(gp['explained'].mean()),
    }
    if with_grid:
        out['grid'] = {
            'west': west, 'south': south, 'east': east, 'north': north, 'nx': nx, 'ny': ny,
            'value': [_sig(v) for v in value], 'sd': [round(float(v), 3) for v in gp['sd']],
            'explained': [round(float(v), 3) for v in gp['explained']],
        }
    return out
