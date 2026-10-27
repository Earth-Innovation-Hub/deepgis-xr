import hashlib
import json
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import Client, TestCase, override_settings
from PIL import Image

from deepgis_xr.apps.web.views import vehicles

POSE_URL = "/label/api/vehicles/pose/"
LIVE_URL = "/label/api/vehicles/live/"
FRAME_URL = "/label/api/vehicles/frame/"
TOKEN = "twin-secret-token"
OTHER = "boat-secret-token"


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def make_jpeg(color=(200, 120, 40)):
    buf = BytesIO()
    Image.new("RGB", (64, 36), color).save(buf, "JPEG")
    return buf.getvalue()


JPEG = make_jpeg()


TWIN_POSE = {
    "vehicle": "locutus", "name": "Locutus (OpenUAV PX4 SITL twin)", "kind": "sim",
    "lat": 37.4593, "lon": -118.4445, "up_m": 20.0, "alt_amsl": 1421.7,
    "ref": {"lat": 37.45934746, "lon": -118.44445906, "alt_amsl": 1401.72},
    "heading_deg": 154.6, "gimbal_pitch_deg": -90.0, "hfov_deg": 114.6, "speed_mps": 0.1,
    "armed": True, "landed": False,
}


@override_settings(
    VEHICLE_POSE_TOKENS=f"locutus:{digest(TOKEN)}, boat1:{digest(OTHER)}, bad entry",
    VEHICLE_FLEET_SECRET="",
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
        self.assertEqual(caches["live"].get(vehicles.IDS_KEY), ["boat1"])

    @override_settings(VEHICLE_FLEET_SECRET="fleet-secret", VEHICLE_FLEET_PREFIX="openuav-")
    def test_launched_sims_post_only_as_themselves(self):
        sim = {"vehicle": "openuav-alice", "lat": 47.3979, "lon": 8.5461, "up_m": 12.0, "kind": "sim"}
        alice = vehicles.fleet_token("fleet-secret", "openuav-alice")
        self.assertEqual(self.post(sim, token=alice).status_code, 200)
        self.assertEqual(self.post({**sim, "vehicle": "openuav-bob"}, token=alice).status_code, 401)
        self.assertEqual(self.post({**sim, "vehicle": "locutus"}, token=alice).status_code, 401)
        self.assertEqual(self.post({k: v for k, v in sim.items() if k != "vehicle"}, token=alice).status_code, 401)
        locutus_as_fleet = vehicles.fleet_token("fleet-secret", "locutus")
        self.assertEqual(self.post({**sim, "vehicle": "locutus"}, token=locutus_as_fleet).status_code, 401)
        self.assertEqual(self.post(sim, token=TOKEN).status_code, 403)  # the twin's token, another id
        with override_settings(VEHICLE_POSE_TOKENS=""):
            self.assertEqual(self.post(sim, token=alice).status_code, 200)
        self.client.force_login(self.user)
        [pose] = self.client.get(LIVE_URL).json()["vehicles"]
        self.assertEqual((pose["id"], pose["up_m"]), ("openuav-alice", 12.0))

    def post_frame(self, jpeg, meta=None, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        if meta is not None:
            headers["HTTP_X_FRAME_META"] = meta if isinstance(meta, str) else json.dumps(meta)
        return self.client.post(FRAME_URL, jpeg, content_type="image/jpeg", **headers)

    def test_frames_need_the_vehicles_token_and_a_jpeg(self):
        meta = {"vehicle": "locutus"}
        self.assertEqual(self.post_frame(JPEG, meta, token=None).status_code, 401)
        self.assertEqual(self.post_frame(JPEG, meta, token="wrong").status_code, 401)
        self.assertEqual(self.post_frame(JPEG, meta, token=OTHER).status_code, 403)
        self.assertEqual(self.post_frame(JPEG, "[1]").status_code, 400)
        self.assertEqual(self.post_frame(JPEG, "{bad").status_code, 400)
        self.assertEqual(self.post_frame(JPEG, None, token=OTHER).status_code, 200)  # metadata is optional
        self.assertEqual(self.post_frame(b"\x89PNG\r\n\x1a\n" + JPEG, meta).status_code, 400)
        self.assertEqual(self.post_frame(b"\xff\xd8\xff" + b"0" * 100, meta).status_code, 400)
        self.assertEqual(self.post_frame(JPEG + b"0" * vehicles.FRAME_MAX_BYTES, meta).status_code, 413)
        with override_settings(VEHICLE_POSE_TOKENS=""):
            self.assertEqual(self.post_frame(JPEG, meta).status_code, 503)
        self.assertEqual(self.client.get(FRAME_URL).status_code, 405)

    def test_signed_in_viewers_get_the_latest_frame(self):
        self.assertEqual(self.post(TWIN_POSE).status_code, 200)
        image_url = "/label/api/vehicles/locutus/frame.jpg"
        self.assertEqual(self.client.get(image_url).status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(image_url).status_code, 404)
        self.assertNotIn("frame", self.client.get(LIVE_URL).json()["vehicles"][0])
        meta = {"vehicle": "locutus", "captured": 1e9, "lat": 37.4593, "lon": -118.4445, "hfov_deg": 114.6}
        self.assertEqual(self.post_frame(JPEG, meta).json(), {"ok": True, "seq": 1})
        newer = make_jpeg(color=(0, 90, 200))
        self.assertEqual(self.post_frame(newer, {}).json(), {"ok": True, "seq": 2})
        [pose] = self.client.get(LIVE_URL).json()["vehicles"]
        self.assertEqual({k: pose["frame"][k] for k in ("seq", "w", "h")}, {"seq": 2, "w": 64, "h": 36})
        resp = self.client.get(image_url)
        self.assertEqual((resp.status_code, resp["Content-Type"], resp.content), (200, "image/jpeg", newer))
        self.assertIn("no-store", resp["Cache-Control"])
        self.assertEqual(self.client.get("/label/api/vehicles/BAD!/frame.jpg").status_code, 404)

    def test_frame_keeps_the_pose_at_capture(self):
        with mock.patch.object(vehicles, "now", return_value=2000.0):
            self.post_frame(JPEG, {"vehicle": "locutus", "captured": 1999.5, "lat": 37.4593,
                                   "lon": -118.4445, "up_m": 20.0, "heading_deg": 90})
        info = caches["live"].get("frame_info:locutus")
        self.assertEqual(info["captured"], 1999.5)
        self.assertEqual(info["pose"], {"lat": 37.4593, "lon": -118.4445, "up_m": 20.0, "heading_deg": 90.0})
        with mock.patch.object(vehicles, "now", return_value=2000.0):
            self.post_frame(JPEG, {"captured": 1.0, "lat": 999, "lon": 0})
        info = caches["live"].get("frame_info:locutus")
        self.assertNotIn("captured", info)
        self.assertNotIn("pose", info)
