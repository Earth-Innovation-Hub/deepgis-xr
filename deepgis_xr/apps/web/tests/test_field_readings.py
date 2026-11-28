import io
import math
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TransactionTestCase, override_settings

from deepgis_xr.apps.web.field_readings import destination, enabled


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class FieldSurfaceTests(SimpleTestCase):
    """The keyframe label under the spectrometer's patch."""

    def test_patch_takes_the_most_confident_mask_over_it(self):
        from deepgis_xr.apps.web.field_surface import label_patch

        detections = [
            {"class_name": "grass", "confidence": 0.6, "mask_polygons_norm": [_box(0, 0, 1, 1)]},
            {"class_name": "fence", "confidence": 0.9, "mask_polygons_norm": [_box(0, 0.3, 1, 0.7)]},
            {"class_name": "sky", "confidence": 0.2, "mask_polygons_norm": [_box(0, 0, 1, 1)]},      # too unsure
            {"class_name": "dog", "confidence": 0.99, "mask_polygons_norm": [_box(0, 0, 1, 1)]},     # not asked for
        ]
        centre = label_patch(detections, (0.5, 0.5, 0.2))
        self.assertEqual((centre["label"], centre["share"], centre["centre"]), ("fence", 1.0, "fence"))
        low = label_patch(detections, (0.5, 0.9, 0.2))
        self.assertEqual((low["label"], low["shares"], low["centre"]), ("grass", {"grass": 1.0}, "grass"))
        # half fence, a quarter each of two others: nothing fills the patch
        edge = label_patch(detections[:2], (0.5, 0.7, 0.2))
        self.assertAlmostEqual(edge["shares"]["fence"], 0.5, delta=0.1)
        thirds = [{"class_name": name, "confidence": 0.8, "mask_polygons_norm": [_box(x, 0, x + 0.07, 1)]}
                  for name, x in (("tree", 0.4), ("hedge", 0.47), ("wall", 0.54))]
        self.assertEqual(label_patch(thirds, (0.5, 0.5, 0.2))["label"], "mixed")
        corner = [{"class_name": "car", "confidence": 0.9, "mask_polygons_norm": [_box(0, 0, 0.1, 0.1)]}]
        self.assertEqual(label_patch(corner, (0.5, 0.5, 0.2)), {"label": "none", "share": 0.0, "shares": {}})
        self.assertIsNone(label_patch([], (0.5, 0.5, 0.2)))

    def test_patch_defaults_to_the_image_centre(self):
        from deepgis_xr.apps.web.field_surface import DEFAULT_FRAC_W, patch_of

        class Row:
            spectrum = {"footprint": {"u": 0.4, "v": 0.6, "frac_w": 0.208}}

        self.assertEqual(patch_of(Row()), (0.4, 0.6, 0.208))
        Row.spectrum = {"footprint": {"u": 7}}
        self.assertEqual(patch_of(Row()), (0.5, 0.5, DEFAULT_FRAC_W))

    def test_segmentation_takes_turns_and_backs_off(self):
        import fcntl

        import requests

        from deepgis_xr.apps.web import field_surface

        with tempfile.TemporaryDirectory() as tmp, override_settings(ULTRALYTICS_API_URL="http://sam.test"), \
                mock.patch.object(field_surface, "_TURN", str(Path(tmp, "turn"))), \
                mock.patch.object(field_surface, "_COOLDOWN", str(Path(tmp, "cooldown"))), \
                mock.patch.object(field_surface, "host_free_mb", return_value=64000) as free, \
                mock.patch("requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"success": True, "detections": [{"class_name": "grass"}],
                                                   "inference_ms": 9}
            self.assertEqual(field_surface.segment(b"x"), ([{"class_name": "grass"}], 9))
            self.assertIsNone(field_surface.refused)
            # a host short of memory is not asked for more
            free.return_value = 2000
            self.assertIsNone(field_surface.segment(b"x"))
            self.assertIn("memory", field_surface.refused)
            free.return_value = 64000
            # one at a time: a second caller is turned away unless it asked to wait
            with open(field_surface._TURN, "a") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                self.assertIsNone(field_surface.segment(b"x"))
                self.assertIn("another", field_surface.refused)
            self.assertEqual(post.call_count, 1)
            # a request that does not come back is still running there: pause before the next
            post.side_effect = requests.exceptions.ReadTimeout()
            self.assertIsNone(field_surface.segment(b"x"))
            self.assertIn("did not answer", field_surface.refused)
            post.side_effect = None
            self.assertIsNone(field_surface.segment(b"x"))
            self.assertIn("pausing", field_surface.refused)
            self.assertEqual(post.call_count, 2)
        with override_settings(ULTRALYTICS_API_URL=""):
            self.assertIsNone(field_surface.segment(b"x"))
            self.assertIn("configured", field_surface.refused)

    def test_live_labelling_is_off_unless_asked_for(self):
        from deepgis_xr.apps.web import field_readings

        with mock.patch.object(field_readings, "enabled", return_value=True), \
                override_settings(ULTRALYTICS_API_URL="http://sam.test", FIELD_SURFACE_LABELS=False), \
                mock.patch.object(field_readings.threading, "Thread") as thread:
            field_readings.schedule_surface(1)
            thread.assert_not_called()
            self.assertEqual(len(field_readings._SURFACE_QUEUE), 0)

    def test_reference_panel_mark_is_kept_on_the_spectrum(self):
        from deepgis_xr.apps.web.views.vehicles import clean_spectrum

        base = {"wl0": 300, "dwl": 1, "full_scale": 16383, "counts": [1] * 32}
        self.assertEqual(clean_spectrum({**base, "reference": {"reflectance": 0.5, "x": 1}})["reference"],
                         {"reflectance": 0.5})
        self.assertNotIn("reference", clean_spectrum(base))
        self.assertNotIn("reference", clean_spectrum({**base, "reference": {"reflectance": 0}}))
        self.assertNotIn("reference", clean_spectrum({**base, "reference": 0.5}))

    def test_admin_names_the_surface(self):
        from django.contrib import admin

        from deepgis_xr.apps.web.models import FieldReading

        model_admin = admin.site._registry[FieldReading]
        row = FieldReading(surface={"label": "grass", "share": 0.8, "shares": {"grass": 0.8, "pavement": 0.1},
                                    "model": "sam3", "from": 41})
        line = model_admin.surface_line(row)
        self.assertIn("grass 80%", line)
        self.assertIn("copied from reading 41", line)
        self.assertEqual(model_admin.surface_line(FieldReading()), "—")


