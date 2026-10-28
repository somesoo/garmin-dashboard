"""Run selection, classification, splits, best efforts and weekly summaries."""

from __future__ import annotations

import unittest

import pandas as pd

from tests.helpers import activities, run, track
from running import physio, sessions, text, units


class Selection(unittest.TestCase):
    def test_drops_non_runs_and_recordings_left_running(self):
        frame = activities([
            run(1, "2026-01-05", 6.0, 6.0),
            run(2, "2026-01-06", 0.5, 6.0),                 # < 1 km
            run(3, "2026-01-07", 3.0, 25.0),                # slower than a walk
            run(4, "2026-01-08", 30.0, 2.0, sport="cycling"),
            run(5, "2026-01-09", 5.0, 5.5, sport="treadmill_running"),
        ])
        self.assertEqual(sessions.select_runs(frame)["activity_id"].tolist(), [1, 5])
        self.assertTrue(sessions.select_runs(pd.DataFrame()).empty)


class Classification(unittest.TestCase):
    def classify(self, rows, segments=None, vdot=None):
        frame = sessions.select_runs(activities(rows))
        series = None
        if vdot is not None:
            series = pd.Series(vdot, index=[frame["day"].min() - pd.Timedelta(days=1)])
        return sessions.classify(frame, segments, None, hr_max=190, vdot_by_day=series).set_index("activity_id")

    def history(self):
        return [run(i, f"2026-01-{i:02d}", 6.0, 6.5, hr=140) for i in range(1, 10)]

    def test_structured_workout_with_reps_is_intervals(self):
        segments = pd.DataFrame([
            {"activity_id": 50, "split_type": "INTERVAL_ACTIVE", "splits": 5, "distance_m": 4000,
             "duration_s": 1080, "avg_speed_ms": 3.7},
            {"activity_id": 50, "split_type": "INTERVAL_RECOVERY", "splits": 5, "distance_m": 1000,
             "duration_s": 600, "avg_speed_ms": 1.7},
        ])
        result = self.classify(self.history() + [run(50, "2026-01-20", 10.0, 6.4, hr=160)], segments)
        self.assertEqual(result.loc[50, "kind"], "intervals")
        self.assertEqual(result.loc[50, "kind_confidence"], "wysoka")

    def test_reps_in_name_is_intervals(self):
        result = self.classify(self.history() + [run(51, "2026-01-20", 9.0, 6.0, name="Track 6x800")])
        self.assertEqual(result.loc[51, "kind"], "intervals")

    def test_hard_hr_at_fast_pace_is_threshold_but_at_easy_pace_is_easy(self):
        rows = self.history() + [
            run(60, "2026-01-20", 6.0, 5.05, hr=170),  # 89% HRmax at T pace for VDOT 40
            run(61, "2026-01-22", 6.0, 6.60, hr=170),  # same HR, easy pace: heat, not tempo
        ]
        result = self.classify(rows, vdot=40.0)
        self.assertEqual(result.loc[60, "kind"], "threshold")
        self.assertEqual(result.loc[61, "kind"], "easy")
        self.assertIn("tętno", text.reason(result.loc[61, "kind_reason"]))

    def test_long_run_and_recovery(self):
        rows = self.history() + [run(70, "2026-01-25", 14.0, 6.7, hr=145), run(71, "2026-01-26", 4.0, 7.2, hr=125)]
        result = self.classify(rows)
        self.assertEqual(result.loc[70, "kind"], "long")
        self.assertEqual(result.loc[71, "kind"], "recovery")

    def test_without_hr_the_label_has_low_confidence(self):
        rows = [run(i, f"2026-01-{i:02d}", 6.0, 6.5, hr=None) for i in range(1, 8)]
        result = self.classify(rows)
        self.assertTrue((result["kind_confidence"] == "niska").all())

    def test_race_word_in_name(self):
        result = self.classify(self.history() + [run(80, "2026-01-20", 10.0, 4.8, name="Bieg Niepodległości parkrun")])
        self.assertEqual(result.loc[80, "kind"], "race")


