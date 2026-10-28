"""Watch workouts rep by rep and against each other."""

from __future__ import annotations

import unittest

import pandas as pd

from running import workouts


def laps(activity_id, rows):
    """rows: (intensity, step_index, metres, seconds, avg_hr)"""
    return pd.DataFrame([
        {"activity_id": activity_id, "lap": i + 1, "intensity": kind, "step_index": step, "distance_m": metres,
         "duration_s": seconds, "avg_hr": hr, "max_hr": hr + 5, "cadence": 170.0}
        for i, (kind, step, metres, seconds, hr) in enumerate(rows)
    ])


TWO_BY_TWO = [
    ("warmup", 0, 2000, 840, 140),
    ("active", 1, 1000, 275, 175), ("active", 1, 1000, 276, 180),
    ("recovery", 2, 250, 120, 165),
    ("active", 1, 1000, 280, 178), ("active", 1, 1000, 281, 183),
    ("cooldown", 3, 1500, 600, 150),
]


class Reps(unittest.TestCase):
    def test_auto_laps_merge_and_the_recovery_follows_its_rep(self):
        table = workouts.reps(laps(1, TWO_BY_TWO))
        self.assertEqual(table["km"].tolist(), [2.0, 2.0])
        self.assertEqual(len(table.iloc[0]["laps"]), 2)
        self.assertEqual(table.iloc[0]["rest_s"], 120)
        self.assertTrue(pd.isna(table.iloc[1]["rest_s"]))
        self.assertAlmostEqual(table.iloc[0]["hr"], 177.5, delta=0.1)

    def test_a_run_without_workout_laps_has_no_reps(self):
        plain = laps(1, [("active", 0, 1000, 300, 150), ("active", 0, 1000, 300, 152)])
        self.assertTrue(workouts.reps(plain).empty)

    def test_summary_measures_the_fade(self):
        shape = workouts.summary(workouts.reps(laps(1, TWO_BY_TWO)))
        self.assertEqual(shape["reps"], 2)
        self.assertAlmostEqual(shape["fade_s"], 5.0, delta=0.1)
        self.assertAlmostEqual(shape["hr_drift"], 3.0, delta=0.1)


class History(unittest.TestCase):
    def test_only_quality_workouts_and_similar_by_rep_length(self):
        short = [("warmup", 0, 2000, 840, 140)] + [
            row for _ in range(5) for row in (("active", 1, 800, 215, 176), ("recovery", 2, 200, 120, 160))]
        frame = pd.concat([laps(1, TWO_BY_TWO), laps(2, short), laps(3, TWO_BY_TWO)])
        runs = pd.DataFrame({"activity_id": [1, 2, 3], "kind": ["intervals", "intervals", "long"],
                             "start_local": pd.to_datetime(["2026-10-01", "2026-10-08", "2026-10-15"])})
        sessions, every = workouts.history(runs, frame)
        self.assertEqual(sessions["activity_id"].tolist(), [1, 2])
        peers = workouts.peers(sessions, 1)
        self.assertEqual(peers.set_index("activity_id")["similar"].to_dict(), {1: True, 2: False})
        self.assertIsNone(workouts.hr_fit(every, 2, pd.Timestamp("2026-10-09")))


if __name__ == "__main__":
    unittest.main()
