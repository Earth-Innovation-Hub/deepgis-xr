import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import Client, TestCase, override_settings
from PIL import Image

from deepgis_xr.apps.web.views import acquisition, vehicles

FRAME_URL = "/label/api/vehicles/frame/"
PRODUCT_URL = "/label/api/vehicles/product/"
TOKEN = "rover-secret-token"
TEMPE = (33.42, -111.93)
AFTERNOON = datetime(2026, 11, 10, 21, 25, tzinfo=timezone.utc).timestamp()  # 14:25 in Tempe
NIGHT = datetime(2026, 11, 11, 7, 0, tzinfo=timezone.utc).timestamp()        # midnight in Tempe

SPECTRUM = {
    "wl0": 300.0, "dwl": 1.0, "counts": [100 + i for i in range(574)], "full_scale": 62434, "baseline": 2066,
    "integration_ms": 31.0, "clipped": [], "clipped_pct": 0.0, "peak_frac": 0.78,
    "indices": {"nir_red": 0.055},
    "laser": {"n": 5, "valid": 1.0, "range_m": 3.9, "min_m": 3.8, "max_m": 4.0},
    "footprint": {"u": 0.5, "v": 0.5, "fov_deg": 14.0, "diameter_m": 0.96},
    "acquisition": {"auto": True, "scans": 12, "target": 0.8, "band": [300, 874], "window_ms": 400,
                    "band_peak": 0.79, "source": "default", "reason": ""},
    "notes": [],
}


def jpeg():
    buf = BytesIO()
    Image.new("RGB", (64, 36), (90, 140, 60)).save(buf, "JPEG")
    return buf.getvalue()


def utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc).timestamp()


class SunPositionTests(TestCase):
    def day(self, start):
        """(elevation, azimuth, solar time) every minute for 24 h from start, at Tempe."""
        return [acquisition.sun_position(start + 60 * i, *TEMPE) for i in range(1440)]

    def test_noon_height_follows_the_season(self):
        # at local noon the sun stands 90 - latitude + declination above the horizon, due south
        for start, top in ((utc(2026, 6, 21, 7), 90 - 33.42 + 23.44), (utc(2026, 12, 21, 7), 90 - 33.42 - 23.44)):
            elevation, azimuth, solar_time = max(self.day(start))
            self.assertAlmostEqual(elevation, top, delta=0.2)
            self.assertAlmostEqual(azimuth, 180.0, delta=2.0)
            self.assertAlmostEqual(solar_time, 12.0, delta=0.05)

    def test_rises_in_the_east_and_sets_in_the_west(self):
        day = self.day(utc(2026, 3, 20, 7))  # the equinox, from local midnight
        self.assertLess(day[0][0], -50)
        rise = next(i for i in range(1, 1440) if day[i - 1][0] < 0 <= day[i][0])
        sets = next(i for i in range(rise, 1440) if day[i - 1][0] >= 0 > day[i][0])
        self.assertAlmostEqual(day[rise][1], 90.0, delta=1.5)
        self.assertAlmostEqual(day[sets][1], 270.0, delta=1.5)
        self.assertAlmostEqual((sets - rise) / 60.0, 12.0, delta=0.2)  # no refraction: 12 h of day
        self.assertTrue(all(a[1] < b[1] for a, b in zip(day[rise:sets], day[rise + 1:sets])))  # east, south, west

    def test_the_afternoon_used_below(self):
        elevation, azimuth, solar_time = acquisition.sun_position(AFTERNOON, *TEMPE)
        self.assertAlmostEqual(elevation, 30.0, delta=2.0)
        self.assertAlmostEqual(azimuth, 217.0, delta=3.0)
        self.assertAlmostEqual(solar_time, 14.2, delta=0.2)