class FieldReadingStoreTests(TransactionTestCase):
    """What needs the readings table: held headings and the copy of an earlier look's label."""

    databases = {"default", "observations"}
    T0 = datetime(2026, 11, 17, 19, 0, tzinfo=timezone.utc)

    def _row(self, i, heading, *, speed=0.0, range_m=6.0, **kw):
        from deepgis_xr.apps.web.models import FieldReading

        when = self.T0 + timedelta(seconds=5 * i)
        return FieldReading.objects.using("observations").create(
            vehicle_id="rover", captured_usec=int(when.timestamp() * 1e6), captured=when,
            heading_deg=heading, speed_mps=speed, range_m=range_m, range_valid=True, **kw)

    def test_heading_repeated_by_a_standing_rover_is_held(self):
        from deepgis_xr.apps.web.field_readings import _heading_held, aim

        from deepgis_xr.apps.web.field_readings import HEADING_SIGMA_DEG, HEADING_STOPPED_SIGMA_DEG

        # no move on record: the course could be from any time
        run = [self._row(i, 45.39) for i in range(5)]
        self.assertEqual([_heading_held(r) for r in run], [float("inf")] * 5)   # the start of the run too
        self.assertTrue(aim(run[3])["held"])
        # a compass at rest repeats a value now and then, not four times running
        live = [self._row(10 + i, h) for i, h in enumerate((162.4, 162.4, 162.4, 163.1, 163.1, 162.9))]
        self.assertEqual([_heading_held(r) for r in live], [None] * 6)
        self.assertEqual((aim(live[1]).get("held"), aim(live[1])["sigma_deg"]), (None, HEADING_SIGMA_DEG))
        # a course over ground while driving straight is a heading
        driving = [self._row(30 + i, 270.0, speed=1.2) for i in range(5)]
        self.assertEqual([_heading_held(r) for r in driving], [None] * 5)
        # stopped on that course: still a heading, a loose one, for an hour
        stopped = [self._row(35 + i, 268.5) for i in range(5)]
        a = aim(stopped[4])
        self.assertEqual((a.get("held"), a["sigma_deg"], a["since_moving_s"]), (None, HEADING_STOPPED_SIGMA_DEG, 25))
        late = [self._row(800 + i, 268.5) for i in range(4)]
        self.assertTrue(aim(late[0])["held"])

    def test_map_layer_says_what_was_seen_and_whether_it_counted(self):
        from types import SimpleNamespace

        from django.contrib.gis.geos import Point

        from deepgis_xr.apps.web.field_readings import _features

        target = Point(-122.0, 36.97, srid=4326)
        surface = {"label": "hedge", "share": 0.62, "shares": {"hedge": 0.62, "wall": 0.3}, "centre": "hedge",
                   "patch": [0.5, 0.5, 0.208], "model": "sam3"}
        seen = self._row(0, 90.0, target=target, surface=surface, spectrum={"counts": [1]})
        held = self._row(1, 90.0, target=target, spectrum={"counts": [1]}, aim={"held": True})
        entity = SimpleNamespace(pk=7, category="vegetation_other", score=0.414)
        link = SimpleNamespace(reading_id=seen.pk, entity=entity, weight=0.8, usable=False,
                               signal={"view": "face", "view_by": "image", "patch": "mixed",
                                       "sun_deg": 30.0, "sun_sep_deg": 12.0})
        with mock.patch("deepgis_xr.apps.scene_store.models.FieldLink.objects") as objects:
            objects.select_related.return_value.filter.return_value = [link]
            props = {f["properties"]["id"]: f["properties"] for f in _features([seen, held])["features"]}
        a, b = props[seen.pk], props[held.pk]
        self.assertEqual((a["surface"]["label"], a["surface"]["centre"], a["surface"]["patch"]),
                         ("hedge", "hedge", [0.5, 0.5, 0.208]))
        self.assertEqual((a["link"]["view"], a["link"]["usable"], a["link"]["entity"], a["link"]["entity_score"]),
                         ("face", False, 7, 0.41))
        self.assertEqual(a["link"]["why_not"],
                         ["face view: no vote", "patch: mixed", "sun 12° from the camera axis"])
        self.assertIsNone(a["unlinked"])
        self.assertEqual((b["surface"], b["link"]), (None, None))
        self.assertIn("kept", b["unlinked"])

    def test_same_view_takes_the_earlier_label(self):
        from deepgis_xr.apps.web import field_surface
        from deepgis_xr.apps.web.models import FieldReading

        def jpeg(across):
            from PIL import Image

            image = Image.new("L", (64, 48))
            image.putdata([(x * 4 if across else y * 5) for y in range(48) for x in range(64)])
            out = io.BytesIO()
            image.convert("RGB").save(out, "JPEG")
            return out.getvalue()

        detections = [{"class_name": "grass", "confidence": 0.8, "mask_polygons_norm": [_box(0, 0, 1, 1)]}]
        field_surface._THUMBS.clear()
        self.addCleanup(field_surface._THUMBS.clear)
        with tempfile.TemporaryDirectory() as root, override_settings(OBSERVATIONS_ROOT=root), \
                mock.patch.object(field_surface, "segment", return_value=(detections, 2400.0)) as segment:
            Path(root, "a.jpg").write_bytes(jpeg(True))
            Path(root, "b.jpg").write_bytes(jpeg(False))
            kw = {"spectrum": {"counts": [1] * 32}, "width": 640, "height": 480}
            first = self._row(0, None, image_relpath="a.jpg", **kw)
            again = self._row(1, None, image_relpath="a.jpg", **kw)
            later = self._row(2, None, image_relpath="a.jpg", **kw)
            turned = self._row(3, None, image_relpath="b.jpg", **kw)
            moved = self._row(4, None, range_m=9.0, image_relpath="a.jpg", **kw)
            fresh = self._row(5, None, range_m=12.0, image_relpath="b.jpg", **kw)
            bare = self._row(6, None, spectrum=kw["spectrum"])
            got = field_surface.write_surface(first.pk)
            self.assertEqual((got["label"], got["share"], got["centre"], got["n_masks"], got["ms"]),
                             ("grass", 1.0, "grass", 1, 2400))
            self.assertIsNone(field_surface.write_surface(first.pk))          # already labelled
            copy = field_surface.write_surface(again.pk)
            self.assertEqual((copy["label"], copy["centre"], copy["from"]), ("grass", "grass", first.pk))
            self.assertEqual(field_surface.write_surface(later.pk)["from"], first.pk)   # from the segmented one
            self.assertEqual(segment.call_count, 1)
            self.assertNotIn("from", field_surface.write_surface(turned.pk))  # same pose, another picture
            self.assertNotIn("from", field_surface.write_surface(moved.pk))   # same picture, another range
            self.assertEqual(segment.call_count, 3)
            self.assertIsNone(field_surface.write_surface(fresh.pk, segment_new=False))   # a new view, copies only
            self.assertEqual(segment.call_count, 3)
            self.assertIsNone(field_surface.write_surface(bare.pk))           # no keyframe
            segment.return_value = None                                       # the service is down
            self.assertIsNone(field_surface.write_surface(first.pk, force=True))
            self.assertEqual(FieldReading.objects.using("observations").get(pk=first.pk).surface["label"], "grass")


