import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from deepgis_xr.apps.web.views.planet import PLANET_BODIES

REGISTRY = Path(settings.BASE_DIR) / "staticfiles" / "web" / "js" / "planet-bodies.js"


class PlanetViewerTests(TestCase):

    def test_bodies_match_the_js_registry(self):
        js_ids = re.findall(r"^\s+id: '([a-z]+)', name:", REGISTRY.read_text(), re.M)
        self.assertEqual(tuple(js_ids), PLANET_BODIES)

    def test_each_body_renders_with_its_id(self):
        for body in ("mars", "Europa", "moon"):
            resp = self.client.get(f"/label/3d/planet/{body}/")
            self.assertEqual(resp.status_code, 200, body)
            self.assertContains(resp, f"window.PLANET_BODY_ID = '{body.lower()}'")

    def test_moon_route_still_opens_the_moon(self):
        resp = self.client.get("/label/3d/moon/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "window.PLANET_BODY_ID = 'moon'")

    def test_unknown_body_is_404(self):
        self.assertEqual(self.client.get("/label/3d/planet/earth/").status_code, 404)
        self.assertEqual(self.client.get("/label/3d/planet/vulcan/").status_code, 404)
