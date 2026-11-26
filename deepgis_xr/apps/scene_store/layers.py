"""Remote-sensing layers sampled onto world entities. A record only: nothing here writes a
factor or changes a belief.

A scene is one look by one sensor: a Sentinel-2 pass, a NAIP aerial photograph, a lidar
survey. It is stored like a capture, with the provider's id, the exact acquisition time and
the ground size of a pixel. Each scene is sampled once onto every live entity it covers, and
again onto entities added later (``LayerScene.sampled_through``).

Sampling. A pixel under a small object mostly measures its neighbours. For each entity the
outline is drawn on the scene's pixel grid and blurred by the sensor's point spread plus the
uncertainty of where the outline sits on the ground (``sigma_m``, an isotropic Gaussian), so
every pixel gets ``c``: the share of its signal that comes from inside the outline. The
sample is the ``c``-weighted mean of each band over the usable pixels; ``purity`` is the
``c``-weighted mean of ``c`` itself (1 = only pixels that lie wholly inside, 0.3 = seven
tenths of the signal is the surroundings); ``clear`` is the share of the entity's weight
that fell on usable pixels (inside the image, not cloud or shadow). Samples under
``MIN_PURITY`` or ``MIN_CLEAR`` are not stored: an entity too small for a sensor simply has
no series from it.

Sources:
  sentinel-2-l2a   surface reflectance at 10 m, every few days; value = NDVI from the band means
  naip             aerial photograph at 0.3-0.6 m, every two years, read at 1.2 m; digital
                   numbers, not reflectance, so its NDVI compares objects within one
                   photograph and not across years
  usgs-3dep-lidar  height above ground at 1 m from the public point cloud, gridded outside
                   this app (see the ``plan_lidar_height`` command); value = the median height

The widths in ``SOURCES`` are set by hand from the sensors' published figures, not fitted.
"""

import glob
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone

import numpy as np
import requests
import shapely
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction
from django.db.models import Count, Max, Min, Sum
from scipy.ndimage import gaussian_filter
from scipy.sparse import csr_matrix
from shapely.geometry import box, shape as shapely_shape
from shapely.ops import transform as shapely_transform

from . import fusion, priors
from .models import Capture, Entity, LayerSample, LayerScene

log = logging.getLogger(__name__)

DB = fusion.DB
STAC_URL = 'https://planetarycomputer.microsoft.com/api/stac/v1/search'
SAS_URL = 'https://planetarycomputer.microsoft.com/api/sas/v1/token/'
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif,.tiff',
                GDAL_HTTP_MAX_RETRY='4', GDAL_HTTP_RETRY_DELAY='2', GDAL_HTTP_TIMEOUT='60', VSI_CACHE='TRUE')

MIN_PURITY = 0.25       # below this a sample says more about the neighbours than the entity
MIN_CLEAR = 0.5         # at least half of the entity's weight must be on usable pixels
MIN_WEIGHT = 0.02       # pixels contributing less than this are dropped
MIN_SUPERSAMPLE, MAX_SUPERSAMPLE = 4, 16   # sub-cells per pixel side the outline is drawn at
SITE_GAP_DEG = 0.05     # capture areas closer than twice this are searched as one site
LOOKBACK_DAYS = 30      # later runs search this far behind the newest known scene for late arrivals
OUTLINE_SIGMA_M = priors.VIRTUAL_CAMERA_SIGMA_H_M   # where an outline drawn on the basemap sits on the ground
# Sentinel-2 classes that are not a view of the ground: no data, defective, cloud shadow, cloud, cirrus
S2_BAD_SCL = (0, 1, 3, 8, 9, 10)
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=dt_timezone.utc)

SOURCES = {
    'sentinel2': {
        'source': 'sentinel-2-l2a', 'layer': 'ndvi', 'label': 'Sentinel-2',
        # 10 m bands: point spread about 4.5 m, geolocation about 3 m (1 sigma)
        'sigma_m': math.sqrt(OUTLINE_SIGMA_M ** 2 + 4.5 ** 2 + 3.0 ** 2),
        'bands': ['green', 'red', 'nir', 'swir16'], 'workers': 8,
    },
    'naip': {
        'source': 'naip', 'layer': 'ndvi', 'label': 'NAIP aerial photograph',
        # absolute accuracy of the photograph about 2.4 m (1 sigma); read at 1.2 m
        'sigma_m': math.sqrt(OUTLINE_SIGMA_M ** 2 + 2.4 ** 2), 'pixel_m': 1.2,
        'bands': ['red', 'green', 'blue', 'nir'], 'workers': 3,
    },
    'lidar': {
        'source': 'usgs-3dep-lidar', 'layer': 'height', 'label': 'USGS 3DEP lidar',
        'sigma_m': OUTLINE_SIGMA_M, 'pixel_m': 1.0, 'bands': ['p25', 'p50', 'p90', 'mean'], 'workers': 1,
    },
}
BY_SOURCE = {cfg['source']: cfg for cfg in SOURCES.values()}
UNITS = {'ndvi': '', 'height': 'm'}


