"""Facts behind the page heroes (facts.py): true sentences, anchors on the chart, both languages."""

from __future__ import annotations

import datetime as dt
import json
import unittest

import numpy as np
import pandas as pd

import facts
import i18n

TODAY = dt.date(2026, 11, 1)


def _runs(days: list[str], kinds: list[str] | None = None) -> pd.DataFrame:
    kinds = kinds or ["easy"] * len(days)
    return pd.DataFrame({"activity_id": range(len(days)), "start_local": pd.to_datetime(days), "day": pd.to_datetime(days),
                         "distance_km": [10.0] * len(days), "pace_min_km": [6.0] * len(days), "kind": kinds,
                         "hr_z1_s": 100, "hr_z2_s": 100, "hr_z3_s": 600, "hr_z4_s": 100, "hr_z5_s": 100})


def _daily() -> pd.DataFrame:
    days = pd.date_range("2026-08-01", "2026-11-01")
    rng = np.random.default_rng(0)
    hrv = 56 + rng.normal(0, 3, len(days))
    hrv[-1] = 60
    sleep = 7.3 + rng.normal(0, 0.4, len(days))
    sleep[-1] = 5.5
    return pd.DataFrame({"day": days, "hrv_last_night": hrv, "hrv_baseline_low": 53.0, "hrv_baseline_high": 64.0,
                         "rhr": 48 + rng.normal(0, 1, len(days)), "sleep_h": sleep, "readiness": 60.0,
                         "sleep_score": 80.0, "sleep_deep_h": 1.2, "sleep_rem_h": 1.3})


class Loop(unittest.TestCase):
    def test_four_numbers(self):
        runs = _runs(["2026-10-28", "2026-10-31", "2026-10-10"])
        forecast = pd.DataFrame({"day": pd.to_datetime(["2026-10-25", "2026-11-01"]), "distance": "10k",
                                 "realistic_s": [3100.0, 3037.0]})
        races = [{"name": "X", "date": "2026-11-11", "distance": "10k"}]
        values = facts.loop_values(_daily(), runs, forecast, races, TODAY)
        self.assertEqual(values["load"], "20 km / 7 dni")
        self.assertTrue(values["response"].startswith("HRV +"))
        self.assertEqual(values["adapt"], "10 km: 50:37")
        self.assertEqual(values["goal"], "za 10 dni")

    def test_nothing_known(self):
        values = facts.loop_values(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), [], TODAY)
        self.assertEqual(set(values.values()), {"—"})


class Recovery(unittest.TestCase):
    def test_headline_and_anchors(self):
        told = facts.recovery(_daily(), _runs(["2026-10-20", "2026-10-27"], ["intervals", "threshold"]), None)
        self.assertIn("<em>", told["headline"])
        sides = {s["side"] for s in told["satellites"]}
        self.assertEqual(sides, {"l", "r"})
        last = next(s for s in told["satellites"] if s["anchor"] and s["anchor"][0] == pd.Timestamp("2026-11-01"))
        self.assertEqual(last["anchor"][1], 60.0)
        json.dumps([{**s, "anchor": None} for s in told["satellites"]])


class Breaks(unittest.TestCase):
    def test_empty_weeks_make_a_break(self):
        runs = _runs(["2026-05-04", "2026-05-11", "2026-09-14", "2026-09-21"])
        calendar = facts.calendar_weeks(facts.weekly_km(runs), pd.Timestamp("2026-05-01"), pd.Timestamp("2026-09-30"))
        gaps = facts.breaks(calendar)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0][0], pd.Timestamp("2026-05-18"))
        self.assertEqual(gaps[0][1], pd.Timestamp("2026-09-14"))
        self.assertEqual(gaps[0][2], 17)

    def test_fitness_that_did_not_drop_is_not_called_a_drop(self):
        # A running break with cycling in it: CTL rose. The sentence must not say it fell.
        runs = _runs(["2026-05-04", "2026-05-11", "2026-09-14", "2026-09-21"])
        pmc = pd.DataFrame({"day": pd.date_range("2026-05-01", "2026-10-01"), "ctl": np.linspace(15, 20, 154)})
        told = facts.running_year(runs, pmc, pd.Timestamp("2026-05-01"), pd.Timestamp("2026-10-01"))
        longest = next(s for s in told["satellites"] if "przerwa" in s["group"].lower())
        self.assertNotIn("Forma (CTL) spadła", longest["text"])
        self.assertIn("nie spadła", longest["text"])


class Load(unittest.TestCase):
    def test_peak_outside_the_range_is_named_not_anchored(self):
        days = pd.date_range("2025-06-01", "2026-11-01")
        ctl = np.concatenate([np.linspace(20, 60, 90), np.linspace(60, 10, len(days) - 140), np.linspace(10, 33, 50)])
        pmc = pd.DataFrame({"day": days, "ctl": ctl, "atl": ctl + 10, "tsb": -10.0})
        told = facts.load(pmc, None, _daily(), pd.Timestamp("2025-11-01"))
        peak = next(s for s in told["satellites"] if s["group"] == "Szczyt formy")
        self.assertIsNone(peak["anchor"])
        self.assertIn("Forma rośnie", told["headline"])


class Forecast(unittest.TestCase):
    def test_faster_than_eight_weeks_ago(self):
        days = pd.date_range("2026-08-01", "2026-11-01", freq="7D")
        history = pd.DataFrame({"day": days, "distance": "10k", "realistic_s": np.linspace(3600, 3037, len(days)),
                                "low_s": 2900.0, "high_s": 3700.0, "vdot": np.linspace(36, 40, len(days))})
        told = facts.forecast(history, [{"name": "X", "date": "2026-11-11", "distance": "10k", "goal_s": 2700.0}], None)
        self.assertIn("szybciej", told["headline"])
        goal = next(s for s in told["satellites"] if s["group"].startswith("Cel"))
        self.assertIn("wolniejsza niż cel", goal["text"])

    def test_english(self):
        i18n.force("en")
        try:
            values = facts.loop_values(_daily(), _runs(["2026-10-31"]), pd.DataFrame(), [], TODAY)
        finally:
            i18n.force("pl")
        self.assertEqual(values["load"], "10 km / 7 days")


if __name__ == "__main__":
    unittest.main()
