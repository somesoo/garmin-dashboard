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



class CriticalSpeed(unittest.TestCase):
    def efforts(self, rows):
        return pd.DataFrame([{"day": pd.Timestamp(d), "distance_m": m, "seconds": t, "minutes": t / 60,
                              "near_max": True, "source": src} for d, m, t, src in rows])

    def test_fit_needs_two_clean_efforts_of_different_length(self):
        anchor = pd.Timestamp("2026-03-01")
        one = self.efforts([("2026-02-20", 4000, 1138, "block")])
        self.assertIsNone(physio.critical_speed(one, anchor))
        dirty = self.efforts([("2026-02-20", 4000, 1138, "block"), ("2026-02-10", 1000, 250, "garmin")])
        self.assertIsNone(physio.critical_speed(dirty, anchor))  # a split inside a run is not clean
        clean = self.efforts([("2026-02-20", 4000, 1138, "block"), ("2026-02-10", 1600, 400, "whole"),
                              ("2026-02-12", 3000, 800, "whole")])
        cs = physio.critical_speed(clean, anchor)
        self.assertIsNotNone(cs)
        self.assertGreater(cs["cs_ms"], 3.0)
        self.assertEqual(cs["efforts"], 3)
        self.assertIsNotNone(cs["r2"])

    def test_threshold_is_never_faster_than_cs(self):
        paces = physio.training_paces(45)
        slow_cs = {"cs_ms": 3.0, "pace": paces["T"][0] + 0.2, "r2": None}
        capped = physio.cap_threshold(paces, slow_cs)
        self.assertAlmostEqual(capped["T"][0], slow_cs["pace"])
        self.assertAlmostEqual(capped["T"][1] - capped["T"][0], paces["T"][1] - paces["T"][0])
        fast_cs = {"cs_ms": 4.0, "pace": paces["T"][0] - 0.3, "r2": None}
        self.assertEqual(physio.cap_threshold(paces, fast_cs), paces)
        self.assertEqual(physio.cap_threshold(paces, None), paces)


class DoneAsPlanned(unittest.TestCase):
    """The ladders climb on what was really run (plan.outcomes), not on what was planned."""

    def setUp(self):
        self.plan, self.runs, self.result = make()
        self.session = next(s for s in self.plan["sessions"] if s["type"] == "threshold")
        self.date = dt.date.fromisoformat(self.session["date"])
        self.reps, band = planning.planned_reps(self.session["steps"])
        self.rep = next(st for st in self.session["steps"] if st["kind"] == "repeat")["steps"][0]["km"]
        self.pace = sum(band) / 2

    def run_on(self, kind="threshold"):
        return pd.DataFrame([{"activity_id": 5000, "day": pd.Timestamp(self.date), "kind": kind,
                              "distance_km": self.session["distance_km"], "pace_min_km": 5.5}])

    def laps(self, reps, pace_factor=1.0, hr=160):
        rows = [("warmup", 0, 2000, 840, 140)]
        for _ in range(reps):
            rows += [("active", 1, self.rep * 1000, self.rep * self.pace * pace_factor * 60, hr),
                     ("recovery", 2, 200, 60, 150)]
        rows.append(("cooldown", 3, 1500, 600, 145))
        return pd.DataFrame([{"activity_id": 5000, "lap": i + 1, "intensity": k, "step_index": st, "distance_m": m,
                              "duration_s": s, "avg_hr": h, "max_hr": h + 5, "cadence": 170.0}
                             for i, (k, st, m, s, h) in enumerate(rows)])

    def outcome(self, runs, laps=None, plan=None):
        return planning.outcomes(plan or self.plan, runs, self.date + dt.timedelta(days=1), laps=laps)[self.session["id"]]

    def test_each_way_a_session_can_go(self):
        self.assertEqual(self.outcome(self.run_on(), self.laps(self.reps)), {"advance": True})
        self.assertEqual(self.outcome(self.runs.iloc[0:0])["reason"], "missed")
        if self.reps > 1:
            self.assertEqual(self.outcome(self.run_on(), self.laps(self.reps - 1))["reason"], "short")
        self.assertEqual(self.outcome(self.run_on(), self.laps(self.reps, pace_factor=1.15))["reason"], "off_pace")
        self.assertEqual(self.outcome(self.run_on("easy"))["reason"], "other_kind")
        hot = {**self.plan, "zones": {"basis": "lthr", "T": [165, 174]}}
        self.assertEqual(self.outcome(self.run_on(), self.laps(self.reps, hr=182), plan=hot)["reason"], "hr_high")

    def test_a_held_rung_is_repeated_with_its_reason(self):
        today = self.date + dt.timedelta(days=1)
        held = planning.replan(self.plan, self.runs[self.runs["day"] < pd.Timestamp("2026-03-02")], self.result,
                               today=today)
        nxt = next(s for s in held["sessions"] if s["date"] >= today.isoformat()
                   and s["text"].get("key") == "threshold")
        self.assertEqual(nxt["text"]["level"], self.session["text"]["level"])
        self.assertIn("rung_hold", [w["key"] for w in nxt.get("why", [])])
        runs = pd.concat([self.runs, self.run_on()], ignore_index=True)
        moved = planning.replan(self.plan, runs, self.result, today=today, laps=self.laps(self.reps))
        nxt = next(s for s in moved["sessions"] if s["date"] >= today.isoformat()
                   and s["text"].get("key") == "threshold")
        self.assertGreaterEqual(nxt["text"]["level"], self.session["text"]["level"])
        self.assertNotIn("rung_hold", [w["key"] for w in nxt.get("why", [])])


