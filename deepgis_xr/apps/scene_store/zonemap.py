"""The fused map of a zone: the point assessment worked out for every cell of a grid, and
drawn with its legends as one page (PDF and PNG).

A zone is a named area (``Zone``: a city, a field site) whose map is kept drawn. The map is
``assess.assess_point`` on a grid instead of at one point: every live object is a patch on
the ground whose outline is trusted to ``SIGMA_M`` and which is there with ``p_exists``, the
patches are laid over each other smallest first, and each cell keeps

    object    1 - prod_i (1 - weight_i p_exists_i)      the chance a stored object accounts for it
    mix       sum_i share_i posterior_i                  the category distribution of that object
    label     the top category, or unknown when it holds less than ``LOW_CONFIDENCE`` of ``object``
    owner     the object with the largest share

Beliefs are as last seen: the map shows the ground at the date of the imagery, which the page
states. Around it the page shows where captures looked, how often and how finely, because a
cell with no object means two different things inside and outside that area.

Nothing here is evidence and nothing is written to the store. The files of a zone live under
``<OBSERVATIONS_ROOT>/maps/zones/<slug>/`` and are replaced whole when the store's content
for the zone (``fingerprint``) differs from the one the files were drawn from. Drawing is
done by the ``render_zone_maps`` command, never by a web request.
"""

import fcntl
import hashlib
import json
import logging
import math
import os
import textwrap
import time
from datetime import datetime, timedelta, timezone as dt_timezone

import numpy as np
import shapely
from django.conf import settings
from django.db import connections
from shapely.ops import transform as shapely_transform

from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import taxonomy_by_name

from . import fusion, layers, looks, priors
from .models import Capture, Entity, Feedback

log = logging.getLogger(__name__)

RENDER_VERSION = 1          # raise when the drawing changes, so every zone is drawn again
SITE = 'deepgis.org'
CELL_M = 2.0                # ground size of a cell; larger when a zone would need more than MAX_SIDE cells
MAX_SIDE = 4200
MARGIN_M = 150.0
SIGMA_M = priors.VIRTUAL_CAMERA_SIGMA_H_M   # where an outline drawn on the basemap sits on the ground
SHOW_MIN = 0.05             # cells less likely than this to hold an object are left as the backdrop
OWNED_MIN = 0.5             # a cell belongs to an object's outline from here
BACKDROP_SPAN_DAYS = 4 * 365
BACKDROP_MAX_SCENES = 12
BACKDROP_KEEP_DAYS = 180
RETRY_BACKDROP_S = 6 * 3600  # a map drawn without its photograph is drawn again after this long
PAGE_W, PAGE_H = 17.0, 11.0  # inches
PNG_DPI = 220
PREVIEW_PX = 1800
FILES = {'pdf': 'fused-map.pdf', 'png': 'fused-map.png', 'jpg': 'preview.jpg'}
SUMMARY = 'map.json'

# The colours of the search page's world-model layer (world-sampler-ui.js ``categoryColor``).
COLOURS = {
    'unknown': '#808080', 'building': '#3b82f6', 'house': '#a855f7', 'solar_panel': '#1e3a8a',
    'road': '#facc15', 'parking_lot': '#e5e7eb', 'pool': '#38bdf8', 'vehicle': '#ef4444',
    'tree': '#16a34a', 'vegetation_other': '#84cc16', 'pavement': '#a3a3a3', 'bare_ground': '#a16207',
    'water': '#06b6d4', 'debris': '#f97316',
}
NAMES = {'vegetation_other': 'other vegetation', 'parking_lot': 'parking lot', 'solar_panel': 'solar panel',
         'bare_ground': 'bare ground'}
VEIL = (233, 236, 241)      # laid over ground no capture has looked at
INK = '#1f2937'
SOFT = '#6b7280'

STATE_SQL = """
SELECT count(*), coalesce(md5(string_agg(
           e.id || ':' || e.category || ':' || round(e.score::numeric, 3) || ':' || round(e.p_exists::numeric, 3)
           || ':' || st_npoints(e.geom) || ':' || round(st_x(st_centroid(e.geom))::numeric, 6), ',' ORDER BY e.id)), '')
  FROM sg_entity e JOIN sg_zone z ON z.id = %s
 WHERE e.taxonomy = z.taxonomy AND e.retired_at IS NULL AND st_intersects(e.geom, z.area)
"""
CAPTURE_SQL = """
SELECT count(*), coalesce(md5(string_agg(
           c.id || ':' || c.imagery_source || ':' || coalesce(c.imagery_start::text, '') || ':'
           || coalesce(c.imagery_end::text, ''), ',' ORDER BY c.id)), '')
  FROM sg_capture c JOIN sg_zone z ON z.id = %s
 WHERE c.taxonomy = z.taxonomy AND st_intersects(c.footprint, z.area)
"""


# ---- where the files are, and whether they are current -------------------------------------------

def zone_root(zone):
    root = getattr(settings, 'OBSERVATIONS_ROOT', '') or ''
    return os.path.join(root, 'maps', 'zones', *zone.slug.split('/')) if root else ''


def file_path(zone, kind):
    root = zone_root(zone)
    return os.path.join(root, FILES[kind]) if root and kind in FILES else ''


def fingerprint(zone):
    """A short hash of everything the map of a zone is drawn from."""
    with connections[fusion.DB].cursor() as cur:
        cur.execute(STATE_SQL, [zone.id])
        ents = cur.fetchone()
        cur.execute(CAPTURE_SQL, [zone.id])
        caps = cur.fetchone()
    parts = [RENDER_VERSION, zone.slug, zone.name, zone.taxonomy, hashlib.md5(bytes(zone.area.wkb)).hexdigest(),
             *ents, *caps, Feedback.objects.filter(superseded_at__isnull=True).count()]
    return hashlib.sha1('|'.join(str(p) for p in parts).encode()).hexdigest()[:16]


