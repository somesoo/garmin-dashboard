"""The forecast model: inputs, endurance correction, interval, history without look-ahead."""

from __future__ import annotations

import math
import unittest

import pandas as pd

from tests.helpers import activities, daily, run, training_block
from running import forecast, physio, sessions, units


def efforts_frame(rows: list[dict]) -> pd.DataFrame:
    """Efforts with quality already set: (activity_id, day, metres, seconds, near_max)."""
    out = []
    for row in rows:
        out.append({
            "activity_id": row["activity_id"], "day": pd.Timestamp(row["day"]), "effort": row.get("effort", "5k"),
            "distance_m": row["metres"], "seconds": row["seconds"],
            "pace_min_km": units.pace_from(row["seconds"], row["metres"] / 1000),
            "avg_hr": row.get("avg_hr"), "source": "test", "vdot": physio.vdot(row["metres"], row["seconds"]),
            "hr_frac": row.get("hr_frac"), "minutes": row["seconds"] / 60, "near_max": row.get("near_max", True),
        })
    return pd.DataFrame(out)


class Fixture(unittest.TestCase):
    """Eight weeks of steady training (3x easy + 12 km long) and a 5 km test at its end."""

    def setUp(self):
        rows = training_block("2026-01-05", 8, long_km=12.0)
        rows.append(run(900, "2026-02-27", 5.0, 5.0, hr=175, name="5 km test"))
        self.runs = sessions.select_runs(activities(rows)).assign(kind="easy", kind_reason="", kind_confidence="")
        self.runs.loc[self.runs["activity_id"] == 900, "kind"] = "race"
        self.daily = daily("2025-12-01", 120)
        self.efforts = efforts_frame([{"activity_id": 900, "day": "2026-02-27", "metres": 5000, "seconds": 1500}])
        self.anchor = pd.Timestamp("2026-03-01")

    def run_forecast(self, **kwargs):
        return forecast.forecast(self.runs, self.efforts, self.daily, self.anchor, hr_max=190, **kwargs)


class Insufficient(unittest.TestCase):
    def test_no_runs(self):
        self.assertEqual(forecast.forecast(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())["status"], "insufficient")

    def test_no_efforts_and_no_hr_calibration(self):
        rows = [run(i, f"2026-01-{i:02d}", 5.0, 6.0, hr=None) for i in range(1, 6)]
        frame = sessions.select_runs(activities(rows)).assign(kind="easy")
        result = forecast.forecast(frame, efforts_frame([]).reindex(columns=["activity_id", "day", "vdot", "near_max"]),
                                   daily("2026-01-01", 10), hr_max=None)
        self.assertEqual(result["status"], "insufficient")
        self.assertIn("test", result["reason"])


