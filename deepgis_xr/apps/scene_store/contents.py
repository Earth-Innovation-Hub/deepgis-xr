"""What a capture of a place should find before anyone looks there.

For every 100 m cell of an area and every zoom band of the sampler, the expected number of
detections per category, from covariates that cover the whole area whether or not it has been
captured:
  Sentinel-2      one clear scene: NDVI mean and spread, share of green pixels, built-up index
                  (SWIR against NIR), brightness, share of wet pixels
  USGS 3DEP lidar where prepared tiles exist: share of ground taller than 2.5 m and 8 m, and
                  their mean height (``lidar_valid`` says where there is none)
  OpenStreetMap   buildings (all, house-sized, large) and their area, road length by class,
                  land-use shares (residential, commercial, industrial, green), parking,
                  water, mapped pools

The model, one per category: a Poisson regression of one capture's detections in one cell on
the covariates, their product with log2 of the capture's pixel size (an effect may differ with
zoom), and the zoom band, with log of the share of the cell the footprint covers as an offset.
Each capture weighs the same however many cells it covers; the ridge penalty is chosen per
category by leaving whole captures out.

Observations of neighbouring cells are not a term. On the Tempe captures, a neighbour term built
from other captures made held-out predictions worse, with or without the covariates: on new
ground it has nothing to say, and next to captured ground it repeats what a different zoom or
the same image saw.

A prior for choosing where to look, and nothing more: nothing here writes a factor or changes
a belief. ``build_area_covariates`` writes an area's covariates, ``fit_area_contents`` fits and
stores the model beside them; ``sampler`` uses it where it covers the arms.
"""

import glob
import json
import logging
import os
import time
from datetime import datetime, timezone as dt_timezone

import numpy as np
from django.utils import timezone
from scipy.optimize import minimize
from scipy.ndimage import uniform_filter

from . import fusion, layers, sampler
from .models import Capture, Detection

log = logging.getLogger(__name__)

MIN_SHARE = 0.3          # a cell the footprint covers less than this is not a training row
FEATURE_CLIP = 4.0       # standardised covariates beyond this many sd are held at it
MAX_PER_CELL = 400.0     # detections a 100 m cell can be expected to give, at most
MIN_DETECTIONS = 40      # a category with fewer stored detections gets no model
LAMBDAS = (1.0, 10.0, 100.0, 1000.0)
FOLDS = 5
OSM_TAGS = {'building': True, 'highway': True, 'landuse': True, 'leisure': True, 'amenity': ['parking'],
            'natural': ['water', 'wood', 'scrub', 'grassland']}
ROAD_CLASSES = {
    'major': ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'motorway_link', 'trunk_link',
              'primary_link', 'secondary_link', 'tertiary_link'],
    'minor': ['residential', 'unclassified', 'living_street'],
    'service': ['service'],
    'path': ['footway', 'path', 'cycleway', 'pedestrian', 'track', 'steps'],
}


def folder():
    root = layers.layer_root()
    return os.path.join(root, 'covariates') if root else ''


def _path(name, suffix):
    return os.path.join(folder(), f'{name}{suffix}')


# ---- covariates -------------------------------------------------------------------------------

