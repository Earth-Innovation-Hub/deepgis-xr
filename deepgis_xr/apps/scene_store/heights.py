"""Lidar height above ground at points, from the prepared 3DEP tiles.

The tiles are the ones the layer watcher samples entities from (``layers.read_lidar``): 1 m
rasters of height above ground under ``<layer_root>/usgs_3dep/<project>/hag_*.tif``. They
hold the top surface only: under a canopy or a patio cover the value is the cover's height,
whatever stands or lies beneath it.
"""

import glob
import os
import threading
from collections import OrderedDict

import numpy as np

from . import layers

KEEP_TILES = 6
_lock = threading.Lock()
_index = None
_arrays = OrderedDict()


def reset():
    """Forget the tile list and the cached tiles (after new tiles are prepared)."""
    global _index
    with _lock:
        _index = None
        _arrays.clear()


def _tiles():
    global _index
    with _lock:
        if _index is None:
            import rasterio

            found = []
            root = layers.layer_root()
            for path in sorted(glob.glob(os.path.join(root, 'usgs_3dep', '*', 'hag_*.tif'))) if root else []:
                try:
                    with rasterio.open(path) as ds:
                        found.append((path, ds.crs.to_string(), tuple(ds.bounds), ~ds.transform, ds.nodata))
                except Exception:  # an unreadable tile is no height, not an error for the reading
                    continue
            _index = found
        return _index


def _array(path):
    with _lock:
        if path in _arrays:
            _arrays.move_to_end(path)
            return _arrays[path]
    import rasterio

    with rasterio.open(path) as ds:
        a = ds.read(1)
    with _lock:
        _arrays[path] = a
        while len(_arrays) > KEEP_TILES:
            _arrays.popitem(last=False)
    return a


def sample(lons, lats):
    """Height above ground (m) at each lon/lat, NaN where no tile has a value."""
    lons, lats = np.atleast_1d(np.asarray(lons, dtype=float)), np.atleast_1d(np.asarray(lats, dtype=float))
    out = np.full(lons.shape, np.nan)
    tiles = _tiles()
    if not tiles:
        return out
    from rasterio.warp import transform

    for crs in {t[1] for t in tiles}:
        xs, ys = transform('EPSG:4326', crs, lons.tolist(), lats.tolist())
        xs, ys = np.asarray(xs), np.asarray(ys)
        for path, tile_crs, (left, bottom, right, top), inverse, nodata in tiles:
            if tile_crs != crs:
                continue
            inside = np.isnan(out) & (xs >= left) & (xs < right) & (ys > bottom) & (ys <= top)
            if not inside.any():
                continue
            a = _array(path)
            cols, rows = inverse * (xs[inside], ys[inside])
            rows = np.clip(np.floor(rows).astype(int), 0, a.shape[0] - 1)
            cols = np.clip(np.floor(cols).astype(int), 0, a.shape[1] - 1)
            values = a[rows, cols].astype(float)
            if nodata is not None:
                values[values == nodata] = np.nan
            out[inside] = values
    return out
