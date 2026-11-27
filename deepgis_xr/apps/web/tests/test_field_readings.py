import math

from django.test import SimpleTestCase

from deepgis_xr.apps.web.field_readings import destination, enabled


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