def _cells(grid, lon, lat):
    x, y = grid.metres(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    ix = np.floor(x / sampler.CELL_M).astype(int)
    iy = np.floor(y / sampler.CELL_M).astype(int)
    ok = (ix >= 0) & (ix < grid.nx) & (iy >= 0) & (iy < grid.ny)
    return ix[ok], iy[ok], ok


def _bin(grid, ix, iy, w):
    out = np.zeros((grid.ny, grid.nx))
    np.add.at(out, (iy, ix), w)
    return out


def _pixel_lonlat(epsg, transform, rows, cols):
    from pyproj import Transformer
    xs, ys = transform * (cols + 0.5, rows + 0.5)
    return Transformer.from_crs(epsg, 4326, always_xy=True).transform(xs, ys)


def sentinel2_covariates(grid, bbox, since, until, max_cloud=5, max_scenes=8):
    """Per-cell statistics of the clearest scenes, the clearest first, until every cell has 50 pixels."""
    tokens = layers.Tokens()
    cands = sorted(layers.sentinel2_candidates(bbox, since, until, max_cloud), key=lambda c: c['cloud_cover'])
    keys = ('n', 'ndvi', 'ndvi2', 'green', 'ndbi', 'bright', 'wet')
    acc = {k: np.zeros((grid.ny, grid.nx)) for k in keys}
    used = []
    for cand in cands[:max_scenes]:
        filled = acc['n'] >= 50
        if filled.all():
            break
        parts = layers.read_sentinel2(cand, bbox, tokens)
        if not parts:
            continue
        g, (G, R, N, S), valid = parts[0]
        rows, cols = np.nonzero(valid)
        lon, lat = _pixel_lonlat(g.epsg, g.transform, rows, cols)
        x, y = grid.metres(np.asarray(lon), np.asarray(lat))
        ix, iy = np.floor(x / sampler.CELL_M).astype(int), np.floor(y / sampler.CELL_M).astype(int)
        ok = (ix >= 0) & (ix < grid.nx) & (iy >= 0) & (iy < grid.ny)
        ok[ok] &= ~filled[iy[ok], ix[ok]]
        ix, iy, rows, cols = ix[ok], iy[ok], rows[ok], cols[ok]
        g_, r_, n_, s_ = (b[rows, cols].astype(float) for b in (G, R, N, S))
        ndvi = (n_ - r_) / np.maximum(n_ + r_, 1e-6)
        vals = {'n': np.ones_like(ndvi), 'ndvi': ndvi, 'ndvi2': ndvi ** 2, 'green': (ndvi > 0.35).astype(float),
                'ndbi': (s_ - n_) / np.maximum(s_ + n_, 1e-6), 'bright': (g_ + r_ + n_) / 3,
                'wet': ((g_ - n_) / np.maximum(g_ + n_, 1e-6) > 0.05).astype(float)}
        for k in keys:
            acc[k] += _bin(grid, ix, iy, vals[k])
        used.append({'item_id': cand['item_id'], 'observed_at': cand['observed_at'].isoformat(),
                     'cloud_cover': cand['cloud_cover'], 'pixels': int(ok.sum())})
    n = np.maximum(acc['n'], 1)
    mean = acc['ndvi'] / n
    feats = {'s2_ndvi': mean, 's2_ndvi_sd': np.sqrt(np.maximum(acc['ndvi2'] / n - mean ** 2, 0)),
             's2_green_share': acc['green'] / n, 's2_ndbi': acc['ndbi'] / n, 's2_bright': acc['bright'] / n,
             's2_wet_share': acc['wet'] / n}
    return feats, {'sentinel2': used, 'sentinel2_cells_filled': float((acc['n'] >= 50).mean())}


def lidar_covariates(grid, bbox, block=5):
    """Height above ground from the prepared 3DEP tiles, averaged to ``block`` m first."""
    from affine import Affine
    cands = layers.lidar_candidates()
    zero = np.zeros((grid.ny, grid.nx))
    feats = {'lidar_valid': zero.copy(), 'lidar_tall_share': zero.copy(), 'lidar_very_tall_share': zero.copy(),
             'lidar_tall_height': zero.copy()}
    if not cands:
        return feats, {'lidar': None}
    parts = layers.read_lidar(cands[0], bbox)
    if not parts:
        return feats, {'lidar': None}
    g, (h,), valid = parts[0]
    hh, ww = (h.shape[0] // block) * block, (h.shape[1] // block) * block
    h, valid = h[:hh, :ww], valid[:hh, :ww]

    def mean(a):
        return a.reshape(hh // block, block, ww // block, block).mean(axis=(1, 3))

    v, t2 = mean(valid.astype(np.float32)), mean(((h > 2.5) & valid).astype(np.float32))
    t8, hs = mean(((h > 8.0) & valid).astype(np.float32)), mean(np.where((h > 2.5) & valid, h, 0).astype(np.float32))
    rows, cols = np.nonzero(v > 0)
    lon, lat = _pixel_lonlat(g.epsg, g.transform * Affine.scale(block), rows, cols)
    ix, iy, ok = _cells(grid, lon, lat)
    rows, cols = rows[ok], cols[ok]
    nv = _bin(grid, ix, iy, v[rows, cols])
    n2 = _bin(grid, ix, iy, t2[rows, cols])
    blocks = _bin(grid, ix, iy, np.ones(len(ix)))
    has = (nv / np.maximum(blocks, 1) > 0.8).astype(float)
    feats = {'lidar_valid': has,
             'lidar_tall_share': has * n2 / np.maximum(nv, 1e-6),
             'lidar_very_tall_share': has * _bin(grid, ix, iy, t8[rows, cols]) / np.maximum(nv, 1e-6),
             'lidar_tall_height': has * _bin(grid, ix, iy, hs[rows, cols]) / np.maximum(n2, 1e-6)}
    return feats, {'lidar': cands[0]['item_id'], 'lidar_cells': float(has.mean())}


def osm_covariates(grid, bbox):
    """Buildings, roads and land use from OpenStreetMap (one Overpass query, cached on disk)."""
    import osmnx as ox
    import shapely
    ox.settings.timeout = 600
    ox.settings.use_cache = True
    ox.settings.cache_folder = os.path.join(folder(), 'osm_cache')
    w, s, e, n = bbox
    gdf = ox.features_from_bbox(n, s, e, w, tags=OSM_TAGS)
    kinds = gdf.geometry.geom_type
    polys = kinds.isin(['Polygon', 'MultiPolygon']).values
    lines = kinds.isin(['LineString', 'MultiLineString']).values
    area_k = grid.mx * grid.my

    def column(name):
        return gdf[name] if name in gdf.columns else None

    def isin(name, values):
        c = column(name)
        return c.isin(values).values if c is not None else np.zeros(len(gdf), bool)

    def counted(sel, weights=None):
        cen = gdf.geometry[sel].representative_point()
        ix, iy, ok = _cells(grid, cen.x.values, cen.y.values)
        w_ = np.ones(ok.sum()) if weights is None else np.asarray(weights)[ok]
        return _bin(grid, ix, iy, w_)

    def area_share(sel):
        geoms = [shapely.make_valid(g) for g in gdf.geometry[sel & polys]]
        if not geoms:
            return np.zeros((grid.ny, grid.nx))
        return grid.raster(geoms).astype(float).reshape(grid.ny, grid.k, grid.nx, grid.k).mean(axis=(1, 3))

    building = column('building')
    is_b = (building.notna().values if building is not None else np.zeros(len(gdf), bool)) & polys
    b_area = gdf.geometry.area.values * area_k
    houses = is_b & isin('building', ['house', 'detached', 'residential', 'semidetached_house', 'yes']) \
        & (b_area > 60) & (b_area < 600)
    feats = {'osm_buildings': counted(is_b), 'osm_building_area_share': counted(is_b, b_area[is_b]) / 1e4,
             'osm_big_buildings': counted(is_b & (b_area > 600)), 'osm_house_sized': counted(houses),
             'osm_pools': counted(isin('leisure', ['swimming_pool']))}
    for name, values in ROAD_CLASSES.items():
        total = np.zeros((grid.ny, grid.nx))
        for geom in gdf.geometry[isin('highway', values) & lines]:
            length_m = geom.length * np.sqrt(area_k)
            k = max(2, int(length_m / 5))
            pts = shapely.line_interpolate_point(geom, np.linspace(0, 1, k), normalized=True)
            ix, iy, ok = _cells(grid, shapely.get_x(pts), shapely.get_y(pts))
            total += _bin(grid, ix, iy, np.full(ok.sum(), length_m / k))
        feats[f'osm_road_{name}_m'] = total
    green = isin('landuse', ['grass', 'recreation_ground', 'meadow', 'village_green', 'cemetery']) \
        | isin('leisure', ['park', 'golf_course', 'pitch', 'garden'])
    for name, sel in {'residential': isin('landuse', ['residential']),
                      'commercial': isin('landuse', ['commercial', 'retail']),
                      'industrial': isin('landuse', ['industrial']), 'green': green,
                      'parking': isin('amenity', ['parking']),
                      'water': isin('natural', ['water'])}.items():
        feats[f'osm_{name}_share'] = area_share(sel)
    return feats, {'osm_features': int(len(gdf)), 'osm_fetched_at': timezone.now().isoformat()}


def build(name, bbox, *, since=None, until=None, sources=('s2', 'lidar', 'osm')):
    """Compute an area's covariates and write them to ``<name>.npz``. Returns the metadata."""
    if not folder():
        raise ValueError('OBSERVATIONS_ROOT is not set')
    os.makedirs(folder(), exist_ok=True)
    grid = sampler.Grid(bbox)
    since = since or datetime(2023, 4, 1, tzinfo=dt_timezone.utc)
    until = until or datetime(2023, 9, 30, tzinfo=dt_timezone.utc)
    feats, meta = {}, {'bbox': list(bbox), 'grid': [grid.nx, grid.ny], 'built_at': timezone.now().isoformat()}
    steps = {'s2': lambda: sentinel2_covariates(grid, bbox, since, until),
             'lidar': lambda: lidar_covariates(grid, bbox), 'osm': lambda: osm_covariates(grid, bbox)}
    for src in sources:
        t0 = time.time()
        f, m = steps[src]()
        feats.update(f)
        meta.update(m, **{f'{src}_seconds': round(time.time() - t0, 1)})
    names = sorted(feats)
    np.savez_compressed(_path(name, '.npz'), bbox=np.array(bbox, dtype=float), names=np.array(names),
                        values=np.stack([feats[k] for k in names]).astype(np.float32), meta=json.dumps(meta))
    _cache.clear()
    return dict(meta, names=names)


# ---- the model --------------------------------------------------------------------------------

_cache = {}


def _load(path, reader):
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    value = reader(path)
    _cache[path] = (stamp, value)
    return value


class Covariates:
    def __init__(self, name, bbox, names, values, meta):
        self.name, self.bbox, self.names, self.values, self.meta = name, list(bbox), list(names), values, meta
        self.grid = sampler.Grid(self.bbox)

    @classmethod
    def load(cls, name):
        def read(path):
            with np.load(path) as z:
                return cls(name, z['bbox'], [str(v) for v in z['names']], z['values'].astype(float),
                           json.loads(str(z['meta'])))
        return _load(_path(name, '.npz'), read)

    def transformed(self):
        """Counts and lengths on a log scale; everything else as stored."""
        out = []
        for k, v in zip(self.names, self.values):
            if k.startswith('osm_') and not k.endswith('_share'):
                v = np.log1p(v / (100.0 if k.endswith('_m') else 1.0))
            out.append(v)
        return np.stack(out)


def available():
    return sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(folder(), '*.npz'))) if folder() else []


def _read_json(path):
    with open(path) as fh:
        return json.load(fh)


def load_model(name, taxonomy):
    return _load(_path(name, f'.{taxonomy}.json'), _read_json)


def _standardised(cov, model=None):
    raw = cov.transformed()
    flat = raw.reshape(len(raw), -1)
    mean = np.array(model['feature_mean']) if model else flat.mean(1)
    sd = np.array(model['feature_sd']) if model else flat.std(1) + 1e-9
    return np.clip((raw - mean[:, None, None]) / sd[:, None, None], -FEATURE_CLIP, FEATURE_CLIP), mean, sd


def _zoom(gsd, model=None):
    """log2 of the pixel size against 0.2 m, held inside the range the model was fitted on."""
    z = np.log2(np.asarray(gsd, dtype=float) / 0.2)
    return np.clip(z, *model['zoom_range']) if model and 'zoom_range' in model else z


def _rate(X, beta, off=0.0):
    return np.exp(np.clip(X @ np.asarray(beta) + off, -20, np.log(MAX_PER_CELL)))


def _design(F, iy, ix, band, z):
    n_b = len(sampler.BAND_GSD)
    f = F[:, iy, ix].T
    return np.concatenate([np.ones((len(iy), 1))] + [(band == j).astype(float)[:, None] for j in range(1, n_b)]
                          + [f, f * z[:, None]], 1)


def _fit_poisson(X, y, off, w, lam):
    pen = np.ones(X.shape[1])
    pen[:len(sampler.BAND_GSD)] = 0.0

    def loss(beta):
        eta = np.clip(X @ beta + off, -20, 20)
        mu = np.exp(eta)
        return (w * (mu - y * eta)).sum() + 0.5 * lam * (pen * beta ** 2).sum(), X.T @ (w * (mu - y)) + lam * pen * beta

    b0 = np.zeros(X.shape[1])
    b0[0] = np.log(max(float(np.average(y, weights=w)), 1e-3))
    return minimize(loss, b0, jac=True, method='L-BFGS-B', options={'maxiter': 3000}).x


def _deviance(y, mu, w):
    mu = np.maximum(mu, 1e-9)
    return float((w * 2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-12) / mu), 0) - (y - mu))).sum())