class FieldReadingTests(SimpleTestCase):
    def test_disabled_while_the_suite_runs(self):
        self.assertFalse(enabled())

    def test_due_north_moves_latitude_only(self):
        lat, lon, up = destination(33.3735, -111.9355, 0, 0, 100)
        self.assertAlmostEqual(lat - 33.3735, math.degrees(100 / 6371000.0), places=8)
        self.assertAlmostEqual(lon, -111.9355, places=8)
        self.assertAlmostEqual(up, 0.0, places=8)

    def test_east_moves_longitude(self):
        lat, lon, up = destination(0.0, 0.0, 90, 0, 100)
        self.assertAlmostEqual(lat, 0.0, places=8)
        self.assertAlmostEqual(lon, math.degrees(100 / 6371000.0), places=8)
        self.assertEqual(up, 0.0)

    def test_downward_pitch_lowers_the_end_of_the_ray(self):
        lat, lon, up = destination(33.0, -112.0, 0, -90, 4.5)
        self.assertAlmostEqual(lat, 33.0, places=6)
        self.assertAlmostEqual(lon, -112.0, places=6)
        self.assertAlmostEqual(up, -4.5, places=6)

    def test_no_heading_has_no_target(self):
        self.assertIsNone(destination(33.0, -112.0, float("nan"), 0, 4.5))

    def test_fcu_pose_keeps_quaternion_rates_and_covariance(self):
        from deepgis_xr.apps.web.views.vehicles import clean_fcu_pose

        cov = [None] * 21
        cov[0], cov[15], cov[20] = 7.3e-05, 1.5e-05, 4.7e-04
        fcu = clean_fcu_pose({
            "src": "px4_odometry", "dt_s": -0.012, "t_boot_us": 828975503, "reset": 17,
            "q": [-0.2327, 0.0289, 0.0206, -0.9719], "rates_rps": [0.0013, 0.0018, 0.0013],
            "pose_cov": cov, "vel_cov": [0.0007] + [None] * 20,
            "ekf": {"flags": 831, "pos_h_acc_m": 4.2, "ratios": [0.1] * 6},
            "mount": {"pitch_deg": 0.0, "hfov_deg": 0.0}, "extra": "dropped",
        })
        self.assertEqual(fcu["q"], [-0.2327, 0.0289, 0.0206, -0.9719])
        self.assertEqual(fcu["pose_cov"][15], 1.5e-05)
        self.assertIsNone(fcu["pose_cov"][1])
        self.assertEqual(fcu["ekf"]["flags"], 831)
        self.assertEqual(fcu["reset"], 17)
        self.assertNotIn("extra", fcu)

    def test_ekf_aim_includes_the_rovers_pitch_and_yaw(self):
        from deepgis_xr.apps.web.field_readings import ekf_aim

        cov = [None] * 21
        cov[18], cov[20] = 1.4e-05, 4.7e-04
        # the parked rover on 2026-11-27: roll -3.1, pitch +2.7, yaw 153.6 degrees
        fcu = {"q": [-0.2271648, 0.02923518, 0.02070377, -0.9731973], "dt_s": -0.016,
               "pose_cov": cov, "ekf": {"flags": 1189}}
        a = ekf_aim(fcu, 0.0)
        self.assertEqual(a["source"], "ekf")
        self.assertAlmostEqual(a["azimuth_deg"], 153.6, delta=0.2)
        self.assertAlmostEqual(a["elevation_deg"], 2.7, delta=0.2)
        self.assertAlmostEqual(a["sigma_deg"], math.hypot(math.degrees(math.sqrt(4.7e-04)), 2.0), places=2)
        # a camera tilted 10 degrees down on the same rover points 10 degrees lower
        self.assertAlmostEqual(ekf_aim(fcu, -10.0)["elevation_deg"], 2.7 - 10.0, delta=0.3)

    def test_ekf_aim_refuses_a_stale_or_unaligned_estimate(self):
        from deepgis_xr.apps.web.field_readings import ekf_aim

        cov = [None] * 21
        cov[20] = 4.7e-04
        good = {"q": [1.0, 0.0, 0.0, 0.0], "dt_s": 0.0, "pose_cov": cov, "ekf": {"flags": 1}}
        self.assertAlmostEqual(ekf_aim(good)["azimuth_deg"], 0.0, places=6)
        self.assertIsNone(ekf_aim({**good, "dt_s": 0.5}))
        self.assertIsNone(ekf_aim({**good, "ekf": {"flags": 0}}))
        self.assertIsNone(ekf_aim({**good, "pose_cov": [None] * 21}))
        wide = [None] * 21
        wide[20] = math.radians(20) ** 2
        self.assertIsNone(ekf_aim({**good, "pose_cov": wide}))

    def test_target_uses_the_ekf_and_records_the_hit_height(self):
        from django.contrib.gis.geos import Point

        from deepgis_xr.apps.web.field_readings import _place
        from deepgis_xr.apps.web.models import FieldReading

        cov = [None] * 21
        cov[18], cov[20] = 1e-05, 1e-04
        fcu = {"q": [1.0, 0.0, 0.0, 0.0], "dt_s": 0.0, "pose_cov": cov,
               "mount": {"pitch_deg": 0.0, "height_m": 1.5}, "gps": {"h_var_m2": 16.0}}
        r = FieldReading(vehicle_id="v", captured_usec=1, camera=Point(-112.0, 33.0, srid=4326),
                         range_m=10.0, range_valid=True, pitch_deg=0.0, heading_deg=90.0, fcu_pose=fcu)
        _place(r)
        self.assertEqual(r.aim["source"], "ekf")
        self.assertAlmostEqual(r.target.x, -112.0, places=7)   # north by the EKF, not east by the heading
        self.assertGreater(r.target.y, 33.0)
        self.assertAlmostEqual(r.aim["hit_height_m"], 1.5, places=3)
        self.assertAlmostEqual(r.aim["gps_sigma_m"], 4.0, places=3)
        self.assertGreater(r.aim["sigma_m"], 4.0)
        r.fcu_pose = None
        with mock.patch("deepgis_xr.apps.web.field_readings._heading_held", return_value=None):
            _place(r)
        self.assertEqual(r.aim["source"], "heading")
        self.assertNotIn("hit_height_m", r.aim)
        self.assertGreater(r.target.x, -112.0)

    def test_fcu_pose_needs_a_unit_quaternion_and_drops_bad_lists(self):
        from deepgis_xr.apps.web.views.vehicles import clean_fcu_pose

        self.assertIsNone(clean_fcu_pose({"q": [1, 1, 0, 0]}))
        self.assertIsNone(clean_fcu_pose({"q": [1, None, 0, 0]}))
        self.assertIsNone(clean_fcu_pose("not a dict"))
        fcu = clean_fcu_pose({"q": [1, 0, 0, 0], "pose_cov": [0.1] * 20, "rates_rps": [0, "x", 0]})
        self.assertNotIn("pose_cov", fcu)
        self.assertNotIn("rates_rps", fcu)


    def test_field_readings_are_in_the_existing_admin(self):
        from django.contrib import admin

        from deepgis_xr.apps.web.models import FieldReading

        model_admin = admin.site._registry[FieldReading]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertIn('frame_and_spectrum', model_admin.readonly_fields)


    def test_spectrum_plot_is_counts_against_wavelength(self):
        from deepgis_xr.apps.web.admin import _spectrum_svg

        svg = _spectrum_svg({
            "wl0": 300, "dwl": 1, "counts": [0, 10, 0],
            "clipped": [[301, 302]], "full_scale": 20,
        })
        self.assertIn("<svg", svg)
        self.assertIn("300 nm", svg)
        self.assertIn("302 nm", svg)
        self.assertIn("<rect", svg)
        self.assertEqual(_spectrum_svg({}), "")
        self.assertEqual(_spectrum_svg({"wl0": 300, "dwl": 1, "counts": [float("nan"), 1]}), "")


    def test_list_spark_is_a_small_curve(self):
        from deepgis_xr.apps.web.admin import _spectrum_spark

        svg = _spectrum_spark({"counts": [0, 5, 1]})
        self.assertIn('width="120"', svg)
        self.assertIn("<polyline", svg)
        self.assertEqual(_spectrum_spark({}), "")
        self.assertEqual(_spectrum_spark({"counts": [float("nan"), 1]}), "")


    def test_notes_join_the_photograph_to_the_instruments(self):
        from deepgis_xr.apps.web.field_readings import _facts, _notes_from

        class Cam:
            y, x = 33.37, -111.94

        class Row:
            camera = Cam()
            heading_deg = None
            pitch_deg = 0.0
            spectrum = {
                "notes": ["a strong red-edge step"],
                "laser": {"range_m": 4.5},
                "indices": {"nir_red": 0.23},
                "footprint": {"diameter_m": 1.1},
            }

        facts = _facts(Row())
        self.assertIn("No heading was reported", facts)
        self.assertIn("4.50 m", facts)
        self.assertIn("red-edge step", facts)
        self.assertIn("nir_red 0.23", facts)
        self.assertEqual(_notes_from({"json": {"image": " A tree. ", "combined": " The tree is 4.5 m away. "}}),
                         {"image": "A tree.", "combined": "The tree is 4.5 m away."})
        self.assertIsNone(_notes_from({"image": "", "combined": "x"}))


    def test_afternoon_sun_in_arizona_is_up_and_west(self):
        from datetime import datetime, timezone

        from deepgis_xr.apps.web.field_readings import _atmosphere_from, sun_position

        azimuth, elevation = sun_position(33.37, -111.94, datetime(2026, 11, 12, 21, 19, tzinfo=timezone.utc))
        self.assertGreater(elevation, 15)
        self.assertLess(elevation, 50)
        self.assertGreater(azimuth, 180)
        self.assertLess(azimuth, 270)
        _noon_az, noon_el = sun_position(0.0, 0.0, datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc))
        self.assertGreater(noon_el, 80)
        air = _atmosphere_from({
            "hourly": {
                "time": ["2026-11-12T20:00", "2026-11-12T21:00"],
                "temperature_2m": [20.0, 21.5],
                "cloud_cover": [0, 10],
                "shortwave_radiation": [400, 380],
            }
        }, datetime(2026, 11, 12, 21, 19, tzinfo=timezone.utc))
        self.assertEqual(air["temperature_c"], 21.5)
        self.assertEqual(air["cloud_cover_pct"], 10)
        self.assertEqual(air["source"], "open-meteo")
        self.assertIsNone(_atmosphere_from({}, datetime(2026, 11, 12, 21, 19, tzinfo=timezone.utc)))


    def test_aircraft_report_keeps_callsign_heading_speed_and_altitude(self):
        from deepgis_xr.apps.web.field_readings import _aircraft_from, _facts, _picked

        report = _aircraft_from({"ac": [
            {"flight": "SWA1  ", "track": 90, "gs": 400, "alt_baro": 10000, "dst": 5},
            {"flight": "N1    ", "track": 10, "gs": 80, "alt_geom": 4400, "dst": 1},
            {"lat": 1},
        ]})
        self.assertEqual([row["flight"].strip() for row in report["aircraft"][:2]], ["N1", "SWA1"])
        self.assertEqual(report["aircraft"][0]["alt_geom"], 4400)
        self.assertEqual(report["aircraft"][1]["alt_baro"], 10000)
        self.assertEqual(len(report["aircraft"]), 3)
        ground = _aircraft_from({"ac": [{"flight": "VAR496", "alt_baro": "ground", "gs": 5.2, "dst": 2, "t": "SR20"}]})
        self.assertEqual(ground["aircraft"][0]["alt_baro"], "ground")
        from deepgis_xr.apps.web.field_readings import aircraft_lines
        self.assertEqual(aircraft_lines(ground)[0]["status"], "on ground")
        self.assertEqual(aircraft_lines(report)[1]["status"], "airborne")
        self.assertIsNone(_aircraft_from({}))

        class Cam:
            y, x = 33.0, -112.0

        class Row:
            camera = Cam()
            heading_deg = None
            pitch_deg = 0
            spectrum = {}
            sky = {
                "sun": {"azimuth_deg": 216.2, "elevation_deg": 29.4},
                "atmosphere": {
                    "time": "2026-11-12T21:00",
                    "temperature_c": 28.9,
                    "cloud_cover_pct": 2,
                    "us_aqi": 69,
                    "pm2_5_ugm3": 18.2,
                },
            }

        facts = _facts(Row())
        self.assertIn("216 degrees", facts)
        self.assertIn("29 degrees", facts)
        self.assertIn("US AQI 69", facts)
        self.assertIn("PM2.5 18.2", facts)
        picked = _picked({
            "hourly": {"time": ["2026-11-12T21:00"], "us_aqi": [69], "pm2_5": [18.2]}
        }, __import__("datetime").datetime(2026, 11, 12, 21, 19, tzinfo=__import__("datetime").timezone.utc),
            {"us_aqi": "us_aqi", "pm2_5_ugm3": "pm2_5"})
        self.assertEqual(picked["us_aqi"], 69)

