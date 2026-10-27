import hashlib
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import Client, TestCase, override_settings

from deepgis_xr.apps.web.views import vehicles

POSE_URL = "/label/api/vehicles/pose/"
LIVE_URL = "/label/api/vehicles/live/"
TOKEN = "twin-secret-token"
OTHER = "boat-secret-token"


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


TWIN_POSE = {
    "vehicle": "locutus", "name": "Locutus (OpenUAV PX4 SITL twin)", "kind": "sim",
    "lat": 37.4593, "lon": -118.4445, "up_m": 20.0, "alt_amsl": 1421.7,
    "ref": {"lat": 37.45934746, "lon": -118.44445906, "alt_amsl": 1401.72},
    "heading_deg": 154.6, "gimbal_pitch_deg": -90.0, "hfov_deg": 114.6, "speed_mps": 0.1,
    "armed": True, "landed": False,
}


@override_settings(
    VEHICLE_POSE_TOKENS=f"locutus:{digest(TOKEN)}, boat1:{digest(OTHER)}, bad entry",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            "live": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "vehicles-test"}},
)
class VehiclePoseTests(TestCase):
    def setUp(self):
        caches["live"].clear()
        self.user = get_user_model().objects.create_user(username="viewer", password="pw")
        self.client = Client(enforce_csrf_checks=True)

    def post(self, payload, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        return self.client.post(POSE_URL, body, content_type="application/json", **headers)

    def test_needs_a_token_for_its_own_vehicle(self):
        self.assertEqual(self.post(TWIN_POSE, token=None).status_code, 401)
        self.assertEqual(self.post(TWIN_POSE, token="wrong").status_code, 401)
        self.assertEqual(self.post(TWIN_POSE, token=OTHER).status_code, 403)
        with override_settings(VEHICLE_POSE_TOKENS=""):
            self.assertEqual(self.post(TWIN_POSE).status_code, 503)
        self.assertEqual(self.client.get(POSE_URL).status_code, 405)

    def test_rejects_bad_bodies(self):
        self.assertEqual(self.post("not json").status_code, 400)
        self.assertEqual(self.post([1, 2]).status_code, 400)
        self.assertEqual(self.post({"lat": 91, "lon": 0}).status_code, 400)
        self.assertEqual(self.post({"lat": "37", "lon": -118}).status_code, 400)
        self.assertEqual(self.post({"lat": 37, "lon": -118, "name": "x" * 5000}).status_code, 413)

    def test_live_list_is_for_signed_in_users(self):
        self.assertEqual(self.post(TWIN_POSE).status_code, 200)
        self.assertEqual(self.client.get(LIVE_URL).status_code, 401)
        self.client.force_login(self.user)
        resp = self.client.get(LIVE_URL)
        self.assertEqual(resp.status_code, 200)
        [pose] = resp.json()["vehicles"]
        expected = {k: v for k, v in TWIN_POSE.items() if k != "vehicle"}
        self.assertEqual({k: v for k, v in pose.items() if k not in ("id", "age_sec")}, expected)
        self.assertEqual(pose["id"], "locutus")
        self.assertLess(pose["age_sec"], 5)

    def test_bad_fields_are_dropped_not_clamped(self):
        pose = {"lat": 37.0, "lon": -118.0, "up_m": float("1e9"), "gimbal_pitch_deg": -120,
                "hfov_deg": True, "heading_deg": 90, "kind": "tank", "armed": "yes",
                "ref": {"lat": 200, "lon": 0}, "name": "  "}
        self.assertEqual(vehicles.clean_pose(pose), {"lat": 37.0, "lon": -118.0, "heading_deg": 90.0})

    def test_newest_first_and_silent_vehicles_expire(self):
        self.client.force_login(self.user)
        with mock.patch.object(vehicles, "now", return_value=1000.0):
            self.post(TWIN_POSE)
        with mock.patch.object(vehicles, "now", return_value=1010.0):
            self.post({"vehicle": "boat1", "lat": 33.43, "lon": -111.93, "kind": "field"}, token=OTHER)
            listed = self.client.get(LIVE_URL).json()["vehicles"]
        self.assertEqual([(p["id"], p["age_sec"]) for p in listed], [("boat1", 0.0), ("locutus", 10.0)])
        caches["live"].delete("vehicle:locutus")  # what the 60 s expiry does
        self.assertEqual([p["id"] for p in self.client.get(LIVE_URL).json()["vehicles"]], ["boat1"])
