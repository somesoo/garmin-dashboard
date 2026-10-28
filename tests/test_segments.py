"""Same-route detection and private segments on synthetic GPS tracks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from running import segments, store

LAT0, LON0 = 52.2, 21.0
DEG_LAT = 1 / 111_320
DEG_LON = DEG_LAT / np.cos(np.radians(LAT0))


def track(activity_id, east_m, north_m, pace_s_km=300.0, hr=150.0):
    """A track through points given in metres; samples every ~25 m."""
    east, north = np.asarray(east_m, float), np.asarray(north_m, float)
    metres = np.concatenate([[0], np.cumsum(np.hypot(np.diff(east), np.diff(north)))])
    grid = np.arange(0, metres[-1], 25.0)
    x, y = np.interp(grid, metres, east), np.interp(grid, metres, north)
    return pd.DataFrame({
        "activity_id": activity_id, "seq": range(len(grid)), "lat": LAT0 + y * DEG_LAT, "lon": LON0 + x * DEG_LON,
        "distance_km": grid / 1000, "duration_s": grid / 1000 * pace_s_km, "hr": hr,
    })


# A 3 km out-and-back along the x axis, and a run that goes elsewhere.
OUT_BACK = ([0, 1500, 0], [0, 0, 0])
ELSEWHERE = ([0, 0], [0, 3000])


class SameRoute(unittest.TestCase):
    def test_overlap_and_distance_decide(self):
        routes = pd.concat([track(1, *OUT_BACK), track(2, [0, 1500, 0], [8, 8, 8]), track(3, *ELSEWHERE)])
        signs = segments.signatures(segments.paths(routes))
        self.assertEqual([a for a, _ in segments.same_route(signs, 1)], [2])
        self.assertEqual(segments.same_route(signs, 3), [])


class Segments(unittest.TestCase):
    def setUp(self):
        self.routes = pd.concat([
            track(1, *OUT_BACK, pace_s_km=300),
            track(2, [0, 1500, 0], [10, 10, 10], pace_s_km=270, hr=165),
            track(3, *ELSEWHERE),
        ])
        self.runs = pd.DataFrame({"activity_id": [1, 2, 3], "kind": ["easy", "tempo", "easy"],
                                  "start_local": pd.to_datetime(["2026-10-01", "2026-10-08", "2026-10-09"])})
        self.segment = {"id": "s", **segments.cut(self.routes[self.routes["activity_id"] == 1], 0.2, 1.2)}

    def test_cut_keeps_length_and_checkpoints(self):
        self.assertAlmostEqual(self.segment["length_m"], 1000, delta=15)
        self.assertGreater(len(self.segment["points"]), 40)

    def test_passes_are_found_ranked_and_directed(self):
        found = segments.efforts([self.segment], segments.paths(self.routes), self.runs)
        # Out-and-back: the way back runs the segment end to start, so it does not count.
        self.assertEqual(sorted(found["activity_id"].tolist()), [1, 2])
        fastest = found.loc[found["rank"] == 1].iloc[0]
        self.assertEqual(fastest["activity_id"], 2)
        self.assertAlmostEqual(fastest["seconds"], 270, delta=8)
        self.assertEqual(int(fastest["of"]), 2)

    def test_shared_stretch_has_its_own_length_and_direction(self):
        # Run 4 shares only the first 800 m of the out leg, then turns off.
        routes = pd.concat([self.routes, track(4, [0, 800, 800], [0, 0, 2000], pace_s_km=330, hr=140)])
        runs = pd.concat([self.runs, pd.DataFrame({"activity_id": [4], "kind": ["easy"],
                                                   "start_local": pd.to_datetime(["2026-10-10"])})])
        found = segments.shared(1, segments.paths(routes), runs).set_index("other_id")
        self.assertEqual(set(found.index), {2, 4})
        self.assertAlmostEqual(found.at[4, "length_m"], 800, delta=60)
        self.assertGreater(found.at[2, "length_m"], 1400)
        self.assertLess(found.at[4, "d_pace_s"], 0)  # run 1 (5:00/km) was faster than run 4 (5:30)
        self.assertGreater(found.at[2, "d_pace_s"], 0)

    def test_frequent_routes_become_segments_once(self):
        loop = ([0, 1200, 1200], [0, 0, 600])
        routes = pd.concat([track(i, loop[0], [y + i * 3 for y in loop[1]], pace_s_km=280 + i) for i in range(1, 6)]
                           + [track(9, *ELSEWHERE)])
        runs = pd.DataFrame({"activity_id": [1, 2, 3, 4, 5, 9], "kind": "easy", "name": "Warsaw - Base",
                             "start_local": pd.date_range("2026-09-01", periods=6, freq="7D")})
        tracks = segments.paths(routes)
        found = segments.frequent(tracks, runs)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["runs"], 5)
        self.assertTrue(found[0]["name"].startswith("Warsaw · "))
        self.assertGreater(found[0]["length_m"], 1500)
        # The same corridor saved by hand is not found again.
        self.assertEqual(segments.frequent(tracks, runs, saved=found), [])
        # Two runs are not "frequent".
        self.assertEqual(segments.frequent(tracks, runs, min_runs=6), [])

    def test_track_sessions_stay_out_of_gps_matching(self):
        # 12 laps of a ~400 m oval (100 x 60 m box): one knot of track.
        angle = np.linspace(0, 2 * np.pi * 12, 12 * 60)
        oval = track(7, 50 * np.cos(angle), 30 * np.sin(angle))
        tracks = segments.paths(pd.concat([self.routes, oval]))
        self.assertTrue(segments.is_loop(tracks[7]))
        self.assertFalse(segments.is_loop(tracks[1]))
        self.assertNotIn(7, segments.routable(tracks))
        runs = pd.concat([self.runs, pd.DataFrame({"activity_id": [7], "kind": ["intervals"],
                                                   "start_local": pd.to_datetime(["2026-10-11"])})])
        self.assertTrue(segments.shared(7, tracks, runs).empty)

    def test_short_best_efforts_come_from_watch_distance(self):
        from running import sessions
        runs = self.runs.assign(day=self.runs["start_local"])
        best = sessions.short_efforts(segments.paths(self.routes), runs)
        fastest = best[best["effort"] == "400m"].sort_values("seconds").iloc[0]
        self.assertEqual(fastest["activity_id"], 2)
        self.assertAlmostEqual(fastest["seconds"], 108, delta=1)

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            original = store.SEGMENTS
            store.SEGMENTS = Path(folder) / "segments.json"
            try:
                with self.assertRaises(ValueError):
                    store.save_segment({"name": " ", **self.segment})
                saved = store.save_segment({**self.segment, "id": None, "name": "prosta"} | {"id": "seg-1"})
                self.assertEqual([s["name"] for s in store.segments()], ["prosta"])
                store.delete_segment(saved["id"])
                self.assertEqual(store.segments(), [])
            finally:
                store.SEGMENTS = original


if __name__ == "__main__":
    unittest.main()