def current(zone):
    """The summary written with the files now on disk, or None when the zone has no map yet."""
    root = zone_root(zone)
    try:
        with open(os.path.join(root, SUMMARY)) as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    return info if all(os.path.exists(os.path.join(root, name)) for name in FILES.values()) else None


def due(zone, with_backdrop=True):
    """Why the zone's map has to be drawn again, or '' when the files show the store as it is."""
    info = current(zone)
    if info is None:
        return 'no map yet'
    if info.get('state') != fingerprint(zone):
        return 'the store changed'
    if with_backdrop and not info.get('backdrop') and info.get('looked_at', {}).get('n_captures'):
        try:
            age = (datetime.now(dt_timezone.utc) - datetime.fromisoformat(info['rendered_at'])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = RETRY_BACKDROP_S
        if age >= RETRY_BACKDROP_S:
            return 'the photograph could not be read last time'
    return ''


# ---- the grid and what is fused onto it ----------------------------------------------------------

def utm_epsg(lon, lat):
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) % 60 + 1


def _project(geom, epsg):
    from pyproj import Transformer
    return shapely_transform(Transformer.from_crs(4326, epsg, always_xy=True).transform, geom)


def frame(zone, feet):
    """The map's grid: around the ground the zone's captures looked at, or the whole zone when none did."""
    from affine import Affine
    from pyproj import Transformer

    seen = shapely.union_all(feet) if feet else None
    w, s, e, n = (seen if seen is not None and not seen.is_empty else fusion._from_geos(zone.area)).bounds
    epsg = utm_epsg((w + e) / 2, (s + n) / 2)
    x0, y0, x1, y1 = Transformer.from_crs(4326, epsg, always_xy=True).transform_bounds(w, s, e, n, densify_pts=21)
    x0, y0, x1, y1 = x0 - MARGIN_M, y0 - MARGIN_M, x1 + MARGIN_M, y1 + MARGIN_M
    cell = float(max(CELL_M, math.ceil(max(x1 - x0, y1 - y0) / MAX_SIDE)))
    west, north = math.floor(x0 / cell) * cell, math.ceil(y1 / cell) * cell
    cols, rows = int(math.ceil((x1 - west) / cell)), int(math.ceil((north - y0) / cell))
    return layers.Grid(epsg, Affine(cell, 0, west, 0, -cell, north), (rows, cols))


def extent(grid):
    """(left, right, bottom, top) of the grid in its projection."""
    rows, cols = grid.shape
    t = grid.transform
    return t.c, t.c + cols * t.a, t.f + rows * t.e, t.f


class Fused:
    """Per-cell grids: ``obj``, ``label`` (-1 where nothing is stored), ``conf``, ``owner`` (-1 or a row of the entities)."""

    def __init__(self, shape):
        self.obj = np.zeros(shape, dtype=np.float32)
        self.label = np.full(shape, -1, dtype=np.int16)
        self.conf = np.zeros(shape, dtype=np.float32)
        self.owner = np.full(shape, -1, dtype=np.int32)


def fuse(ents, grid, tax, sigma_m=SIGMA_M):
    """``assess.assess_point`` for every cell: the objects composed smallest first."""
    out = Fused(grid.shape)
    ents = [e for e in ents if len(e.posterior) == tax.n]
    if not ents:
        return out
    weights = layers.coverage(layers.Shapes.of(ents).projected(grid.epsg), grid, sigma_m).weights
    touched = np.unique(weights.indices)
    if not len(touched):
        return out
    slot = np.full(grid.shape[0] * grid.shape[1], -1, dtype=np.int32)
    slot[touched] = np.arange(len(touched), dtype=np.int32)
    remaining = np.ones(len(touched), dtype=np.float32)
    mix = np.zeros((len(touched), tax.n), dtype=np.float32)
    best = np.zeros(len(touched), dtype=np.float32)
    owner = np.full(len(touched), -1, dtype=np.int32)
    post = np.asarray([e.posterior for e in ents], dtype=np.float32)
    order = sorted(range(len(ents)), key=lambda i: (ents[i].area_m2 if ents[i].area_m2 is not None else math.inf,
                                                    ents[i].id))
    for i in order:
        a, b = weights.indptr[i], weights.indptr[i + 1]
        if a == b:
            continue
        idx = slot[weights.indices[a:b]]
        share = remaining[idx] * (weights.data[a:b] * float(ents[i].p_exists)).astype(np.float32)
        remaining[idx] -= share
        mix[idx] += share[:, None] * post[i][None, :]
        lead = share > best[idx]
        best[idx[lead]] = share[lead]
        owner[idx[lead]] = i
    obj = 1.0 - remaining
    top = mix.argmax(axis=1)
    conf = np.divide(mix.max(axis=1), obj, out=np.zeros_like(obj), where=obj > 1e-6)
    if 'unknown' in tax.categories:
        top = np.where(conf < priors.LOW_CONFIDENCE, tax.index_of('unknown'), top)
    out.obj.ravel()[touched] = obj
    out.conf.ravel()[touched] = conf
    out.label.ravel()[touched] = np.where(obj >= SHOW_MIN, top, -1)
    out.owner.ravel()[touched] = np.where(obj >= OWNED_MIN, owner, -1)
    return out


def _window(geom, grid, pad=1):
    inv = ~grid.transform
    x0, y0, x1, y1 = geom.bounds
    ca, ra = inv * (x0, y1)
    cb, rb = inv * (x1, y0)
    c0, r0 = max(int(math.floor(min(ca, cb))) - pad, 0), max(int(math.floor(min(ra, rb))) - pad, 0)
    c1 = min(int(math.ceil(max(ca, cb))) + pad, grid.shape[1])
    r1 = min(int(math.ceil(max(ra, rb))) + pad, grid.shape[0])
    return (r0, r1, c0, c1) if r1 > r0 and c1 > c0 else None


