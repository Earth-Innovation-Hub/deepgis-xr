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

    def test_surface_temp_and_colormap(self):
        out = pilot.clean_actions([
            {"type": "orbit", "place": "Tempe, Arizona"},
            {"type": "show_layer", "kind": "surface_temp", "place": "Tempe, Arizona", "colormap": "jet"},
            {"type": "show_layer", "kind": "surface_temp", "colormap": "hotpink"},
            {"type": "goto", "place": "Tempe", "colormap": "jet"},
        ])
        self.assertEqual(out, [
            {"type": "show_layer", "kind": "surface_temp", "place": "Tempe, Arizona", "colormap": "jet"},
            {"type": "show_layer", "kind": "surface_temp"},
            {"type": "orbit", "place": "Tempe, Arizona"},
            {"type": "goto", "place": "Tempe"},
        ])
        items = pilot.PILOT_SCHEMA["properties"]["actions"]["items"]["properties"]
        self.assertEqual(list(items)[:4], ["type", "kind", "place", "colormap"])
        self.assertNotIn("colormap", json.dumps(pilot.PLANET_LAYER_SCHEMAS["moon"]))
        self.assertEqual(pilot.clean_actions([{"type": "show_layer", "kind": "elevation", "colormap": "jet"}],
                                             body="moon"), [{"type": "show_layer", "kind": "elevation"}])

    def test_weather_sea_and_vegetation_layers(self):
        out = pilot.clean_actions([
            {"type": "show_layer", "kind": "sea_temp", "place": "Monterey Bay, California", "radius_m": 150000},
            {"type": "show_layer", "kind": "chlorophyll", "distance_km": 900},
            {"type": "show_layer", "kind": "ndvi", "place": "Phoenix, Arizona", "colormap": "rdylgn"},
            {"type": "show_layer", "kind": "humidity", "place": "Tucson, Arizona"},
            {"type": "show_layer", "kind": "air_temp", "colormap": "coolwarm"},
            {"type": "orbit", "place": "Monterey Bay, California", "radius_m": 150000},
        ])
        self.assertEqual(out, [
            {"type": "show_layer", "kind": "sea_temp", "place": "Monterey Bay, California", "radius_m": 150000.0},
            {"type": "show_layer", "kind": "chlorophyll", "radius_m": 200000.0},
            {"type": "show_layer", "kind": "ndvi", "place": "Phoenix, Arizona", "colormap": "rdylgn"},
            {"type": "show_layer", "kind": "humidity", "place": "Tucson, Arizona"},
            {"type": "show_layer", "kind": "air_temp", "colormap": "coolwarm"},
            {"type": "orbit", "place": "Monterey Bay, California", "radius_m": 20000.0},
        ])

    def test_schema_key_order_and_layer_fields(self):
        out = pilot.clean_actions([
            {"type": "show_layer", "place": "Monterey Bay, California", "radius_m": 80000, "pitch_deg": -90,
             "heading_deg": 360, "seconds": 0, "clockwise": False, "kind": "sea_temp"},
            {"type": "hide_layer", "place": "Tempe", "kind": "ndvi"},
            {"type": "orbit", "clockwise": True, "radius_m": 900, "place": "Tempe"},
        ])
        self.assertEqual([list(a) for a in out], [["type", "kind", "place", "radius_m"], ["type", "kind"],
                                                  ["type", "place", "radius_m", "clockwise"]])

    def test_named_colormap(self):
        self.assertEqual(pilot.named_colormap("sea temperature in Jet please"), "jet")
        self.assertEqual(pilot.named_colormap("rainbow, like jet"), "jet")
        self.assertEqual(pilot.named_colormap("red-yellow-green NDVI"), "rdylgn")
        self.assertIsNone(pilot.named_colormap("jet or viridis?"))
        self.assertIsNone(pilot.named_colormap("show the jetty"))

    def test_caps_action_count(self):
        self.assertEqual(len(pilot.clean_actions([{"type": "wait", "seconds": 1}] * 20)), pilot.MAX_ACTIONS)

    def test_planet_scale_and_layers(self):
        out = pilot.clean_actions([{"type": "orbit", "place": "Tycho", "radius_m": 60000, "alt_m": 1e9},
                                   {"type": "show_layer", "kind": "geology", "place": "Tycho"},
                                   {"type": "show_layer", "kind": "elevation", "place": "Tycho", "distance_km": 200},
                                   {"type": "hide_layer"}], body="moon")
        self.assertEqual(out, [{"type": "show_layer", "kind": "elevation", "place": "Tycho", "radius_m": 200000.0},
                               {"type": "orbit", "place": "Tycho", "radius_m": 60000.0, "alt_m": 500000.0},
                               {"type": "hide_layer"}])

    def test_layers_per_body(self):
        plan = [{"type": "show_layer", "kind": "slope"}, {"type": "show_layer", "kind": "elevation"}]
        self.assertEqual(pilot.clean_actions(plan, body="mars"), [{"type": "show_layer", "kind": "elevation"}])
        self.assertEqual(pilot.clean_actions(plan + [{"type": "hide_layer"}], body="europa"), [])
        self.assertIn("no data layers", pilot.planet_prompt("europa"))
        self.assertIn("- slope:", pilot.planet_prompt("moon"))
        self.assertNotIn("- slope:", pilot.planet_prompt("mars"))


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
                                                         {"type": "show_layer", "kind": "faults"},
                                                         {"type": "show_layer", "kind": "elevation"}]}
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)) as post:
            resp = self.post({"message": "orbit tycho with an elevation heat map", "body": "moon"})
        self.assertEqual(resp.json()["actions"], [{"type": "show_layer", "kind": "elevation"},
                                                  {"type": "orbit", "place": "Tycho"}])
        args = post.call_args.kwargs["json"]["params"]["arguments"]
        self.assertEqual(args["json_schema"], pilot.PLANET_LAYER_SCHEMAS["moon"])
        self.assertIn("3D globe of the Moon", args["system_prompt"])
        kinds = args["json_schema"]["properties"]["actions"]["items"]["properties"]["kind"]["enum"]
        self.assertEqual(kinds, ["elevation", "slope", "contours"])

    def test_body_without_layers_gets_no_layer_schema(self):
        self.client.force_login(self.user)
        plan = {"reply": "ok", "actions": []}
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)) as post:
            self.post({"message": "show elevation", "body": "europa"})
        args = post.call_args.kwargs["json"]["params"]["arguments"]
        self.assertEqual(args["json_schema"], pilot.PLANET_SCHEMA)
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

    def test_promised_but_empty_plan_is_retried_once(self):
        self.client.force_login(self.user)
        empty = {"reply": "Pulling up the chlorophyll for Monterey Bay.", "actions": []}
        good = {"reply": "Showing chlorophyll.", "actions": [{"type": "show_layer", "kind": "chlorophyll",
                                                               "place": "Monterey Bay, California"}]}
        with mock.patch.object(pilot.requests, "post", side_effect=[mcp_response(empty), mcp_response(good)]) as post:
            resp = self.post({"message": "show chlorophyll in monterey bay"})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(resp.json()["actions"], good["actions"])
        with mock.patch.object(pilot.requests, "post", side_effect=[mcp_response(empty)] * 2) as post:
            resp = self.post({"message": "show chlorophyll in monterey bay"})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(resp.json()["reply"], empty["reply"])
        self.assertEqual(resp.json()["actions"], [])

    def test_history_plans_go_back_in_schema_order(self):
        self.client.force_login(self.user)
        old = {"reply": "SST.", "actions": [{"type": "show_layer", "place": "Monterey Bay", "seconds": 0, "kind": "sea_temp"}]}
        history = [{"role": "user", "content": "sst"}, {"role": "assistant", "content": json.dumps(old)},
                   {"role": "assistant", "content": "plain text"}]
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response({"reply": "ok", "actions": []})) as post:
            self.post({"message": "hi", "history": history})
        sent = post.call_args.kwargs["json"]["params"]["arguments"]["history"]
        self.assertEqual(json.loads(sent[1]["content"]),
                         {"reply": "SST.", "actions": [{"type": "show_layer", "kind": "sea_temp", "place": "Monterey Bay"}]})
        self.assertTrue(sent[1]["content"].index('"kind"') < sent[1]["content"].index('"place"'))
        self.assertEqual(sent[2]["content"], "plain text")

    def test_colormap_named_in_message_applies_to_colour_layers(self):
        self.client.force_login(self.user)
        plan = {"reply": "ok", "actions": [{"type": "show_layer", "kind": "sea_temp", "place": "Monterey Bay"},
                                           {"type": "show_layer", "kind": "ndvi", "colormap": "viridis"},
                                           {"type": "show_layer", "kind": "faults"}]}
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)):
            resp = self.post({"message": "water temperature and vegetation in jet"})
        self.assertEqual(resp.json()["actions"], [
            {"type": "show_layer", "kind": "sea_temp", "place": "Monterey Bay", "colormap": "jet"},
            {"type": "show_layer", "kind": "ndvi", "colormap": "jet"},
            {"type": "show_layer", "kind": "faults"}])
        self.assertEqual(list(resp.json()["actions"][0]), ["type", "kind", "place", "colormap"])

    def test_answer_without_actions_is_not_retried(self):
        self.client.force_login(self.user)
        plan = {"reply": "NDVI is a vegetation index from red and near-infrared light.", "actions": []}
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)) as post:
            resp = self.post({"message": "what is ndvi?"})
        self.assertEqual(post.call_count, 1)
        self.assertEqual(resp.json()["actions"], [])

    def test_rate_limited(self):
        self.client.force_login(self.user)
        plan = {"reply": "ok", "actions": []}
        with mock.patch.object(pilot.requests, "post", return_value=mcp_response(plan)):
            codes = [self.post({"message": "hi"}).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])


