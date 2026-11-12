import json
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from core import config, tenant
from etl import load, terrain
from tests.helpers import person, people
from ui import replay


def track(aid=1):
    return pd.DataFrame({"activity_id": aid, "seq": range(11), "lat": 52.2, "lon": 21.0,
                         "distance_km": np.arange(11) / 100, "duration_s": np.arange(11) * 5,
                         "elevation_m": np.arange(11) + 200.0})


def enable(since="2026-11-01"):
    terrain.settings_path().parent.mkdir(parents=True, exist_ok=True)
    terrain.settings_path().write_text(json.dumps({"since": since, "source": terrain.SOURCE}))


class TerrainTests(unittest.TestCase):
    def test_ascii_orientation_and_optional_nodata_header(self):
        body = b"ncols 2\nnrows 2\nxllcorner 10\nyllcorner 20\ncellsize 2\n1 2\n3 4\n"
        z, x, y, cell = terrain.parse_ascii(body)
        np.testing.assert_array_equal(z, [[3, 4], [1, 2]])
        self.assertEqual((x, y, cell), (10, 20, 2))
        z, *_ = terrain.parse_ascii(body.replace(b"1 2\n", b"NODATA_value -9999\n-9999 2\n"))
        self.assertTrue(np.isnan(z[1, 0]))
        with self.assertRaises(ValueError):
            terrain.parse_ascii(body[:-5])

    def test_local_bilinear_sampling_and_no_network(self):
        with person(), mock.patch.object(terrain, "cache_dir", return_value=terrain.settings_path().parent / "tiles"):
            path = terrain.tile_path(0, 0)
            path.parent.mkdir(parents=True)
            np.savez_compressed(path, elevation=np.array([[10., 20.], [30., 40.]]), x=0., y=0., cell=2.)
            with mock.patch.object(terrain, "projected", return_value=(np.array([2.]), np.array([2.]))), \
                 mock.patch.object(terrain, "download", side_effect=AssertionError("network")):
                self.assertEqual(terrain.sample(pd.DataFrame(index=[0])).tolist(), [25.])
            with mock.patch.object(terrain, "projected", return_value=(np.array([2002.]), np.array([2.]))):
                with self.assertRaises(FileNotFoundError):
                    terrain.sample(pd.DataFrame(index=[0]))

    def test_cutoff_and_disabled_person_leave_old_values_unchanged(self):
        activities = pd.DataFrame({"activity_id": [1, 2], "start_local": ["2026-10-31 23:59:59", "2026-11-01"]})
        routes = pd.concat([track(1), track(2)], ignore_index=True)
        with person():
            with mock.patch.object(terrain, "sample", side_effect=AssertionError("disabled")):
                pd.testing.assert_frame_equal(terrain.correct_routes(routes, activities), routes)
            enable()
            with mock.patch.object(terrain, "sample", return_value=np.arange(11) + 100.) as sampler:
                result = terrain.correct_routes(routes, activities)
            self.assertEqual(sampler.call_count, 1)
            pd.testing.assert_frame_equal(result.loc[:10, routes.columns], routes.loc[:10])
            self.assertEqual(result.loc[11, "elevation_m"], 100.)
            self.assertEqual(result.loc[11, "elevation_original_m"], 200.)
            self.assertTrue(result.loc[:10, "elevation_source"].isna().all())

    def test_summary_laps_and_replay_use_one_profile(self):
        with person():
            enable()
            activities = pd.DataFrame({"activity_id": [1, 2], "start_local": ["2026-11-01", "2026-10-31"],
                                       "elevation_gain_m": [100., 77.]})
            routes = pd.concat([track(1), track(2)], ignore_index=True)
            with mock.patch.object(terrain, "sample", return_value=np.arange(11, dtype=float) + 100):
                corrected = terrain.correct_routes(routes, activities)
            summaries = pd.DataFrame({"activity_id": [1, 2], "elevation_gain_m": [90., 70.]})
            laps = pd.DataFrame({"activity_id": [1, 1, 2], "lap": [0, 1, 0],
                                 "distance_m": [50., 50., 100.], "elevation_gain_m": [50., 50., 77.]})
            a, s, l = terrain.correct_summaries(activities, summaries, laps, corrected)
            total = corrected[corrected.activity_id == 1].elevation_gain_cum_m.iloc[-1]
            self.assertEqual(a.loc[0, "elevation_gain_m"], round(total, 1))
            self.assertEqual(s.loc[0, "elevation_gain_m"], round(total, 1))
            self.assertAlmostEqual(l.loc[:1, "elevation_gain_m"].sum(), total, places=1)
            self.assertEqual(a.loc[1, "elevation_gain_m"], 77.)
            self.assertEqual(s.loc[1, "elevation_gain_m"], 70.)
            self.assertEqual(l.loc[2, "elevation_gain_m"], 77.)
            data = replay.payload(corrected[corrected.activity_id == 1])
            self.assertEqual(data["gain"][-1], total)
            self.assertIn("GUGiK", replay._text(corrected[corrected.activity_id == 1])["elevation"])
            self.assertIsNone(replay.payload(corrected[corrected.activity_id == 2])["gain"])

    def test_settings_do_not_leak_between_people(self):
        with people({"a": {}, "b": {}}, current="a"):
            tenant.current().root.mkdir(parents=True, exist_ok=True)
            enable()
            self.assertIsNotNone(terrain.settings())
            with tenant.use("b"):
                self.assertIsNone(terrain.settings())

    def test_bad_coverage_fails_before_any_tables_are_published(self):
        with person():
            enable()
            with mock.patch.object(load, "build_routes", side_effect=ValueError("NMT missing")), \
                 mock.patch.object(load, "write_table") as write:
                with self.assertRaisesRegex(ValueError, "NMT missing"):
                    load.main()
                write.assert_not_called()

    def test_production_backfill_preserves_history_and_is_idempotent(self):
        from running import sessions

        with person():
            enable()
            a = pd.DataFrame({"activity_id": [1, 2], "start_local": ["2026-11-01", "2026-10-31"],
                              "elevation_gain_m": [99., 88.], "other": [12., 13.]})
            routes = pd.concat([track(1), track(2)], ignore_index=True)
            routes["distance_km"] *= 10
            routes["duration_s"] *= 10
            laps = pd.DataFrame({"activity_id": [1, 1, 2], "lap": [0, 1, 0],
                                 "distance_m": [500., 500., 1000.], "elevation_gain_m": [49., 50., 88.]})
            splits = pd.concat([sessions.km_splits(t).assign(activity_id=aid)
                                for aid, t in routes.groupby("activity_id")], ignore_index=True)
            tables = dict(activities=a, routes=routes, route_summary=a[["activity_id", "elevation_gain_m"]],
                          run_laps=laps, run_sessions=a.copy(), run_splits=splits)
            for name, frame in tables.items():
                load.write_table(frame, name)
            with mock.patch.object(terrain, "sample", return_value=np.arange(11, dtype=float) + 100), \
                 mock.patch.object(terrain, "prepare_routes"):
                self.assertEqual(terrain.backfill(), 1)
                first = {n: pd.read_parquet(config.tables() / f"{n}.parquet") for n in tables}
                self.assertEqual(terrain.backfill(), 1)
            for name, before in tables.items():
                after = pd.read_parquet(config.tables() / f"{name}.parquet")
                pd.testing.assert_frame_equal(first[name], after, check_exact=True)
                old = ~before.activity_id.eq(1)
                pd.testing.assert_frame_equal(before.loc[old], after.loc[old, before.columns], check_exact=True)
            self.assertEqual(first["activities"].loc[0, "elevation_gain_original_m"], 99.)
            self.assertEqual(first["run_sessions"].loc[0, "elevation_gain_original_m"], 99.)


if __name__ == "__main__":
    unittest.main()