class Model(Fixture):
    def test_potential_is_daniels_equivalent_of_the_test(self):
        result = self.run_forecast()
        self.assertEqual(result["status"], "ok")
        vdot = physio.vdot(5000, 1500)
        self.assertAlmostEqual(result["vdot"], vdot, places=6)  # fresh near-max test speaks for itself
        for key, item in result["distances"].items():
            self.assertAlmostEqual(item.potential_s, physio.race_time(vdot, units.RACES[key] * 1000), delta=0.5)

    def test_no_endurance_tax_at_or_below_the_anchor_distance(self):
        item = self.run_forecast()["distances"]["5k"]
        self.assertAlmostEqual(item.realistic_s, item.potential_s, delta=0.5)

    def test_endurance_tax_grows_with_distance_and_missing_preparation(self):
        result = self.run_forecast()
        ratios = {k: i.realistic_s / i.potential_s for k, i in result["distances"].items()}
        self.assertLess(ratios["10k"], ratios["hm"])
        self.assertLess(ratios["hm"], ratios["m"])
        marathon = result["distances"]["m"]
        expected = (42195 / 5000) ** (forecast.MAX_EXTRA_EXPONENT * (1 - marathon.prep["score"]))
        self.assertAlmostEqual(ratios["m"], expected, places=6)
        # 12 km long runs and ~31 km weeks: a marathon is clearly under-prepared.
        self.assertLess(marathon.prep["score"], 0.75)
        self.assertGreater(marathon.prep["score"], 0.0)

    def test_full_preparation_removes_the_tax(self):
        self.assertEqual(forecast._penalty(42195, 5000, 1.0), 1.0)
        self.assertEqual(forecast._penalty(3000, 5000, 0.0), 1.0)
        self.assertAlmostEqual(forecast._penalty(42195, 5000, 0.0), (42195 / 5000) ** 0.08)

    def test_interval_brackets_the_estimate_and_widens_with_distance(self):
        result = self.run_forecast()
        widths = {}
        for key, item in result["distances"].items():
            self.assertLess(item.low_s, item.realistic_s)
            self.assertGreater(item.high_s, item.realistic_s)
            self.assertAlmostEqual(item.pace, item.realistic_s / 60 / units.RACES[key])
            widths[key] = math.log(item.high_s / item.low_s)
        self.assertLess(widths["5k"], widths["m"])

    def test_confidence_reasons_name_what_widens_the_interval(self):
        result = self.run_forecast()
        for item in result["distances"].values():
            reasons = forecast.confidence_reasons(item, result["perf"])
            self.assertEqual(reasons == [], item.confidence == "wysoka")
        marathon = result["distances"]["m"]
        self.assertNotEqual(marathon.confidence, "wysoka")
        self.assertTrue(any("maraton" in reason for reason in forecast.confidence_reasons(marathon, result["perf"])))

    def test_target_after_plan_is_faster_than_today(self):
        result = self.run_forecast(weeks_to_race={"hm": 10}, plan_prep={"hm": 0.9})
        item = result["distances"]["hm"]
        self.assertLess(item.target_s, item.realistic_s)
        self.assertLess(item.target_low_s, item.target_s)
        self.assertGreater(item.target_high_s, item.target_s)
        self.assertIsNone(result["distances"]["5k"].target_s)

    def test_target_is_per_race(self):
        item = self.run_forecast()["distances"]["hm"]
        near, far = forecast.target(item, 17.6, 0.9), forecast.target(item, 22.6, 0.9)
        self.assertLess(far.target_s, near.target_s)
        self.assertIsNone(item.target_s)
        self.assertEqual(forecast.counted_weeks(10), 10)
        self.assertEqual(forecast.counted_weeks(20), 18)
        self.assertEqual(forecast.counted_weeks(60), forecast.counted_weeks(32))

    def test_steady_target_flattens_and_keeps_preparation(self):
        item = self.run_forecast()["distances"]["hm"]
        self.assertEqual(forecast.steady(item, 10, 0.0).target_s, item.realistic_s)  # no regular running: no gain
        soon, later, much_later = (forecast.steady(item, w, 1.0) for w in (6, 18, 40))
        self.assertLess(later.target_s, soon.target_s)
        self.assertLess(later.target_s - much_later.target_s, 1.0 + (soon.target_s - later.target_s) / 5)
        self.assertGreater(later.target_s, forecast.target(item, 18, 1.0).target_s)  # a plan beats "as now"
        self.assertEqual(later.target_basis, "steady")
        self.assertEqual(forecast.goal_status(later, later.target_s + 1), "steady")

    def test_preparation_components(self):
        prep = forecast.preparation(self.runs, self.anchor, "hm")
        self.assertEqual(prep["long_km"], 12.0)
        self.assertEqual(prep["long_need"], 18)
        self.assertAlmostEqual(prep["consistency"], 1.0)
        self.assertAlmostEqual(prep["score"], 0.4 * 12 / 18 + 0.4 * min(1, prep["weekly_km"] / 40) + 0.2, places=3)


