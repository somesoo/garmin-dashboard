"""Workout ladders, strength sessions and the 30-day spike rule in the plan."""

from __future__ import annotations

import datetime as dt
import unittest

import pandas as pd

from running import coach, library, physio, plan as planning, store
from tests.test_plan_store_coach import fixture


def make(distance="hm", race=dt.date(2026, 8, 30), days=(1, 3, 5, 6), strength_history=0, **settings):
    runs, _, _, result = fixture()
    request = planning.PlanRequest(distance, race, run_days=list(days), long_day=6, start=dt.date(2026, 3, 2))
    plan = planning.generate(request, runs, result, anchor=pd.Timestamp("2026-03-01"),
                             strength_history=strength_history)
    return plan, runs, result


def minutes_at(session, pace):
    """Work time of a session's main set at the middle of ``pace``."""
    total = 0.0
    for step in session["steps"]:
        if step["kind"] == "repeat":
            work = next(s for s in step["steps"] if s["kind"] == "run")
            total += step["reps"] * (work.get("s", 0) / 60 or work["km"] * sum(pace) / 2)
        elif step["kind"] == "run":
            total += step["km"] * sum(pace) / 2
    return total


class Ladders(unittest.TestCase):
    def test_threshold_reps_get_longer(self):
        plan, _, _ = make()
        weeks = {w["week"]: w for w in plan["weeks"]}
        rungs = [s["text"]["level"] for s in plan["sessions"]
                 if s["text"].get("key") == "threshold" and not weeks[s["week"]].get("recovery")
                 and s["phase"] != "taper"]
        self.assertGreaterEqual(len(rungs), 3)
        self.assertEqual(rungs, sorted(rungs))
        self.assertGreater(rungs[-1], rungs[0])

    def test_work_stays_within_the_cap(self):
        for distance in ("5k", "10k", "hm", "m"):
            plan, _, _ = make(distance)
            paces = {k: tuple(v) for k, v in plan["paces"].items()}
            weeks = {w["week"]: w for w in plan["weeks"]}
            for session in plan["sessions"]:
                family = session["text"].get("key")
                if family not in ("threshold", "intervals"):
                    continue
                limit = library.cap(family, distance, weeks[session["week"]]["volume_km"], paces)
                pace = paces["T" if family == "threshold" else "I"]
                # Reps are rounded to 0.2 km, so a rung can sit a few percent over its minutes.
                self.assertLessEqual(minutes_at(session, pace), limit * 1.12 + 0.5, (distance, session["title"]))

    def test_one_quality_day_rotates_kinds(self):
        plan, _, _ = make("hm", days=(1, 3, 6))
        families = {s["text"]["key"] for s in plan["sessions"] if s["type"] in planning.QUALITY_TYPES}
        self.assertTrue({"hills", "threshold", "race_pace"} <= families, families)

    def test_lighter_week_repeats_the_rung_below(self):
        used, reps, rung = library.fit("threshold", "hm", 3, 30)
        self.assertEqual((used, reps), (3, 3))
        used, reps, _ = library.fit("threshold", "hm", 4, 20)
        self.assertEqual((used, reps), (4, 1))  # 2x15 cut to one 15-minute rep, not dropped
        used, reps, _ = library.fit("intervals", "hm", 4, 12)
        self.assertGreaterEqual(reps, library.MIN_REPS["intervals"])
        self.assertLess(used, 4)

    def test_hills_have_no_pace_target(self):
        work = library.quality("hills", 2, 30, "hm", physio.training_paces(45), None)
        repeat = next(s for s in work["steps"] if s["kind"] == "repeat")
        self.assertNotIn("pace", repeat["steps"][0])
        self.assertEqual(work["type"], "intervals")


