from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from deepgis_xr.apps.core.models import Simulation

URL = "/label/api/sims/"

LAB = [
    {
        "slug": "aquatic",
        "name": "Kiwanis Lake",
        "world": "Kiwanis Lake",
        "robots": ["otter_k", "xudrone"],
        "commands": True,
        "kind": "lab",
        "status": "unknown",
        "url": "/openuav/llm/40077/",
    },
    {
        "slug": "locutus",
        "name": "Locutus",
        "world": "Locutus",
        "robots": ["kestrel", "badger"],
        "commands": True,
        "kind": "lab",
        "status": "unknown",
        "url": "/openuav/llm/40088/",
    },
    {
        "slug": "tempe-lake",
        "name": "Tempe Town Lake",
        "world": "Tempe Town Lake",
        "robots": ["otter"],
        "commands": True,
        "kind": "lab",
        "status": "unknown",
        "url": "/openuav/llm/40099/",
    },
]


class SimsListTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(username="pilot", password="pw", phone_number="+12015550111")
        self.other = User.objects.create_user(username="visitor", password="pw", phone_number="+12015550112")

    def test_signed_out_is_401(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"], "login_required")

    def test_signed_in_user_sees_the_three_lab_desktops(self):
        self.client.force_login(self.other)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["sims"], LAB)

    def test_member_sees_the_three_lab_desktops(self):
        self.client.force_login(self.member)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["sims"], LAB)
        for row in body["sims"]:
            self.assertNotIn("container", row)
            self.assertNotIn("host_port", row)
            self.assertTrue(row["url"].startswith("/openuav/llm/"))
            self.assertNotIn("://", row["url"])

    def test_course_and_session_rows_are_not_listed(self):
        Simulation.objects.create(
            slug="session-one", name="Session", container="digital-twin-session-one",
            host_port=40001, world="Session", robots=["ktwin"], kind="session", position=9,
        )
        self.client.force_login(self.member)
        slugs = [row["slug"] for row in self.client.get(URL).json()["sims"]]
        self.assertEqual(slugs, ["aquatic", "locutus", "tempe-lake"])

    def test_a_stopped_session_stays_on_the_owners_list(self):
        Simulation.objects.create(
            slug="ktwin-stopped", name="Stopped", container="digital-twin-session-ktwin-stopped",
            host_port=40111, world="Stopped", robots=["ktwin-stopped"],
            kind="session", status="down", owner=self.member, position=50,
        )
        self.client.force_login(self.member)
        rows = {row["slug"]: row for row in self.client.get(URL).json()["sims"]}
        self.assertEqual(rows["ktwin-stopped"]["status"], "down")
        self.client.force_login(self.other)
        slugs = [row["slug"] for row in self.client.get(URL).json()["sims"]]
        self.assertNotIn("ktwin-stopped", slugs)

    def _session(self, slug="ktwin-ctrl", port=40112, status="up"):
        return Simulation.objects.create(
            slug=slug, name="Ctrl", container=f"digital-twin-session-{slug}",
            host_port=port, world="Ctrl", robots=[slug],
            kind="session", status=status, owner=self.member, position=50,
        )

    def post_action(self, slug, action, user=None):
        self.client.force_login(user or self.member)
        return self.client.post(
            f"/label/api/sims/{slug}/",
            data=f'{{"action": "{action}"}}',
            content_type="application/json",
        )

    @override_settings(DEEPGIS_TWIN_BUILDER_URL="http://builder.invalid", DEEPGIS_TWIN_BUILDER_TOKEN="t")
    def test_owner_can_stop_start_and_purge_only_their_session(self):
        self._session()
        ok = mock.Mock(status_code=200, json=lambda: {"status": "down"})
        with mock.patch("deepgis_xr.apps.web.views.sims.requests.post", return_value=ok) as posted:
            resp = self.post_action("ktwin-ctrl", "stop")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "down")
        self.assertTrue(posted.call_args.args[0].endswith("/sessions/ktwin-ctrl/stop"))
        self.assertEqual(Simulation.objects.get(slug="ktwin-ctrl").status, "down")
        with mock.patch("deepgis_xr.apps.web.views.sims.requests.post", return_value=ok):
            resp = self.post_action("ktwin-ctrl", "start")
        self.assertEqual(resp.json()["status"], "up")
        self.assertEqual(Simulation.objects.get(slug="ktwin-ctrl").status, "up")
        with mock.patch("deepgis_xr.apps.web.views.sims.requests.post", return_value=ok):
            resp = self.post_action("ktwin-ctrl", "purge")
        self.assertEqual(resp.json()["status"], "purged")
        self.assertFalse(Simulation.objects.filter(slug="ktwin-ctrl").exists())

    @override_settings(DEEPGIS_TWIN_BUILDER_URL="http://builder.invalid", DEEPGIS_TWIN_BUILDER_TOKEN="t")
    def test_lab_desktops_and_other_owners_cannot_be_controlled(self):
        self._session()
        self.assertEqual(self.client.post("/label/api/sims/locutus/", data="{}", content_type="application/json").status_code, 401)
        self.client.force_login(self.member)
        self.assertEqual(self.post_action("locutus", "stop").status_code, 404)
        self.assertEqual(self.post_action("ktwin-ctrl", "fly").status_code, 400)
        self.assertEqual(self.post_action("ktwin-ctrl", "purge", user=self.other).status_code, 404)
        self.assertTrue(Simulation.objects.filter(slug="locutus").exists())
        self.assertTrue(Simulation.objects.filter(slug="ktwin-ctrl").exists())

    def test_control_needs_the_builder(self):
        self._session()
        with override_settings(DEEPGIS_TWIN_BUILDER_URL="", DEEPGIS_TWIN_BUILDER_TOKEN=""):
            self.assertEqual(self.post_action("ktwin-ctrl", "stop").status_code, 503)

    def test_port_outside_the_hub_range_is_rejected(self):
        sim = Simulation(
            slug="bad-port", name="Bad", container="digital-twin-bad",
            host_port=80, world="Nowhere", kind="lab",
        )
        with self.assertRaises(ValidationError):
            sim.full_clean()