def _burn(geom, grid):
    """(window, mask) of a projected shape on the grid, or (None, None) when it lies off it."""
    from affine import Affine
    from rasterio.features import rasterize

    win = _window(geom, grid)
    if win is None or geom.is_empty:
        return None, None
    r0, r1, c0, c1 = win
    mask = rasterize([(geom, 1)], out_shape=(r1 - r0, c1 - c0), transform=grid.transform * Affine.translation(c0, r0),
                     fill=0, dtype='uint8').astype(bool)
    return win, mask


def looked_at(feet, gsds, grid):
    """How many captures cover each cell, and the finest ground pixel among them (inf where none)."""
    count = np.zeros(grid.shape, dtype=np.uint16)
    finest = np.full(grid.shape, np.inf, dtype=np.float32)
    for geom, gsd in zip(feet, gsds):
        win, mask = _burn(geom, grid)
        if win is None:
            continue
        r0, r1, c0, c1 = win
        count[r0:r1, c0:c1] += mask
        if gsd:
            part = finest[r0:r1, c0:c1]
            part[mask] = np.minimum(part[mask], gsd)
    return count, finest


# ---- the photograph under the map ----------------------------------------------------------------

def _read_photo(cand, grid, bounds_ll, tokens):
    """One aerial photograph resampled onto the grid: (rgb uint8, valid)."""
    import rasterio
    from affine import Affine
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    rows, cols = grid.shape
    with rasterio.Env(**layers.GDAL_ENV):
        with rasterio.open(f"{cand['metadata']['assets']['image']}?{tokens.get('naip')}") as ds:
            win = layers._window(ds, bounds_ll, 30.0)
            if win is None or ds.count < 3:
                return None, None
            step = max(1, int(grid.pixel_m / abs(ds.res[0]) / 1.5))
            h, w = int(math.ceil(win.height / step)), int(math.ceil(win.width / step))
            data = ds.read([1, 2, 3], window=win, out_shape=(3, h, w), resampling=Resampling.average)
            src_transform = ds.window_transform(win) * Affine.scale(win.width / w, win.height / h)
            src_crs = ds.crs
    out = np.zeros((3, rows, cols), dtype=np.uint8)
    reproject(data, out, src_transform=src_transform, src_crs=src_crs, dst_transform=grid.transform,
              dst_crs=f'EPSG:{grid.epsg}', resampling=Resampling.bilinear, src_nodata=0, dst_nodata=0)
    return np.moveaxis(out, 0, -1), out.max(axis=0) > 0


def backdrop(grid, when, root, say=None):
    """A grey aerial photograph under the map, from the public NAIP photographs nearest in time to
    ``when``: (grey uint8 grid or None, {source, dates, items}). Kept on disk for the same grid."""
    from pyproj import Transformer

    say = say or (lambda text: None)
    key = hashlib.md5(repr((grid.key, when.date().isoformat())).encode()).hexdigest()[:12]
    path = os.path.join(root, f'backdrop-{key}.npz') if root else ''
    if path and os.path.exists(path) and time.time() - os.path.getmtime(path) < BACKDROP_KEEP_DAYS * 86400:
        try:
            with np.load(path, allow_pickle=False) as kept:
                return kept['grey'], json.loads(str(kept['info']))
        except Exception:
            log.warning('zone map: unreadable backdrop %s, reading the photographs again', path)
    left, right, bottom, top = extent(grid)
    bounds_ll = Transformer.from_crs(grid.epsg, 4326, always_xy=True).transform_bounds(left, bottom, right, top,
                                                                                         densify_pts=21)
    now = datetime.now(dt_timezone.utc)
    try:
        cands = layers.naip_candidates(list(bounds_ll), when - timedelta(days=BACKDROP_SPAN_DAYS),
                                       min(now, when + timedelta(days=BACKDROP_SPAN_DAYS)))
    except Exception as exc:
        log.warning('zone map: no photograph catalogue (%s)', exc)
        return None, None
    cands.sort(key=lambda c: (abs((c['observed_at'] - when).total_seconds()), c['item_id']))
    rgb = np.zeros((*grid.shape, 3), dtype=np.uint8)
    filled = np.zeros(grid.shape, dtype=bool)
    tokens, used = layers.Tokens(), []
    for cand in cands[:BACKDROP_MAX_SCENES]:
        if filled.mean() > 0.998:
            break
        try:
            part, valid = _read_photo(cand, grid, bounds_ll, tokens)
        except Exception as exc:
            log.warning('zone map: could not read %s (%s)', cand['item_id'], exc)
            continue
        if part is None:
            continue
        new = valid & ~filled
        if new.mean() < 0.002:
            continue
        rgb[new] = part[new]
        filled |= new
        used.append(cand)
        say(f"  photograph {cand['item_id']} of {cand['observed_at']:%Y-%m-%d}: {filled.mean():.0%} of the frame")
    if not used:
        return None, None
    grey = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.uint8)
    grey[~filled] = 0
    info = {'source': 'naip', 'label': 'USDA NAIP aerial photograph',
            'dates': sorted({c['observed_at'].date().isoformat() for c in used}),
            'items': [c['item_id'] for c in used], 'covered': round(float(filled.mean()), 3)}
    if path:
        os.makedirs(root, exist_ok=True)
        for old in os.listdir(root):
            if old.startswith('backdrop-') and old.endswith('.npz'):
                os.remove(os.path.join(root, old))
        np.savez_compressed(path, grey=grey, info=json.dumps(info))
    return grey, info


# ---- words and numbers ---------------------------------------------------------------------------