class Strength(unittest.TestCase):
    def test_placement_rules(self):
        plan, _, _ = make("hm", race=dt.date(2026, 8, 30))
        sessions = plan["sessions"]
        strength = [s for s in sessions if s["type"] == "strength"]
        self.assertTrue(strength)
        hard = {s["date"] for s in sessions if s["type"] in planning.HARD_TYPES}
        longs = {s["date"] for s in sessions if s["type"] in ("long", "race")}
        for session in strength:
            date = dt.date.fromisoformat(session["date"])
            self.assertNotIn((date + dt.timedelta(days=1)).isoformat(), hard, session["date"])
            self.assertNotIn(session["date"], longs)
            self.assertGreaterEqual((dt.date(2026, 8, 30) - date).days, library.BEFORE_RACE_DAYS["A"])
        dates = sorted(dt.date.fromisoformat(s["date"]) for s in strength)
        for first, second in zip(dates, dates[1:]):
            self.assertGreaterEqual((second - first).days, 2)
        self.assertEqual(store.validate_plan(plan), [])

    def test_adaptation_first_then_heavy(self):
        plan, _, _ = make()
        stages = [s["text"]["stage"] for s in plan["sessions"] if s["type"] == "strength"]
        self.assertEqual(stages[:library.ADAPT_SESSIONS], ["adapt"] * library.ADAPT_SESSIONS)
        self.assertIn("strength", stages)
        trained, _, _ = make(strength_history=10)
        first = next(s for s in trained["sessions"] if s["type"] == "strength")
        self.assertEqual(first["text"]["stage"], "strength")

    def test_switched_off(self):
        runs, _, _, result = fixture()
        settings = planning.PlanSettings(run_days=[1, 3, 5, 6], long_day=6, start=dt.date(2026, 3, 2), strength=False)
        goal = {"race_id": None, "name": None, "distance": "hm", "date": "2026-06-14", "goal_s": None, "priority": "A"}
        plan = planning.generate_goals(settings, [goal], runs, result, anchor=pd.Timestamp("2026-03-01"))
        self.assertFalse([s for s in plan["sessions"] if s["type"] == "strength"])
        self.assertFalse(plan["request"]["strength"])

    def test_soften_and_postpone_keep_strength_with_its_run(self):
        plan, _, _ = make()
        today = dt.date(2026, 3, 2)
        pair = next(s for s in plan["sessions"] if s["type"] in planning.QUALITY_TYPES
                    and any(o["type"] == "strength" and o["date"] == s["date"] for o in plan["sessions"]))
        date = pair["date"]
        moved = planning.postpone(dict(plan, sessions=[dict(s) for s in plan["sessions"]]), pair["id"], today=today)
        after = (dt.date.fromisoformat(date) + dt.timedelta(days=1)).isoformat()
        self.assertTrue(any(s["type"] == "strength" and s["date"] == after for s in moved["sessions"]))
        softened = planning.soften(plan, pair["id"], today=today)
        same_day = [s for s in softened["sessions"] if s["date"] == date and s["text"].get("key") == "rest_strength"]
        self.assertEqual(len(same_day), 1)

    def test_match_with_watch_strength(self):
        plan, runs, _ = make()
        session = next(s for s in plan["sessions"] if s["type"] == "strength")
        activities = pd.DataFrame([{"activity_id": 77, "day": pd.Timestamp(session["date"]),
                                    "sport": "strength_training"}])
        matched = planning.match(plan, runs, today=dt.date(2026, 9, 1), activities=activities)
        row = matched[matched["id"] == session["id"]].iloc[0]
        self.assertEqual((row["activity_id"], row["effective"]), (77, "done"))
        summary = planning.compliance(matched)
        self.assertEqual(summary["strength_done"], 1)
        self.assertEqual(planning.strength_done(activities, dt.date.fromisoformat(session["date"])
                                                + dt.timedelta(days=1)), 1)