def layer_root():
    """Where rasters prepared outside the app are kept (lidar height tiles)."""
    root = getattr(settings, 'OBSERVATIONS_ROOT', '') or ''
    return os.path.join(root, 'layers') if root else ''


# ---- entity footprints on a pixel grid ----------------------------------------------------------

class Grid:
    """A pixel grid: EPSG code, affine transform of its top-left corner, (rows, columns)."""

    def __init__(self, epsg, transform, shape):
        self.epsg, self.transform, self.shape = epsg, transform, (int(shape[0]), int(shape[1]))

    @property
    def key(self):
        return (self.epsg, tuple(round(v, 6) for v in tuple(self.transform)[:6]), self.shape)

    @property
    def pixel_m(self):
        return abs(self.transform.a)


class Shapes:
    """Entity outlines, in lon/lat and (on demand) in a scene's projection."""

    def __init__(self, ids, lonlat):
        self.ids = np.asarray(ids, dtype=np.int64)
        self.lonlat = list(lonlat)
        self.boxes = np.array([g.bounds for g in self.lonlat], dtype=float).reshape(-1, 4)
        self._projected = {}
        self._box_geoms = None

    @classmethod
    def of(cls, entities):
        geoms = []
        for e in entities:
            g = fusion._from_geos(e.geom)
            geoms.append(g if g.is_valid else g.buffer(0))
        return cls([e.id for e in entities], geoms)

    def __len__(self):
        return len(self.ids)

    def projected(self, epsg):
        if epsg not in self._projected:
            from pyproj import Transformer
            tf = Transformer.from_crs(4326, epsg, always_xy=True).transform
            self._projected[epsg] = [shapely_transform(tf, g) for g in self.lonlat]
        return self._projected[epsg]

    def inside(self, geom, margin_deg=0.0):
        """Indices of the outlines whose bounding box lies inside ``geom`` shrunk by a margin."""
        if not len(self):
            return np.zeros(0, dtype=int)
        inner = geom.buffer(-margin_deg) if margin_deg else geom
        if inner.is_empty:
            return np.zeros(0, dtype=int)
        b = self.boxes
        if inner.contains(box(b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max())):
            return np.arange(len(self))   # the usual case: the scene covers every outline
        if self._box_geoms is None:
            self._box_geoms = shapely.box(b[:, 0], b[:, 1], b[:, 2], b[:, 3])
        shapely.prepare(inner)
        return np.nonzero(shapely.contains(inner, self._box_geoms))[0]

    def bounds(self, idx):
        b = self.boxes[idx]
        return float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())


class Footprint:
    """Per-pixel weights of a set of outlines on one grid (rows = outlines, columns = pixels)."""

    def __init__(self, weights, totals):
        self.weights = weights
        self.squares = weights.multiply(weights).tocsr()
        self.totals = totals


def coverage(shapes, grid, sigma_m, sub=None):
    """Footprint of projected ``shapes`` on ``grid``: for each pixel, the share of its signal
    that comes from inside the outline, after a Gaussian blur of ``sigma_m`` metres.

    ``totals`` is each outline's whole weight, on the grid or off it."""
    from affine import Affine
    from rasterio.features import rasterize

    rows_n, cols_n = grid.shape
    px = grid.pixel_m
    s = sigma_m / px
    pad = int(math.ceil(3 * s)) + 1
    # the outline is drawn on cells of about 0.6 m, so a small object's share of a large pixel is right
    sub = sub or min(MAX_SUPERSAMPLE, max(MIN_SUPERSAMPLE, int(math.ceil(px / 0.6))))
    inv = ~grid.transform
    rows, cols, vals = [], [], []
    totals = np.zeros(len(shapes))
    for i, g in enumerate(shapes):
        if g.is_empty:
            continue
        x0, y0, x1, y1 = g.bounds
        ca, ra = inv * (x0, y1)
        cb, rb = inv * (x1, y0)
        c0, r0 = int(math.floor(min(ca, cb))) - pad, int(math.floor(min(ra, rb))) - pad
        c1, r1 = int(math.ceil(max(ca, cb))) + pad, int(math.ceil(max(ra, rb))) + pad
        if c1 <= 0 or r1 <= 0 or c0 >= cols_n or r0 >= rows_n:
            continue
        h, w = r1 - r0, c1 - c0
        k = sub
        while k > 1 and h * w * k * k > 3e7:
            k //= 2
        fine = grid.transform * Affine.translation(c0, r0) * Affine.scale(1.0 / k)
        mask = rasterize([(g, 1)], out_shape=(h * k, w * k), transform=fine, fill=0, dtype='uint8')
        cov = mask.reshape(h, k, w, k).mean(axis=(1, 3))
        if s > 0:
            cov = gaussian_filter(cov, s, mode='constant', truncate=3.0)
        rr, cc = np.nonzero(cov >= MIN_WEIGHT)
        totals[i] = cov[rr, cc].sum()
        gr, gc = rr + r0, cc + c0
        keep = (gr >= 0) & (gr < rows_n) & (gc >= 0) & (gc < cols_n)
        if not keep.any():
            continue
        rows.append(np.full(int(keep.sum()), i, dtype=np.int64))
        cols.append(gr[keep] * cols_n + gc[keep])
        vals.append(cov[rr[keep], cc[keep]])
    n_px = rows_n * cols_n
    if rows:
        weights = csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                             shape=(len(shapes), n_px))
    else:
        weights = csr_matrix((len(shapes), n_px))
    return Footprint(weights, totals)


