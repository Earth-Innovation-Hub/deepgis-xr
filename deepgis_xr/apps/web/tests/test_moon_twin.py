"""Moon create_twin: the pilot offers it, and the job carries the elevation grid."""
import json
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import Client, TestCase, TransactionTestCase, override_settings

from deepgis_xr.apps.web.views import create_twin, pilot

URL = "/label/api/pilot/"
CREATE_URL = "/label/api/pilot/create-twin/"


def moon_dem(grid=17):
    return {"grid": grid, "heights": [float((i % grid) - grid // 2) for i in range(grid * grid)]}


class MoonTwinCleanTests(TestCase):
    def test_moon_keeps_create_twin_for_a_superuser(self):
        raw = [{"type": "create_twin", "vehicle_class": "kestrel", "count": 1,
                "width_m": 80, "length_m": 80}]
        self.assertEqual(pilot.clean_actions(raw, body="moon", allow_twin=False), [])
        kept = pilot.clean_actions(raw, body="moon", allow_twin=True)
        self.assertEqual(kept[0]["type"], "create_twin")
        self.assertEqual(kept[0]["width_m"], 80.0)
        self.assertEqual(pilot.clean_actions(raw, body="mars", allow_twin=True), [])

    def test_moon_schema_offers_create_twin(self):
        props = pilot.moon_twin_schema()["properties"]["actions"]["items"]["properties"]
        self.assertIn("create_twin", props["type"]["enum"])
        plain = pilot.PLANET_LAYER_SCHEMAS["moon"]["properties"]["actions"]["items"]["properties"]
        self.assertNotIn("create_twin", plain["type"]["enum"])

    def test_lunar_patch_is_wider_in_degrees_than_the_same_metres_on_earth(self):
        earth = create_twin._bbox_from_patch(0, 0, 150, 150, "earth")
        moon = create_twin._bbox_from_patch(0, 0, 150, 150, "moon")
        self.assertGreater(moon["north"] - moon["south"], earth["north"] - earth["south"])

    def test_dem_is_required_on_the_moon_and_kept_on_earth(self):
        with self.assertRaises(ValueError):
            create_twin._dem({}, "moon")
        self.assertIsNone(create_twin._dem({}, "earth"))
        grid = create_twin._dem({"dem": moon_dem()}, "moon")
        self.assertEqual(grid["grid"], 17)
        self.assertEqual(len(grid["heights"]), 17 * 17)
        earth = create_twin._dem({"dem": moon_dem()}, "earth")
        self.assertEqual(earth["grid"], 17)
        self.assertEqual(len(earth["heights"]), 17 * 17)
        buried = moon_dem()
        buried["heights"] = [400.0] * (17 * 17)
        with self.assertRaises(ValueError):
            create_twin._dem({"dem": buried}, "moon")


@override_settings(DEEPGIS_PILOT_MCP_TOKEN="test-token",
                   DEEPGIS_TWIN_BUILDER_URL="",
                   DEEPGIS_TWIN_BUILDER_TOKEN="")
class MoonTwinJobTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        caches["live"].clear()
        self.admin = get_user_model().objects.create_superuser(
            username="boss", email="b@example.org", password="pw",
            phone_number="+14805550199")
        self.client = Client()
        self.client.force_login(self.admin)

    def payload(self):
        return {
            "vehicle_class": "kestrel",
            "count": 1,
            "width_m": 150,
            "length_m": 150,
            "body": "moon",
            "look_at": {"lat": -89.774, "lon": -156.208, "elev_m": 1800},
            "dem": moon_dem(),
        }

    def test_enqueue_bakes_a_moon_world(self):
        with mock.patch.object(create_twin.time, "sleep", return_value=None):
            resp = self.client.post(CREATE_URL, json.dumps(self.payload()),
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["body"], "moon")
        self.assertNotIn("dem", data)
        ready = None
        for _ in range(40):
            time.sleep(0.05)
            ready = self.client.get(f"{CREATE_URL}{data['id']}/").json()
            if ready["status"] in ("ready", "failed"):
                break
        self.assertEqual(ready["status"], "ready", ready)
        job = caches["live"].get(create_twin.JOB_KEY.format(data["id"]))
        text = open(job["artifact"]["world_sdf"], encoding="utf-8").read()
        self.assertIn("MOON_SCS", text)
        self.assertIn("lunar heightmap 17", text)

    def test_enqueue_records_an_earth_heightmap(self):
        payload = self.payload()
        payload["body"] = "earth"
        payload["look_at"] = {"lat": 33.425, "lon": -111.940, "elev_m": 400}
        with mock.patch.object(create_twin.time, "sleep", return_value=None):
            resp = self.client.post(CREATE_URL, json.dumps(payload),
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["body"], "earth")
        self.assertNotIn("dem", data)
        ready = None
        for _ in range(40):
            time.sleep(0.05)
            ready = self.client.get(f"{CREATE_URL}{data['id']}/").json()
            if ready["status"] in ("ready", "failed"):
                break
        self.assertEqual(ready["status"], "ready", ready)
        job = caches["live"].get(create_twin.JOB_KEY.format(data["id"]))
        text = open(job["artifact"]["world_sdf"], encoding="utf-8").read()
        self.assertIn("EARTH_WGS84", text)
        self.assertIn("earth heightmap 17", text)
        self.assertNotIn("MOON_SCS", text)

    def test_chat_offers_a_moon_twin_to_a_superuser(self):
        plan = {"reply": "I can create a lunar twin here; confirm below.",
                "actions": [{"type": "create_twin", "vehicle_class": "kestrel", "count": 1,
                             "width_m": 150, "length_m": 150}]}
        with mock.patch.object(pilot.requests, "post", return_value=pilot_mcp(plan)) as post:
            resp = self.client.post(URL, json.dumps({
                "message": "create a digital twin of this place",
                "body": "moon",
            }), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["actions"][0]["type"], "create_twin")
        schema = post.call_args.kwargs["json"]["params"]["arguments"]["json_schema"]
        kinds = schema["properties"]["actions"]["items"]["properties"]["type"]["enum"]
        self.assertIn("create_twin", kinds)
        self.assertIn("LOLA", post.call_args.kwargs["json"]["params"]["arguments"]["system_prompt"])


def pilot_mcp(plan):
    """The shape call_mcp_tool expects is built inside pilot; mock requests.post."""
    from deepgis_xr.apps.web.tests.test_pilot import mcp_response
    return mcp_response(plan)
