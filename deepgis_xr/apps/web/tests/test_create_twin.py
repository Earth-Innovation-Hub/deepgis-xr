"""create_twin Pilot action + job API."""
import json
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import Client, TestCase, TransactionTestCase, override_settings

from deepgis_xr.apps.core.models import Simulation
from deepgis_xr.apps.web.views import create_twin, pilot
from deepgis_xr.apps.web.tests.test_pilot import mcp_response

URL = "/label/api/pilot/"
CREATE_URL = "/label/api/pilot/create-twin/"


class CreateTwinCleanTests(TestCase):
    def test_dropped_without_allow_twin(self):
        raw = [{"type": "create_twin", "vehicle_class": "kestrel", "count": 1, "width_m": 20, "length_m": 20}]
        self.assertEqual(pilot.clean_actions(raw), [])
        self.assertEqual(pilot.clean_actions(raw, allow_twin=False), [])

    def test_kept_for_superuser_flag(self):
        raw = [
            {"type": "create_twin", "vehicle_class": "kestrel", "count": 1, "width_m": 20, "length_m": 20},
            {"type": "create_twin", "vehicle_class": "kestrel", "width_m": 999, "length_m": 10},
            {"type": "create_twin", "vehicle_class": "kestrel", "count": 2, "width_m": 20, "length_m": 20},
            {"type": "create_twin", "vehicle_class": "spaceship"},
            {"type": "follow_vehicle", "vehicle": "kestrel", "view": "chase"},
        ]
        out = pilot.clean_actions(raw, allow_twin=True)
        self.assertEqual(out[0], {
            "type": "create_twin", "vehicle_class": "kestrel", "count": 1,
            "width_m": 20.0, "length_m": 20.0,
        })
        self.assertEqual(out[1], {
            "type": "create_twin", "vehicle_class": "kestrel", "count": 1,
            "width_m": 400.0, "length_m": 20.0,
        })
        self.assertEqual(out[2]["type"], "follow_vehicle")

    def test_control_schema_includes_create_twin(self):
        items = pilot.CONTROL_SCHEMA["properties"]["actions"]["items"]["properties"]
        self.assertIn("create_twin", items["type"]["enum"])
        self.assertEqual(items["vehicle_class"]["enum"], list(pilot.VEHICLE_CLASSES))
        self.assertIn("width_m", items)
        self.assertIn("length_m", items)
        self.assertIn("count", items)
        self.assertNotIn("create_twin",
                         pilot.PILOT_SCHEMA["properties"]["actions"]["items"]["properties"]["type"]["enum"])


@override_settings(DEEPGIS_PILOT_MCP_TOKEN="test-token",
                   DEEPGIS_TWIN_BUILDER_URL="",
                   DEEPGIS_TWIN_BUILDER_TOKEN="")
class CreateTwinJobTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        caches["live"].clear()
        self.user = get_user_model().objects.create_user(
            username="pilot", password="pw", phone_number="+14805550111")
        self.admin = get_user_model().objects.create_superuser(
            username="boss", email="b@example.org", password="pw",
            phone_number="+14805550112")
        self.client = Client()

    def payload(self, **extra):
        body = {
            "vehicle_class": "kestrel",
            "count": 1,
            "width_m": 20,
            "length_m": 20,
            "look_at": {"lat": 37.45, "lon": -118.44, "elev_m": 1400},
            "bbox": {"west": -118.442, "south": 37.448, "east": -118.438, "north": 37.452},
        }
        body.update(extra)
        return body

    def test_requires_superuser(self):
        self.client.force_login(self.user)
        resp = self.client.post(CREATE_URL, json.dumps(self.payload()),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_enqueue_and_stub_ready(self):
        self.client.force_login(self.admin)
        with mock.patch.object(create_twin.time, "sleep", return_value=None):
            resp = self.client.post(CREATE_URL, json.dumps(self.payload()),
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "queued")
        self.assertTrue(data["callsign"].startswith("ktwin-"))
        job_id = data["id"]
        self.assertIsNotNone(caches["live"].get(create_twin.JOB_KEY.format(job_id)))
        self.assertIsNone(cache.get(create_twin.JOB_KEY.format(job_id)))
        # Wait briefly for stub thread
        ready = None
        for _ in range(40):
            time.sleep(0.05)
            st = self.client.get(f"{CREATE_URL}{job_id}/")
            self.assertEqual(st.status_code, 200)
            ready = st.json()
            if ready["status"] in ("ready", "failed"):
                break
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["vehicle"], data["callsign"])
        self.assertEqual(ready["follow_view"], "chase")
        sim = Simulation.objects.get(slug=data["callsign"])
        self.assertEqual(sim.kind, "session")
        self.assertEqual(sim.owner, self.admin)
        self.assertEqual(sim.status, "up")
        self.assertEqual(sim.robots, [data["callsign"]])
        self.assertTrue(40100 <= sim.host_port <= 40199)
        self.assertNotIn(sim.host_port, (40077, 40088, 40099))
        self.assertEqual(ready["url"], f"/openuav/llm/{sim.host_port}/")
        self.assertNotIn("host_port", ready)
        self.assertNotIn("container", ready)

    def test_rejects_bad_look_at(self):
        self.client.force_login(self.admin)
        resp = self.client.post(CREATE_URL, json.dumps(self.payload(look_at={"lat": 999, "lon": 0})),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_one_active_job_per_user(self):
        self.client.force_login(self.admin)
        # Freeze stub so first job stays queued
        with mock.patch.object(create_twin, "_stub_pipeline", lambda *_: None):
            r1 = self.client.post(CREATE_URL, json.dumps(self.payload()),
                                  content_type="application/json")
            r2 = self.client.post(CREATE_URL, json.dumps(self.payload()),
                                  content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 400)

    def test_chat_offers_create_twin_for_superuser(self):
        self.client.force_login(self.admin)
        plan = {"reply": "I can create a twin here; confirm below.",
                "actions": [{"type": "create_twin", "vehicle_class": "kestrel", "count": 1,
                             "width_m": 20, "length_m": 20}]}
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)) as post:
            resp = self.client.post(URL, json.dumps({
                "message": "create digital twin of a 20x20m patch at the center of view, with one kestrel class drone",
            }), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["actions"], [
            {"type": "create_twin", "vehicle_class": "kestrel", "count": 1,
             "width_m": 20.0, "length_m": 20.0}])
        args = post.call_args.kwargs["json"]["params"]["arguments"]
        self.assertEqual(args["json_schema"], pilot.CONTROL_SCHEMA)
        self.assertIn("create_twin", args["system_prompt"])
        self.assertIn("20x20m path", args["system_prompt"])
        self.assertIn("width_m", args["system_prompt"])
