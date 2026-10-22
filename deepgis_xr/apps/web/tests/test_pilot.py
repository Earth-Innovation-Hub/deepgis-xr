import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from deepgis_xr.apps.web.views import pilot

URL = "/label/api/pilot/"


def mcp_response(plan, model="test-model"):
    """A streamable-HTTP (SSE) MCP tools/call reply carrying ask_robot_llm's result."""
    result = {"response": json.dumps(plan), "model": model, "duration_sec": 1.2, "json": plan}
    body = {"jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": json.dumps(result)}],
                       "structuredContent": {"result": result}, "isError": False}}
    resp = mock.Mock(status_code=200, text="event: message\ndata: " + json.dumps(body) + "\n\n",
                     headers={"Content-Type": "text/event-stream"})
    resp.raise_for_status = mock.Mock()
    return resp


class CleanActionsTests(TestCase):
    def test_drops_unknown_types_and_fields(self):
        out = pilot.clean_actions([{"type": "orbit", "place": " Tempe Town Lake ", "evil": 1},
                                   {"type": "self_destruct"}, "nope"])
        self.assertEqual(out, [{"type": "orbit", "place": "Tempe Town Lake"}])

    def test_clamps_numbers_and_rejects_bad_coordinates(self):
        out = pilot.clean_actions([{"type": "orbit", "radius_m": 1e9, "revolutions": 0,
                                    "pitch_deg": 30, "lat": 120, "lon": 10, "clockwise": True}])
        self.assertEqual(out, [{"type": "orbit", "radius_m": 20000.0, "revolutions": 0.25,
                                "pitch_deg": 0.0, "clockwise": True}])

    def test_keeps_valid_coordinates(self):
        out = pilot.clean_actions([{"type": "goto", "lat": 33.43, "lon": -111.94, "alt_m": 200}])
        self.assertEqual(out, [{"type": "goto", "lat": 33.43, "lon": -111.94, "alt_m": 200.0}])

    def test_layer_actions(self):
        out = pilot.clean_actions([
            {"type": "show_layer", "kind": "geology", "place": "Hayden Butte, Tempe, Arizona",
             "radius_m": 5000, "features": ["Lake Tempe"]},
            {"type": "show_layer", "kind": "volcanoes", "place": "Tempe, Arizona"},
            {"type": "show_layer", "place": "Tempe, Arizona"},
            {"type": "show_layer", "kind": "river", "place": "Salt River", "distance_km": 9000},
            {"type": "hide_layer", "kind": "faults"},
            {"type": "hide_layer", "kind": "bogus"},
            {"type": "hide_layer"},
        ])
        self.assertEqual(out, [
            {"type": "show_layer", "kind": "geology", "place": "Hayden Butte, Tempe, Arizona", "radius_m": 5000.0},
            {"type": "show_layer", "kind": "river", "place": "Salt River", "distance_km": 500.0},
            {"type": "hide_layer", "kind": "faults"},
            {"type": "hide_layer"},
        ])

    def test_layers_go_before_an_orbit(self):
        out = pilot.clean_actions([{"type": "goto", "place": "Tempe"},
                                   {"type": "orbit", "place": "Hayden Butte"},
                                   {"type": "show_layer", "kind": "geology", "place": "Hayden Butte"},
                                   {"type": "wait", "seconds": 2},
                                   {"type": "show_layer", "kind": "faults"}])
        self.assertEqual([a["type"] for a in out], ["goto", "show_layer", "orbit", "wait", "show_layer"])

    def test_kind_only_on_layer_actions(self):
        self.assertEqual(pilot.clean_actions([{"type": "goto", "place": "Tempe", "kind": "faults", "distance_km": 5}]),
                         [{"type": "goto", "place": "Tempe"}])

    def test_distance_km_is_a_radius_except_for_river(self):
        out = pilot.clean_actions([{"type": "show_layer", "kind": "faults", "place": "Bishop", "distance_km": 15},
                                   {"type": "show_layer", "kind": "fires", "distance_km": 5, "radius_m": 900}])
        self.assertEqual(out, [{"type": "show_layer", "kind": "faults", "place": "Bishop", "radius_m": 15000.0},
                               {"type": "show_layer", "kind": "fires", "radius_m": 900.0}])

    def test_caps_action_count(self):
        self.assertEqual(len(pilot.clean_actions([{"type": "wait", "seconds": 1}] * 20)), pilot.MAX_ACTIONS)

    def test_planet_scale_and_no_layers(self):
        out = pilot.clean_actions([{"type": "orbit", "place": "Tycho", "radius_m": 60000, "alt_m": 1e9},
                                   {"type": "show_layer", "kind": "geology", "place": "Tycho"},
                                   {"type": "hide_layer"}], body="moon")
        self.assertEqual(out, [{"type": "orbit", "place": "Tycho", "radius_m": 60000.0, "alt_m": 500000.0}])


