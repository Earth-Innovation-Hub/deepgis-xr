import math
import os
import sqlite3

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from deepgis_xr.apps.web.views import features

ROCKS = os.path.join(features.DATA_DIR, "rockPoly_all_v0.mbtiles")


def _tile_point(path, z):
    """A point inside one polygon of the densest tile at zoom z, and that polygon's attributes."""
    with sqlite3.connect(path) as db:
        x, row, data = db.execute("SELECT tile_column, tile_row, tile_data FROM tiles WHERE zoom_level=? "
                                  "ORDER BY length(tile_data) DESC LIMIT 1", (z,)).fetchone()
    n = 2 ** z
    f = features.decode_tile(bytes(data))[0]
    c = features._shape(f["rings"]).representative_point()
    lon = (x + c.x / f["extent"]) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (n - 1 - row + c.y / f["extent"]) / n))))
    return lat, lon, f["attributes"]


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class FeatureLookupTests(SimpleTestCase):
    def test_decode_square_with_hole(self):
        def zz(v):
            return (v << 1) ^ (v >> 31)

        def varints(vals):
            b = bytearray()
            for v in vals:
                while v > 0x7F:
                    b.append(v & 0x7F | 0x80)
                    v >>= 7
                b.append(v)
            return bytes(b)

        def msg(*fields):
            b = bytearray()
            for num, wire, val in fields:
                b += varints([num << 3 | wire])
                if wire == 0:
                    b += varints([val])
                else:
                    b += varints([len(val)]) + val
            return bytes(b)

        # MoveTo 1 (9), LineTo 3 (26), ClosePath (15); deltas zigzag-encoded. The outer
        # 100x100 square winds positive in tile space, the 20x20 hole negative.
        outer = [9, zz(0), zz(0), 26, zz(100), zz(0), zz(0), zz(100), zz(-100), zz(0), 15]
        hole = [9, zz(40), zz(-60), 26, zz(0), zz(20), zz(20), zz(0), zz(0), zz(-20), 15]
        geom = varints(outer + hole)
        feat = msg((2, 2, varints([0, 0])), (3, 0, 3), (4, 2, geom))
        layer = msg((15, 0, 2), (1, 2, b"rocks"), (2, 2, feat), (3, 2, b"size"),
                    (4, 2, msg((6, 0, zz(42)))), (5, 0, 4096))
        [f] = features.decode_tile(msg((3, 2, layer)))
        self.assertEqual(f["attributes"], {"size": 42})
        shape = features._shape(f["rings"])
        self.assertAlmostEqual(shape.area, 100 * 100 - 20 * 20)

    def test_rock_lookup(self):
        if not os.path.isfile(ROCKS) or "rockPoly_all_v0" not in features.vector_layers():
            self.skipTest("rockPoly_all_v0.mbtiles is not served here")
        lat, lon, attrs = _tile_point(ROCKS, 20)
        r = self.client.get(reverse("pilot_feature"), {"layer": "rockPoly_all_v0", "lat": lat, "lon": lon})
        self.assertEqual(r.status_code, 200)
        f = r.json()["feature"]
        self.assertEqual(f["attributes"], attrs)
        self.assertGreater(f["area_m2"], 0)
        self.assertGreaterEqual(f["length_m"], f["width_m"])
        miss = self.client.get(reverse("pilot_feature"), {"layer": "rockPoly_all_v0", "lat": 37.0, "lon": -118.0})
        self.assertIsNone(miss.json()["feature"])

    def test_bad_requests(self):
        self.assertEqual(self.client.get(reverse("pilot_feature"), {"layer": "x"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("pilot_feature"),
                                         {"layer": "no_such_layer", "lat": 1, "lon": 1}).status_code, 404)
