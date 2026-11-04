import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import hrzones


class Anchors(unittest.TestCase):
    def test_measured_threshold_estimates_vt1(self):
        found = hrzones.anchors(lthr=179, hr_max=192, manual={})
        self.assertEqual((found["lthr"], found["lthr_source"], found["vt1"], found["vt1_source"]),
                         (179, "data", 163, "estimate"))
        self.assertEqual(hrzones.edges(found), [152, 163, 170, 179])
        self.assertEqual(hrzones.basis(found), "lthr")

    def test_typed_in_values_beat_the_data(self):
        found = hrzones.anchors(lthr=179, hr_max=192, manual={"lthr": 175, "vt1": 150, "hr_max": 195})
        self.assertEqual((found["lthr"], found["vt1"], found["hr_max"]), (175, 150, 195))
        self.assertEqual({found["lthr_source"], found["vt1_source"], found["hr_max_source"]}, {"manual"})
        self.assertEqual(hrzones.basis(found), "manual")

    def test_only_a_maximum_gives_a_labelled_estimate(self):
        found = hrzones.anchors(hr_max=192, manual={})
        self.assertEqual((found["lthr"], found["lthr_source"]), (180, "estimate"))
        self.assertEqual(hrzones.basis(found), "hr_max")

    def test_nothing_known_means_no_zones(self):
        self.assertIsNone(hrzones.anchors(manual={}))
        self.assertIsNone(hrzones.edges(None))
        self.assertIsNone(hrzones.bands(None))

    def test_bands_meet_without_gaps(self):
        bands = hrzones.bands(hrzones.anchors(lthr=179, hr_max=192, manual={}))
        self.assertEqual(bands[0], (None, 151))
        self.assertEqual(bands[-1], (179, 192))
        for (_, high), (low, _) in zip(bands[:-1], bands[1:]):
            self.assertEqual(high + 1, low)

    def test_a_low_measured_vt1_keeps_the_zones_ordered(self):
        cuts = hrzones.edges(hrzones.anchors(lthr=180, manual={"vt1": 140}))
        self.assertEqual(cuts, sorted(set(cuts)))


class Settings(unittest.TestCase):
    def test_round_trip_validation_and_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "zones.json"
            stored = hrzones.save({"lthr": 176, "vt1": 158, "hr_max": None, "method": "field",
                                   "measured": "2026-10-01"}, file)
            self.assertEqual(hrzones.settings(file), stored)
            self.assertEqual(stored, {"lthr": 176, "vt1": 158, "method": "field", "measured": "2026-10-01"})
            with self.assertRaises(ValueError):
                hrzones.save({"lthr": 170, "vt1": 171}, file)
            self.assertEqual(hrzones.problems({"lthr": 190, "hr_max": 185}), ["lthr_above_max"])
            hrzones.save({}, file)
            self.assertFalse(file.exists())
            self.assertEqual(hrzones.settings(file), {})

    def test_clean_drops_what_is_not_a_heart_rate(self):
        self.assertEqual(hrzones.clean({"lthr": 300, "hr_max": "190", "method": "guess"}), {"hr_max": 190})


class ZoneTime(unittest.TestCase):
    def frames(self, source="garmin"):
        activities = pd.DataFrame({"activity_id": [1, 2], "day": pd.to_datetime(["2026-03-01", "2026-03-02"]),
                                   "source": source, **{f"hr_z{i}_s": [10.0, 5.0] for i in range(1, 6)}})
        routes = pd.DataFrame({"activity_id": 1, "duration_s": np.arange(20) * 10.0,
                               "hr": [150.0] * 10 + [175.0] * 10})
        return activities, routes

    def test_stream_split_in_the_persons_zones(self):
        activities, routes = self.frames()
        zones = hrzones.zone_time(activities, routes, None, 192, manual={"lthr": 179})
        row = zones.iloc[0]
        self.assertEqual(list(zones["activity_id"]), [1])          # no stream, no row
        self.assertEqual((row["hr_z1_s"], row["hr_z4_s"]), (100, 90))  # 150 < 152; 170 <= 175 < 179
        self.assertEqual((row["zone_lthr"], row["zone_vt1"], row["zone_basis"]), (179, 163, "manual"))

        merged = hrzones.with_zone_time(activities, zones)
        self.assertEqual(merged.loc[0, "hr_z1_s"], 100)
        self.assertTrue(np.isnan(merged.loc[1, "hr_z1_s"]))         # the watch's split is not reused
        self.assertEqual(merged.loc[1, "garmin_hr_z1_s"], 5)

    def test_apple_rows_without_a_stream_keep_their_own_split(self):
        activities, routes = self.frames("apple")
        merged = hrzones.with_zone_time(activities, hrzones.zone_time(activities, routes, None, 192, manual={}))
        self.assertEqual(merged.loc[1, "hr_z1_s"], 5)

    def test_no_anchor_no_split(self):
        activities, routes = self.frames()
        self.assertTrue(hrzones.zone_time(activities, routes, None, None, manual={}).empty)


if __name__ == "__main__":
    unittest.main()