class Splits(unittest.TestCase):
    def test_even_pace_gives_equal_splits(self):
        table = sessions.km_splits(track(1, 5.0, 5.0))
        self.assertEqual(len(table), 5)
        for seconds in table["seconds"]:
            self.assertAlmostEqual(seconds, 300, delta=1.0)
        self.assertTrue((table["cadence"] > 160).all())  # one-foot stream doubled

    def test_partial_last_split_is_kept_with_its_length(self):
        table = sessions.km_splits(track(1, 5.5, 6.0))
        self.assertEqual(len(table), 6)
        self.assertAlmostEqual(table["length_km"].iloc[-1], 0.5, places=2)
        self.assertAlmostEqual(table["pace_min_km"].iloc[-1], 6.0, delta=0.05)

    def test_no_stream_no_splits(self):
        self.assertTrue(sessions.km_splits(pd.DataFrame()).empty)

    def test_best_segment_finds_the_fast_part(self):
        # 2 km easy, 2 km fast (4:00), 2 km easy
        seconds, _ = sessions.best_segment(track(1, 6.0, [6.0, 4.0, 6.0], points=600), 2000)
        self.assertAlmostEqual(seconds, 480, delta=6)
        self.assertIsNone(sessions.best_segment(track(1, 3.0, 5.0), 5000))


class Efforts(unittest.TestCase):
    def test_sources_and_gps_artefacts(self):
        rows = [
            run(1, "2026-01-05", 10.0, 5.0, best_1k_s=280, best_5k_s=1480),
            run(2, "2026-01-06", 6.0, 5.0, best_1k_s=120),  # 2:00 /km: GPS cut, dropped
        ]
        frame = sessions.select_runs(activities(rows))
        routes = pd.concat([track(1, 10.0, 5.0), track(2, 6.0, 5.0)])
        table = sessions.efforts(frame, routes)
        mine = table[table["activity_id"] == 1].set_index("effort")
        self.assertEqual(mine.loc["1k", "source"], "garmin")
        self.assertEqual(mine.loc["10k", "source"], "whole")
        self.assertEqual(mine.loc["3k", "source"], "stream")
        self.assertNotIn("1k", set(table[table["activity_id"] == 2]["effort"]))
        self.assertAlmostEqual(mine.loc["10k", "vdot"], physio.vdot(10000, 3000), places=3)

    def test_records_pick_fastest(self):
        table = pd.DataFrame([
            {"effort": "5k", "seconds": 1500, "activity_id": 1},
            {"effort": "5k", "seconds": 1450, "activity_id": 2},
            {"effort": "10k", "seconds": 3100, "activity_id": 3},
        ])
        records = sessions.records(table).set_index("effort")
        self.assertEqual(records.loc["5k", "activity_id"], 2)
        self.assertEqual(list(records.index), ["5k", "10k"])


class Summaries(unittest.TestCase):
    def setUp(self):
        rows = [
            run(1, "2026-03-02", 10.0, 6.0),
            run(2, "2026-03-04", 5.0, 5.0),
            run(3, "2026-03-20", 8.0, 6.0),  # two empty weeks before it
        ]
        self.runs = sessions.select_runs(activities(rows)).assign(kind=["easy", "threshold", "easy"])

    def test_window_summary_uses_total_time_over_total_distance(self):
        summary = sessions.window_summary(self.runs, pd.Timestamp("2026-03-05"), 7)
        self.assertEqual(summary["runs"], 2)
        self.assertAlmostEqual(summary["pace"], (60 + 25) / 15)  # not the mean of 6.0 and 5.0
        self.assertEqual(summary["longest_km"], 10.0)
        empty = sessions.window_summary(self.runs, pd.Timestamp("2025-01-01"), 7)
        self.assertEqual(empty["runs"], 0)
        self.assertIsNone(empty["pace"])

    def test_weekly_is_gap_free(self):
        weeks = sessions.weekly(self.runs)
        self.assertEqual(weeks["km"].tolist(), [15.0, 0.0, 8.0])
        self.assertEqual(weeks["hard"].tolist(), [1, 0, 0])
        self.assertEqual(weeks["hard_km"].tolist(), [5.0, 0.0, 0.0])

    def test_gaps(self):
        info = sessions.gaps(self.runs, pd.Timestamp("2026-03-01"), pd.Timestamp("2026-03-22"))
        self.assertEqual(info["run_days"], 3)
        self.assertEqual(info["longest_break"], 15)  # 5th..19th
        self.assertEqual(info["days_since_last"], 2)

    def test_km_ratio_needs_a_real_base(self):
        ratio = sessions.km_ratio(self.runs)
        self.assertTrue(ratio["ratio"].isna().all())  # chronic < 5 km/week: not computed

    def test_similar_same_kind_and_distance(self):
        rows = [run(i, f"2026-02-{i:02d}", km, 6.0) for i, km in ((1, 10.0), (2, 11.0), (3, 6.0), (4, 9.0))]
        frame = sessions.select_runs(activities(rows)).assign(kind="easy")
        self.assertEqual(sorted(sessions.similar(frame, 1)["activity_id"]), [2, 4])


if __name__ == "__main__":
    unittest.main()
