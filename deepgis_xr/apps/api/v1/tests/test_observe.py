"""Integration tests for ``POST /api/observe`` + ``GET /api/scene-graph`` (PR-6).

These exercise the full earth_rover -> deepgis -> client path: the test
builds packed superquadric bytes via the same kernelcal codec the
earth_rover uses, POSTs them with a UTM ``FrameSpec`` envelope, and
then verifies a Cesium-style WGS84 client can pull the same scene back
inside a bbox -- with each SQ correctly re-projected and a binary
re-pack that round-trips through the codec.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Tuple

import numpy as np
from django.test import TestCase
from django.urls import reverse


# ---------------------------------------------------------------------------
# Fixture helpers (lazy kernelcal imports keep module-load fast and avoid
# hard test-time coupling on environments without kernelcal installed).
# ---------------------------------------------------------------------------


def _kc():
    from kernelcal.distinction_game.geometry import (  # noqa: PLC0415
        FrameSpec,
        PropertyId,
        Superquadric,
        compress_spectrum,
        pack_superquadric,
        superquadric_box,
        superquadric_cylinder,
        superquadric_ellipsoid,
        unpack_superquadric,
    )

    return {
        "FrameSpec": FrameSpec,
        "PropertyId": PropertyId,
        "Superquadric": Superquadric,
        "compress_spectrum": compress_spectrum,
        "pack_superquadric": pack_superquadric,
        "superquadric_box": superquadric_box,
        "superquadric_cylinder": superquadric_cylinder,
        "superquadric_ellipsoid": superquadric_ellipsoid,
        "unpack_superquadric": unpack_superquadric,
    }


#: Origin LLA used for the test ENU station (Tempe Town Lake area).
#:
#: The earth_rover producer is expected to pack SQs in a local frame
#: (ENU at a station origin or a tile centre), *not* in raw UTM,
#: because the codec's translation field is int32 mm = +/- 2,000 km
#: and a UTM northing of ~3,700 km would clip.  This origin is the
#: same convention the earth_rover ROS2 publisher will use.
_PHX_ORIGIN_LLA: Tuple[float, float, float] = (33.4258, -111.9400, 350.0)


def _phoenix_local_scene() -> Tuple[List, List[int]]:
    """Build a small Phoenix scene in ENU local frame: a tree + a building."""
    kc = _kc()
    # All SQs are within ~50 m of the station origin.
    trunk = kc["superquadric_cylinder"](
        base=(0.0, 0.0, 0.0),
        axis=(0.0, 0.0, 1.0),
        radius=0.20,
        height=4.0,
    )
    crown = kc["superquadric_ellipsoid"](
        center=(0.0, 0.0, 4.0),
        axes=(2.0, 2.0, 1.5),
    )
    crown.parent_id = trunk.id
    building = kc["superquadric_box"](
        center=(15.0, 12.0, 4.0),
        size=(8.0, 6.0, 8.0),
    )
    sqs = [trunk, crown, building]
    class_idx = [10, 11, 20]  # arbitrary class ids
    return sqs, class_idx


def _phoenix_local_envelope_frame() -> Dict[str, Any]:
    return {
        "kind": "enu_local",
        "params": {"origin_lla": list(_PHX_ORIGIN_LLA)},
        "name": "earth_rover/station_phx",
    }


def _pack_payload(sqs, class_idx, with_properties: bool = True) -> bytes:
    """Concatenate packed-SQ bytes the way the earth_rover would."""
    kc = _kc()
    PropertyId = kc["PropertyId"]
    out = bytearray()
    for sq, ci in zip(sqs, class_idx):
        props = None
        if with_properties:
            props = {
                PropertyId.NDVI: 0.7 if ci == 11 else 0.1,
                PropertyId.SURFACE_TEMP_C: 22.5 if ci == 11 else 35.0,
                PropertyId.LIDAR_INTENSITY_MEAN: 0.4,
            }
        out += kc["pack_superquadric"](sq, class_idx=ci, properties=props)
    return bytes(out)


# ---------------------------------------------------------------------------
# POST /api/v1/observe
# ---------------------------------------------------------------------------


class PostObservationTests(TestCase):
    def test_json_envelope_round_trip(self):
        """earth_rover posts ENU-local SQs as JSON; server stores ECEF view + bbox."""
        sqs, class_idx = _phoenix_local_scene()
        payload = _pack_payload(sqs, class_idx, with_properties=True)
        envelope = {
            "source_id": "earth_rover_01",
            "session_id": "mission_2026_04_26",
            "frame": _phoenix_local_envelope_frame(),
            "n_superquadrics": len(sqs),
            "payload_size": len(payload),
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "attributes": {"battery_pct": 78, "mission_tag": "phx_demo"},
        }
        url = reverse("post_observation")
        resp = self.client.post(
            url,
            data=json.dumps(envelope),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["n_superquadrics"], len(sqs))
        bbox = body["bbox_wgs84"]
        # Phoenix lat/lon should land inside the AZ envelope.
        self.assertGreater(bbox["lat_min"], 33.0)
        self.assertLess(bbox["lat_max"], 34.0)
        self.assertGreater(bbox["lon_min"], -113.0)
        self.assertLess(bbox["lon_max"], -110.0)

        from deepgis_xr.apps.web.models import Observation

        obs = Observation.objects.get(pk=body["observation_id"])
        self.assertEqual(obs.payload_size, len(payload))
        self.assertEqual(bytes(obs.payload), payload)
        self.assertEqual(obs.n_superquadrics, len(sqs))
        # ECEF view: 3 SQs, all positions within ~50 m of each other.
        ecef = obs.superquadrics_ecef
        self.assertEqual(len(ecef), len(sqs))
        ecef_t = np.array([v["t_ecef"] for v in ecef])
        max_pairdist = float(
            np.max(np.linalg.norm(ecef_t[:, None] - ecef_t[None, :], axis=-1))
        )
        self.assertLess(max_pairdist, 200.0)

    def test_octet_stream_envelope(self):
        """Octet-stream transport (no base64 inflation) for tight links."""
        sqs, class_idx = _phoenix_local_scene()
        payload = _pack_payload(sqs[:1], class_idx[:1], with_properties=False)
        envelope = {
            "source_id": "earth_rover_01",
            "frame": _phoenix_local_envelope_frame(),
            "n_superquadrics": 1,
            "payload_size": len(payload),
        }
        url = reverse("post_observation")
        resp = self.client.post(
            url,
            data=payload,
            content_type="application/octet-stream",
            HTTP_X_OBSERVATION_ENVELOPE=json.dumps(envelope),
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["n_superquadrics"], 1)

    def test_missing_source_id_is_rejected(self):
        envelope = {"frame": {"kind": "ecef"}}
        resp = self.client.post(
            reverse("post_observation"),
            data=json.dumps(envelope),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("source_id", resp.json()["message"])

    def test_invalid_frame_is_rejected(self):
        envelope = {
            "source_id": "x",
            "frame": {"kind": "utm", "params": {"zone": 99}},
        }
        resp = self.client.post(
            reverse("post_observation"),
            data=json.dumps(envelope),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_payload_size_mismatch_is_rejected(self):
        sqs, class_idx = _phoenix_local_scene()
        payload = _pack_payload(sqs, class_idx, with_properties=False)
        envelope = {
            "source_id": "earth_rover_01",
            "frame": _phoenix_local_envelope_frame(),
            "n_superquadrics": len(sqs),
            "payload_size": len(payload) + 1,  # lie
            "payload_b64": base64.b64encode(payload).decode("ascii"),
        }
        resp = self.client.post(
            reverse("post_observation"),
            data=json.dumps(envelope),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_corrupt_payload_returns_422(self):
        envelope = {
            "source_id": "earth_rover_01",
            "frame": {"kind": "ecef"},
            "n_superquadrics": 1,
            "payload_size": 4,
            "payload_b64": base64.b64encode(b"\x00\x00\x00\x00").decode("ascii"),
        }
        resp = self.client.post(
            reverse("post_observation"),
            data=json.dumps(envelope),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 422)


# ---------------------------------------------------------------------------
# GET /api/v1/scene-graph
# ---------------------------------------------------------------------------


class GetSceneGraphTests(TestCase):
    def setUp(self):
        # Seed one observation in ENU-local at a Phoenix station.
        sqs, class_idx = _phoenix_local_scene()
        payload = _pack_payload(sqs, class_idx, with_properties=True)
        envelope = {
            "source_id": "earth_rover_01",
            "session_id": "mission_2026_04_26",
            "frame": _phoenix_local_envelope_frame(),
            "n_superquadrics": len(sqs),
            "payload_size": len(payload),
            "payload_b64": base64.b64encode(payload).decode("ascii"),
        }
        resp = self.client.post(
            reverse("post_observation"),
            data=json.dumps(envelope),
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.content
        self.bbox_wgs84 = resp.json()["bbox_wgs84"]

    def test_publish_in_wgs84(self):
        # bbox covering Phoenix.
        url = reverse("get_scene_graph")
        bbox = "-113,33,-111,34"
        resp = self.client.get(url, {"bbox": bbox, "frame": "wgs84_lla"})
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["frame"]["kind"], "wgs84_lla")
        self.assertEqual(body["n_observations"], 1)
        self.assertEqual(body["n_superquadrics"], 3)
        # Every SQ has a (lat, lon, alt) translation in the WGS84 frame.
        for v in body["superquadrics"]:
            t = v["t"]
            self.assertEqual(len(t), 3)
            self.assertGreater(t[0], 33.0)
            self.assertLess(t[0], 34.0)
            self.assertGreater(t[1], -113.0)
            self.assertLess(t[1], -110.0)
            # No leftover ECEF fields.
            self.assertNotIn("t_ecef", v)

    def test_publish_in_ecef(self):
        url = reverse("get_scene_graph")
        bbox = "-113,33,-111,34"
        resp = self.client.get(url, {"bbox": bbox, "frame": "ecef"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["frame"]["kind"], "ecef")
        # ECEF: |t| ~= R_earth ~= 6.37e6 m.
        for v in body["superquadrics"]:
            r = float(np.linalg.norm(v["t"]))
            self.assertGreater(r, 6_300_000.0)
            self.assertLess(r, 6_400_000.0)

    def test_publish_in_enu_local(self):
        url = reverse("get_scene_graph")
        bbox = "-113,33,-111,34"
        # Local tangent at Phoenix.
        frame = "enu_local:33.42,-111.94,350"
        resp = self.client.get(url, {"bbox": bbox, "frame": frame})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["frame"]["kind"], "enu_local")
        # ENU at this origin: SQ centroids should be within a few km.
        for v in body["superquadrics"]:
            self.assertLess(float(np.linalg.norm(v["t"])), 5_000.0)

    def test_publish_in_enu_round_trip(self):
        """Re-publishing in the producer's ENU frame should recover ~origin SQs."""
        url = reverse("get_scene_graph")
        bbox = "-113,33,-111,34"
        # Same origin as the producer.
        lat, lon, alt = _PHX_ORIGIN_LLA
        frame = f"enu_local:{lat},{lon},{alt}"
        resp = self.client.get(url, {"bbox": bbox, "frame": frame})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # ENU at the producer origin: positions should be within ~50 m of (0,0,0).
        for v in body["superquadrics"]:
            self.assertLess(float(np.linalg.norm(v["t"])), 50.0)

    def test_publish_binary_round_trips_through_codec(self):
        url = reverse("get_scene_graph")
        bbox = "-113,33,-111,34"
        resp = self.client.get(
            url, {"bbox": bbox, "frame": "wgs84_lla", "format": "binary"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/octet-stream")
        self.assertEqual(resp["X-SceneGraph-Count"], "3")
        kc = _kc()
        body = resp.content
        self.assertGreater(len(body), 0)
        # Walk the buffer and confirm we can decode 3 SQs.
        cursor = 0
        decoded = 0
        while cursor < len(body):
            sq, meta = kc["unpack_superquadric"](body[cursor:])
            cursor += int(meta["bytes_consumed"])
            decoded += 1
        self.assertEqual(decoded, 3)

    def test_bbox_outside_phoenix_returns_zero(self):
        url = reverse("get_scene_graph")
        # Sydney, AU.
        resp = self.client.get(url, {"bbox": "150,-34,152,-33"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["n_superquadrics"], 0)

    def test_missing_bbox_is_rejected(self):
        resp = self.client.get(reverse("get_scene_graph"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("bbox", resp.json()["message"])

    def test_invalid_bbox_is_rejected(self):
        resp = self.client.get(reverse("get_scene_graph"), {"bbox": "1,2,3"})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_frame_is_rejected(self):
        resp = self.client.get(
            reverse("get_scene_graph"),
            {"bbox": "-113,33,-111,34", "frame": "spaghetti"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_source_filter(self):
        url = reverse("get_scene_graph")
        bbox = "-113,33,-111,34"
        resp = self.client.get(
            url, {"bbox": bbox, "sources": "nonexistent_rover"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["n_observations"], 0)
        # With the right source.
        resp = self.client.get(
            url, {"bbox": bbox, "sources": "earth_rover_01"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["n_superquadrics"], 3)
