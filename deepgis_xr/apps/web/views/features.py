"""
Feature lookup in the vector MBTiles that tileserver-gl serves (data/config.json).

The globe shows vector layers as tiles rendered by tileserver-gl styles
(/styles/<id>_styled/...), so the browser has no geometry to click. This view
reads the vector tile under a point straight from the .mbtiles file, decodes it
(Mapbox Vector Tile 2.1) and returns the polygon there: its attributes plus area
and axis lengths in metres, measured from the geometry itself because the
attribute units are not documented (rockPoly_all_v0 sizes are in source pixels).
"""

import gzip
import json
import math
import os
import sqlite3
import struct

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

DATA_DIR = os.path.join(settings.BASE_DIR, "data")
EARTH_CIRCUMFERENCE_M = 40075016.686
# A click this close to a polygon still picks it (thin outlines, a shaky hand)
NEAR_M = 1.0
CACHE_SEC = 3600


# ---- Mapbox Vector Tile decoding (protobuf wire format, no dependencies) ----

def _varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _fields(buf):
    """(field number, wire type, value) for each field of one protobuf message."""
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _varint(buf, i)
        elif wire == 1:
            val, i = buf[i:i + 8], i + 8
        elif wire == 2:
            ln, i = _varint(buf, i)
            val, i = buf[i:i + ln], i + ln
        elif wire == 5:
            val, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield field, wire, val


def _packed(buf):
    out, i = [], 0
    while i < len(buf):
        v, i = _varint(buf, i)
        out.append(v)
    return out


def _zigzag(v):
    return (v >> 1) ^ -(v & 1)


def _value(buf):
    for field, _, val in _fields(buf):
        if field == 1:
            return val.decode("utf-8", "replace")
        if field == 2:
            return struct.unpack("<f", val)[0]
        if field == 3:
            return struct.unpack("<d", val)[0]
        if field in (4, 5):
            return val if field == 5 or val < 1 << 63 else val - (1 << 64)
        if field == 6:
            return _zigzag(val)
        if field == 7:
            return bool(val)
    return None


def _rings(geometry):
    """Rings of a polygon feature, in tile units."""
    rings, ring, x, y, i = [], [], 0, 0, 0
    while i < len(geometry):
        cmd, count = geometry[i] & 7, geometry[i] >> 3
        i += 1
        if cmd == 7:
            if len(ring) >= 3:
                rings.append(ring)
            ring = []
            continue
        for _ in range(count):
            x += _zigzag(geometry[i])
            y += _zigzag(geometry[i + 1])
            i += 2
            if cmd == 1:
                if len(ring) >= 3:
                    rings.append(ring)
                ring = [(x, y)]
            else:
                ring.append((x, y))
    if len(ring) >= 3:
        rings.append(ring)
    return rings


def _shape(rings):
    """Polygons from MVT rings: a ring with positive signed area (in tile space, y down)
    starts a polygon, a negative one is a hole in the current polygon."""
    polys, outer, holes = [], None, []

    def area(r):
        return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1])) / 2

    for r in rings:
        if area(r) > 0 or outer is None:
            if outer:
                polys.append(Polygon(outer, holes))
            outer, holes = r, []
        else:
            holes.append(r)
    if outer:
        polys.append(Polygon(outer, holes))
    geom = unary_union([p if p.is_valid else p.buffer(0) for p in polys])
    return geom


