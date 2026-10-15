"""Pace/time arithmetic and Daniels' model against his published tables."""

from __future__ import annotations

import math
import unittest

import pandas as pd

import tests.helpers  # noqa: F401 - puts the repo on sys.path
from running import physio, units


class Units(unittest.TestCase):
    def test_pace_and_time_are_inverse(self):
        pace = units.pace_from(1500, 5)  # 25:00 for 5 km
        self.assertAlmostEqual(pace, 5.0)
        self.assertAlmostEqual(units.time_from(pace, 5), 1500)
        self.assertAlmostEqual(units.time_from(5.0, units.RACES["hm"]), 6329.25)

    def test_speed_conversion(self):
        self.assertAlmostEqual(units.speed_ms(5.0), 1000 / 300)
        self.assertAlmostEqual(units.pace_from_speed(1000 / 300), 5.0)

    def test_invalid_inputs_return_none(self):
        for args in ((0, 5), (1500, 0), (None, 5), (float("nan"), 5), ("x", 5), (-10, 5)):
            self.assertIsNone(units.pace_from(*args), args)
        self.assertIsNone(units.time_from(None, 10))
        self.assertIsNone(units.speed_ms(0))

    def test_formatting_rounds_on_whole_seconds(self):
        self.assertEqual(units.fmt_pace(5.999), "6:00 /km")
        self.assertEqual(units.fmt_pace(5.5, unit=False), "5:30")
        self.assertEqual(units.fmt_time(59 * 60 + 59.6), "1:00:00")
        self.assertEqual(units.fmt_time(1447), "24:07")
        self.assertEqual(units.fmt_time(6654), "1:50:54")
        self.assertEqual(units.fmt_delta(-65), "-1:05")
        self.assertEqual(units.fmt_delta(40), "+0:40")
        for missing in (None, float("nan"), pd.NA):
            self.assertEqual(units.fmt_time(missing), "—")
            self.assertEqual(units.fmt_pace(missing), "—")

    def test_parse_time(self):
        self.assertEqual(units.parse_time("1:45:00"), 6300)
        self.assertEqual(units.parse_time("45:30"), 2730)
        self.assertEqual(units.parse_time(" 24:07.6 "), 1447)
        for bad in ("", "abc", "45:75", "1:61:00", "0:00", None, "12"):
            self.assertIsNone(units.parse_time(bad), bad)

    def test_parse_pace(self):
        self.assertAlmostEqual(units.parse_pace("4:55"), 4 + 55 / 60)
        self.assertAlmostEqual(units.parse_pace("5:30/km"), 5.5)
        self.assertIsNone(units.parse_pace("5:75"))
        self.assertIsNone(units.parse_pace("0:00"))

    def test_race_key_tolerance(self):
        self.assertEqual(units.race_key(21.1), "hm")
        self.assertEqual(units.race_key(42.4), "m")
        self.assertEqual(units.race_key(5.08), "5k")
        self.assertIsNone(units.race_key(7.0))
        self.assertIsNone(units.race_key(None))


class Daniels(unittest.TestCase):
    # Daniels' Running Formula, VDOT table: (vdot, distance m, h:mm:ss)
    TABLE = [
        (40, 5000, "24:08"), (40, 10000, "50:03"), (40, 21097.5, "1:50:59"), (40, 42195, "3:49:45"),
        (50, 5000, "19:57"), (50, 10000, "41:21"), (50, 21097.5, "1:31:35"), (50, 42195, "3:10:49"),
    ]

    def test_race_times_match_published_table(self):
        for vdot, metres, published in self.TABLE:
            predicted = physio.race_time(vdot, metres)
            # The book rounds its own curve; within 0.25% is the same number.
            self.assertLess(abs(predicted / units.parse_time(published) - 1), 0.0025, (vdot, metres))

    def test_vdot_and_race_time_are_inverse(self):
        for metres, seconds in ((5000, 1500), (10000, 3000), (21097.5, 6600), (42195, 14400)):
            value = physio.vdot(metres, seconds)
            self.assertAlmostEqual(physio.race_time(value, metres), seconds, delta=1.0)

    def test_vdot_outside_curve_range_is_none(self):
        self.assertIsNone(physio.vdot(400, 70))  # 70 s: below 3.5 min
        self.assertIsNone(physio.vdot(0, 100))
        self.assertIsNone(physio.vdot(5000, None))
        self.assertIsNone(physio.race_time(None, 5000))

    def test_training_paces_are_ordered(self):
        paces = physio.training_paces(45)
        centre = {k: (a + b) / 2 for k, (a, b) in paces.items()}
        self.assertGreater(centre["E"], centre["M"])
        self.assertGreater(centre["M"], centre["T"])
        self.assertGreater(centre["T"], centre["I"])
        self.assertGreater(centre["I"], centre["R"])
        for fast, slow in paces.values():
            self.assertLess(fast, slow)
        # VDOT 50 threshold pace is 4:15 /km in the tables.
        t_fast, t_slow = physio.training_paces(50)["T"]
        self.assertTrue(t_fast * 60 <= 255 + 3 and t_slow * 60 >= 255 - 3)
        self.assertEqual(physio.training_paces(None), {})


class HeartRate(unittest.TestCase):
    def test_robust_hr_max_ignores_single_spikes(self):
        values = [178, 181, 183, 185, 186, 186, 186, 199, 205, 240]  # 240 is not a heart rate
        self.assertEqual(physio.robust_hr_max(values), 186)
        self.assertIsNone(physio.robust_hr_max([180, 182]))

    def test_resting_hr_uses_window_before_anchor(self):
        daily = pd.DataFrame({"day": pd.date_range("2026-01-01", periods=60), "rhr": [60] * 30 + [50] * 30})
        self.assertEqual(physio.resting_hr(daily, pd.Timestamp("2026-01-30")), 60)
        self.assertEqual(physio.resting_hr(daily, pd.Timestamp("2026-03-01")), 50)
        self.assertIsNone(physio.resting_hr(pd.DataFrame()))

    def test_vo2max_from_hr(self):
        speed = units.speed_ms(5.5)
        value = physio.vo2max_from_hr(speed, 150, 190, 50)
        reserve = (150 - 50) / 140
        self.assertAlmostEqual(value, (physio.oxygen_cost(speed * 60) - 3.5) / reserve + 3.5)
        self.assertIsNone(physio.vo2max_from_hr(speed, 80, 190, 50))   # below 55% HRR
        self.assertIsNone(physio.vo2max_from_hr(speed, 185, 190, 50))  # above 92% HRR
        self.assertIsNone(physio.vo2max_from_hr(speed, 150, 50, 60))
        self.assertIsNone(physio.vo2max_from_hr(speed, math.nan, 190, 50))


if __name__ == "__main__":
    unittest.main()
