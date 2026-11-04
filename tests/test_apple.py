"""Apple Health export -> warehouse tables (etl/apple.py), on a synthetic export with known answers."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import math
import unittest
import zipfile
from pathlib import Path

import pandas as pd

import tenant
from etl import apple, load, schema
from tests.helpers import person

Q, C = apple.Q, apple.C


def rec(kind, source, start, end=None, value=None, unit=""):
    value_attr = f' value="{value}"' if value is not None else ""
    return (f'<Record type="{kind}" sourceName="{source}" unit="{unit}" startDate="{start} +0100" '
            f'endDate="{end or start} +0100"{value_attr}/>')


def sleep(source, start, end, stage):
    return rec(f"{C}SleepAnalysis", source, start, end, f"HKCategoryValueSleepAnalysis{stage}")


def workout(kind, source, start, end, minutes, km=None, route=None, hr=None):
    stats = ""
    if km is not None:
        stats += (f'<WorkoutStatistics type="{Q}DistanceWalkingRunning" startDate="{start} +0100" '
                  f'endDate="{end} +0100" sum="{km}" unit="km"/>')
    if hr:
        stats += (f'<WorkoutStatistics type="{Q}HeartRate" startDate="{start} +0100" endDate="{end} +0100" '
                  f'average="{hr[0]}" maximum="{hr[1]}" unit="count/min"/>')
    ref = f'<WorkoutRoute sourceName="{source}"><FileReference path="{route}"/></WorkoutRoute>' if route else ""
    return (f'<Workout workoutActivityType="HKWorkoutActivityType{kind}" duration="{minutes}" durationUnit="min" '
            f'sourceName="{source}" startDate="{start} +0100" endDate="{end} +0100">'
            f'<MetadataEntry key="HKElevationAscended" value="4200 cm"/>{stats}{ref}</Workout>')


def gpx(points, same_time=False):
    rows = []
    for i, (lat, lon) in enumerate(points):
        stamp = "2026-04-24T14:00:00Z" if same_time else f"2026-04-24T14:{i // 60:02d}:{i % 60:02d}Z"
        rows.append(f'<trkpt lat="{lat}" lon="{lon}"><ele>{100 + i % 7}</ele><time>{stamp}</time></trkpt>')
    return ('<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
            + "".join(rows) + "</trkseg></trk></gpx>").encode()


def line(n=60, km=1.0):
    """n points going north, km long in total."""
    step = km / 111.2 / (n - 1)
    return [(51.0 + i * step, 17.0) for i in range(n)]


def build_zip(body: str, files: dict[str, bytes] | None = None) -> bytes:
    xml = ('<?xml version="1.0" encoding="UTF-8"?><HealthData locale="pl_PL">'
           '<ExportDate value="2026-11-02 21:00:00 +0100"/>'
           '<Me HKCharacteristicTypeIdentifierDateOfBirth="2001-09-04" '
           'HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"/>' + body + "</HealthData>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("apple_health_export/export.xml", xml)
        for name, data in (files or {}).items():
            archive.writestr(f"apple_health_export{name}", data)
    return buffer.getvalue()


EXPORT = "".join([
    # Steps on 2026-04-20 from two sources covering the same walk: max, not sum.
    rec(f"{Q}StepCount", "iPhone", "2026-04-20 09:00:00", "2026-04-20 10:00:00", 4000, "count"),
    rec(f"{Q}StepCount", "iPhone", "2026-04-20 18:00:00", "2026-04-20 19:00:00", 2000, "count"),
    rec(f"{Q}StepCount", "Connect", "2026-04-20 00:00:00", "2026-04-20 23:59:00", 6500, "count"),
    rec(f"{Q}DistanceWalkingRunning", "iPhone", "2026-04-20 09:00:00", "2026-04-20 10:00:00", 3.2, "km"),
    rec(f"{Q}ActiveEnergyBurned", "iPhone", "2026-04-20 09:00:00", "2026-04-20 10:00:00", 400, "kcal"),
    rec(f"{Q}BasalEnergyBurned", "iPhone", "2026-04-20 00:00:00", "2026-04-20 23:00:00", 1700, "kcal"),
    rec(f"{Q}RestingHeartRate", "Connect", "2026-04-20 08:00:00", None, 50, "count/min"),
    rec(f"{Q}RestingHeartRate", "Connect", "2026-04-21 08:00:00", None, 52, "count/min"),
    rec(f"{Q}HeartRateVariabilitySDNN", "Watch", "2026-04-21 03:00:00", None, 0.055, "s"),
    rec(f"{Q}BodyMass", "Health", "2026-04-21 07:00:00", None, 165, "lb"),
    # Night ending 2026-04-21: Connect staged session + iPhone in-bed only + a nap that day.
    sleep("Connect", "2026-04-20 23:10:00", "2026-04-21 01:10:00", "AsleepCore"),
    sleep("Connect", "2026-04-21 01:10:00", "2026-04-21 02:10:00", "AsleepDeep"),
    sleep("Connect", "2026-04-21 02:10:00", "2026-04-21 02:20:00", "Awake"),
    sleep("Connect", "2026-04-21 02:20:00", "2026-04-21 06:20:00", "AsleepREM"),
    sleep("Connect", "2026-04-21 02:20:00", "2026-04-21 03:20:00", "AsleepREM"),  # re-synced duplicate
    sleep("iPhone", "2026-04-20 22:50:00", "2026-04-21 06:40:00", "InBed"),
    sleep("Connect", "2026-04-21 14:00:00", "2026-04-21 14:40:00", "AsleepCore"),  # nap
    # Night ending 2023-03-02: only the iPhone's bedtime.
    sleep("iPhone", "2023-03-01 23:00:00", "2023-03-02 07:00:00", "InBed"),
    # Heart rate during the run of 2026-04-24 (no HR statistic on the workout itself).
    *[rec(f"{Q}HeartRate", "Connect", f"2026-04-24 15:{m:02d}:00", None, 150 + m % 10, "count/min")
      for m in range(0, 30)],
    workout("Running", "Connect", "2026-04-24 15:00:00", "2026-04-24 15:30:00", 30, km=1.0, route="/workout-routes/a.gpx"),
    # The same run also written by Strava two seconds later, without distance: a twin, dropped.
    workout("Running", "Strava", "2026-04-24 15:00:02", "2026-04-24 15:30:00", 30),
    # Two Strava rides pointing at one route file (the export's naming collision).
    workout("Cycling", "Strava", "2023-06-01 10:00:00", "2023-06-01 11:00:00", 60, route="/workout-routes/b.gpx"),
    workout("Cycling", "Strava", "2023-06-08 10:00:00", "2023-06-08 11:00:00", 60, route="/workout-routes/b.gpx"),
    workout("Hiking", "Connect", "2025-08-14 06:00:00", "2025-08-14 16:00:00", 600, hr=(128, 175)),
])
FILES = {"/workout-routes/a.gpx": gpx(line(60, 1.0), same_time=True), "/workout-routes/b.gpx": gpx(line(40, 20.0))}


class Parsed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = cls._tmp = __import__("tempfile").TemporaryDirectory()
        path = Path(cls._tmp.name) / "export.zip"
        path.write_bytes(build_zip(EXPORT, FILES))
        cls.export = apple.parse(path)
        cls.tables = apple.build(cls.export, today=dt.date(2026, 11, 2))
        cls.daily = cls.tables["daily"].set_index(cls.tables["daily"]["day"].dt.date)
        cls.acts = cls.tables["activities"]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_person_from_me(self):
        self.assertEqual(self.export.birth_date, dt.date(2001, 9, 4))
        self.assertEqual(self.export.sex, "male")

    def test_overlapping_sources_take_the_largest_total_not_the_sum(self):
        day = self.daily.loc[dt.date(2026, 4, 20)]
        self.assertEqual(day["steps"], 6500)
        self.assertEqual(day["distance_m"], 3200)
        self.assertEqual(day["calories"], 2100)
        self.assertEqual(day["source"], "apple")

    def test_units_converted(self):
        day = self.daily.loc[dt.date(2026, 4, 21)]
        self.assertAlmostEqual(day["weight_kg"], 74.84, places=2)
        self.assertAlmostEqual(day["hrv_sdnn"], 55.0)

    def test_overnight_sdnn_is_marked_as_sdnn(self):
        """One person has one source, so overnight SDNN fills the HRV column -- named by hrv_kind,
        never mixed with Garmin's RMSSD in one series."""
        night = self.daily.loc[dt.date(2026, 4, 21)]
        self.assertAlmostEqual(night["hrv_last_night"], 55.0)
        self.assertEqual(night["hrv_kind"], "sdnn")
        self.assertEqual(set(self.tables["daily"]["hrv_kind"].dropna()), {"sdnn"})
        series = self.tables["night_series"]
        self.assertEqual(set(series["metric"]), {"hrv"})
        self.assertTrue((series["day"] == pd.Timestamp("2026-04-21")).all())

    def test_own_hrv_norm_from_previous_nights(self):
        days = pd.date_range("2026-01-01", periods=40)
        frame = pd.DataFrame({"day": days, "hrv_last_night": [50.0 + (i % 10) for i in range(40)],
                              "hrv_baseline_low": float("nan"), "hrv_baseline_high": float("nan"),
                              "hrv_norm": None})
        normed = apple.hrv_norm(frame)
        self.assertTrue(normed["hrv_baseline_low"].iloc[:apple.NORM_MIN].isna().all(), "needs 14 nights first")
        last = normed.iloc[-1]
        self.assertEqual(last["hrv_norm"], "own")
        # The 39 nights before: 50..58 four times each, 59 three times (linear interpolation).
        self.assertAlmostEqual(last["hrv_baseline_low"], 50.8, places=1)
        self.assertAlmostEqual(last["hrv_baseline_high"], 58.0, places=1)

    def test_staged_night_wins_over_in_bed_and_nap(self):
        night = self.daily.loc[dt.date(2026, 4, 21)]
        self.assertEqual(night["sleep_source"], "Connect")
        self.assertFalse(night["sleep_in_bed_only"])
        self.assertAlmostEqual(night["sleep_light_h"], 2.0)  # core -> light; the nap lost
        self.assertAlmostEqual(night["sleep_deep_h"], 1.0)
        self.assertAlmostEqual(night["sleep_rem_h"], 4.0)  # the duplicate REM is not counted twice
        self.assertAlmostEqual(night["sleep_awake_h"], round(10 / 60, 2))
        self.assertAlmostEqual(night["sleep_h"], 7.0)

    def test_in_bed_only_night_has_hours_without_stages(self):
        night = self.daily.loc[dt.date(2023, 3, 2)]
        self.assertTrue(night["sleep_in_bed_only"])
        self.assertAlmostEqual(night["sleep_h"], 8.0)
        self.assertTrue(math.isnan(night["sleep_deep_h"]))

    def test_hypnogram_rows(self):
        stages = self.tables["sleep_stages"]
        night = stages[stages["day"] == pd.Timestamp("2026-04-21")]
        self.assertEqual(sorted(night["stage"].unique()), ["awake", "deep", "light", "rem"])
        self.assertAlmostEqual(night["minutes"].sum(), 430)

    def test_twin_workouts_collapse_to_the_richer_one(self):
        runs = self.acts[self.acts["sport"] == "running"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs.iloc[0]["distance_km"], 1.0)

    def test_workout_heart_rate_from_samples_and_trimp(self):
        run = self.acts[self.acts["sport"] == "running"].iloc[0]
        self.assertAlmostEqual(run["avg_hr"], 154.5, places=1)
        self.assertEqual(run["max_hr"], 159)
        self.assertEqual(run["pace_min_km"], 30.0)
        hr_max = run["hr_max_used"]
        self.assertAlmostEqual(hr_max, round(208 - 0.7 * (dt.date(2026, 11, 2) - dt.date(2001, 9, 4)).days / 365.25, 1))
        self.assertEqual(run["training_load"], apple.trimp(30, 154.5, 51, hr_max, "male"))
        self.assertEqual(run["load_source"], "trimp")

    def test_activity_ids_are_stable(self):
        again = apple.build(self.export, today=dt.date(2026, 11, 2))["activities"]
        self.assertEqual(sorted(self.acts["activity_id"]), sorted(again["activity_id"]))
        self.assertTrue((self.acts["activity_id"] < 2**53).all())

    def test_shared_route_file_belongs_to_no_one_and_constant_gpx_time_is_spread(self):
        summary = self.tables["route_summary"]
        self.assertEqual(len(summary), 1)
        points = self.tables["routes"]
        self.assertAlmostEqual(points["distance_km"].max(), 1.0, places=2)
        self.assertAlmostEqual(points["duration_s"].max(), 1800, delta=1)
        self.assertTrue(points["hr"].notna().any())
        run = self.acts[self.acts["sport"] == "running"].iloc[0]
        self.assertAlmostEqual(run["start_lat"], 51.0)

    def test_tables_have_the_whole_schema(self):
        self.assertTrue(set(schema.DAILY) <= set(self.tables["daily"].columns))
        self.assertTrue(set(schema.ACTIVITIES) <= set(self.tables["activities"].columns))