def measure(fp, bands, valid):
    """Weighted band means per outline over the ``valid`` pixels.

    Returns (means [n x bands], clear, purity, n_pixels); rows with no usable pixel are NaN."""
    m = np.asarray(valid, dtype=np.float64).ravel()
    den = fp.weights @ m
    with np.errstate(divide='ignore', invalid='ignore'):
        means = np.stack([(fp.weights @ (np.asarray(b, dtype=np.float64).ravel() * m)) / den for b in bands], axis=1)
        purity = (fp.squares @ m) / den
        clear = np.where(fp.totals > 0, den / fp.totals, 0.0)
    return means, np.clip(clear, 0.0, 1.0), purity, den


def measure_quantiles(fp, values, valid, quantiles=(0.25, 0.5, 0.9)):
    """Weighted quantiles and mean of one band per outline: (stats [n x (quantiles + 1)], clear, purity, n_pixels)."""
    v = np.asarray(values, dtype=np.float64).ravel()
    m = np.asarray(valid, dtype=bool).ravel()
    w_all = fp.weights
    n = w_all.shape[0]
    out = np.full((n, len(quantiles) + 1), np.nan)
    clear, purity, n_px = np.zeros(n), np.full(n, np.nan), np.zeros(n)
    for i in range(n):
        sl = slice(w_all.indptr[i], w_all.indptr[i + 1])
        idx, w = w_all.indices[sl], w_all.data[sl]
        ok = m[idx]
        if not ok.any():
            continue
        w, x = w[ok], v[idx[ok]]
        total = w.sum()
        order = np.argsort(x)
        cum = (np.cumsum(w[order]) - 0.5 * w[order]) / total
        out[i, :len(quantiles)] = np.interp(quantiles, cum, x[order])
        out[i, -1] = float((w * x).sum() / total)
        n_px[i] = total
        purity[i] = float((w * w).sum() / total)
        clear[i] = total / fp.totals[i] if fp.totals[i] > 0 else 0.0
    return out, np.clip(clear, 0.0, 1.0), purity, n_px


# ---- catalogue ----------------------------------------------------------------------------------

def stac_search(body, max_pages=40):
    """Every item of a Planetary Computer STAC search."""
    items, url = [], STAC_URL
    for _ in range(max_pages):
        resp = requests.post(url, json=body, timeout=60)
        resp.raise_for_status()
        page = resp.json()
        items += page.get('features', [])
        link = next((ln for ln in page.get('links', []) if ln.get('rel') == 'next'), None)
        if not link:
            break
        url, body = link['href'], link.get('body') or body
    return items