def _rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def _name(category):
    return NAMES.get(category, category.replace('_', ' '))


def _day(d):
    return f'{d.day} {d:%b %Y}'


def _span(a, b):
    """'1 Mar to 1 Sep 2023' for two dates."""
    if a.date() == b.date():
        return _day(a)
    return f"{a.day} {a:%b}{'' if a.year == b.year else f' {a.year}'} to {_day(b)}"


def _num(v, digits=1):
    """A number with thousands separators, and decimals only while it is small."""
    if v is None:
        return ''
    if abs(v) >= 100 or float(v).is_integer():
        return f'{v:,.0f}'
    return f'{v:,.{digits}f}'


def _imagery_words(imagery):
    """The images the captures showed, as words."""
    out = []
    for row in imagery:
        source = (row['source'] or '').replace('bing:', 'Bing ').strip() or 'undated imagery'
        if row['start'] and row['end']:
            a, b = fusion._parse_time(row['start'], None), fusion._parse_time(row['end'], None)
            out.append(f'{source}, {_span(a, b)}')
        else:
            out.append(source if row['source'] else 'imagery of unknown date')
    return out


def _nice(span, target=5):
    """A round step that splits ``span`` into about ``target`` parts."""
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)


# ---- drawing ------------------------------------------------------------------------------------

def _shrink(a, f):
    """Block mean of a grid by a whole factor."""
    if f <= 1:
        return a.astype(np.float32)
    r, c = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    return a[:r, :c].reshape(r // f, f, c // f, f).mean(axis=(1, 3), dtype=np.float32)


def _base(grey, shape):
    """The ground under the colours: the photograph washed out, or plain paper."""
    if grey is None:
        return np.full(shape, 247.0, dtype=np.float32)
    return np.where(grey > 0, 255.0 - (255.0 - grey.astype(np.float32)) * 0.62, 247.0).astype(np.float32)


def _veil(base, never):
    out = np.repeat(base[..., None], 3, axis=2)
    out[never] = out[never] * 0.3 + np.asarray(VEIL, dtype=np.float32) * 0.7
    return out


def compose(fused, count, grey, tax):
    """The main map as RGB: category colours by the chance of an object, over the photograph."""
    rgb = _veil(_base(grey, fused.obj.shape), count == 0)
    palette = np.asarray([_rgb(COLOURS.get(c, '#ffffff')) for c in tax.categories], dtype=np.float32)
    shown = fused.label >= 0
    alpha = np.clip(fused.obj[shown], 0.0, 1.0)[:, None] * 0.86
    rgb[shown] = rgb[shown] * (1 - alpha) + palette[fused.label[shown]] * alpha
    # the rim of each object, so that neighbours of one category stay apart
    own = fused.owner
    rim = np.zeros(own.shape, dtype=bool)
    d = own[:, 1:] != own[:, :-1]
    rim[:, 1:] |= d
    rim[:, :-1] |= d
    d = own[1:, :] != own[:-1, :]
    rim[1:, :] |= d
    rim[:-1, :] |= d
    rim &= own >= 0
    rgb[rim] *= 0.62
    return np.clip(rgb, 0, 255).astype(np.uint8)


def _few_colours(rgb):
    """The same picture in at most 256 colours: the PDF then stores one byte a cell."""
    from PIL import Image
    return np.asarray(Image.fromarray(rgb).quantize(256, dither=Image.Dither.NONE).convert('RGB'))


def _outline(ax, geom, **style):
    for part in getattr(geom, 'geoms', [geom]):
        if part.is_empty or part.geom_type != 'Polygon':
            continue
        for ring in (part.exterior, *part.interiors):
            ax.plot(*ring.xy, **style)


def _graticule(ax, grid):
    """Longitude and latitude ticks on the frame of a projected map."""
    from pyproj import Transformer
    to_ll = Transformer.from_crs(grid.epsg, 4326, always_xy=True)
    to_xy = Transformer.from_crs(4326, grid.epsg, always_xy=True)
    left, right, bottom, top = extent(grid)
    w, s = to_ll.transform(left, bottom)
    e, n = to_ll.transform(right, top)
    step = _nice(max(e - w, n - s), 4)
    digits = max(0, -int(math.floor(math.log10(step))))
    lons = np.arange(math.ceil(w / step) * step, e, step)
    lats = np.arange(math.ceil(s / step) * step, n, step)
    xs = [to_xy.transform(lon, s)[0] for lon in lons]
    ys = [to_xy.transform(w, lat)[1] for lat in lats]
    keep_x = [(x, lon) for x, lon in zip(xs, lons) if left < x < right]
    keep_y = [(y, lat) for y, lat in zip(ys, lats) if bottom < y < top]
    ax.set_xticks([x for x, _ in keep_x])
    ax.set_xticklabels([f"{abs(lon):.{digits}f}°{'W' if lon < 0 else 'E'}" for _, lon in keep_x])
    ax.set_yticks([y for y, _ in keep_y])
    ax.set_yticklabels([f"{abs(lat):.{digits}f}°{'S' if lat < 0 else 'N'}" for _, lat in keep_y], rotation=90, va='center')
    ax.tick_params(length=3, width=0.5, labelsize=7, colors=SOFT, pad=2)


def _scale_bar(ax, grid):
    left, right, bottom, top = extent(grid)
    length = _nice((right - left) * 0.22, 1)
    while length > (right - left) * 0.3:
        length /= 2
    x0, y0 = left + (right - left) * 0.035, bottom + (top - bottom) * 0.028
    h = (top - bottom) * 0.006
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((x0 - h * 2, y0 - h * 2), length + h * 4, h * 9, facecolor='white', edgecolor='none',
                           alpha=0.82, zorder=6))
    ax.add_patch(Rectangle((x0, y0), length / 2, h, facecolor=INK, edgecolor=INK, linewidth=0.4, zorder=7))
    ax.add_patch(Rectangle((x0 + length / 2, y0), length / 2, h, facecolor='white', edgecolor=INK, linewidth=0.4,
                           zorder=7))
    label = f'{length / 1000:g} km' if length >= 1000 else f'{length:g} m'
    ax.text(x0 + length / 2, y0 + h * 2.2, label, ha='center', va='bottom', fontsize=8, color=INK, zorder=7)