def _cover(grid, shape):
    fine = grid.raster([shape]).astype(float)
    return fine.reshape(grid.ny, grid.k, grid.nx, grid.k).mean(axis=(1, 3))


def _captures(taxonomy, cov):
    box = layers.box(*cov.bbox)
    out = []
    for c in Capture.objects.filter(taxonomy=taxonomy, gsd_m__isnull=False).order_by('id'):
        if 'sam3' not in c.sources:
            continue
        shape = fusion._from_geos(c.footprint)
        if shape.intersects(box):
            out.append((c, shape))
    return out


def _counts(grid, capture, cats):
    out = np.zeros((len(cats), grid.ny, grid.nx))
    index = {c: i for i, c in enumerate(cats)}
    for category, geom in Detection.objects.filter(capture=capture, gate='').values_list('category', 'geom'):
        if category in index:
            p = geom.point_on_surface
            ix, iy, ok = _cells(grid, [p.x], [p.y])
            if ok[0]:
                out[index[category], iy[0], ix[0]] += 1
    return out


def _expected_in(F, betas, cover, band, gsd, zoom_range):
    """Expected detections, all categories, in the part of each cell ``cover`` gives, summed."""
    iy, ix = np.nonzero(cover > 0)
    if not len(iy):
        return 0.0
    z = float(np.clip(np.log2(gsd / 0.2), *zoom_range))
    X = _design(F, iy, ix, np.full(len(iy), band), np.full(len(iy), z))
    off = np.log(cover[iy, ix])
    return float(sum(_rate(X, b, off).sum() for b in betas))


