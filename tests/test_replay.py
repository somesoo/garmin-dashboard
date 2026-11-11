import unittest

import pandas as pd

from ui import replay


def _track(n: int = 60, **extra) -> pd.DataFrame:
    frame = pd.DataFrame({
        "seq": range(n), "lat": [52.0 + i * 1e-4 for i in range(n)], "lon": [21.0 + i * 1e-4 for i in range(n)],
        "distance_km": [i * 0.03 for i in range(n)], "duration_s": [i * 10 for i in range(n)],
    })
    for name, value in extra.items():
        frame[name] = value
    return frame


class ReplayPayloadTest(unittest.TestCase):
    def test_parallel_arrays_on_one_clock(self):
        data = replay.payload(_track(hr=150, elevation_m=100.0, pace_min_km=5.5))
        n = len(data["t"])
        self.assertEqual(n, 60)
        for key in ("km", "lat", "lon", "hr", "ele", "pace"):
            self.assertEqual(len(data[key]), n, key)
        self.assertEqual(data["t"][0], 0)
        self.assertEqual(data["t"], sorted(data["t"]))
        self.assertEqual(data["km"], sorted(data["km"]))

    def test_streams_the_watch_never_recorded_are_left_out(self):
        data = replay.payload(_track())
        self.assertIsNone(data["hr"])
        self.assertIsNone(data["ele"])
        self.assertIsNone(data["cad"])

    def test_gaps_are_filled_not_sent_as_nulls(self):
        hr = [None, None] + [140.0] * 58
        data = replay.payload(_track(hr=hr))
        self.assertTrue(all(v == 140 for v in data["hr"]))

    def test_cadence_counts_both_feet(self):
        data = replay.payload(_track(cadence=85.0))
        self.assertEqual(set(data["cad"]), {170.0})
        data = replay.payload(_track(cadence=170.0))
        self.assertEqual(set(data["cad"]), {170.0})

    def test_clock_never_runs_backwards(self):
        track = _track()
        track.loc[30, "duration_s"] = 5
        data = replay.payload(track)
        self.assertEqual(data["t"], sorted(set(data["t"])))

    def test_no_clock_or_too_short_means_no_replay(self):
        self.assertIsNone(replay.payload(_track().drop(columns="duration_s")))
        self.assertIsNone(replay.payload(_track(n=3)))
        self.assertIsNone(replay.payload(pd.DataFrame()))
        self.assertFalse(replay.ready(None))
        self.assertTrue(replay.ready(_track()))

    def test_a_track_without_a_clock_is_still_a_map(self):
        track = _track().drop(columns="duration_s")
        self.assertIsNone(replay.payload(track))
        data = replay.route(track)
        self.assertFalse(data["playable"])
        self.assertEqual(data["t"], sorted(set(data["t"])))
        self.assertEqual(len(data["lat"]), len(data["t"]))
        self.assertTrue(replay.route(_track())["playable"])
        self.assertIsNone(replay.route(pd.DataFrame()))

    def test_distance_is_measured_along_the_line_when_the_watch_gave_none(self):
        data = replay.route(_track().drop(columns=["duration_s", "distance_km"]))
        self.assertFalse(data["playable"])
        # 59 steps of 1e-4 degrees both ways near Warsaw: about 0.8 km.
        self.assertAlmostEqual(data["km"][-1], 0.77, delta=0.05)
        self.assertEqual(data["km"], sorted(data["km"]))

    def test_speeds_start_at_ten(self):
        self.assertEqual(replay.SPEEDS[0], 10)
        self.assertEqual(list(replay.SPEEDS), sorted(replay.SPEEDS))


if __name__ == "__main__":
    unittest.main()