class EffortHandling(Fixture):
    def test_training_split_is_a_lower_bound(self):
        self.efforts = efforts_frame([{"activity_id": 900, "day": "2026-02-27", "metres": 5000, "seconds": 1500,
                                       "near_max": False}])
        result = self.run_forecast()
        self.assertTrue(result["lower_bound"])
        self.assertTrue(any("dolna granica" in note for note in result["notes"]))
        item = result["distances"]["5k"]
        # The fast side of the band is wider than the slow side.
        self.assertGreater(math.log(item.realistic_s / item.low_s), math.log(item.high_s / item.realistic_s))

    def test_lone_gps_outlier_is_ignored(self):
        self.efforts = efforts_frame([
            {"activity_id": 900, "day": "2026-02-27", "metres": 5000, "seconds": 1500},
            {"activity_id": 901, "day": "2026-02-20", "metres": 5000, "seconds": 1200, "near_max": False},  # 4:00/km?
        ])
        perf = forecast.performance_vdot(self.efforts, self.anchor)
        self.assertEqual(perf["activity_id"], 900)

    def test_old_maximal_effort_fades_but_counts(self):
        self.efforts = efforts_frame([{"activity_id": 900, "day": "2025-09-01", "metres": 5000, "seconds": 1500}])
        perf = forecast.performance_vdot(self.efforts, self.anchor)
        self.assertIsNotNone(perf)
        self.assertLess(perf["vdot"], perf["vdot_raw"])
        self.assertAlmostEqual(perf["vdot"] / perf["vdot_raw"], forecast.detraining(perf["age_days"]))
        self.assertEqual(forecast.detraining(14), 1.0)
        self.assertEqual(forecast.detraining(10_000), 0.88)

    def test_effort_quality_flags(self):
        frame = efforts_frame([
            {"activity_id": 1, "day": "2026-02-01", "metres": 3000, "seconds": 840, "avg_hr": 176},
            {"activity_id": 2, "day": "2026-02-02", "metres": 1000, "seconds": 260, "avg_hr": 180},  # < 6 min
            {"activity_id": 3, "day": "2026-02-03", "metres": 5000, "seconds": 1600, "avg_hr": 150},
        ]).drop(columns=["hr_frac", "minutes", "near_max"])
        quality = forecast.effort_quality(frame, pd.DataFrame(), 190).set_index("activity_id")
        self.assertTrue(quality.loc[1, "near_max"])
        self.assertFalse(quality.loc[2, "near_max"])
        self.assertFalse(quality.loc[3, "near_max"])


class History(Fixture):
    def test_snapshots_do_not_see_the_future(self):
        frame = forecast.history(self.runs, self.efforts, self.daily, hr_max=190, step_days=7)
        before = frame[frame["day"] < pd.Timestamp("2026-02-27")]
        after = frame[frame["day"] >= pd.Timestamp("2026-02-27")]
        self.assertTrue(before.empty)  # the only effort is the test; nothing to forecast from before it
        self.assertFalse(after.empty)
        self.assertEqual(set(after["distance"]), set(units.RACES))

    def test_trend_and_backtest(self):
        history = pd.DataFrame([
            {"day": pd.Timestamp("2026-01-01"), "distance": "10k", "realistic_s": 3000, "vdot": 33.0},
            {"day": pd.Timestamp("2026-02-01"), "distance": "10k", "realistic_s": 2900, "vdot": 34.0},
        ])
        self.assertEqual(forecast.trend(history, "10k", 4), -100)
        self.assertIsNone(forecast.trend(history, "10k", 12))
        table = forecast.backtest(history, self.efforts)
        self.assertEqual(len(table), 1)
        predicted = physio.race_time(34.0, 5000)
        self.assertAlmostEqual(table["error_pct"].iloc[0], round(100 * (predicted / 1500 - 1), 1), places=6)


class Goals(Fixture):
    def test_goal_status_ordering(self):
        item = self.run_forecast(weeks_to_race={"10k": 12})["distances"]["10k"]
        self.assertEqual(forecast.goal_status(item, None), "none")
        self.assertEqual(forecast.goal_status(item, item.realistic_s + 60), "now")
        self.assertEqual(forecast.goal_status(item, (item.realistic_s + item.target_s) / 2), "plan")
        self.assertEqual(forecast.goal_status(item, (item.target_s + item.target_low_s) / 2), "ambitious")
        self.assertEqual(forecast.goal_status(item, item.target_low_s - 120), "stretch")

    def test_advice_names_the_missing_long_run(self):
        result = self.run_forecast()
        tips = forecast.advice(result, self.runs, "m")
        self.assertTrue(any("Długie wybieganie" in tip for tip in tips))
        self.assertLessEqual(len(tips), 4)


if __name__ == "__main__":
    unittest.main()
