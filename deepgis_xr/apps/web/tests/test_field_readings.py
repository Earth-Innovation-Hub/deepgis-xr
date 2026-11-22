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