class Spike(unittest.TestCase):
    def test_cap_counts_the_longest_of_30_days(self):
        history = [(dt.date(2026, 3, 1), 10.0), (dt.date(2026, 1, 20), 20.0)]
        self.assertEqual(planning.spike_cap(history, dt.date(2026, 3, 5)), (10.0, 11.0))
        self.assertEqual(planning.spike_cap([], dt.date(2026, 3, 5)), (0.0, planning.SPIKE_FLOOR_KM))

    def test_morning_decision_cuts_a_spike(self):
        plan, runs, result = make()
        long_run = next(s for s in plan["sessions"] if s["type"] == "long" and s["date"] >= "2026-04-01")
        date = dt.date.fromisoformat(long_run["date"])
        short = runs.assign(day=pd.Timestamp(date - dt.timedelta(days=3)), distance_km=5.0).head(1)  # one 5 km run in 30 days
        check = coach.spike_check(long_run, short, date)
        self.assertIsNotNone(check)
        self.assertAlmostEqual(check["cap_km"], 5.5)
        self.assertIn("5.5", check["reason"])


if __name__ == "__main__":
    unittest.main()


class Zones(unittest.TestCase):
    def efforts(self, minutes=19.0, near_max=True, hr=179.0):
        return pd.DataFrame([
            {"day": pd.Timestamp("2026-02-20"), "effort": "block", "minutes": minutes, "avg_hr": hr,
             "near_max": near_max},
            {"day": pd.Timestamp("2026-02-10"), "effort": "5k", "minutes": 25.0, "avg_hr": 170.0, "near_max": True},
            {"day": pd.Timestamp("2026-02-12"), "effort": "3k", "minutes": 12.0, "avg_hr": 185.0, "near_max": True},
        ])

    def test_threshold_hr_from_the_hardest_sustained_effort(self):
        found = physio.threshold_hr(self.efforts(), pd.Timestamp("2026-03-01"))
        self.assertEqual((found["bpm"], found["day"]), (179, "2026-02-20"))  # 12 min is too short to count
        self.assertEqual(physio.threshold_hr(self.efforts(near_max=False), pd.Timestamp("2026-03-01"))["bpm"], 170)
        self.assertIsNone(physio.threshold_hr(self.efforts().iloc[2:], pd.Timestamp("2026-03-01")))
        self.assertIsNone(physio.threshold_hr(self.efforts(), pd.Timestamp("2026-09-01")))  # older than 120 days

    def test_zones_follow_lthr_and_fall_back_to_hr_max(self):
        zones = physio.hr_zones(192, 179)
        self.assertEqual(zones["basis"], "lthr")
        self.assertEqual(zones["T"], (170, 179))
        self.assertLessEqual(zones["I"][1], 192)
        self.assertEqual(physio.hr_zones(190, None)["E"], (124, 150))
        self.assertIsNone(physio.hr_zones(None, None)["E"])

    def test_easy_runs_target_heart_rate_on_the_watch(self):
        from running import garmin_workout as gw

        runs, _, _, result = fixture()
        result = {**result, "lthr": {"bpm": 175, "day": "2026-02-27", "minutes": 25.0, "effort": "5k"}}
        request = planning.PlanRequest("hm", dt.date(2026, 6, 14), run_days=[1, 3, 5, 6], long_day=6,
                                       start=dt.date(2026, 3, 2))
        plan = planning.generate(request, runs, result, anchor=pd.Timestamp("2026-03-01"))
        self.assertEqual(store.validate_plan(plan), [])
        easy = next(s for s in plan["sessions"] if s["type"] == "easy")
        self.assertEqual(easy["steps"][0]["hr"], list(physio.hr_zones(result["hr_max"], 175)["E"]))
        self.assertNotIn("pace", easy["steps"][0])
        step = gw.to_garmin(easy)["workoutSegments"][0]["workoutSteps"][0]
        self.assertEqual(step["targetType"]["workoutTargetTypeKey"], "heart.rate.zone")
        quality = next(s for s in plan["sessions"] if s["type"] == "threshold")
        self.assertTrue(any("pace" in st for st in quality["steps"] if st["kind"] == "warmup"))
        self.assertEqual(plan["zones"]["basis"], "lthr")
        self.assertTrue(store.validate_steps([{"kind": "run", "km": 5, "hr": [140, 150], "pace": [6.0, 6.5]}]))