def _north(ax, grid):
    left, right, bottom, top = extent(grid)
    x, y = right - (right - left) * 0.045, top - (top - bottom) * 0.03
    ax.annotate('', xy=(x, y), xytext=(x, y - (top - bottom) * 0.05),
                arrowprops=dict(arrowstyle='-|>', color=INK, lw=1.2, mutation_scale=12), zorder=7)
    ax.text(x, y - (top - bottom) * 0.056, 'N', ha='center', va='top', fontsize=9, fontweight='bold', color=INK,
            zorder=7, bbox=dict(facecolor='white', edgecolor='none', alpha=0.8, pad=1.2))


def draw(zone, grid, fused, count, finest, grey, shapes, summary, paths):
    """The page: the fused map, its legend, what it rests on, and three maps of the evidence."""
    from matplotlib import colormaps
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    from PIL import Image

    tax = taxonomy_by_name(zone.taxonomy)
    rows, cols = grid.shape
    ext = extent(grid)
    fig = Figure(figsize=(PAGE_W, PAGE_H), facecolor='white')
    FigureCanvasAgg(fig)

    def box(x, y, w, h):
        return fig.add_axes([x / PAGE_W, y / PAGE_H, w / PAGE_W, h / PAGE_H])

    page = box(0, 0, PAGE_W, PAGE_H)
    page.set_xlim(0, PAGE_W)
    page.set_ylim(0, PAGE_H)
    page.axis('off')

    def frame_of(ax):
        ax.set_xlim(ext[0], ext[1])
        ax.set_ylim(ext[2], ext[3])
        ax.set_aspect('auto')
        for side in ax.spines.values():
            side.set_linewidth(0.6)
            side.set_color(INK)

    # -- the fused map
    top_y, bottom_y, left_x = 9.72, 0.78, 0.55
    map_h = top_y - bottom_y
    map_w = map_h * cols / rows
    if map_w > 7.7:
        map_w, map_h = 7.7, 7.7 * rows / cols
    ax = box(left_x, top_y - map_h, map_w, map_h)
    picture = ax.imshow(_few_colours(compose(fused, count, grey, tax)), extent=ext, interpolation='antialiased',
                        zorder=1)
    _outline(ax, shapes['seen'], color=INK, linewidth=0.45, alpha=0.75, zorder=3)
    _outline(ax, shapes['zone'], color='#b91c1c', linewidth=0.9, linestyle=(0, (5, 3)), zorder=4)
    frame_of(ax)
    _graticule(ax, grid)
    _scale_bar(ax, grid)
    _north(ax, grid)

    # -- title
    page.text(left_x, 10.56, f'World model: {zone.name}', fontsize=21, fontweight='bold', color=INK, va='center')
    page.text(left_x, 10.16, summary['headline'], fontsize=10.5, color=SOFT, va='center')

    # -- legend
    lx = left_x + map_w + 0.55
    page.text(lx, top_y - 0.02, 'What is on the ground', fontsize=12, fontweight='bold', color=INK, va='top')
    heads = (('objects', 2.55), ('hectares', 3.35), ('sure of label', 4.3))
    y = top_y - 0.42
    for text, dx in heads:
        page.text(lx + dx, y, text, fontsize=8, color=SOFT, ha='right', va='center')
    y -= 0.07
    page.plot([lx, lx + 4.3], [y - 0.06, y - 0.06], color='#d1d5db', linewidth=0.6)
    for row in summary['objects']['by_category']:
        y -= 0.215
        page.add_patch(Rectangle((lx, y - 0.075), 0.3, 0.15, facecolor=row['colour'], edgecolor=INK, linewidth=0.4))
        page.text(lx + 0.42, y, _name(row['category']), fontsize=9.5, color=INK, va='center')
        page.text(lx + 2.55, y, _num(row['n']), fontsize=9.5, color=INK, ha='right', va='center')
        page.text(lx + 3.35, y, _num(row['area_ha']) if row['area_ha'] >= 0.05 or not row['area_ha'] else '<0.1',
                  fontsize=9.5, color=INK, ha='right', va='center')
        page.text(lx + 4.3, y, f"{row['confidence']:.0%}" if row['confidence'] is not None else '', fontsize=9.5,
                  color=INK, ha='right', va='center')
    y -= 0.13
    page.plot([lx, lx + 4.3], [y, y], color='#d1d5db', linewidth=0.6)
    ground = summary['ground']
    paper = '#%02x%02x%02x' % ((205, 205, 205) if grey is not None else (247, 247, 247))
    for colour, text, ha in ((paper, 'viewed, no object stored', ground['no_object_ha']),
                             ('#%02x%02x%02x' % VEIL, 'never viewed (in this frame)', ground['never_viewed_ha'])):
        y -= 0.235
        page.add_patch(Rectangle((lx, y - 0.075), 0.3, 0.15, facecolor=colour, edgecolor=INK, linewidth=0.4))
        page.text(lx + 0.42, y, text, fontsize=9.5, color=INK, va='center')
        page.text(lx + 3.35, y, _num(ha), fontsize=9.5, color=INK, ha='right', va='center')
    y -= 0.3
    page.plot([lx, lx + 0.3], [y, y], color=INK, linewidth=0.6, alpha=0.75)
    page.text(lx + 0.42, y, 'edge of the viewed ground', fontsize=9.5, color=INK, va='center')
    y -= 0.235
    page.plot([lx, lx + 0.3], [y, y], color='#b91c1c', linewidth=0.9, linestyle=(0, (5, 3)))
    page.text(lx + 0.42, y, f'{zone.name} limit', fontsize=9.5, color=INK, va='center')
    legend_bottom = y - 0.2

    # -- what it rests on, and how to read it
    fx = lx + 4.75
    fw = PAGE_W - 0.5 - fx
    page.text(fx, top_y - 0.02, 'What this rests on', fontsize=12, fontweight='bold', color=INK, va='top')
    y = top_y - 0.36
    width = max(34, int(fw * 13.2))
    for line in summary['facts']:
        for k, part in enumerate(textwrap.wrap(line, width)):
            page.text(fx + (0.0 if k == 0 else 0.12), y, part, fontsize=9, color=INK, va='top')
            y -= 0.185
        y -= 0.06
    y -= 0.1
    page.text(fx, y, 'How to read it', fontsize=12, fontweight='bold', color=INK, va='top')
    y -= 0.34
    for para in summary['reading']:
        for part in textwrap.wrap(para, width):
            page.text(fx, y, part, fontsize=9, color=INK, va='top')
            y -= 0.185
        y -= 0.07
    text_bottom = y

    # -- three maps of the evidence, and where the frame is in the zone
    f = max(1, int(math.ceil(max(rows, cols) / 900)))
    small_obj = _shrink(fused.obj, f)
    seen_small = _shrink((count > 0).astype(np.float32), f) > 0.5
    base_small = np.where(seen_small[..., None], 226.0, np.asarray(VEIL, dtype=np.float32)[None, None, :])

    def paint(values, where, cmap):
        out = base_small.copy()
        out[where] = np.asarray(colormaps[cmap](np.clip(values[where], 0, 1)))[:, :3] * 255
        return out.astype(np.uint8)

    with np.errstate(divide='ignore', invalid='ignore'):
        sure = np.where(small_obj > 0.25, _shrink(fused.conf * fused.obj, f) / small_obj, 0.0)
        times = _shrink(count.astype(np.float32), f)
        most = max(int(count.max()), 1)
        known = np.isfinite(finest)
        fine, coarse = (float(finest[known].min()), float(finest[known].max())) if known.any() else (1.0, 1.0)
        lo, hi = math.log10(max(fine, 1e-3)) - 0.03, math.log10(max(coarse, fine)) + 0.03
        share_known = _shrink(known.astype(np.float32), f)
        small_fine = np.where(share_known > 0, _shrink(np.where(known, np.log10(np.maximum(finest, 1e-3)), 0.0), f)
                              / share_known, lo)
    gsd_ticks = []
    for v in (10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02):
        if lo <= math.log10(v) <= hi and (not gsd_ticks or math.log10(gsd_ticks[-1] / v) >= 0.24 * (hi - lo)):
            gsd_ticks.append(v)
    gsd_ticks = gsd_ticks or [fine]
    panels = [
        ('How sure the label is', 'chance that the category shown is right',
         paint(sure, small_obj > 0.25, 'viridis'), 'viridis',
         [(0, '0'), (0.25, '25%'), (0.5, '50%'), (0.75, '75%'), (1, '100%')]),
        ('How often it was viewed', 'number of captures covering the ground',
         paint(times / most, seen_small, 'YlGnBu'), 'YlGnBu',
         [(k / most, str(k)) for k in sorted({1, max(1, most // 2), most})]),
        ('How fine the best view was', 'ground size of a pixel in the most detailed capture',
         paint(1 - (small_fine - lo) / (hi - lo), seen_small, 'magma'), 'magma',
         [(1 - (math.log10(v) - lo) / (hi - lo), f'{v:.2g} m') for v in gsd_ticks]),
    ]
    right_x = PAGE_W - 0.5
    gap, loc_w = 0.32, 1.55
    pw = (right_x - lx - loc_w - 3 * gap) / 3
    iy = bottom_y + 0.55
    ph = min(min(legend_bottom, text_bottom) - 0.25 - 0.6 - iy, pw * rows / cols)
    pw_img = ph * cols / rows
    pictures = [picture]
    for k, (title, sub, img, cmap, ticks) in enumerate(panels):
        x = lx + k * (pw + gap)
        page.text(x, iy + ph + 0.43, title, fontsize=10.5, fontweight='bold', color=INK, va='center')
        page.text(x, iy + ph + 0.17, '\n'.join(textwrap.wrap(sub, max(24, int(pw * 15)))[:2]), fontsize=7.5,
                  color=SOFT, va='center', linespacing=1.25)
        pax = box(x, iy, pw_img, ph)
        pictures.append(pax.imshow(img, extent=ext, interpolation='antialiased'))
        _outline(pax, shapes['zone'], color='#b91c1c', linewidth=0.6, linestyle=(0, (5, 3)))
        frame_of(pax)
        pax.set_xticks([])
        pax.set_yticks([])
        bar = box(x, iy - 0.2, min(pw_img, 2.2), 0.09)
        bar.imshow(np.linspace(0, 1, 256)[None, :], aspect='auto', cmap=cmap, extent=(0, 1, 0, 1))
        bar.set_yticks([])
        bar.set_xticks([t for t, _ in ticks])
        bar.set_xticklabels([s for _, s in ticks])
        bar.tick_params(length=2, width=0.4, labelsize=7, colors=SOFT, pad=1.5)
        for side in bar.spines.values():
            side.set_linewidth(0.4)
            side.set_color(SOFT)

    zb = shapes['zone'].bounds
    zw, zh = zb[2] - zb[0], zb[3] - zb[1]
    loc_x = right_x - loc_w
    loc_h = min(loc_w * zh / zw, ph * 0.72)
    page.text(loc_x, iy + ph + 0.43, 'Where this is', fontsize=10.5, fontweight='bold', color=INK, va='center')
    lax = box(loc_x, iy + ph - loc_h, loc_w, loc_h)
    pad = max(zw, zh) * 0.04
    for part in getattr(shapes['seen'], 'geoms', [shapes['seen']]):
        if not part.is_empty and part.geom_type == 'Polygon':
            lax.fill(*part.exterior.xy, facecolor='#93c5fd', edgecolor='none')
    _outline(lax, shapes['zone'], color='#b91c1c', linewidth=0.8)
    lax.add_patch(Rectangle((ext[0], ext[2]), ext[1] - ext[0], ext[3] - ext[2], fill=False, edgecolor=INK,
                            linewidth=0.9))
    lax.set_xlim(min(zb[0], ext[0]) - pad, max(zb[2], ext[1]) + pad)
    lax.set_ylim(min(zb[1], ext[2]) - pad, max(zb[3], ext[3]) + pad)
    lax.set_aspect('equal', adjustable='datalim')
    lax.axis('off')
    page.text(loc_x, iy + ph - loc_h - 0.12,
              '\n'.join(textwrap.wrap(f"The frame of this map (black) in {zone.name} (red). Blue is the ground "
                                      f"captures have viewed: {ground['viewed_share_of_zone']:.0%} of the zone.", 27)),
              fontsize=8, color=SOFT, va='top', linespacing=1.35)

    page.text(left_x, 0.3, summary['footer'], fontsize=7.5, color=SOFT, va='center')

    fig.savefig(paths['png'], dpi=PNG_DPI, format='png')
    for shown in pictures:
        shown.set_interpolation('none')   # the PDF keeps every cell
    fig.savefig(paths['pdf'], format='pdf', metadata={
        'Title': f'DeepGIS world model: {zone.name}', 'Author': 'DeepGIS', 'Creator': f'{SITE} scene store',
        'Subject': summary['headline']})
    with Image.open(paths['png']) as im:
        im = im.convert('RGB')
        im.thumbnail((PREVIEW_PX, PREVIEW_PX))
        im.save(paths['jpg'], format='JPEG', quality=86, optimize=True)


# ---- one zone ------------------------------------------------------------------------------------

def render(zone, *, with_backdrop=True, say=None):
    """Draw the zone's map from the store as it is now and replace the files. Returns the summary,
    or None when another process is already drawing this zone."""
    say = say or (lambda text: None)
    root = zone_root(zone)
    if not root:
        raise RuntimeError('OBSERVATIONS_ROOT is not set: there is nowhere to keep the maps')
    os.makedirs(root, exist_ok=True)
    t0 = time.perf_counter()
    with open(os.path.join(root, '.lock'), 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        state = fingerprint(zone)
        tax = taxonomy_by_name(zone.taxonomy)
        ents = list(Entity.objects.filter(taxonomy=zone.taxonomy, retired_at__isnull=True, geom__intersects=zone.area)
                    .only('id', 'category', 'posterior', 'score', 'p_exists', 'geom', 'area_m2'))
        caps = list(Capture.objects.filter(taxonomy=zone.taxonomy, footprint__intersects=zone.area)
                    .only('id', 'footprint', 'gsd_m', 'captured_at', 'observed_at', 'imagery_source',
                          'imagery_start', 'imagery_end'))
        feet_ll = [fusion._from_geos(c.footprint) for c in caps]
        grid = frame(zone, feet_ll)
        cell = grid.pixel_m
        say(f'{zone.slug}: {len(ents)} objects, {len(caps)} captures, {grid.shape[1]} x {grid.shape[0]} cells of {cell:g} m')

        fused = fuse(ents, grid, tax)
        feet = [_project(g, grid.epsg) for g in feet_ll]
        count, finest = looked_at(feet, [c.gsd_m for c in caps], grid)
        zone_shape = _project(fusion._from_geos(zone.area), grid.epsg)
        seen = shapely.union_all(feet) if feet else shapely.Polygon()
        say(f'  fused in {time.perf_counter() - t0:.1f} s')

        grey, photo = None, None
        if with_backdrop:
            times = sorted(c.world_time for c in caps)
            when = times[len(times) // 2] if times else datetime.now(dt_timezone.utc)
            grey, photo = backdrop(grid, when, root, say)

        # numbers
        ha = cell * cell / 1e4
        by_cat = {}
        for e in ents:
            by_cat[e.category] = by_cat.get(e.category, 0) + 1
        rows_out = []
        for k, name in enumerate(tax.categories):
            cells = fused.label == k
            area = float(fused.obj[cells].sum()) * ha
            if not by_cat.get(name) and area < 0.005:
                continue
            weight = float(fused.obj[cells].sum())
            rows_out.append({
                'category': name, 'colour': COLOURS.get(name, '#ffffff'), 'n': by_cat.get(name, 0),
                'area_ha': round(area, 2),
                'confidence': round(float((fused.conf[cells] * fused.obj[cells]).sum()) / weight, 3) if weight else None,
            })
        rows_out.sort(key=lambda r: (r['category'] == 'unknown', -r['area_ha']))
        viewed = count > 0
        object_ha = float(fused.obj.sum()) * ha
        viewed_ha = float(viewed.sum()) * ha
        zone_km2 = zone_shape.area / 1e6
        seen_in_zone_km2 = seen.intersection(zone_shape).area / 1e6 if not seen.is_empty else 0.0
        imagery = fusion.imagery_dates(Capture.objects.filter(id__in=[c.id for c in caps]))
        n_looks = len({looks.key_of(c.id, c.imagery_source, c.imagery_start, c.imagery_end) for c in caps})
        gsds = [c.gsd_m for c in caps if c.gsd_m]
        views = sorted(c.captured_at for c in caps)
        n_fix = Feedback.objects.filter(superseded_at__isnull=True, entity_id__in=[e.id for e in ents]).count()
        gone = sum(1 for e in ents if e.p_exists < 0.5)
        now = datetime.now(dt_timezone.utc)

        words = _imagery_words(imagery)
        if not caps:
            headline = 'No capture has looked at this zone yet.'
        elif len(words) == 1:
            headline = f'The ground as {words[0]}, showed it. Fused from {len(ents):,} objects; drawn {_day(now)}.'
        else:
            headline = f'The ground as {len(words)} images showed it. Fused from {len(ents):,} objects; drawn {_day(now)}.'
        facts = [f'{len(ents):,} objects, found in {len(caps)} capture{"s" if len(caps) != 1 else ""} '
                 f'of the basemap' + (f', taken {_span(views[0], views[-1])}.' if views else '.')]
        if caps:
            facts.append((f'Every capture shows the same image ({words[0]}): one look, however often it was captured.'
                          if n_looks == 1 and len(words) == 1 else
                          f'The captures show {n_looks} different images: ' + '; '.join(words[:4]) + '.'))
            facts.append(f'{seen_in_zone_km2:,.1f} km² viewed, {seen_in_zone_km2 / zone_km2:.0%} of the zone\'s '
                         f'{zone_km2:,.0f} km².' + (f' Finest view {min(gsds):.2g} m a pixel, coarsest {max(gsds):.2g} m.'
                                                    if gsds else ''))
        facts.append(f'{n_fix} correction{"s" if n_fix != 1 else ""} by people. {gone} object{"s" if gone != 1 else ""} '
                     f'believed gone.')
        if photo:
            facts.append(f"Photograph underneath: {photo['label']}, "
                         f"{' and '.join(_day(fusion._parse_time(d, None)) for d in photo['dates'][:3])}. "
                         f"It is not what the objects were found on.")
        reading = [
            f'Each {cell:g} m cell takes the colour of the category most likely there. An object reaches a cell by '
            f'how much of the cell lies inside its outline (placed to within {SIGMA_M:g} m) times the chance that '
            f'it exists; small objects lie over large ones.',
            'Stronger colour: likelier that a stored object accounts for the cell. A dark rim separates objects. '
            'Beliefs are as last seen, at the date of the imagery, not today.',
            f'The same answer for one point: {SITE}/webclient/sampler/world/assess?lon=&lat=',
        ]
        left, right, bottom, top = extent(grid)
        from pyproj import Transformer
        bounds_ll = Transformer.from_crs(grid.epsg, 4326, always_xy=True).transform_bounds(left, bottom, right, top,
                                                                                             densify_pts=21)
        summary = {
            'zone': {'slug': zone.slug, 'name': zone.name, 'taxonomy': zone.taxonomy, 'area_km2': round(zone_km2, 2),
                     'outline': zone.source},
            'state': state, 'rendered_at': now.isoformat(timespec='seconds'), 'beliefs': 'as last seen',
            'headline': headline,
            'grid': {'epsg': grid.epsg, 'cell_m': cell, 'rows': grid.shape[0], 'cols': grid.shape[1],
                     'bounds_lonlat': [round(v, 6) for v in bounds_ll]},
            'sigma_m': SIGMA_M,
            'objects': {'n': len(ents), 'believed_gone': gone, 'by_category': rows_out},
            'ground': {'frame_ha': round(grid.shape[0] * grid.shape[1] * ha, 1), 'viewed_ha': round(viewed_ha, 1),
                       'object_ha': round(object_ha, 1),
                       'no_object_ha': round(max(viewed_ha - float(fused.obj[viewed].sum()) * ha, 0.0), 1),
                       'never_viewed_ha': round(float((~viewed).sum()) * ha, 1),
                       'viewed_km2_in_zone': round(seen_in_zone_km2, 3),
                       'viewed_share_of_zone': round(seen_in_zone_km2 / zone_km2, 4) if zone_km2 else 0.0},
            'looked_at': {'n_captures': len(caps), 'n_looks': n_looks, 'imagery': imagery,
                          'finest_gsd_m': round(min(gsds), 3) if gsds else None,
                          'coarsest_gsd_m': round(max(gsds), 3) if gsds else None,
                          'first_viewed': views[0].isoformat() if views else None,
                          'last_viewed': views[-1].isoformat() if views else None},
            'n_corrections': n_fix,
            'backdrop': photo,
            'facts': facts, 'reading': reading,
            'footer': (f'{SITE}/world-model/zones/{zone.slug}   ·   drawn {_day(now)} {now:%H:%M} UTC   ·   '
                       f'state {state}   ·   UTM zone {grid.epsg % 100}{"N" if grid.epsg < 32700 else "S"}, '
                       f'{cell:g} m cells   ·   objects: SAM 3 and other models on basemap captures, fused in the '
                       f'DeepGIS scene store'),
        }
        paths = {kind: os.path.join(root, f'.{name}.tmp') for kind, name in FILES.items()}
        t1 = time.perf_counter()
        draw(zone, grid, fused, count, finest, grey, {'zone': zone_shape, 'seen': seen}, summary, paths)
        summary['files'] = {kind: os.path.getsize(path) for kind, path in paths.items()}
        summary['seconds'] = round(time.perf_counter() - t0, 1)
        for kind, path in paths.items():
            os.replace(path, os.path.join(root, FILES[kind]))
        tmp = os.path.join(root, f'.{SUMMARY}.tmp')
        with open(tmp, 'w') as fh:
            json.dump(summary, fh, indent=1)
        os.replace(tmp, os.path.join(root, SUMMARY))
        say(f'  drawn in {time.perf_counter() - t1:.1f} s; {summary["seconds"]} s in all')
        return summary