class Response(unittest.TestCase):
    def daily(self, hrv_recent=60.0, rhr_recent=48.0):
        days = pd.date_range("2026-01-01", "2026-03-01")
        rows = []
        for i, day in enumerate(days):
            recent = day > pd.Timestamp("2026-02-22")
            rows.append({"day": day, "hrv_last_night": hrv_recent if recent else 60.0 + (i % 5 - 2),
                         "rhr": rhr_recent if recent else 48.0 + (i % 3 - 1)})
        return pd.DataFrame(rows)

    def test_signals_and_decision(self):
        today = dt.date(2026, 3, 1)
        self.assertEqual(planning.response(self.daily(), today)["decision"], "grow")
        low = planning.response(self.daily(hrv_recent=52.0), today)
        self.assertEqual((low["decision"], [s["key"] for s in low["signals"]]), ("hold", ["hrv_low"]))
        both = planning.response(self.daily(hrv_recent=52.0, rhr_recent=53.0), today)
        self.assertEqual(both["decision"], "lighter")
        missed = planning.response(self.daily(), today, {"due": 6, "km_ratio": 0.5, "actual_km": 20.0,
                                                         "planned_km": 40.0})
        self.assertEqual(missed["decision"], "hold")
        self.assertEqual(planning.response(None, today)["decision"], "grow")

    def test_the_first_week_follows_the_decision(self):
        runs, _, _, result = fixture()
        settings = planning.PlanSettings(run_days=[1, 3, 5, 6], long_day=6, start=dt.date(2026, 3, 2))
        goal = {"race_id": None, "name": None, "distance": "hm", "date": "2026-06-14", "goal_s": None,
                "priority": "A"}

        def weeks(decision):
            plan = planning.generate_goals(settings, [goal], runs, result, anchor=pd.Timestamp("2026-03-01"),
                                           adapt={"decision": decision, "signals": [], "day": "2026-03-01"})
            return plan

        grow, hold, lighter = weeks("grow"), weeks("hold"), weeks("lighter")
        self.assertGreater(grow["weeks"][1]["volume_km"], grow["weeks"][0]["volume_km"])
        self.assertEqual(hold["weeks"][1]["volume_km"], hold["weeks"][0]["volume_km"])
        self.assertTrue(lighter["weeks"][0]["recovery"])
        self.assertLess(lighter["weeks"][0]["volume_km"], grow["weeks"][0]["volume_km"])
        first = next(s for s in lighter["sessions"] if s["type"] in planning.RUN_TYPES)
        self.assertEqual(first["why"][0]["key"], "response")
        self.assertEqual(store.validate_plan(lighter), [])


