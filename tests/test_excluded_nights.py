"""Excluded nights blank the night columns and stay out of the rolling baselines."""

from __future__ import annotations

import datetime as dt
import unittest

import pandas as pd

import tests.helpers  # noqa: F401 - puts the repo root on sys.path
from etl import load


class MaskNights(unittest.TestCase):
    def frame(self):
        days = pd.date_range("2026-10-10", periods=8)
        return pd.DataFrame({
            "day": days,
            "sleep_h": [7.0] * 7 + [3.0],
            "hrv_last_night": [60.0] * 7 + [120.0],
            "rhr": [48.0] * 7 + [70.0],
            "readiness": [70.0] * 7 + [20.0],
            "steps": [10000.0] * 8,
        })

    def test_blanks_night_but_keeps_day(self):
        df = load.add_derived(load.mask_nights(self.frame(), {dt.date(2026, 10, 17): "x"}))
        last = df.iloc[-1]
        for col in ("sleep_h", "hrv_last_night", "rhr", "readiness", "hrv_deviation"):
            self.assertTrue(pd.isna(last[col]), col)
        self.assertEqual(last["steps"], 10000.0)
        self.assertTrue(last["night_excluded"])
        self.assertEqual(last["hrv_last_night_roll7"], 60.0)
        self.assertEqual(last["sleep_h_roll7"], 7.0)

    def test_no_exclusions_is_noop(self):
        df = load.mask_nights(self.frame(), {})
        self.assertFalse(df["night_excluded"].any())
        self.assertEqual(df["sleep_h"].iloc[-1], 3.0)


if __name__ == "__main__":
    unittest.main()
