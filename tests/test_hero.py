"""The day in facts (hero.py): the right run, true sentences, both languages."""

from __future__ import annotations

import datetime as dt
import json
import unittest

import pandas as pd

from analysis import hero
from core import i18n

TODAY = dt.date(2026, 11, 1)


def _runs() -> pd.DataFrame:
    return pd.DataFrame([
        {"activity_id": 1, "start_local": "2026-10-20 18:00", "day": "2026-10-20", "distance_km": 10.0,
         "duration_min": 60.0, "pace_min_km": 6.0, "avg_hr": 150, "max_hr": 165, "kind": "easy",
         "hr_max_used": 192, "elevation_gain_m": 40},
        {"activity_id": 2, "start_local": "2026-10-27 17:00", "day": "2026-10-27", "distance_km": 10.1,
         "duration_min": 57.0, "pace_min_km": 5.64, "avg_hr": 166, "max_hr": 188, "kind": "intervals",
         "hr_max_used": 192, "elevation_gain_m": 48},
        {"activity_id": 3, "start_local": "2026-11-01 09:15", "day": "2026-11-01", "distance_km": 10.25,
         "duration_min": 68.5, "pace_min_km": 6.69, "avg_hr": 152, "max_hr": 165, "kind": "long",
         "hr_max_used": 192, "elevation_gain_m": 48},
    ])


def _daily() -> pd.DataFrame:
    days = pd.date_range("2026-10-25", "2026-11-01")
    sleep = [7.3, 6.0, 7.05, 7.3, 8.4, 7.0, 8.2, 5.5]
    return pd.DataFrame({"day": days, "sleep_h": sleep, "sleep_score": [82, 72, 77, 82, 97, 76, 87, 65],
                         "sleep_deep_h": [1.3, .8, .8, 1.4, 1.9, 1.4, 1.2, 1.2],
                         "sleep_rem_h": [1.4, .9, 1.4, 1.0, 2.4, .8, 1.1, .9],
                         "hrv_last_night": [53, 56, 52, 55, 54, 49, 71, 60], "rhr": [48, 49, 48, 50, 47, 50, 48, 49],
                         "bb_wake": [79, 63, 87, 73, 98, 75, 90, 64], "readiness": [80, 61, 75, 26, 70, 73, 68, 50],
                         "steps": [21091, 7931, 19724, 11328, 13479, 6100, 7614, 17843]})


def _splits() -> pd.DataFrame:
    hr = [139, 149, 147, 153, 153, 153, 154, 155, 157, 154]
    pace = [6.52, 6.58, 7.41, 6.50, 6.55, 6.57, 6.75, 6.84, 6.50, 6.72]
    stop = [0, 0, 66, 0, 0, 0, 0, 14, 0, 0]
    return pd.DataFrame({"activity_id": 3, "km": range(1, 11), "length_km": 1.0, "pace_min_km": pace,
                         "seconds": [p * 60 for p in pace], "hr": hr, "stop_s": stop})


def _route() -> pd.DataFrame:
    rows = [{"seq": i, "lat": 52.2 + 0.001 * i, "lon": 21.0 + 0.0005 * i, "hr": 140 + i % 20,
             "distance_km": i * 0.1} for i in range(103)]
    return pd.DataFrame(rows)


def _build(today: dt.date = TODAY, runs: pd.DataFrame | None = None, session=None, **kwargs):
    runs = _runs() if runs is None else runs
    stops = pd.DataFrame({"activity_id": 3, "km": [2.18, 2.32, 7.01], "lat": [52.22, 52.223, 52.27],
                          "lon": [21.01, 21.011, 21.035], "seconds": [36.0, 30.0, 14.0]})
    args = dict(runs=runs, activities=pd.DataFrame(), daily=_daily(), splits=_splits(), stops=stops,
                efforts=pd.DataFrame({"effort": ["1k"], "pace_min_km": [6.28]}), laps=pd.DataFrame(),
                circadian=pd.DataFrame(), route=_route(),
                races=[{"name": "Bieg Niepodległości", "date": "2026-11-11", "distance": "10k", "goal_s": 2700.0}],
                session=session, has_plan=session is not None)
    args.update(kwargs)
    return hero.build(today, **args)