class Durability(unittest.TestCase):
    def laps(self, hr_second, km=14):
        rows = []
        for i in range(km):
            rows.append({"activity_id": 9000, "lap": i + 1, "distance_m": 1000.0, "duration_s": 400.0,
                         "avg_hr": 145.0 if i < km / 2 else hr_second, "intensity": "active"})
        return pd.DataFrame(rows)

    def test_drift_from_laps(self):
        self.assertAlmostEqual(library.drift(self.laps(145.0)), 0.0)
        self.assertGreater(library.drift(self.laps(155.0)), library.DRIFT_LIMIT)
        self.assertAlmostEqual(library.drift(self.laps(155.0), easy_km=7), 0.0)  # the finish is left out
        self.assertIsNone(library.drift(self.laps(145.0, km=3)))

    def test_finish_grows_through_the_peak(self):
        plan, _, _ = make("hm", race=dt.date(2026, 8, 30))
        weeks = {w["week"]: w for w in plan["weeks"]}
        parts = [s["text"]["part"] for s in plan["sessions"]
                 if s["type"] == "long" and s["text"].get("part") and not weeks[s["week"]].get("recovery")]
        self.assertGreaterEqual(len(parts), 2)
        self.assertEqual(parts, sorted(parts))
        self.assertGreater(parts[-1], parts[0])
        for s in plan["sessions"]:
            if s["text"].get("part"):
                self.assertLessEqual(s["text"]["part"], s["distance_km"] * library.FINISH_SHARE + 0.01)

    def test_drift_holds_the_finish(self):
        plan, runs, result = make("hm", race=dt.date(2026, 8, 30))
        long_run = next(s for s in plan["sessions"] if s["type"] == "long" and s["text"].get("part"))
        date = dt.date.fromisoformat(long_run["date"])
        run = pd.DataFrame([{"activity_id": 9000, "day": pd.Timestamp(date), "kind": "long",
                             "distance_km": long_run["distance_km"], "pace_min_km": 6.5}])
        laps = self.laps(160.0, km=int(long_run["distance_km"]))
        found = planning.outcomes(plan, pd.concat([runs, run], ignore_index=True), date + dt.timedelta(days=1),
                                  laps=laps)[long_run["id"]]
        self.assertEqual(found["reason"], "drift")
        steady = planning.outcomes(plan, pd.concat([runs, run], ignore_index=True), date + dt.timedelta(days=1),
                                   laps=self.laps(145.0, km=int(long_run["distance_km"])))[long_run["id"]]
        self.assertTrue(steady["advance"])



class PlanCheck(unittest.TestCase):
    def test_backtest_finds_no_broken_rules(self):
        from running import plan_check

        runs, efforts, days, _ = fixture()
        # The fixture's only measured effort is on 27.02, so the anchors are its last days.
        table = plan_check.backtest(runs, efforts, days, hr_max=190, every_days=1, since_days=365, history_days=50,
                                    follow_days=1)
        self.assertFalse(table.empty)
        summary = plan_check.summary(table)
        self.assertEqual(summary["broken"], {rule: 0 for rule in plan_check.RULES})
        self.assertEqual(summary["plans"], len(table))



class Constants(unittest.TestCase):
    """The heuristic numbers stay consistent with the forecast's requirements."""

    def test_peak_and_long_run_cover_what_the_forecast_calls_prepared(self):
        from running import forecast

        for distance, need in forecast.REQUIREMENTS.items():
            self.assertGreaterEqual(planning.PEAK_KM[distance] * 0.8, need["weekly_km"] * 0.8, distance)
            self.assertGreater(planning.PEAK_KM[distance], need["weekly_km"], distance)
            self.assertGreaterEqual(planning.LONG_TARGET_KM[distance], need["long_km"], distance)

    def test_every_constant_is_labelled(self):
        doc = planning.__doc__
        for name in ("SPIKE", "LONG_TARGET_KM", "PEAK_KM", "MAX_STEP_KM", "TAPER_WEEKS", "LONG_GAP_DAYS",
                     "QUALITY_ROOM_KM", "ON_PACE_SHARE", "HR_MARGIN"):
            self.assertIn(name, doc)