def fit(name, taxonomy, *, min_detections=MIN_DETECTIONS, lambdas=LAMBDAS, folds=FOLDS, write=True):
    """Fit the per-category model on the captures over an area's covariates. Returns the model."""
    cov = Covariates.load(name)
    if cov is None:
        raise ValueError(f'no covariates called {name}: run build_area_covariates')
    grid = cov.grid
    F, f_mean, f_sd = _standardised(cov)
    caps = _captures(taxonomy, cov)
    counts = {}
    for c, _ in caps:
        for category in Detection.objects.filter(capture=c, gate='').values_list('category', flat=True):
            counts[category] = counts.get(category, 0) + 1
    cats = sorted(k for k, n in counts.items() if n >= min_detections)
    if len(caps) < folds or not cats:
        raise ValueError(f'too little to fit: {len(caps)} captures, categories {counts}')

    covers = [_cover(grid, shape) for _, shape in caps]
    parts = {'X': [], 'y': [], 'off': [], 'w': [], 'cap': []}
    for ci, ((c, _), cover) in enumerate(zip(caps, covers)):
        iy, ix = np.nonzero(cover >= MIN_SHARE)
        if not len(iy):
            continue
        band = sampler.band_of(c.gsd_m)
        parts['X'].append(_design(F, iy, ix, np.full(len(iy), band), np.full(len(iy), np.log2(c.gsd_m / 0.2))))
        parts['y'].append(_counts(grid, c, cats)[:, iy, ix].T)
        parts['off'].append(np.log(cover[iy, ix]))
        parts['w'].append(np.full(len(iy), 1.0 / len(iy)))
        parts['cap'].append(np.full(len(iy), ci))
    X, Y, off, w, cap = (np.concatenate(parts[k]) for k in ('X', 'y', 'off', 'w', 'cap'))
    w = w * len(w) / w.sum()
    fold = cap % folds

    betas, lams, cv_model, cv_band = [], [], 0.0, 0.0
    n_band = len(sampler.BAND_GSD)
    for k in range(len(cats)):
        best = None
        for lam in lambdas:
            dev = 0.0
            for f_ in range(folds):
                tr, te = fold != f_, fold == f_
                beta = _fit_poisson(X[tr], Y[tr, k], off[tr], w[tr], lam)
                dev += _deviance(Y[te, k], _rate(X[te], beta, off[te]), w[te])
            if best is None or dev < best[0]:
                best = (dev, lam)
        cv_model += best[0]
        for f_ in range(folds):     # the zoom band alone, for comparison
            tr, te = fold != f_, fold == f_
            beta = _fit_poisson(X[tr][:, :n_band], Y[tr, k], off[tr], w[tr], 1e-3)
            cv_band += _deviance(Y[te, k], _rate(X[te][:, :n_band], beta, off[te]), w[te])
        lams.append(best[1])
        betas.append(_fit_poisson(X, Y[:, k], off, w, best[1]))

    # What the model would have said of each capture without it: these, not the in-sample
    # predictions, are what the sampler's yields are fitted against.
    zooms = [float(np.log2(c.gsd_m / 0.2)) for c, _ in caps]
    zoom_range = [min(zooms), max(zooms)]
    expected = np.zeros(len(caps))
    for f_ in range(folds):
        tr = fold != f_
        held = [_fit_poisson(X[tr], Y[tr, k], off[tr], w[tr], lams[k]) for k in range(len(cats))]
        for ci in np.nonzero(np.arange(len(caps)) % folds == f_)[0]:
            c = caps[ci][0]
            expected[ci] = _expected_in(F, held, covers[ci], sampler.band_of(c.gsd_m), c.gsd_m, zoom_range)
    model = {
        'name': name, 'taxonomy': taxonomy, 'fitted_at': timezone.now().isoformat(), 'bbox': cov.bbox,
        'categories': cats, 'features': cov.names, 'feature_mean': f_mean.tolist(), 'feature_sd': f_sd.tolist(),
        'betas': [b.tolist() for b in betas], 'lambdas': lams, 'zoom_range': zoom_range,
        'n_captures': len(caps), 'n_rows': int(len(Y)), 'last_capture_id': max(c.id for c, _ in caps),
        'cv_deviance_per_row': {'band_only': round(cv_band / len(Y), 3), 'model': round(cv_model / len(Y), 3)},
    }
    # Content is relative to the area's median at each band, so it is about 1 in every band,
    # including bands no capture has used yet. It is held at the richest view any capture at
    # that band gave: past that the model is extrapolating (ground without lidar, at 1 m, went to 30).
    whole = expected_maps(cov, model, sampler.DEFAULT_IMAGE)
    band_mean = [max(float(np.median(whole[b])), 1e-6) for b in range(n_band)]
    model['band_mean'] = band_mean
    ratios = [float(expected[i] / band_mean[sampler.band_of(c.gsd_m)]) for i, (c, _) in enumerate(caps)]
    model['capture_ratio'] = {str(c.id): round(r, 4) for (c, _), r in zip(caps, ratios)}
    by_band = [[r for (c, _), r in zip(caps, ratios) if sampler.band_of(c.gsd_m) == b] for b in range(n_band)]
    model['content_cap'] = [round(max(v) if len(v) >= 3 else max(ratios), 4) for v in by_band]
    if write:
        with open(_path(name, f'.{taxonomy}.json'), 'w') as fh:
            json.dump(model, fh)
        _cache.pop(_path(name, f'.{taxonomy}.json'), None)
    return model