class RulePolicyTests(TestCase):
    def ctx(self, **change):
        return {"lat": TEMPE[0], "lon": TEMPE[1], "t": AFTERNOON, "speed_mps": 0.0, "sun_elevation_deg": 30.0,
                "sun_azimuth_deg": 217.0, "solar_time_h": 14.2, "heading_deg": 40.0, "sun_relative_deg": 177.0,
                "range_m": 3.83, "patch_m": 0.94, **change}

    def test_parked_with_the_sun_behind_uses_the_scale(self):
        policy = acquisition.rule_policy(self.ctx())
        self.assertEqual((policy["target"], policy["band"], policy["window_ms"]), (0.85, "full", 400))
        self.assertIn("parked", policy["why"])

    def test_facing_a_low_sun_keeps_headroom(self):
        self.assertEqual(acquisition.rule_policy(self.ctx(heading_deg=220.0, sun_relative_deg=-3.0))["target"], 0.6)
        high = self.ctx(heading_deg=220.0, sun_relative_deg=-3.0, sun_elevation_deg=70.0)
        self.assertEqual(acquisition.rule_policy(high)["target"], 0.85)  # a high sun is not in the view

    def test_a_moving_rover_reads_within_a_share_of_its_patch(self):
        policy = acquisition.rule_policy(self.ctx(speed_mps=2.0))
        self.assertEqual(policy["target"], 0.7)
        self.assertAlmostEqual(policy["window_ms"], 1000 * 0.25 * 0.94 / 2.0, delta=1)
        fast = acquisition.rule_policy(self.ctx(speed_mps=20.0))
        self.assertEqual(fast["window_ms"], acquisition.WINDOW_LIMITS_MS[0])
        no_range = self.ctx(speed_mps=2.0)
        del no_range["patch_m"]
        self.assertEqual(acquisition.rule_policy(no_range)["window_ms"], 400)

    def test_night_and_missing_heading(self):
        self.assertIn("sun is down", acquisition.rule_policy(self.ctx(sun_elevation_deg=-20.0))["why"])
        blind = self.ctx()
        del blind["heading_deg"], blind["sun_relative_deg"]
        self.assertEqual(acquisition.rule_policy(blind)["target"], 0.85)

    def test_the_models_answer_is_clamped(self):
        base = acquisition.rule_policy(self.ctx())
        wild = {"target_peak": 5, "band": "x-ray", "window_ms": 99999, "patch": " tree\n foliage ", "reason": "r" * 500}
        got = acquisition.clean_judgement(wild, base, False)
        self.assertEqual((got["target"], got["band"], got["window_ms"], got["patch"]), (0.9, "full", 400, "tree foliage"))
        self.assertEqual(len(got["reason"]), 200)
        low = acquisition.clean_judgement({"target_peak": 0.1, "band": "red_edge", "window_ms": 1}, base, False)
        self.assertEqual((low["target"], low["band"], low["window_ms"]), (0.5, "red_edge", 30))
        for bad in (None, "0.8", {"band": "full"}, {"target_peak": "high"}, {"target_peak": float("nan")}):
            self.assertIsNone(acquisition.clean_judgement(bad, base, False))
        # in motion the model may only be more cautious than the rules
        moving = acquisition.rule_policy(self.ctx(speed_mps=2.0))
        got = acquisition.clean_judgement({"target_peak": 0.9, "band": "red_edge", "window_ms": 400}, moving, True)
        self.assertEqual((got["target"], got["band"], got["window_ms"]), (0.7, "full", moving["window_ms"]))
        got = acquisition.clean_judgement({"target_peak": 0.55, "band": "full", "window_ms": 40}, moving, True)
        self.assertEqual((got["target"], got["window_ms"]), (0.55, 40))