def decode_tile(data):
    """[{layer, extent, attributes, geometry}] for the polygon features of one tile."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    out = []
    for field, _, layer in _fields(data):
        if field != 3:
            continue
        name, extent, keys, values, feats = "", 4096, [], [], []
        for f, _, v in _fields(layer):
            if f == 1:
                name = v.decode("utf-8", "replace")
            elif f == 2:
                feats.append(v)
            elif f == 3:
                keys.append(v.decode("utf-8", "replace"))
            elif f == 4:
                values.append(_value(v))
            elif f == 5:
                extent = v
        for feat in feats:
            tags, gtype, geometry = [], 0, []
            for f, _, v in _fields(feat):
                if f == 2:
                    tags = _packed(v)
                elif f == 3:
                    gtype = v
                elif f == 4:
                    geometry = _packed(v)
            if gtype != 3:
                continue
            attrs = {keys[tags[k]]: values[tags[k + 1]] for k in range(0, len(tags) - 1, 2)
                     if tags[k] < len(keys) and tags[k + 1] < len(values)}
            out.append({"layer": name, "extent": extent, "attributes": attrs, "rings": _rings(geometry)})
    return out


# ---- the served layers ----

def vector_layers():
    """{id: (path, maxzoom)} for the pbf layers in tileserver-gl's config.json."""
    cfg_path = os.path.join(DATA_DIR, "config.json")
    key = f"vector-layers:{os.path.getmtime(cfg_path)}"
    found = cache.get(key)
    if found is not None:
        return found
    with open(cfg_path) as fh:
        cfg = json.load(fh)
    found = {}
    for lid, entry in (cfg.get("data") or {}).items():
        path = os.path.join(DATA_DIR, os.path.basename(str(entry.get("mbtiles", ""))))
        if not path.endswith(".mbtiles") or not os.path.isfile(path):
            continue
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                md = dict(db.execute("SELECT name, value FROM metadata"))
        except sqlite3.Error:
            continue
        if md.get("format") == "pbf":
            found[lid] = (path, int(md.get("maxzoom") or 14))
    cache.set(key, found, CACHE_SEC)
    return found


def feature_at(layer_id, lon, lat):
    path, z = vector_layers()[layer_id]
    n = 2 ** z
    fx = (lon + 180) / 360 * n
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    tx, ty = int(fx), int(fy)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        row = None
        # MBTiles rows are TMS (y up); fall back to XYZ for files written the other way
        for tile_row in (n - 1 - ty, ty):
            row = db.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                             (z, tx, tile_row)).fetchone()
            if row:
                break
    if not row:
        return None, 0
    feats = decode_tile(bytes(row[0]))
    if not feats:
        return None, 0
    extent = feats[0]["extent"]
    m_per_unit = EARTH_CIRCUMFERENCE_M * math.cos(math.radians(lat)) / n / extent
    px, py = (fx - tx) * extent, (fy - ty) * extent
    pt, pad = Point(px, py), NEAR_M / m_per_unit
    best = None
    for f in feats:
        xs = [x for r in f["rings"] for x, _ in r]
        ys = [y for r in f["rings"] for _, y in r]
        if not (min(xs) - pad <= px <= max(xs) + pad and min(ys) - pad <= py <= max(ys) + pad):
            continue
        geom = _shape(f["rings"])
        if geom.is_empty:
            continue
        d = geom.distance(pt) * m_per_unit
        if d <= NEAR_M and (best is None or d < best[0] or (d == best[0] and geom.area < best[1].area)):
            best = (d, geom, f)
    if not best:
        return None, len(feats)
    d, geom, f = best
    rect = geom.minimum_rotated_rectangle
    sides = sorted({round(math.dist(a, b), 6) for a, b in zip(rect.exterior.coords, rect.exterior.coords[1:])})
    length, width = (sides[-1], sides[0]) if sides else (0, 0)
    return {
        "attributes": f["attributes"],
        "source_layer": f["layer"],
        "area_m2": round(geom.area * m_per_unit ** 2, 4),
        "length_m": round(length * m_per_unit, 3),
        "width_m": round(width * m_per_unit, 3),
        "distance_m": round(d, 3),
        "zoom": z,
    }, len(feats)


@require_GET
def pilot_feature(request):
    """GET ?layer=<vector layer id>&lat=&lon= -> the polygon there, or feature null."""
    layer = request.GET.get("layer", "")
    try:
        lat, lon = float(request.GET["lat"]), float(request.GET["lon"])
    except (KeyError, ValueError):
        return JsonResponse({"error": "layer, lat and lon are required"}, status=400)
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        return JsonResponse({"error": "lat or lon is out of range"}, status=400)
    if layer not in vector_layers():
        return JsonResponse({"error": f"No vector layer named {layer!r}"}, status=404)
    lat, lon = round(lat, 7), round(lon, 7)
    key = f"pilot-feature:{layer}:{lat}:{lon}"
    hit = cache.get(key)
    if hit is None:
        try:
            feature, in_tile = feature_at(layer, lon, lat)
        except (sqlite3.Error, ValueError, IndexError) as e:
            return JsonResponse({"error": f"The layer cannot be read ({e})"}, status=500)
        hit = {"layer": layer, "lat": lat, "lon": lon, "feature": feature, "features_in_tile": in_tile}
        cache.set(key, hit, CACHE_SEC)
    return JsonResponse(hit)
