from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

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
        "url": "/openuav/llm/40077/",
    },
    {
        "slug": "locutus",
        "name": "Locutus",
        "world": "Locutus",
        "robots": ["kestrel", "badger"],
        "commands": True,
        "kind": "lab",
        "url": "/openuav/llm/40088/",
    },
    {
        "slug": "tempe-lake",
        "name": "Tempe Town Lake",
        "world": "Tempe Town Lake",
        "robots": ["otter"],
        "commands": True,
        "kind": "lab",
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

    def test_course_and_other_sessions_stay_hidden(self):
        Simulation.objects.create(
            slug="session-one", name="Session", container="digital-twin-session-one",
            host_port=40101, world="Session", robots=["ktwin-other"], kind="session",
            position=9, owner=self.other, status="up",
        )
        Simulation.objects.create(
            slug="course-one", name="Course", container="digital-twin-course",
            host_port=40102, world="Course", robots=["student"], kind="course", position=8,
        )
        self.client.force_login(self.member)
        slugs = [row["slug"] for row in self.client.get(URL).json()["sims"]]
        self.assertEqual(slugs, ["aquatic", "locutus", "tempe-lake"])

    def test_owner_sees_their_session_after_the_lab_desktops(self):
        Simulation.objects.create(
            slug="ktwin-mine", name="37.450, -118.440", container="digital-twin-session-ktwin-mine",
            host_port=40110, world="37.450, -118.440", robots=["ktwin-mine"],
            kind="session", status="up", owner=self.member, position=50, commands=False,
        )
        self.client.force_login(self.member)
        rows = self.client.get(URL).json()["sims"]
        self.assertEqual([row["slug"] for row in rows], ["aquatic", "locutus", "tempe-lake", "ktwin-mine"])
        session = rows[-1]
        self.assertEqual(session["url"], "/openuav/llm/40110/")
        self.assertEqual(session["kind"], "session")
        self.assertFalse(session["commands"])
        self.assertNotIn("host_port", session)
        self.assertNotIn("container", session)
        self.client.force_login(self.other)
        slugs = [row["slug"] for row in self.client.get(URL).json()["sims"]]
        self.assertNotIn("ktwin-mine", slugs)

    def test_port_outside_the_hub_range_is_rejected(self):
        sim = Simulation(
            slug="bad-port", name="Bad", container="digital-twin-bad",
            host_port=80, world="Nowhere", kind="lab",
        )
        with self.assertRaises(ValidationError):
            sim.full_clean()
