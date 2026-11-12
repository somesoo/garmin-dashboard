import json
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from core import db, elevation, tenant
from etl import load, terrain, terrain_global
from tests.helpers import people, person
from tests.test_terrain import enable, track
from ui import shell, replay


class ElevationView(unittest.TestCase):
    def test_visible_switch_changes_values_and_survives_a_new_session(self):
        from streamlit.testing.v1 import AppTest

        script = """
import streamlit as st
from ui import shell, elevation
elevation.selector()
st.metric('gain', str(shell.table('activities').elevation_gain_m.iloc[0]))
"""
        with person():
            load.write_table(pd.DataFrame({"activity_id": [1], "elevation_gain_m": [12.],
                                          "elevation_gain_original_m": [88.]}), "activities")
            app = AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "12.0")
            app.get("segmented_control")[0].set_value("garmin").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "88.0")
            fresh = AppTest.from_string(script).run()
            self.assertEqual(fresh.metric[0].value, "88.0")
            fresh.get("segmented_control")[0].set_value("terrain").run()
            self.assertEqual(fresh.metric[0].value, "12.0")

    def test_switch_restores_recorded_values_without_mutating_cached_frame(self):
        frame = track()
        frame["elevation_original_m"] = 77.
        frame["elevation_source"] = terrain.SOURCE
        frame["elevation_gain_cum_m"] = np.arange(len(frame))
        frame["elevation_loss_cum_m"] = 0.
        original = frame.copy()
        raw = elevation.select(frame, "routes", "garmin")
        self.assertTrue(raw.elevation_m.eq(77.).all())
        self.assertTrue(raw.elevation_source.isna().all())
        self.assertNotIn("elevation_gain_cum_m", raw)
        self.assertIsNone(replay.payload(raw)["gain"])
        pd.testing.assert_frame_equal(frame, original)
        self.assertIs(elevation.select(frame, "routes", "terrain"), frame)

    def test_preference_is_per_viewer_and_preserves_other_settings(self):
        with people({"a": {}, "b": {}}, current="a"):
            p = tenant.current().ui_settings
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({"lang": "en", "level": "basic"}))
            elevation.remember("garmin")
            self.assertEqual(elevation.saved(), "garmin")
            self.assertEqual(json.loads(p.read_text())["level"], "basic")
            with tenant.use("b"):
                self.assertEqual(elevation.saved(), "terrain")

    def test_shell_cache_key_separates_modes_and_sql_uses_same_values(self):
        with person():
            a = pd.DataFrame({"activity_id": [1], "elevation_gain_m": [12.],
                              "elevation_gain_original_m": [88.], "elevation_source": [terrain.SOURCE]})
            r = track()
            r["elevation_original_m"] = 77.
            r["elevation_source"] = terrain.SOURCE
            r["elevation_gain_cum_m"] = 0.
            load.write_table(a, "activities")
            load.write_table(r, "routes")
            with mock.patch.object(elevation, "current", return_value="terrain"):
                corrected_key = shell.build_id()
                self.assertEqual(shell.table("activities").elevation_gain_m.iloc[0], 12.)
                self.assertEqual(shell.query("SELECT SUM(elevation_gain_m) AS gain FROM activities").gain.iloc[0], 12.)
            with mock.patch.object(elevation, "current", return_value="garmin"):
                self.assertNotEqual(corrected_key, shell.build_id())
                self.assertEqual(shell.table("activities").elevation_gain_m.iloc[0], 88.)
                self.assertEqual(shell.query("SELECT SUM(elevation_gain_m) AS gain FROM activities").gain.iloc[0], 88.)
                self.assertEqual(shell.query("SELECT elevation_m FROM routes LIMIT 1").elevation_m.iloc[0], 77.)
            # The ETL and unselected warehouse remain corrected.
            self.assertEqual(db.table("activities").elevation_gain_m.iloc[0], 12.)

    def test_global_sampler_interpolates_across_tile_boundaries(self):
        with person(), mock.patch.object(terrain_global, "cache_dir", return_value=terrain.settings_path().parent / "global"):
            terrain_global.cache_dir().mkdir(parents=True)
            for x, value in ((0, 10.), (1, 30.)):
                np.savez_compressed(terrain_global.cache_dir() / f"{x}_0.npz", elevation=np.full((256, 256), value))
            with mock.patch.object(terrain_global, "pixel_coordinates", return_value=(np.array([255.5]), np.array([3.25]))):
                self.assertEqual(terrain_global.sample(pd.DataFrame(index=[0])).tolist(), [20.])
                self.assertEqual(terrain_global.tiles(pd.DataFrame(index=[0])), {(0, 0), (1, 0)})

    def test_missing_distance_can_use_gps_without_overwriting_source(self):
        t = track()
        t["distance_km"] = np.nan
        t["lat"] = 52. + np.arange(len(t)) / 10000
        before = t.copy()
        up, down = terrain.cumulative(t)
        self.assertGreater(up[-1], 0)
        self.assertEqual(down[-1], 0)
        pd.testing.assert_frame_equal(t, before)

    def test_outside_poland_uses_global_source_for_whole_activity(self):
        with person():
            enable()
            options = terrain.settings()
            options["global_fallback"] = True
            terrain.settings_path().write_text(json.dumps(options))
            t = track()
            t["lat"] = 60.
            a = pd.DataFrame({"activity_id": [1], "start_local": ["2026-11-01"]})
            with mock.patch.object(terrain_global, "sample", return_value=np.arange(len(t)) + 100.), \
                 mock.patch.object(terrain, "sample", side_effect=AssertionError("wrong source")):
                out = terrain.correct_routes(t, a)
            self.assertTrue(out.elevation_source.eq(terrain_global.SOURCE).all())
            self.assertIn("Mapzen", replay._text(out)["elevation"])