class Units(unittest.TestCase):
    def test_trimp(self):
        self.assertIsNone(apple.trimp(30, None, 50, 190, "male"))
        self.assertGreater(apple.trimp(60, 170, 50, 190, "male"), apple.trimp(60, 140, 50, 190, "male"))
        self.assertNotEqual(apple.trimp(60, 150, 50, 190, "female"), apple.trimp(60, 150, 50, 190, "male"))

    def test_hr_max_prefers_the_record_once_it_is_higher(self):
        self.assertEqual(apple.hr_max_estimate([200, 199, 198, 150], dt.date(2001, 1, 1), dt.date(2026, 1, 1)), 198)
        self.assertEqual(apple.hr_max_estimate([175, 170, 165], None, dt.date(2026, 1, 1)), 165)
        self.assertAlmostEqual(apple.hr_max_estimate([175, 170, 165], dt.date(2001, 1, 1), dt.date(2026, 1, 1)),
                               190.5, places=1)
        self.assertIsNone(apple.hr_max_estimate([], None, dt.date(2026, 1, 1)))


class Pipeline(unittest.TestCase):
    def test_load_hands_an_apple_person_to_the_apple_builder(self):
        with person("y", source="apple") as y, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(load.main(), 1, "nothing imported yet")
            source = Path(y.root) / "export.zip"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(build_zip(EXPORT, FILES))
            apple.import_export(source)
            self.assertEqual(load.main(), 0)
            state = json.loads(y.state_file.read_text())
            self.assertEqual(state["source"], "apple")
            daily = pd.read_parquet(y.tables / "daily.parquet")
            self.assertEqual(set(daily["source"]), {"apple"})
            for name in ("activities", "sleep_stages", "routes", "route_summary", "night_series", "intraday",
                         "run_laps", "activity_segments"):
                self.assertTrue((y.tables / f"{name}.parquet").exists(), name)

    def test_import_refuses_what_is_not_an_export(self):
        with person("y", source="apple") as y:
            bogus = Path(y.root) / "x.zip"
            bogus.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(bogus, "w") as archive:
                archive.writestr("hello.txt", "hi")
            with self.assertRaises(ValueError):
                apple.import_export(bogus)

    def test_excluded_night_is_blank_in_both_tables(self):
        with person("y", source="apple") as y:
            path = Path(y.root) / "export.zip"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(build_zip(EXPORT, FILES))
            tables = apple.build(apple.parse(path), today=dt.date(2026, 11, 2), skip={dt.date(2026, 4, 21)})
            night = tables["daily"][tables["daily"]["day"] == pd.Timestamp("2026-04-21")].iloc[0]
            self.assertTrue(night["night_excluded"])
            self.assertTrue(math.isnan(night["sleep_h"]))
            self.assertFalse((tables["sleep_stages"]["day"] == pd.Timestamp("2026-04-21")).any())
        self.assertIsNotNone(tenant)


class Schema(unittest.TestCase):
    def test_conform_adds_empty_columns_and_keeps_extras(self):
        frame = pd.DataFrame({"day": pd.to_datetime(["2026-01-01"]), "steps": [10], "hrv_sdnn": [40.0]},
                             index=[7])
        out = schema.daily(frame)
        self.assertEqual(list(out.columns[:3]), ["day", "source", "steps"])
        self.assertIn("hrv_sdnn", out.columns)
        self.assertTrue(out["readiness"].isna().all())
        self.assertIsNone(out["hrv_status"].iloc[0])
        self.assertEqual(out.index.tolist(), [7])


if __name__ == "__main__":
    unittest.main()