def expected_maps(cov, model, image_size):
    """(bands, ny, nx): expected detections in a footprint of ``image_size`` centred on each cell,
    at each band's pixel size, over the covariates' own grid. Ground outside the grid counts as
    empty."""
    F, _, _ = _standardised(cov, model)
    grid = cov.grid
    iy, ix = np.mgrid[0:grid.ny, 0:grid.nx]
    iy, ix = iy.ravel(), ix.ravel()
    out = np.zeros((len(sampler.BAND_GSD), grid.ny, grid.nx))
    for b, gsd in enumerate(sampler.BAND_GSD):
        X = _design(F, iy, ix, np.full(len(iy), b), np.full(len(iy), float(_zoom(gsd, model))))
        rate = sum(_rate(X, beta) for beta in model['betas']).reshape(grid.ny, grid.nx)
        fine = np.kron(rate, np.ones((grid.k, grid.k))) / grid.k ** 2
        size = (max(1, int(round(image_size[1] * gsd / sampler.FINE_M))),
                max(1, int(round(image_size[0] * gsd / sampler.FINE_M))))
        total = uniform_filter(fine, size=size, mode='constant', cval=0.0) * size[0] * size[1]
        out[b] = total[grid.k // 2::grid.k, grid.k // 2::grid.k][:grid.ny, :grid.nx]
    return out


def for_sampler(taxonomy, grid, image_size):
    """The content factor for the sampler's arms, or None where no fitted model covers them.

    Returns {'maps': (bands, ny, nx) expected detections over the band's mean, 1 outside the
    covariates; 'ratio': callable(record) giving the same factor for a stored capture; 'name';
    'fitted_at'; 'covered': share of the arms inside the covariates}."""
    cx, cy = grid.centre(grid.nx // 2, grid.ny // 2)
    for name in available():
        cov = Covariates.load(name)
        model = load_model(name, taxonomy)
        if cov is None or model is None:
            continue
        w, s, e, n = cov.bbox
        if not (w <= cx <= e and s <= cy <= n):
            continue
        key = (name, taxonomy, model['fitted_at'], tuple(image_size))
        hit = _maps_cache.get(key)
        if hit is None:
            hit = expected_maps(cov, model, image_size)
            _maps_cache.clear()
            _maps_cache[key] = hit
        band_mean = np.maximum(np.array(model['band_mean']), 1e-6)
        maps = np.ones((len(sampler.BAND_GSD), grid.ny, grid.nx))
        lon = np.array([grid.centre(ix, 0)[0] for ix in range(grid.nx)])
        lat = np.array([grid.centre(0, iy)[1] for iy in range(grid.ny)])
        LON, LAT = np.meshgrid(lon, lat)
        cix, ciy, ok = _cells(cov.grid, LON.ravel(), LAT.ravel())
        inside = ok.reshape(grid.ny, grid.nx)
        for b in range(len(sampler.BAND_GSD)):
            maps[b][inside] = np.minimum(hit[b][ciy, cix] / band_mean[b], model['content_cap'][b])
        return {'maps': maps, 'ratio': _record_ratio(cov, model), 'name': name, 'fitted_at': model['fitted_at'],
                'covered': float(inside.mean())}
    return None


_maps_cache = {}
_ratio_cache = {}


def _record_ratio(cov, model):
    stored = model['capture_ratio']
    band_mean = np.maximum(np.array(model['band_mean']), 1e-6)
    box = layers.box(*cov.bbox)

    def ratio(record):
        hit = stored.get(str(record['id']))
        if hit is not None:
            return hit
        if not record['shape'].intersects(box):
            return 1.0
        key = (model['fitted_at'], record['id'])
        if key not in _ratio_cache:
            F, _, _ = _standardised(cov, model)
            b = record['band']
            _ratio_cache[key] = min(_expected_in(F, model['betas'], _cover(cov.grid, record['shape']), b,
                                                 record['gsd'], model['zoom_range']) / band_mean[b],
                                    model['content_cap'][b])
        return _ratio_cache[key]

    return ratio


def summary(taxonomy):
    out = []
    for name in available():
        model = load_model(name, taxonomy)
        if model:
            out.append({k: model[k] for k in ('name', 'fitted_at', 'bbox', 'categories', 'n_captures',
                                              'cv_deviance_per_row', 'lambdas')})
    return out
