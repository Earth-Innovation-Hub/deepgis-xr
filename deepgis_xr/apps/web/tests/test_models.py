import json
import math
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from deepgis_xr.apps.web.views import pilot

STATIC = Path(settings.BASE_DIR) / "staticfiles"
MODELS_JS = STATIC / "web" / "js" / "hud" / "models.js"
INDEX = STATIC / "deepgis" / "models" / "index.json"
LUNAR_BASE = "https://deepgis.org/static/deepgis/models/gltf/lunar_base.glb"

MOON_RADIUS_KM = 1737.4
SHACKLETON = (-89.67, 129.78)   # IAU centre, degrees; the crater is 21 km across


def km_between(a, b):
    (lat1, lon1), (lat2, lon2) = (tuple(map(math.radians, p)) for p in (a, b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * MOON_RADIUS_KM * math.asin(math.sqrt(h))


def site_option(html):
    m = re.search(r'<option value="shackleton_base"([^>]*)>', html)
    return dict(re.findall(r'data-([a-z-]+)="([^"]*)"', m.group(1))) if m else None


class LunarBaseTests(TestCase):

    def page(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, url)
        return resp.content.decode()

    def test_moon_opens_with_the_base_on_the_rim_of_shackleton(self):
        html = self.page("/label/3d/moon/")
        site = site_option(html)
        self.assertIsNotNone(site)
        self.assertEqual(site["model"], LUNAR_BASE)
        self.assertEqual(site["site"], "shackleton-base")
        from_centre = km_between((float(site["lat"]), float(site["lon"])), SHACKLETON)
        self.assertTrue(9.5 < from_centre < 11.5, from_centre)
        self.assertIn('data-fly-site="shackleton-base"', html)

    def test_other_bodies_have_no_site(self):
        for url in ("/label/3d/search/", "/label/3d/planet/mars/"):
            html = self.page(url)
            self.assertIsNone(site_option(html), url)
            self.assertNotIn("data-fly-site", html, url)

    def test_the_credit_is_shown_wherever_the_model_is_offered(self):
        for url in ("/label/3d/moon/", "/label/3d/search/", "/label/3d/planet/mars/"):
            html = self.page(url)
            self.assertIn(f'data-url="{LUNAR_BASE}"', html, url)
            credit = re.search(r'<span data-model-credit="lunar_base.glb">(.*?)</span>', html, re.S)
            self.assertIsNotNone(credit, url)
            for part in ("popo57", "CC BY 4.0", "sketchfab.com/3d-models/lunar-base", "creativecommons.org/licenses/by/4.0"):
                self.assertIn(part, credit.group(1), url)

    def test_the_loader_knows_the_model_the_site_names(self):
        src = MODELS_JS.read_text(encoding="utf-8")
        self.assertRegex(src, r"'lunar_base\.glb': \{ anchor: \[")
        self.assertIn("option[data-model]", src)

    def test_the_catalog_lists_the_model_with_its_licence(self):
        cat = json.loads(INDEX.read_text(encoding="utf-8"))
        entry = cat["models"]["lunar_base"]
        self.assertEqual(cat["endpoints"]["base_url"] + entry["file"], LUNAR_BASE)
        self.assertEqual(entry["license"], "CC-BY-4.0")
        self.assertIn("popo57", entry["attribution"])

    def test_the_pilot_can_name_the_base(self):
        prompt = pilot.planet_prompt("moon")
        self.assertIn('"Shackleton base"', prompt)

    def test_moonbase_aliases_are_on_the_site(self):
        html = self.page("/label/3d/moon/")
        site = site_option(html)
        aliases = {a.strip() for a in site["aliases"].split(",")}
        for a in ("moonbase", "moon base", "lunar base", "the moonbase"):
            self.assertIn(a, aliases)
        self.assertEqual(site["radius-m"], "100")

    def test_the_pilot_treats_models_as_queryable_places(self):
        prompt = pilot.planet_prompt("moon")
        self.assertIn("Models line", prompt)
        self.assertIn('"orbit the moonbase"', prompt)
        self.assertIn('"is there a moonbase nearby?"', prompt)
        self.assertIn('{"type": "orbit", "place": "Shackleton base"}', prompt)

    def test_models_context_names_the_nearest_base(self):
        models = [{"id": "shackleton-base", "name": "Shackleton base",
                   "lat": -89.77438, "lon": -156.2076,
                   "aliases": ["moonbase", "lunar base"]}]
        # Standing on the rim next to the base
        line = pilot.models_context({"lat": -89.7744, "lon": -156.21}, models, "moon")
        self.assertIn('"Shackleton base"', line)
        self.assertIn("also called moonbase, lunar base", line)
        self.assertRegex(line, r"\d+ m [A-Z]+ of the point in view")  # metres, not Earth-scaled thousands of km
        self.assertTrue(line.startswith("3D models on this globe:"))
        # From the equator the base is ~ halfway to the pole on the Moon (~2700 km), not Earth-scaled
        far = pilot.models_context({"lat": 0, "lon": -156.21}, models, "moon")
        self.assertRegex(far, r"2\.\d+ km S")
        self.assertEqual(pilot.models_context({"lat": 0, "lon": 0}, [], "moon"), "")
        self.assertEqual(pilot.models_context({"lat": 0, "lon": 0}, None, "moon"), "")


    def test_place_model_is_in_the_planet_schema(self):
        schema = pilot.PLANET_LAYER_SCHEMAS["moon"]
        types = schema["properties"]["actions"]["items"]["properties"]["type"]["enum"]
        self.assertIn("place_model", types)
        self.assertIn("model", schema["properties"]["actions"]["items"]["properties"])

    def test_available_models_line_names_the_lunar_base(self):
        line = pilot.available_models_line()
        self.assertIn('"Lunar base"', line)
        self.assertIn("moonbase", line)
        self.assertIn("place_model", line)

    def test_clean_actions_keeps_place_model(self):
        out = pilot.clean_actions([
            {"type": "goto", "place": "Tycho"},
            {"type": "place_model", "model": "moonbase", "place": "Tycho"},
        ], body="moon")
        self.assertEqual([a["type"] for a in out], ["place_model", "goto"])
        self.assertEqual(out[0]["model"], "Lunar base")
        self.assertEqual(out[0]["place"], "Tycho")

    def test_resolve_model_aliases(self):
        self.assertEqual(pilot.resolve_model("the moonbase")["id"], "lunar_base")
        self.assertEqual(pilot.resolve_model("Lunar base 3D model")["id"], "lunar_base")
        self.assertIsNone(pilot.resolve_model("death star"))

    def test_the_pilot_prompt_teaches_placing_a_model(self):
        prompt = pilot.planet_prompt("moon")
        self.assertIn("place_model", prompt)
        self.assertIn("go to Tycho and load the moonbase 3D model there", prompt)
