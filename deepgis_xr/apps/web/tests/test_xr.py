from pathlib import Path

from django.conf import settings
from django.test import TestCase

JS = Path(settings.BASE_DIR) / "staticfiles" / "web" / "js"
SCRIPT = r'<script src="[^"\\]*/web/js/hud/xr\.js\?v=\w+"></script>'
COCKPIT_THEN_XR = (r'<script src="[^"\\]*/web/js/hud/xr-cockpit\.js\?v=\w+"></script>\s*'
                   r'<script src="[^"\\]*/web/js/hud/xr\.js\?v=\w+"></script>')


class ImmersiveVRTests(TestCase):

    def test_vr_panel_and_script_on_earth_and_moon(self):
        for url in ("/label/3d/search/", "/label/3d/moon/"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            for needle in ('id="enterVR"', 'id="exitVR"', 'id="vrResolution"', 'id="vrSteer"', 'id="vrStatus"'):
                self.assertContains(resp, needle, msg_prefix=url)
            self.assertRegex(resp.content.decode(), SCRIPT)
            self.assertRegex(resp.content.decode(), COCKPIT_THEN_XR)

    def test_viewers_take_the_headset_context_options(self):
        self.assertIn("...window.DeepGISXRContext", (JS / "core" / "cesium-init.js").read_text(encoding="utf-8"))
        moon = (Path(settings.BASE_DIR) / "deepgis_xr" / "apps" / "web" / "templates" / "web"
                / "label_moon_viewer.html").read_text(encoding="utf-8")
        self.assertIn("contextOptions: { webgl: { ...window.DeepGISXRContext } }", moon)

    def test_old_webxr_module_is_gone(self):
        self.assertFalse((JS.parent / "features" / "webxr.js").exists())
        self.assertNotIn("webxr", (JS / "main.js").read_text(encoding="utf-8").lower())