class PickRun(unittest.TestCase):
    def test_todays_run_wins(self):
        run, today_run = hero.pick_run(_runs(), TODAY)
        self.assertEqual(int(run["activity_id"]), 3)
        self.assertTrue(today_run)

    def test_before_todays_run_the_last_one_is_shown(self):
        run, today_run = hero.pick_run(_runs(), dt.date(2026, 10, 30))
        self.assertEqual(int(run["activity_id"]), 2)
        self.assertFalse(today_run)

    def test_no_runs(self):
        self.assertEqual(hero.pick_run(pd.DataFrame(), TODAY), (None, False))


class Facts(unittest.TestCase):
    def test_after_the_run(self):
        payload = _build()
        self.assertEqual(payload["state"], "done")
        keys = [f["key"] for f in payload["facts"]]
        self.assertEqual(keys[0], "run")
        for key in ("stretch", "stops", "fastest", "compared", "race", "sleep", "hrv", "battery"):
            self.assertIn(key, keys)
        self.assertNotIn("plan", keys)
        stretch = next(f for f in payload["facts"] if f["key"] == "stretch")
        self.assertIn("+18", stretch["head"])                      # 139 -> 157 at the same pace
        self.assertEqual(stretch["anchor"], {"km": 8.5})
        sleep = next(f for f in payload["facts"] if f["key"] == "sleep")
        self.assertIn("najkrótszy", sleep["head"])
        self.assertIn("najkrótszej nocy", payload["headline"])
        stops = next(f for f in payload["facts"] if f["key"] == "stops")
        self.assertIn("80 s", stops["head"])
        self.assertIn("3. km", stops["text"])                      # the stops made km 3 the slowest

    def test_priorities_sorted_and_json_ready(self):
        payload = _build()
        priorities = [f["priority"] for f in payload["facts"]]
        self.assertEqual(priorities, sorted(priorities))
        json.dumps(payload)
        self.assertGreater(len(payload["run"]["pts"]), 100)
        self.assertEqual(payload["run"]["zones"], [153, 164, 171, 180])  # hrzones from HRmax 192
        self.assertFalse(payload["run"]["dim"])

    def test_hrv_is_a_percentage_of_the_week(self):
        hrv = next(f for f in _build()["facts"] if f["key"] == "hrv")
        self.assertIn("+8%", hrv["head"])                          # 60 vs the 7 nights before (55.7)

    def test_planned_day_shows_the_last_run_faded(self):
        session = {"date": "2026-10-30", "type": "easy", "distance_km": 8, "title": "Spokojny", "main": "8 km w strefie E"}
        payload = _build(dt.date(2026, 10, 30), session=session)
        self.assertEqual(payload["state"], "planned")
        self.assertTrue(payload["run"]["dim"])
        keys = [f["key"] for f in payload["facts"]]
        self.assertIn("plan", keys)
        self.assertIn("since", keys)
        self.assertIn("Spokojny", payload["headline"])

    def test_no_data_at_all(self):
        payload = hero.build(TODAY, runs=pd.DataFrame(), activities=pd.DataFrame(), daily=pd.DataFrame(),
                             splits=pd.DataFrame(), stops=pd.DataFrame(), efforts=pd.DataFrame(), laps=pd.DataFrame(),
                             circadian=pd.DataFrame(), route=pd.DataFrame(), races=[], session=None, has_plan=False)
        self.assertNotIn("run", payload)
        self.assertEqual(payload["facts"], [])
        json.dumps(payload)

    def test_english(self):
        i18n.force("en")
        try:
            payload = _build()
        finally:
            i18n.force("pl")
        self.assertIn("Today", payload["headline"])
        stretch = next(f for f in payload["facts"] if f["key"] == "stretch")
        self.assertIn("beats at the same pace", stretch["head"])
        self.assertTrue(payload["date"].startswith("Sunday, 1 November 2026"))

    def test_trivia(self):
        heads = [t["head"] for t in _build()["trivia"]]
        self.assertTrue(any("3 biegi" in h for h in heads), heads)
        self.assertTrue(any("kroków" in h for h in heads), heads)


if __name__ == "__main__":
    unittest.main()
