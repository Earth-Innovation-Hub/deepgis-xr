import re

from django.contrib.auth import get_user_model
from django.test import TestCase

SCRIPT = r'<script src="[^"\\]*/web/js/hud/pilot-widgets\.js\?v=\w+"></script>'


class PilotWidgetsTests(TestCase):

    def test_fly_to_place_on_earth_and_moon(self):
        for url in ("/label/3d/search/", "/label/3d/moon/"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            for needle in ('id="flyToInput"', 'id="flyToBtn"', 'id="orbitPlaceBtn"', 'id="flyStopBtn"'):
                self.assertContains(resp, needle, msg_prefix=url)
            self.assertRegex(resp.content.decode(), SCRIPT)

    def test_describe_needs_a_sign_in(self):
        resp = self.client.get("/label/3d/search/")
        self.assertNotContains(resp, 'id="describeViewBtn"')
        self.assertContains(resp, "The vision model needs a sign-in.")
        self.assertTrue(re.search(r'href="/label/admin/login/\?next=/label/3d/search/"', resp.content.decode()))

    def test_describe_for_signed_in_users(self):
        user = get_user_model().objects.create_user("widget-tester", password="unused-pass-123")
        self.client.force_login(user)
        for url in ("/label/3d/search/", "/label/3d/moon/"):
            resp = self.client.get(url)
            self.assertContains(resp, 'id="describeViewBtn"', msg_prefix=url)
            self.assertContains(resp, 'id="describeQuestion"', msg_prefix=url)
            self.assertNotContains(resp, "The vision model needs a sign-in.", msg_prefix=url)
