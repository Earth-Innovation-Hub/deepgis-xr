import json
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from deepgis_xr.apps.web.views import pilot

ACTIONS_JS = Path(settings.BASE_DIR) / "staticfiles" / "web" / "js" / "hud" / "actions.js"


def js_table_keys(name):
    src = ACTIONS_JS.read_text(encoding="utf-8")
    start = src.index(f"    const {name} = {{\n")
    end = src.index("\n    };\n", start)
    return set(re.findall(r"^        ([a-z_]+): \{", src[start:end], re.M))


def page_catalog(resp):
    m = re.search(r'<script id="hudLayerCatalog" type="application/json">(.*?)</script>', resp.content.decode(), re.S)
    return json.loads(m.group(1)) if m else None


class LayersPanelTests(TestCase):

    def test_js_layers_match_the_server_kinds(self):
        self.assertEqual(js_table_keys("LAYERS"), set(pilot.LAYER_KINDS))

    def test_js_planet_layers_cover_each_body(self):
        js = js_table_keys("PLANET_LAYERS")
        for body, kinds in pilot.PLANET_LAYER_KINDS.items():
            self.assertLessEqual(set(kinds), js, body)

    def test_earth_catalog(self):
        cat = pilot.layer_catalog("earth")
        self.assertEqual(cat["kinds"], list(pilot.LAYER_KINDS))
        self.assertEqual(cat["colormaps"], list(pilot.COLORMAPS))
        self.assertEqual(set(cat["colormap_kinds"]), set(pilot.RASTER_KINDS))
        self.assertEqual(set(cat["signin_kinds"]), {"sea_temp", "chlorophyll", "lidar_dem"})
        self.assertEqual(cat["radius_m"], list(pilot.LAYER_LIMITS["radius_m"]))

    def test_planet_catalogs(self):
        moon = pilot.layer_catalog("moon")
        self.assertEqual(moon["kinds"], ["elevation", "slope", "contours"])
        self.assertEqual((moon["colormaps"], moon["colormap_kinds"], moon["signin_kinds"]), ([], [], []))
        self.assertEqual(moon["radius_m"], list(pilot.PLANET_LIMITS["radius_m"]))
        self.assertEqual(pilot.layer_catalog("venus")["kinds"], [])

    def test_search_page_has_data_layers_and_tile_catalog(self):
        resp = self.client.get("/label/3d/search/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(page_catalog(resp), pilot.layer_catalog("earth"))
        for needle in ('id="hudLayersBtn"', 'id="dataLayersMount"', 'id="tileCatalogMount"'):
            self.assertContains(resp, needle)
        self.assertRegex(resp.content.decode(), r'<script src="[^"\\]*/web/js/hud/layers-panel\.js\?v=\w+"></script>')

    def test_moon_has_data_layers_only(self):
        resp = self.client.get("/label/3d/moon/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(page_catalog(resp), pilot.layer_catalog("moon"))
        self.assertContains(resp, 'id="hudLayersBtn"')
        self.assertNotContains(resp, 'id="tileCatalogMount"')
        self.assertRegex(resp.content.decode(), r'<script src="[^"\\]*/web/js/hud/layers-panel\.js\?v=\w+"></script>')

    def test_body_without_layers_has_no_layers_button(self):
        resp = self.client.get("/label/3d/planet/venus/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="hudLayersBtn"')
        self.assertIsNone(page_catalog(resp))