@override_settings(
    VEHICLE_POSE_TOKENS="santacruz:" + hashlib.sha256(TOKEN.encode()).hexdigest(),
    VEHICLE_FLEET_SECRET="",
    VEHICLE_ENROLL_SECRET="",
    DEEPGIS_PILOT_MCP_TOKEN="test-token",
    DEEPGIS_ACQUISITION_ADVICE="llm",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            "live": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "acquisition-test"}},
)
class AcquisitionAdviceTests(TestCase):
    def setUp(self):
        caches["live"].clear()
        self.client = Client(enforce_csrf_checks=True)
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}
        self.answer = {"patch": "tree foliage in even light", "target_peak": 0.88, "band": "red_edge",
                       "window_ms": 350, "reason": "Foliage fills the patch and the light is even."}
        ran = mock.patch.object(acquisition, "run_async", side_effect=lambda fn: fn())  # the model answers at once
        self.call = mock.patch.object(acquisition.pilot, "call_mcp_tool",
                                      side_effect=lambda *a, **k: {"json": self.answer, "model": "gemma-test"})
        ran.start()
        self.mcp = self.call.start()
        self.addCleanup(ran.stop)
        self.addCleanup(self.call.stop)

    def read(self, t=AFTERNOON, heading=40.0, speed=0.0, lat=TEMPE[0], data=SPECTRUM, frame=True):
        """The rover posts a frame and then its spectrum, as the keyframe publisher does."""
        with mock.patch.object(vehicles, "now", return_value=t):
            if frame:
                meta = {"vehicle": "santacruz", "lat": lat, "lon": TEMPE[1], "heading_deg": heading, "speed_mps": speed}
                sent = self.client.post(FRAME_URL, jpeg(), content_type="image/jpeg",
                                        HTTP_X_FRAME_META=json.dumps(meta), **self.auth)
                self.assertEqual(sent.status_code, 200)
            resp = self.client.post(PRODUCT_URL, json.dumps({"vehicle": "santacruz", "product": "spectrum", "data": data}),
                                    content_type="application/json", **self.auth)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_no_position_no_advice(self):
        self.assertEqual(self.read(frame=False), {"ok": True, "seq": 1})
        self.mcp.assert_not_called()

    @override_settings(DEEPGIS_ACQUISITION_ADVICE="off")
    def test_it_can_be_switched_off(self):
        self.assertEqual(self.read(), {"ok": True, "seq": 1})
        self.mcp.assert_not_called()

    @override_settings(DEEPGIS_ACQUISITION_ADVICE="rules")
    def test_rules_alone(self):
        advice = self.read()["advice"]
        self.assertEqual((advice["target"], advice["band"], advice["window_ms"], advice["source"]),
                         (0.85, [300.0, 874.0], 400, "deepgis:rules"))
        self.assertEqual(advice["ttl_s"], acquisition.ADVICE_ROBOT_TTL_SEC)
        self.assertIn("sun behind the camera", advice["reason"])
        self.assertEqual(self.read(heading=220.0)["advice"]["target"], 0.6)  # now it looks toward the sun
        self.assertEqual(self.read(speed=2.0)["advice"]["window_ms"], 120)  # a quarter of 0.96 m at 2 m/s
        self.mcp.assert_not_called()

    def test_the_model_refines_the_rules_from_the_frame(self):
        first = self.read()["advice"]  # the model is asked; this reply still carries the rules
        self.assertEqual(first["source"], "deepgis:rules")
        name, args, timeout = self.mcp.call_args.args
        self.assertEqual(name, "describe_image")
        self.assertTrue(args["image"].startswith("/9j/"))  # the frame it just posted, as base64 JPEG
        self.assertEqual(args["json_schema"], acquisition.ADVICE_SCHEMA)
        self.assertNotIn("model", args)  # the lab's bridge chooses, unless a model is named
        for text in ("2026-11-10 21:25 UTC, local solar time 14:", "degrees above the horizon at azimuth 2",
                     "behind the camera (front-lit scene)", "Rover: parked.",
                     "the laser measures 3.9 m to it and the patch is about 1.0 m across",
                     "Its last reading: 12 scans of 31 ms, brightest pixel at 78% of full scale, 0% of the visible range clipped.",
                     "Baseline from the geometry: target_peak 0.85, band full, window_ms 400 (parked, sun behind the camera)."):
            self.assertIn(text, args["prompt"])
        second = self.read()["advice"]
        self.assertEqual((second["target"], second["band"], second["window_ms"], second["source"], second["reason"]),
                         (0.88, [650.0, 800.0], 350, "deepgis:llm", "Foliage fills the patch and the light is even."))
        self.read()
        self.assertEqual(self.mcp.call_count, 1)  # its judgement is reused while nothing changes

    @override_settings(DEEPGIS_ACQUISITION_MODEL="gemma-test")
    def test_a_named_model_is_asked_for(self):
        self.read()
        self.assertEqual(self.mcp.call_args.args[1]["model"], "gemma-test")

    def test_a_change_of_scene_goes_back_to_the_rules_until_the_model_is_asked_again(self):
        self.read()
        self.assertEqual(self.read()["advice"]["source"], "deepgis:llm")
        for change in ({"heading": 130.0}, {"speed": 2.0}, {"lat": TEMPE[0] + 0.0003}, {"t": AFTERNOON + 3600}):
            self.assertEqual(self.read(**change)["advice"]["source"], "deepgis:rules", change)
        self.assertEqual(self.mcp.call_count, 1)  # asked at most once per ADVICE_MIN_INTERVAL_SEC
        caches["live"].delete("advice_try:santacruz")
        self.answer = {**self.answer, "target_peak": 0.9, "band": "red_edge", "window_ms": 400}
        self.read(speed=2.0)
        self.assertEqual(self.mcp.call_count, 2)
        moving = self.read(speed=2.0)["advice"]  # in motion its answer cannot exceed the rules'
        self.assertEqual((moving["target"], moving["band"], moving["window_ms"], moving["source"]),
                         (0.7, [300.0, 874.0], 120, "deepgis:llm"))

    def test_a_silent_or_confused_model_leaves_the_rules_in_charge(self):
        self.mcp.side_effect = RuntimeError("tool error")
        self.read()
        self.assertEqual(self.read()["advice"]["source"], "deepgis:rules")
        caches["live"].delete("advice_try:santacruz")
        self.mcp.side_effect = lambda *a, **k: {"json": {"band": "full"}, "model": "gemma-test"}
        self.read()
        self.assertEqual(self.read()["advice"]["source"], "deepgis:rules")

    def test_the_model_is_not_asked_at_night(self):
        advice = self.read(t=NIGHT)["advice"]
        self.assertEqual((advice["source"], advice["window_ms"]), ("deepgis:rules", 400))
        self.assertIn("sun is down", advice["reason"])
        self.mcp.assert_not_called()

    def test_viewers_see_the_reading_with_its_exposure_and_the_advice(self):
        self.read()
        self.read()
        self.client.force_login(get_user_model().objects.create_user(username="viewer", password="pw"))
        with mock.patch.object(vehicles, "now", return_value=AFTERNOON + 4):
            product = self.client.get("/label/api/vehicles/santacruz/product/spectrum.json").json()
        self.assertEqual(product["data"]["acquisition"], {
            "auto": True, "scans": 12.0, "target": 0.8, "band": [300.0, 874.0], "window_ms": 400.0, "band_peak": 0.79,
            "source": "default"})
        advice = product["advice"]
        self.assertEqual((advice["source"], advice["patch"], advice["model"], advice["age_sec"]),
                         ("deepgis:llm", "tree foliage in even light", "gemma-test", 4.0))
        self.assertAlmostEqual(advice["sun"]["sun_elevation_deg"], 30.0, delta=2.0)
        self.assertAlmostEqual(advice["sun"]["sun_relative_deg"], 177.0, delta=3.0)

    def test_a_malformed_exposure_is_dropped_not_trusted(self):
        messy = {**SPECTRUM, "acquisition": {"auto": "yes", "scans": 0, "target": 7, "band": [900, 300],
                                             "source": "  a\n b ", "reason": 5, "extra": 1}}
        self.assertEqual(vehicles.clean_spectrum(messy)["acquisition"], {"auto": False, "source": "a b"})
        self.assertNotIn("acquisition", vehicles.clean_spectrum({**SPECTRUM, "acquisition": [1]}))