@override_settings(DEEPGIS_PILOT_MCP_TOKEN="test-token", DEEPGIS_PILOT_RATE_PER_MIN=3)
class PilotChatTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="pilot", password="pw")
        self.client = Client()

    def post(self, payload, client=None):
        return (client or self.client).post(URL, json.dumps(payload), content_type="application/json")

    def test_requires_login(self):
        resp = self.post({"message": "orbit Tempe Town Lake"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"], "login_required")

    def test_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_enforces_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.post({"message": "hi"}, client).status_code, 403)

    def test_rejects_empty_message(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post({"message": "  "}).status_code, 400)

    @override_settings(DEEPGIS_PILOT_MCP_TOKEN="")
    def test_unconfigured(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post({"message": "hi"}).status_code, 503)

    def test_orbit_request(self):
        self.client.force_login(self.user)
        plan = {"reply": "Orbiting Tempe Town Lake.",
                "actions": [{"type": "orbit", "place": "Tempe Town Lake, Tempe, Arizona", "revolutions": 2}]}
        view = {"lat": 33.43, "lon": -111.94, "height_agl": 812.4, "heading_deg": 10,
                "target": {"lat": 33.432, "lon": -111.93}}
        history = [{"role": "user", "content": "hello"}, {"role": "system", "content": "ignored"}]
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)) as post:
            resp = self.post({"message": "orbit around tempe town lake twice", "view": view, "history": history})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["reply"], "Orbiting Tempe Town Lake.")
        self.assertEqual(resp.json()["actions"], [{"type": "orbit", "place": "Tempe Town Lake, Tempe, Arizona",
                                                   "revolutions": 2.0}])
        call = post.call_args
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-token")
        params = call.kwargs["json"]["params"]
        self.assertEqual(params["name"], "ask_robot_llm")
        args = params["arguments"]
        self.assertEqual(args["json_schema"], pilot.PILOT_SCHEMA)
        self.assertEqual(args["history"], [{"role": "user", "content": "hello"}])
        self.assertIn("lat 33.43000, lon -111.94000, 812 m above ground", args["prompt"])
        self.assertIn("looking at lat 33.43200", args["prompt"])
        self.assertTrue(args["prompt"].endswith("User: orbit around tempe town lake twice"))

    def test_planet_request(self):
        self.client.force_login(self.user)
        plan = {"reply": "Orbiting Tycho.", "actions": [{"type": "orbit", "place": "Tycho"},
                                                         {"type": "show_layer", "kind": "faults"}]}
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)) as post:
            resp = self.post({"message": "orbit tycho", "body": "moon"})
        self.assertEqual(resp.json()["actions"], [{"type": "orbit", "place": "Tycho"}])
        args = post.call_args.kwargs["json"]["params"]["arguments"]
        self.assertEqual(args["json_schema"], pilot.PLANET_SCHEMA)
        self.assertIn("3D globe of the Moon", args["system_prompt"])
        self.assertNotIn("show_layer", json.dumps(args["json_schema"]))

    def test_rejects_unknown_body(self):
        self.client.force_login(self.user)
        for body in ("vulcan", ["moon"]):
            self.assertEqual(self.post({"message": "hi", "body": body}).status_code, 400)

    def test_backend_error_is_502(self):
        self.client.force_login(self.user)
        with mock.patch.object(pilot.requests, "post", side_effect=pilot.requests.ConnectionError("down")):
            resp = self.post({"message": "orbit"})
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn("down", resp.json()["error"])

    def test_rate_limited(self):
        self.client.force_login(self.user)
        plan = {"reply": "ok", "actions": []}
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)):
            codes = [self.post({"message": "hi"}).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])
