"""General readiness and the discipline ranking on synthetic days with known answers."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from sport import catalog, readiness, recommend, store, text, variety
from tests import helpers

TODAY = dt.date(2026, 10, 30)
NOW = pd.Timestamp("2026-10-30 18:00")


def nights(hrv_today: float = 60, rhr_today: float = 50, sleep_today: float = 7.5, readiness_today: float = 70,
           days: int = 70) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    rows = []
    for offset in range(days, 0, -1):
        rows.append({"day": pd.Timestamp(TODAY - dt.timedelta(days=offset)), "hrv_last_night": 60 * rng.uniform(0.9, 1.1),
                     "rhr": 50 + rng.integers(-1, 2), "sleep_h": 7.5, "sleep_score": 75, "readiness": 70})
    rows.append({"day": pd.Timestamp(TODAY), "hrv_last_night": hrv_today, "rhr": rhr_today, "sleep_h": sleep_today,
                 "sleep_score": 75, "readiness": readiness_today})
    return pd.DataFrame(rows)


def activity(activity_id: int, when: str, sport: str, minutes: float, load: float = 80, **extra) -> dict:
    return helpers.run(activity_id, when, 0, 1, sport=sport, duration_min=minutes, training_load=load,
                       start_local=pd.Timestamp(when), **extra)


def history(rows: list[dict]) -> pd.DataFrame:
    return helpers.activities(rows)


# A month of running every other day plus the odd ride: running dominates.
BASE = [activity(i, f"2026-10-{d:02d} 07:00", "running", 45) for i, d in enumerate(range(1, 28, 2), start=1)] + \
       [activity(100, "2026-10-12 17:00", "cycling", 90), activity(101, "2026-08-20 18:00", "lap_swimming", 40),
        activity(102, "2026-09-10 19:00", "volleyball", 100), activity(103, "2026-06-01 19:00", "volleyball", 100),
        activity(104, "2026-05-01 19:00", "volleyball", 100)]


class Catalog(unittest.TestCase):
    def test_garmin_types_map_onto_disciplines(self):
        self.assertEqual(catalog.discipline_of("treadmill_running"), "run")
        self.assertEqual(catalog.discipline_of("kiteboarding_v2"), "kite")
        self.assertIsNone(catalog.discipline_of("multi_sport"))

    def test_every_discipline_is_consistent(self):
        for key, d in catalog.DISCIPLINES.items():
            self.assertIn(d.family, catalog.FAMILIES, key)
            self.assertTrue(set(d.load) <= set(catalog.SYSTEMS), key)
            self.assertTrue(set(d.trains) <= set(catalog.QUALITIES), key)
            self.assertTrue(set(d.needs) <= set(catalog.CONDITIONS), key)
            self.assertTrue(d.level_range(), key)
            self.assertTrue(catalog.blurb(key), key)

    def test_open_water_is_summer_only(self):
        self.assertFalse(catalog.get("kayak").in_season(10))
        self.assertFalse(catalog.get("kite").in_season(11))
        self.assertTrue(catalog.get("kayak").in_season(7))


class Readiness(unittest.TestCase):
    def test_an_ordinary_day_is_moderate_or_better(self):
        result = readiness.assess(nights(), history(BASE), TODAY, NOW)
        self.assertGreaterEqual(result["score"], 52)
        self.assertIn(result["level"], ("moderate", "hard"))
        self.assertEqual(set(result["parts"]), {"garmin", "hrv", "rhr", "sleep", "load", "fresh"})

    def test_two_bad_night_signals_cap_the_day(self):
        result = readiness.assess(nights(hrv_today=35, rhr_today=60, readiness_today=95), history(BASE), TODAY, NOW)
        self.assertTrue(result["capped"] or result["level"] in ("easy", "recover"))
        self.assertIn(result["level"], ("easy", "recover"))

    def test_an_old_night_is_not_trusted(self):
        days = nights()
        days = days[days["day"] < pd.Timestamp(TODAY - dt.timedelta(days=3))]
        result = readiness.assess(days, history(BASE), TODAY, NOW)
        self.assertFalse(result["night_used"])
        self.assertEqual(result["stale_days"], 4)

    def test_a_ride_tires_the_legs_not_the_arms(self):
        rows = BASE + [activity(200, "2026-10-30 10:00", "cycling", 120, load=160)]
        systems = readiness.assess(nights(), history(rows), TODAY, NOW)["systems"]
        self.assertGreater(systems["legs"], 0.5)
        self.assertLess(systems["upper"], 0.2)

    def test_a_hard_session_last_night_lowers_freshness(self):
        rows = BASE + [activity(201, "2026-10-29 19:00", "squash", 60, load=200, te_aerobic=4.5)]
        fresh = readiness.assess(nights(), history(rows), TODAY, NOW)["parts"]["fresh"]
        self.assertEqual(fresh["discipline"], "squash")
        self.assertLessEqual(fresh["score"], 50)


class Variety(unittest.TestCase):
    def test_one_sport_is_one_effective_discipline(self):
        self.assertEqual(variety.effective_number(pd.Series([300.0])), 1.0)
        self.assertAlmostEqual(variety.effective_number(pd.Series([100.0, 100.0, 100.0])), 3.0)

    def test_running_only_lacks_mobility_and_strength(self):
        frame = readiness.sessions(history(BASE))
        profile = variety.profile(frame, NOW).set_index("quality")
        self.assertEqual(profile.loc["mobility", "gap"], 1.0)
        self.assertGreaterEqual(profile.loc["strength", "gap"], 0.5)
        self.assertEqual(profile.loc["aerobic", "gap"], 0.0)


class Recommend(unittest.TestCase):
    def setUp(self):
        self.frame = readiness.sessions(history(BASE))
        self.state = readiness.assess(nights(), history(BASE), TODAY, NOW)

    def rank(self, state=None, **kwargs):
        return recommend.rank(state or self.state, self.frame, TODAY, now=NOW, **kwargs)

    def test_no_trip_and_no_off_season_in_the_ranking(self):
        available = store.default_available({"run", "cycling", "swim", "volleyball"})
        self.assertNotIn("water", available)
        result = self.rank(available=available)
        ranked = {r["discipline"] for r in result["ranked"]}
        self.assertFalse(ranked & {"kayak", "kite", "sup", "ski", "hiking"})
        reasons = {s["discipline"]: s["reason"] for s in result["skipped"]}
        self.assertEqual(reasons["kayak"], "season")

    def test_main_picks_are_things_already_done_one_per_family(self):
        result = self.rank(available=store.default_available({"run", "cycling", "swim", "volleyball"}))
        chosen = recommend.picks(result, self.state["level"])
        self.assertTrue(chosen["main"])
        self.assertTrue(all(not r["new"] for r in chosen["main"]))
        families = [r["family"] for r in chosen["main"]]
        self.assertEqual(len(families), len(set(families)))
        self.assertTrue(chosen["new"]["new"])
        self.assertFalse(set(catalog.get(chosen["new"]["discipline"]).needs) & set(catalog.TRAVEL))

    def test_the_dominant_sport_is_pushed_down(self):
        result = self.rank()
        run = next(r for r in result["ranked"] if r["discipline"] == "run")
        self.assertIn("dominant", [r["code"] for r in run["reasons"]])
        self.assertGreater(result["ranked"].index(run), 2)

    def test_a_recovery_day_leaves_out_match_sports(self):
        state = {**self.state, "level": "recover"}
        result = self.rank(state)
        ranked = {r["discipline"] for r in result["ranked"]}
        self.assertNotIn("squash", ranked)
        self.assertNotIn("volleyball", ranked)
        self.assertTrue(all(r["level"] == "recover" for r in result["ranked"]))

    def test_tired_legs_favour_the_upper_body(self):
        state = {**self.state, "systems": {"impact": 1.0, "legs": 1.2, "upper": 0.0}}
        result = self.rank(state)
        order = [r["discipline"] for r in result["ranked"]]
        self.assertLess(order.index("swim"), order.index("cycling"))

    def test_key_run_tomorrow_keeps_legs_moderate(self):
        state = {**self.state, "level": "hard"}
        result = self.rank(state, before_key=True)
        cycling = next(r for r in result["ranked"] if r["discipline"] == "cycling")
        self.assertEqual(cycling["level"], "moderate")
        self.assertIn("before", [r["code"] for r in cycling["reasons"]])

    def test_plan_link(self):
        plan = {"sessions": [{"date": "2026-10-30", "type": "easy", "title": "Easy"},
                             {"date": "2026-10-31", "type": "long", "title": "Long"}]}
        link = recommend.from_plan(plan, TODAY)
        self.assertEqual(len(link["today"]), 1)
        self.assertTrue(link["before_key"])
        self.assertFalse(recommend.from_plan(None, TODAY)["before_key"])

    def test_every_reason_has_words(self):
        state = {**self.state, "systems": {"impact": 0.8, "legs": 0.8, "upper": 0.0}}
        for item in self.rank(state, before_key=True)["ranked"]:
            for reason in item["reasons"]:
                self.assertNotEqual(text.reason(reason), reason["code"])
        for key, part in self.state["parts"].items():
            self.assertTrue(text.part_detail(key, part), key)


class Store(unittest.TestCase):
    def test_default_follows_the_record_without_trips(self):
        self.assertEqual(store.default_available({"swim", "kite"}), ["pool"])

    def test_saved_choice_wins(self):
        path = Path(tempfile.mkdtemp()) / "sport.json"
        self.assertEqual(store.available({"swim"}, path), ["pool"])
        store.save_available(["water", "pool", "bogus"], path)
        self.assertEqual(store.available({"swim"}, path), ["pool", "water"])


if __name__ == "__main__":
    unittest.main()