OCEAN_URL = "/label/api/pilot/ocean/"
BOX = {"south": "36.6", "north": "37.0", "west": "-122.2", "east": "-121.8"}


def erddap_response(rows):
    resp = mock.Mock(status_code=200)
    resp.json = mock.Mock(return_value={"table": {"rows": rows}})
    resp.raise_for_status = mock.Mock()
    return resp


class PilotOceanTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="pilot", password="pw")
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(OCEAN_URL, {"kind": "sea_temp", **BOX}).status_code, 401)

    def test_rejects_bad_requests(self):
        self.assertEqual(self.client.get(OCEAN_URL, {"kind": "salinity", **BOX}).status_code, 400)
        self.assertEqual(self.client.get(OCEAN_URL, {"kind": "sea_temp", "south": "36"}).status_code, 400)
        self.assertEqual(self.client.get(OCEAN_URL, {"kind": "sea_temp", **BOX, "north": "nan"}).status_code, 400)
        self.assertEqual(self.client.get(OCEAN_URL, {"kind": "sea_temp", **BOX, "north": "50"}).status_code, 400)
        self.assertEqual(self.client.post(OCEAN_URL, {"kind": "sea_temp", **BOX}).status_code, 405)

    def test_chlorophyll_grid_and_cache(self):
        # This dataset has an altitude axis and stores latitude north to south
        rows = [["2026-10-09T12:00:00Z", 0, 37.0, -122.2, 1.5], ["2026-10-09T12:00:00Z", 0, 37.0, -121.8, None],
                ["2026-10-09T12:00:00Z", 0, 36.6, -122.2, 0.4], ["2026-10-09T12:00:00Z", 0, 36.6, -121.8, 9.25]]
        with mock.patch.object(pilot.requests, "get", return_value=erddap_response(rows)) as get:
            first = self.client.get(OCEAN_URL, {"kind": "chlorophyll", **BOX}).json()
            second = self.client.get(OCEAN_URL, {"kind": "chlorophyll", **BOX}).json()
        self.assertEqual(get.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["lat"], [36.6, 37.0])
        self.assertEqual(first["lon"], [-122.2, -121.8])
        self.assertEqual(first["values"], [[0.4, 9.25], [1.5, None]])
        self.assertEqual(first["time"], "2026-10-09T12:00:00Z")
        url = get.call_args.args[0]
        self.assertTrue(url.startswith("https://coastwatch.noaa.gov/erddap/griddap/noaacwNPPN20S3ASCIDINEOF2kmDaily.json?"))
        self.assertIn("chlor_a%5B(last)%5D%5B(0.0)%5D%5B(37.0):1:(36.6)%5D%5B(-122.2):1:(-121.8)%5D", url)

    def test_large_areas_are_subsampled(self):
        url, stride = pilot.ocean_query(pilot.OCEAN_DATASETS["sea_temp"], 30.0, 34.0, -124.0, -120.0)
        self.assertEqual(stride, 3)
        self.assertIn("analysed_sst%5B(last)%5D%5B(30.0):3:(34.0)%5D%5B(-124.0):3:(-120.0)%5D", url)

    def test_upstream_error_is_retried_then_502(self):
        with mock.patch.object(pilot.requests, "get", side_effect=pilot.requests.Timeout("slow")) as get:
            resp = self.client.get(OCEAN_URL, {"kind": "sea_temp", **BOX})
        self.assertEqual(get.call_count, 2)
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn("slow", resp.json()["error"])
        busy = mock.Mock(status_code=503)
        ok = erddap_response([["2026-10-22T09:00:00Z", 36.6, -122.2, 18.1]])
        with mock.patch.object(pilot.requests, "get", side_effect=[busy, ok]):
            self.assertEqual(self.client.get(OCEAN_URL, {"kind": "sea_temp", **BOX}).json()["values"], [[18.1]])
        missing = mock.Mock(status_code=404)
        with mock.patch.object(pilot.requests, "get", return_value=missing) as get:
            resp = self.client.get(OCEAN_URL, {"kind": "chlorophyll", **BOX})
        self.assertEqual((get.call_count, resp.status_code), (1, 502))
        self.assertIn("HTTP 404", resp.json()["error"])