class Tokens:
    """Read tokens for the public imagery store, one per collection, renewed before they lapse."""

    def __init__(self):
        self._held, self._lock = {}, threading.Lock()

    def get(self, collection):
        with self._lock:
            token, until = self._held.get(collection, ('', 0.0))
            if time.time() > until:
                resp = requests.get(SAS_URL + collection, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                token = data['token']
                expiry = fusion._parse_time(data.get('msft:expiry'), None)
                until = (expiry.timestamp() - 600) if expiry else time.time() + 900
                self._held[collection] = (token, until)
            return token


def _when(text):
    return fusion._parse_time(text, None)


def _polygon(geometry, bbox):
    """A STAC item's footprint as one lon/lat polygon."""
    try:
        g = shapely_shape(geometry)
        if not g.is_valid:
            g = g.buffer(0)
        if g.geom_type != 'Polygon':
            g = g.convex_hull
        if g.geom_type == 'Polygon' and not g.is_empty:
            return g
    except Exception:
        pass
    return box(*bbox)


def sites(taxonomy):
    """Lon/lat boxes around the capture areas of a taxonomy; areas a few km apart share one."""
    feet = [fusion._from_geos(f) for f in Capture.objects.filter(taxonomy=taxonomy).values_list('footprint', flat=True)]
    if not feet:
        return []
    merged = shapely.union_all([f.buffer(SITE_GAP_DEG) for f in feet if not f.is_empty])
    parts = list(merged.geoms) if hasattr(merged, 'geoms') else [merged]
    out = []
    for part in parts:
        inside = [f for f in feet if f.intersects(part)]
        b = shapely.union_all(inside).bounds
        out.append([round(b[0] - 0.002, 5), round(b[1] - 0.002, 5), round(b[2] + 0.002, 5), round(b[3] + 0.002, 5)])
    return out


def sentinel2_candidates(bbox, since, until, max_cloud):
    items = stac_search({'collections': ['sentinel-2-l2a'], 'bbox': bbox, 'limit': 250,
                         'datetime': f'{since:%Y-%m-%dT%H:%M:%SZ}/{until:%Y-%m-%dT%H:%M:%SZ}',
                         'query': {'eo:cloud_cover': {'lt': max_cloud}}})
    out = []
    for it in items:
        p, a = it.get('properties', {}), it.get('assets', {})
        at = _when(p.get('datetime'))
        hrefs = {name: (a.get(key) or {}).get('href') for name, key in
                 (('green', 'B03'), ('red', 'B04'), ('nir', 'B08'), ('swir16', 'B11'), ('scl', 'SCL'))}
        if at is None or not all(hrefs.values()):
            continue
        out.append({
            'source': 'sentinel-2-l2a', 'layer': 'ndvi', 'item_id': it['id'], 'observed_at': at, 'gsd_m': 10.0,
            'look': f"{p.get('platform') or 's2'}:{at:%Y-%m-%d}", 'geometry': _polygon(it.get('geometry'), it['bbox']),
            'cloud_cover': p.get('eo:cloud_cover'),
            'metadata': {'platform': p.get('platform'), 'tile': p.get('s2:mgrs_tile'),
                         'baseline': p.get('s2:processing_baseline'), 'assets': hrefs,
                         'bands': SOURCES['sentinel2']['bands'], 'units': 'surface reflectance'},
        })
    return out


def naip_candidates(bbox, since, until):
    items = stac_search({'collections': ['naip'], 'bbox': bbox, 'limit': 200,
                         'datetime': f'{since:%Y-%m-%dT%H:%M:%SZ}/{until:%Y-%m-%dT%H:%M:%SZ}'})
    out = []
    for it in items:
        p, a = it.get('properties', {}), it.get('assets', {})
        at = _when(p.get('datetime'))
        href = (a.get('image') or {}).get('href')
        if at is None or not href:
            continue
        out.append({
            'source': 'naip', 'layer': 'ndvi', 'item_id': it['id'], 'observed_at': at,
            'gsd_m': float(p.get('gsd') or 0.6), 'look': f'naip:{at:%Y-%m-%d}',
            'geometry': _polygon(it.get('geometry'), it['bbox']), 'cloud_cover': None,
            'metadata': {'year': str(p.get('naip:year') or at.year), 'state': p.get('naip:state'),
                         'assets': {'image': href}, 'bands': SOURCES['naip']['bands'],
                         'read_at_m': SOURCES['naip']['pixel_m'], 'units': 'digital numbers, not reflectance'},
        })
    return out


def lidar_candidates():
    """Height-above-ground tiles prepared under ``<layer_root>/usgs_3dep/<project>/``."""
    import rasterio
    from rasterio.warp import transform_bounds

    root = layer_root()
    out = []
    for folder in sorted(glob.glob(os.path.join(root, 'usgs_3dep', '*'))) if root else []:
        tiles = sorted(glob.glob(os.path.join(folder, 'hag_*.tif')))
        times, n_points = [], 0
        for meta in glob.glob(os.path.join(folder, 'pipelines', 'hag_*.meta.json')):
            try:
                with open(meta) as fh:
                    stats = json.load(fh)['stages']['filters.stats']['statistic']
                gps = next(s for s in stats if s['name'] == 'GpsTime')
                times += [gps['minimum'], gps['maximum']]
                n_points += int(gps.get('count') or 0)
            except Exception:
                continue
        if not tiles or not times:
            continue   # no tiles, or nothing to date them by
        boxes = []
        for path in tiles:
            with rasterio.open(path) as ds:
                boxes.append(box(*transform_bounds(ds.crs, 'EPSG:4326', *ds.bounds, densify_pts=5)))
                gsd = float(ds.res[0])
        # adjusted standard GPS time: seconds since 1980-01-06, less 1e9
        start = GPS_EPOCH + timedelta(seconds=min(times) + 1e9)
        end = GPS_EPOCH + timedelta(seconds=max(times) + 1e9)
        project = os.path.basename(folder)
        area = shapely.union_all(boxes)
        out.append({
            'source': 'usgs-3dep-lidar', 'layer': 'height', 'item_id': project, 'observed_at': start + (end - start) / 2,
            'window': (start, end), 'gsd_m': gsd, 'look': f'lidar:{project}', 'geometry': area.envelope,
            'covered': area, 'cloud_cover': None,
            'metadata': {'project': project, 'n_tiles': len(tiles), 'n_points': n_points, 'folder': folder,
                         'bands': SOURCES['lidar']['bands'], 'units': 'metres above ground',
                         'method': 'highest return per 1 m cell above the nearest ground returns'},
        })
    return out


# ---- reading ------------------------------------------------------------------------------------

def _window(ds, bounds_ll, pad_m):
    """A whole-pixel window of ``ds`` around lon/lat bounds, or None when they do not meet."""
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    b = transform_bounds('EPSG:4326', ds.crs, *bounds_ll, densify_pts=21)
    w = from_bounds(b[0] - pad_m, b[1] - pad_m, b[2] + pad_m, b[3] + pad_m, ds.transform)
    c0, r0 = max(int(math.floor(w.col_off)), 0), max(int(math.floor(w.row_off)), 0)
    c1 = min(int(math.ceil(w.col_off + w.width)), ds.width)
    r1 = min(int(math.ceil(w.row_off + w.height)), ds.height)
    return Window(c0, r0, c1 - c0, r1 - r0) if c1 > c0 and r1 > r0 else None


def read_sentinel2(cand, bounds_ll, tokens):
    """[(grid, bands, valid)] over lon/lat bounds: reflectance in green, red, nir and swir16."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import bounds as window_bounds, from_bounds

    token = tokens.get('sentinel-2-l2a')
    assets = cand['metadata']['assets']
    # from processing baseline 04.00 the numbers carry a +1000 offset
    offset = -1000.0 if float(cand['metadata'].get('baseline') or 0) >= 4 else 0.0
    dn = {}
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(f"{assets['red']}?{token}") as ds:
            win = _window(ds, bounds_ll, 60.0)
            if win is None:
                return []
            grid = Grid(ds.crs.to_epsg(), ds.window_transform(win), (win.height, win.width))
            edges = window_bounds(win, ds.transform)
            dn['red'] = ds.read(1, window=win)
        for name in ('green', 'nir', 'swir16', 'scl'):
            with rasterio.open(f'{assets[name]}?{token}') as ds:
                dn[name] = ds.read(1, window=from_bounds(*edges, ds.transform), out_shape=grid.shape,
                                   resampling=Resampling.nearest)
    valid = (dn['red'] > 0) & (dn['nir'] > 0) & (dn['green'] > 0) & ~np.isin(dn['scl'], S2_BAD_SCL)
    bands = [(dn[name].astype(np.float32) + offset) / 10000.0 for name in SOURCES['sentinel2']['bands']]
    return [(grid, bands, valid)]


def read_naip(cand, bounds_ll, tokens):
    """[(grid, bands, valid)]: the photograph's four bands averaged to about 1.2 m pixels."""
    import rasterio
    from affine import Affine
    from rasterio.enums import Resampling

    token = tokens.get('naip')
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(f"{cand['metadata']['assets']['image']}?{token}") as ds:
            if ds.count < 4:
                return []
            win = _window(ds, bounds_ll, 15.0)
            if win is None:
                return []
            step = max(1, int(round(SOURCES['naip']['pixel_m'] / abs(ds.res[0]))))
            h, w = int(math.ceil(win.height / step)), int(math.ceil(win.width / step))
            data = ds.read([1, 2, 3, 4], window=win, out_shape=(4, h, w), resampling=Resampling.average)
            transform = ds.window_transform(win) * Affine.scale(win.width / w, win.height / h)
            grid = Grid(ds.crs.to_epsg(), transform, (h, w))
    valid = data.max(axis=0) > 0
    return [(grid, [data[i].astype(np.float32) for i in range(4)], valid)]


def read_lidar(cand, bounds_ll, tokens=None):
    """[(grid, [height], valid)] mosaicked from the prepared tiles that meet lon/lat bounds."""
    import rasterio
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds

    tiles = sorted(glob.glob(os.path.join(cand['metadata']['folder'], 'hag_*.tif')))
    opened = []
    try:
        want = None
        for path in tiles:
            ds = rasterio.open(path)
            if want is None:
                b = transform_bounds('EPSG:4326', ds.crs, *bounds_ll, densify_pts=21)
                want = (math.floor(b[0]) - 10, math.floor(b[1]) - 10, math.ceil(b[2]) + 10, math.ceil(b[3]) + 10)
            t = ds.bounds
            if t.right <= want[0] or t.left >= want[2] or t.top <= want[1] or t.bottom >= want[3]:
                ds.close()
                continue
            opened.append(ds)
        if not opened:
            return []
        nodata = opened[0].nodata if opened[0].nodata is not None else -9999.0
        data, transform = merge(opened, bounds=want, nodata=nodata)
        grid = Grid(opened[0].crs.to_epsg(), transform, data.shape[1:])
    finally:
        for ds in opened:
            ds.close()
    return [(grid, [data[0]], data[0] != nodata)]


READERS = {'sentinel-2-l2a': read_sentinel2, 'naip': read_naip, 'usgs-3dep-lidar': read_lidar}


def values_of(source, fp, bands, valid):
    """(value, band stats, clear, purity, n_pixels) for one source's raster under a footprint."""
    if source == 'usgs-3dep-lidar':
        stats, clear, purity, n_px = measure_quantiles(fp, bands[0], valid)
        return stats[:, 1], stats, clear, purity, n_px
    means, clear, purity, n_px = measure(fp, bands, valid)
    names = BY_SOURCE[source]['bands']
    red, nir = means[:, names.index('red')], means[:, names.index('nir')]
    with np.errstate(divide='ignore', invalid='ignore'):
        ndvi = np.where(nir + red > 1e-3, (nir - red) / (nir + red), np.nan)
    return ndvi, means, clear, purity, n_px


# ---- the watch ----------------------------------------------------------------------------------

def _scene_candidate(scene):
    """A stored scene in the shape of a catalogue candidate, for sampling entities added since."""
    look = scene.metadata.get('look') or f'{scene.source}:{scene.item_id}'
    return {'source': scene.source, 'layer': scene.layer, 'item_id': scene.item_id, 'observed_at': scene.observed_at,
            'gsd_m': scene.gsd_m, 'look': look, 'geometry': fusion._from_geos(scene.footprint),
            'cloud_cover': scene.cloud_cover, 'metadata': scene.metadata, 'scene': scene}


def _plan(candidates, shapes, margin_deg):
    """Give each entity still to be sampled to one scene per look: the scene that covers most.

    Two scenes of one look (the same pass cut into two overlapping tiles) show the same pixels,
    so an entity is read from one of them, and never again once a scene of that look has
    considered it. Returns [(candidate, entity indices)] for every candidate; the indices are
    empty when it has nothing to add."""
    by_look = {}
    for cand in candidates:
        by_look.setdefault(cand['look'], []).append(cand)
    plan = []
    for look in sorted(by_look):
        group = []
        taken = np.zeros(len(shapes), dtype=bool)
        for cand in by_look[look]:
            area = cand['covered'] if cand.get('covered') is not None else cand['geometry']
            idx = shapes.inside(area, margin_deg)
            done = cand['scene'].sampled_through if cand.get('scene') is not None else 0
            seen = shapes.ids[idx] <= done
            taken[idx[seen]] = True
            group.append((cand, idx[~seen]))
        group = [(cand, idx[~taken[idx]]) for cand, idx in group]
        # most entities first; between equals a scene already stored, so a look keeps to one scene
        for cand, idx in sorted(group, key=lambda ci: (-len(ci[1]), ci[0].get('scene') is None, ci[0]['item_id'])):
            mine = idx[~taken[idx]]
            taken[mine] = True
            plan.append((cand, mine))
    return plan


def _save_scene(cand, through, n_new, note=None):
    meta = {**{k: v for k, v in cand['metadata'].items() if k != 'folder'}, 'look': cand['look']}
    if note:
        meta['note'] = note
    else:
        meta.pop('note', None)
    scene = cand.get('scene')
    if scene is None:
        window = cand.get('window') or (None, None)
        scene, _ = LayerScene.objects.get_or_create(
            source=cand['source'], item_id=cand['item_id'],
            defaults={'layer': cand['layer'], 'observed_at': cand['observed_at'], 'window_start': window[0],
                      'window_end': window[1], 'gsd_m': cand['gsd_m'],
                      'footprint': GEOSGeometry(cand['geometry'].wkb.hex(), srid=4326),
                      'cloud_cover': cand['cloud_cover'], 'metadata': meta})
    scene.metadata = meta
    scene.sampled_through = max(scene.sampled_through, through)
    scene.n_samples = scene.n_samples + n_new
    scene.save(update_fields=['metadata', 'sampled_through', 'n_samples'])
    return scene


def watch(taxonomy='urban_v1', *, sources=('sentinel2', 'naip', 'lidar'), since=None, until=None,
          max_cloud=20.0, apply=False, limit=None, full=False, say=None):
    """Find scenes not yet sampled, and entities not yet sampled from known scenes, and sample them.

    A later run searches only the last ``LOOKBACK_DAYS`` before the newest known scene, unless
    entities have been added since (or ``full``): then the whole period is searched again and
    every known scene is read for the new entities. Without ``apply`` nothing is stored: the
    first scene of each source is read to show what a scene yields. Returns a report."""
    say = say or (lambda text: None)
    until = until or datetime.now(dt_timezone.utc)
    report = {'taxonomy': taxonomy, 'applied': bool(apply), 'sources': {}}
    entities = list(Entity.objects.filter(taxonomy=taxonomy, retired_at__isnull=True).only('id', 'geom', 'category'))
    report['n_entities'] = len(entities)
    areas = sites(taxonomy)
    report['n_sites'] = len(areas)
    if not entities or not areas:
        return report
    if since is None:
        first = Capture.objects.filter(taxonomy=taxonomy).aggregate(a=Min('imagery_start'), b=Min('captured_at'))
        since = first['a'] or first['b']
    shapes = Shapes.of(entities)
    category = [e.category for e in entities]
    through = int(shapes.ids.max())
    tokens = Tokens()

    for name in sources:
        cfg = SOURCES[name]
        source = cfg['source']
        t0 = time.perf_counter()
        known = {s.item_id: s for s in LayerScene.objects.filter(source=source)}
        newest = max((s.observed_at for s in known.values()), default=None)
        behind = any(s.sampled_through < through for s in known.values())
        start = since if full or behind or newest is None else max(since, newest - timedelta(days=LOOKBACK_DAYS))
        found = {}
        if name == 'lidar':
            found = {c['item_id']: c for c in lidar_candidates()}
        else:
            for bbox in areas:
                got = sentinel2_candidates(bbox, start, until, max_cloud) if name == 'sentinel2' \
                    else naip_candidates(bbox, start, until)
                found.update({c['item_id']: c for c in got})
        for item_id, cand in found.items():
            cand['scene'] = known.get(item_id)
        # known scenes the search did not return (older than its window, or cloudier than asked now)
        candidates = list(found.values()) + [_scene_candidate(s) for i, s in known.items()
                                             if i not in found and s.sampled_through < through and name != 'lidar']
        # an entity must lie inside the scene with room for its blurred footprint
        margin = (3 * cfg['sigma_m'] + 2 * cfg.get('pixel_m', 10.0)) / 111320.0
        plan = _plan(candidates, shapes, margin)
        work = [(c, idx) for c, idx in plan if len(idx)]
        idle = [c for c, idx in plan if not len(idx) and c.get('scene') is not None]
        if limit is not None:
            work = work[:limit]
        rep = {'scenes_known': len(known), 'scenes_found': len(found),
               'scenes_new': sum(1 for c, _ in work if c.get('scene') is None),
               'scenes_to_read': len(work), 'entities_to_sample': int(sum(len(idx) for _, idx in work)),
               'searched_from': start.date().isoformat() if name != 'lidar' else None,
               'samples': 0, 'scenes_read': 0, 'failed': 0}
        report['sources'][name] = rep
        say(f"{cfg['label']}: {rep['scenes_known']} scenes known, {rep['scenes_new']} new; "
            f"{rep['scenes_to_read']} to read for {rep['entities_to_sample']} entity samples")
        if apply:
            for cand in idle:   # nothing in it for the entities added since: note that it was considered
                if cand['scene'].sampled_through < through:
                    _save_scene(cand, through, 0, note=cand['scene'].metadata.get('note'))
        elif work:
            work = work[:1]
        footprints = {}
        reader = READERS[source]

        def fetch(job):
            cand, idx = job
            try:
                return job, reader(cand, shapes.bounds(idx), tokens), None
            except Exception as exc:   # network, a lapsed token, a damaged file: try again next run
                return job, None, f'{type(exc).__name__}: {str(exc)[:160]}'

        kept_by_category, purities = {}, []
        batch = 2 * cfg['workers']   # results are held in memory until stored
        with ThreadPoolExecutor(max_workers=cfg['workers']) as pool:
            for at in range(0, len(work), batch):
                for (cand, idx), patches, error in pool.map(fetch, work[at:at + batch]):
                    if error:
                        rep['failed'] += 1
                        say(f"  {cand['item_id']}: {error}")
                        if apply and cand.get('scene') is None:
                            _save_scene(cand, 0, 0, note=f'not read: {error}')
                        continue
                    rows = []
                    for grid, bands, valid in patches:
                        key = (grid.key, idx.tobytes())
                        if key not in footprints:
                            if len(footprints) >= 3:
                                footprints.clear()
                            projected = shapes.projected(grid.epsg)
                            footprints[key] = coverage([projected[i] for i in idx], grid, cfg['sigma_m'])
                        value, stats, clear, purity, n_px = values_of(source, footprints[key], bands, valid)
                        keep = np.isfinite(value) & (clear >= MIN_CLEAR) & (purity >= MIN_PURITY)
                        for j in np.nonzero(keep)[0]:
                            rows.append((int(idx[j]), float(value[j]), float(purity[j]), float(clear[j]),
                                         float(n_px[j]), [round(float(x), 5) for x in stats[j]]))
                    rep['scenes_read'] += 1
                    rep['samples'] += len(rows)
                    for row in rows:
                        kept_by_category[category[row[0]]] = kept_by_category.get(category[row[0]], 0) + 1
                    purities += [row[2] for row in rows]
                    if not apply:
                        continue
                    with transaction.atomic(using=DB):
                        scene = _save_scene(cand, through, 0)
                        LayerSample.objects.bulk_create(
                            [LayerSample(entity_id=int(shapes.ids[i]), scene=scene, value=v, purity=p, clear=c,
                                         n_pixels=n, bands=b) for i, v, p, c, n, b in rows],
                            ignore_conflicts=True, batch_size=2000)
                        scene.n_samples = LayerSample.objects.filter(scene=scene).count()
                        scene.save(update_fields=['n_samples'])
        rep['seconds'] = round(time.perf_counter() - t0, 1)
        rep['samples_by_category'] = dict(sorted(kept_by_category.items(), key=lambda kv: -kv[1]))
        if purities:
            q = np.percentile(purities, [10, 50, 90])
            rep['purity_p10_p50_p90'] = [round(float(x), 2) for x in q]
        say(f"  read {rep['scenes_read']} scenes, {rep['samples']} samples"
            f"{'' if apply else ' (first scene only, nothing stored)'}, {rep['failed']} failed, {rep['seconds']} s")
    _stats_cache.clear()
    return report


# ---- reading the record back --------------------------------------------------------------------

def entity_layers(entity, max_points=60):
    """What the layers recorded over one entity, one row per source.

    Each row has the number of samples, their span, the latest value, the value around the
    entity's imagery date (``at_last_seen``: the median within 30 days of ``last_seen``), the
    spread, the median purity and a series: one median per month when there are many samples,
    else every sample."""
    rows = list(LayerSample.objects.filter(entity=entity).select_related('scene').order_by('scene__observed_at'))
    groups = {}
    for r in rows:
        groups.setdefault((r.scene.source, r.scene.layer), []).append(r)
    out = []
    for (source, layer), samples in groups.items():
        # two scenes of one day (overlapping tiles) are one look: keep the one that saw more of it
        by_day = {}
        for r in samples:
            day = r.scene.observed_at.date()
            if day not in by_day or r.purity * r.clear > by_day[day].purity * by_day[day].clear:
                by_day[day] = r
        pts = [by_day[d] for d in sorted(by_day)]
        values = np.array([p.value for p in pts])
        last = pts[-1]
        near = [p.value for p in pts if abs((p.scene.observed_at - entity.last_seen).total_seconds()) <= 30 * 86400]
        cfg = BY_SOURCE.get(source, {})
        row = {
            'source': source, 'layer': layer, 'label': cfg.get('label', source), 'unit': UNITS.get(layer, ''),
            'gsd_m': last.scene.gsd_m, 'n': len(pts),
            'first': pts[0].scene.observed_at.isoformat(), 'last': last.scene.observed_at.isoformat(),
            'latest': {'at': last.scene.observed_at.isoformat(), 'value': round(last.value, 3)},
            'at_last_seen': {'value': round(float(np.median(near)), 3), 'n': len(near)} if near else None,
            'min': round(float(values.min()), 3), 'median': round(float(np.median(values)), 3),
            'max': round(float(values.max()), 3),
            'purity': round(float(np.median([p.purity for p in pts])), 2),
        }
        names = (last.scene.metadata or {}).get('bands') or []
        if layer == 'height' and 'p90' in names and len(last.bands) == len(names):
            row['latest']['p90'] = round(last.bands[names.index('p90')], 2)
        if last.scene.window_start and last.scene.window_end:
            row['window'] = [last.scene.window_start.isoformat(), last.scene.window_end.isoformat()]
        if source == 'naip':
            row['note'] = 'digital numbers, not reflectance: compare within one photograph, not across years'
        if len(pts) > max_points:
            months = {}
            for p in pts:
                months.setdefault(p.scene.observed_at.strftime('%Y-%m'), []).append(p.value)
            row['series'] = [[m, round(float(np.median(v)), 3), len(v)] for m, v in sorted(months.items())]
            row['series_step'] = 'month'
        else:
            row['series'] = [[p.scene.observed_at.date().isoformat(), round(p.value, 3), 1] for p in pts]
            row['series_step'] = 'sample'
        out.append(row)
    order = {cfg['source']: i for i, cfg in enumerate(SOURCES.values())}
    return sorted(out, key=lambda r: order.get(r['source'], 99))


_stats_cache = {}


def layer_stats(ttl=300):
    """Per source: scenes, their span, samples and entities sampled. Cached for a few minutes."""
    held = _stats_cache.get('stats')
    if held and time.time() - held[0] < ttl:
        return held[1]
    out = []
    for row in (LayerScene.objects.values('source', 'layer')
                .annotate(n_scenes=Count('id'), first=Min('observed_at'), last=Max('observed_at'),
                          n_samples=Sum('n_samples'), gsd=Min('gsd_m')).order_by('source')):
        cfg = BY_SOURCE.get(row['source'], {})
        out.append({
            'source': row['source'], 'layer': row['layer'], 'label': cfg.get('label', row['source']),
            'unit': UNITS.get(row['layer'], ''), 'gsd_m': row['gsd'], 'n_scenes': row['n_scenes'],
            'first': row['first'].isoformat(), 'last': row['last'].isoformat(), 'n_samples': row['n_samples'] or 0,
            'n_entities': LayerSample.objects.filter(scene__source=row['source']).values('entity_id').distinct().count(),
        })
    _stats_cache['stats'] = (time.time(), out)
    return out
