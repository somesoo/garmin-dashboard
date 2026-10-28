"""Plan generator rules, plan-vs-actual, the JSON store contract and the coach brief."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tests.helpers import activities, daily, run, training_block
from running import coach, forecast, physio, plan as planning, sessions, store, units


class TempStore(unittest.TestCase):
    """Points the store at a temporary directory for the duration of a test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (store.ROOT, store.RACES, store.PLANS)
        store.ROOT = Path(self.tmp.name)
        store.RACES = store.ROOT / "races.json"
        store.PLANS = store.ROOT / "plans"

    def tearDown(self):
        store.ROOT, store.RACES, store.PLANS = self.saved
        self.tmp.cleanup()


def fixture():
    rows = training_block("2026-01-05", 8, long_km=12.0)
    rows.append(run(900, "2026-02-27", 5.0, 5.0, hr=175))
    runs = sessions.select_runs(activities(rows)).assign(kind="easy", kind_reason="r", kind_confidence="średnia")
    runs.loc[runs["activity_id"] == 900, "kind"] = "race"
    runs["hr_max_used"] = 190.0
    efforts = pd.DataFrame([{
        "activity_id": 900, "day": pd.Timestamp("2026-02-27"), "effort": "5k", "distance_m": 5000.0,
        "seconds": 1500.0, "pace_min_km": 5.0, "avg_hr": 175, "source": "test", "vdot": physio.vdot(5000, 1500),
        "hr_frac": 175 / 190, "minutes": 25.0, "near_max": True,
    }])
    days = daily("2025-12-01", 120)
    result = forecast.forecast(runs, efforts, days, pd.Timestamp("2026-03-01"), hr_max=190)
    return runs, efforts, days, result


class Generator(unittest.TestCase):
    def setUp(self):
        self.runs, _, _, self.result = fixture()

    def make(self, distance="hm", race=dt.date(2026, 6, 14), days=(1, 3, 5, 6), **kwargs):
        request = planning.PlanRequest(distance, race, run_days=list(days), long_day=6, start=dt.date(2026, 3, 2), **kwargs)
        return planning.generate(request, self.runs, self.result, anchor=pd.Timestamp("2026-03-01"))

    def test_plan_satisfies_the_file_contract(self):
        plan = self.make()
        self.assertEqual(store.validate_plan(plan), [])
        json.dumps(plan)  # serialisable as-is

    def test_race_on_race_day_and_rest_the_day_before(self):
        plan = self.make()
        race = [s for s in plan["sessions"] if s["type"] == "race"]
        self.assertEqual(len(race), 1)
        self.assertEqual(race[0]["date"], "2026-06-14")
        self.assertNotIn("2026-06-13", {s["date"] for s in plan["sessions"]})
        self.assertLessEqual(max(s["date"] for s in plan["sessions"]), "2026-06-14")

    def test_no_two_hard_days_in_a_row(self):
        for days in ((1, 3, 5, 6), (0, 1, 2, 3, 4, 5, 6), (4, 5, 6), (0, 2, 4, 6)):
            plan = self.make(days=days)
            hard = sorted(dt.date.fromisoformat(s["date"]) for s in plan["sessions"]
                          if s["type"] in ("tempo", "threshold", "intervals", "long"))
            for first, second in zip(hard, hard[1:]):
                self.assertGreaterEqual((second - first).days, 2, (days, first, second))

    def test_steps_cover_the_planned_distance(self):
        for distance in ("5k", "hm", "m"):
            plan = self.make(distance=distance, race=dt.date(2026, 8, 30))
            easy = plan["paces"]["E"]
            for session in plan["sessions"]:
                if session["type"] == "rest":
                    continue
                self.assertTrue(session.get("steps"), session["title"])
                covered = planning.steps_km(session["steps"], easy_pace=sum(easy) / 2)
                if session["type"] == "race":
                    continue  # warm-up jog is on top of the race distance
                self.assertAlmostEqual(covered, session["distance_km"], delta=0.25 * session["distance_km"] + 0.3,
                                       msg=session["title"])
            self.assertEqual(store.validate_plan(plan), [])

    def test_bad_steps_are_rejected(self):
        self.assertEqual(store.validate_steps([{"kind": "run", "km": 5, "pace": [5.0, 5.2]}]), [])
        bad = [
            [{"kind": "sprint", "km": 1}],
            [{"kind": "run"}],
            [{"kind": "run", "km": 1, "s": 60}],
            [{"kind": "run", "km": 1, "pace": [5.5, 5.0]}],
            [{"kind": "repeat", "reps": 0, "steps": []}],
            [{"kind": "repeat", "reps": 2, "steps": [{"kind": "repeat", "reps": 2, "steps": []}]}],
            "3x1km",
        ]
        for steps in bad:
            self.assertTrue(store.validate_steps(steps), steps)

    def test_only_chosen_days_are_used(self):
        plan = self.make(days=(1, 3, 6))
        weekdays = {dt.date.fromisoformat(s["date"]).weekday() for s in plan["sessions"] if s["type"] != "race"}
        self.assertTrue(weekdays <= {1, 3, 6})

    def test_volume_respects_the_acute_chronic_guard(self):
        plan = self.make(distance="m", race=dt.date(2026, 9, 27))
        volumes = plan["baseline"]["history_km"][-planning.GUARD_WEEKS:] + [w["volume_km"] for w in plan["weeks"]]
        floor = 3.0 * 4
        for index in range(planning.GUARD_WEEKS, len(volumes)):
            chronic = sum(volumes[index - planning.GUARD_WEEKS:index]) / planning.GUARD_WEEKS
            self.assertLessEqual(volumes[index], max(planning.GUARD * chronic, floor) + 0.11, index)

    def test_recovery_weeks_taper_and_growth(self):
        plan = self.make(distance="m", race=dt.date(2026, 9, 27))
        weeks = plan["weeks"]
        self.assertTrue(any(w.get("recovery") for w in weeks))
        build = [w for w in weeks if w["phase"] in ("base", "build", "peak") and not w.get("recovery")]
        self.assertGreater(build[-1]["volume_km"], build[0]["volume_km"])  # it does build
        taper = [w for w in weeks if w["phase"] == "taper"]
        self.assertEqual(len(taper) + 1, planning.TAPER_WEEKS["m"])  # + race week
        self.assertLess(taper[-1]["volume_km"], build[-1]["volume_km"])
        self.assertLess(weeks[-1]["volume_km"], taper[-1]["volume_km"])

    def test_long_run_capped_by_target_and_time(self):
        plan = self.make(distance="m", race=dt.date(2026, 9, 27))
        easy = sum(physio.training_paces(self.result["vdot"])["E"]) / 2
        for week in plan["weeks"]:
            self.assertLessEqual(week["long_km"], planning.LONG_TARGET_KM["m"] + 1e-6)
            self.assertLessEqual(week["long_km"] * easy, 165 + 1)

    def test_paces_come_from_current_fitness_not_the_goal(self):
        plan = self.make(goal_s=units.parse_time("1:30:00"))  # far faster than a 25:00 5 km runner
        threshold = next(s for s in plan["sessions"] if s["type"] == "threshold")
        t_fast, t_slow = physio.training_paces(self.result["vdot"])["T"]
        self.assertAlmostEqual(threshold["pace_lo"], t_fast)
        self.assertTrue(any("szybszy" in w for w in plan["warnings"]))

    def test_too_close_to_race_warns(self):
        plan = self.make(race=dt.date(2026, 3, 15))
        self.assertTrue(any("3 tygodnie" in w for w in plan["warnings"]))

    def test_invalid_requests(self):
        with self.assertRaises(ValueError):
            self.make(days=(6,))
        with self.assertRaises(ValueError):
            self.make(race=dt.date(2026, 1, 1))
        with self.assertRaises(ValueError):
            planning.generate(planning.PlanRequest("hm", dt.date(2026, 6, 1), start=dt.date(2026, 3, 2)),
                              self.runs, {"status": "insufficient", "reason": "x"})

    def test_hard_day_placement(self):
        self.assertEqual(planning.place_hard_days([1, 3, 5, 6], 6, 2), [1, 3])
        self.assertEqual(planning.place_hard_days([4, 5, 6], 6, 2), [4])  # Sat would touch Sun
        self.assertEqual(planning.place_hard_days([5, 6], 6, 1), [])


class Tracking(unittest.TestCase):
    def setUp(self):
        self.runs, _, _, self.result = fixture()
        request = planning.PlanRequest("10k", dt.date(2026, 5, 10), run_days=[1, 3, 5, 6], long_day=6,
                                       start=dt.date(2026, 2, 2))
        self.plan = planning.generate(request, self.runs, self.result, anchor=pd.Timestamp("2026-02-01"))

    def test_match_same_day_then_neighbour(self):
        matched = planning.match(self.plan, self.runs, today=dt.date(2026, 3, 1))
        past = matched[matched["date"] < dt.date(2026, 3, 1)]
        self.assertTrue(past["activity_id"].notna().all())  # the block runs Tue/Thu/Sat/Sun
        self.assertEqual(past["activity_id"].nunique(), len(past))  # no run used twice
        future = matched[matched["date"] > dt.date(2026, 3, 1)]
        self.assertTrue((future["effective"] == "planned").all())

    def test_missing_run_is_missed_and_manual_status_wins(self):
        runs = self.runs[self.runs["day"] != pd.Timestamp("2026-02-03")]
        matched = planning.match(self.plan, runs, today=dt.date(2026, 3, 1)).set_index("date")
        self.assertEqual(matched.loc[dt.date(2026, 2, 3), "effective"], "missed")
        session = next(s for s in self.plan["sessions"] if s["date"] == "2026-02-03")
        planning.set_status(self.plan, session["id"], "skipped", note="choroba")
        matched = planning.match(self.plan, runs, today=dt.date(2026, 3, 1)).set_index("date")
        self.assertEqual(matched.loc[dt.date(2026, 2, 3), "effective"], "skipped")
        summary = planning.compliance(planning.match(self.plan, runs, today=dt.date(2026, 3, 1)))
        self.assertGreaterEqual(summary["skipped"], 1)

    def test_replan_keeps_the_past(self):
        today = dt.date(2026, 3, 2)
        session = next(s for s in self.plan["sessions"] if s["date"] < today.isoformat())
        planning.set_status(self.plan, session["id"], "skipped")
        fresh = planning.replan(self.plan, self.runs, self.result, today=today)
        past = [s for s in fresh["sessions"] if s["date"] < today.isoformat()]
        self.assertEqual(past, [s for s in self.plan["sessions"] if s["date"] < today.isoformat()])
        self.assertEqual(fresh["id"], self.plan["id"])
        self.assertEqual(store.validate_plan(fresh), [])
        self.assertEqual(fresh["history"][-1]["action"], "replan")

    def test_adjust_for_illness(self):
        today = dt.date(2026, 3, 2)
        changed = planning.adjust(json.loads(json.dumps(self.plan)), "sick", today=today)
        first_days = [s for s in changed["sessions"] if today <= dt.date.fromisoformat(s["date"]) < today + dt.timedelta(days=4)]
        self.assertTrue(all(s["type"] == "rest" for s in first_days))
        later = [s for s in changed["sessions"]
                 if today + dt.timedelta(days=4) <= dt.date.fromisoformat(s["date"]) < today + dt.timedelta(days=11)]
        self.assertFalse(any(s["type"] in ("threshold", "intervals", "tempo") for s in later))
        self.assertEqual(store.validate_plan(changed), [])
        with self.assertRaises(ValueError):
            planning.adjust(self.plan, "holiday")

    def test_soften_turns_one_hard_session_easy(self):
        plan = json.loads(json.dumps(self.plan))
        hard = next(s for s in plan["sessions"] if s["type"] in ("threshold", "intervals", "tempo"))
        today = dt.date.fromisoformat(hard["date"])
        planning.soften(plan, hard["id"], today=today)
        changed = next(s for s in plan["sessions"] if s["id"] == hard["id"])
        self.assertEqual(changed["type"], "easy")
        self.assertLessEqual(changed["distance_km"], 6.0)
        self.assertEqual(store.validate_plan(plan), [])
        self.assertEqual(plan["history"][-1]["action"], "soften")
        with self.assertRaises(ValueError):
            planning.soften(plan, hard["id"], today=today)  # already easy

    def test_postpone_never_puts_hard_days_side_by_side(self):
        plan = json.loads(json.dumps(self.plan))
        hard_types = ("tempo", "threshold", "intervals", "long")
        for session in [s for s in plan["sessions"] if s["type"] != "race"][:12]:
            today = dt.date.fromisoformat(session["date"])
            try:
                planning.postpone(plan, session["id"], today=today)
            except ValueError:
                continue
            hard = sorted(dt.date.fromisoformat(s["date"]) for s in plan["sessions"] if s["type"] in hard_types)
            for first, second in zip(hard, hard[1:]):
                self.assertGreaterEqual((second - first).days, 2)
        self.assertEqual(store.validate_plan(plan), [])
        easy = next(s for s in plan["sessions"] if s["type"] == "easy")
        date = dt.date.fromisoformat(easy["date"])
        neighbours = {s["date"] for s in plan["sessions"] if s["type"] in hard_types}
        if (date + dt.timedelta(days=2)).isoformat() not in neighbours:
            planning.postpone(plan, easy["id"], today=date)
            self.assertEqual(next(s for s in plan["sessions"] if s["id"] == easy["id"])["date"],
                             (date + dt.timedelta(days=1)).isoformat())


class Store(TempStore):
    def test_race_roundtrip_and_validation(self):
        saved = store.save_race({"name": "Maraton Warszawski", "date": "2026-09-27", "distance": "m", "goal_s": 14400})
        self.assertEqual(store.race(saved["id"])["name"], "Maraton Warszawski")
        self.assertEqual(saved["priority"], "A")
        with self.assertRaises(ValueError):
            store.save_race({"name": "", "date": "27.09.2026", "distance": "ultra"})
        self.assertEqual(len(store.validate_race({"name": "", "date": "x", "distance": "ultra", "goal_s": -1})), 4)
        store.save_race({**saved, "result_activity_id": 123})
        self.assertEqual(store.manual_kinds(), {123: "race"})
        store.delete_race(saved["id"])
        self.assertEqual(store.races(), [])

    def test_plan_roundtrip_is_atomic_and_validated(self):
        plan = {"id": "plan-x", "sessions": [{"id": "s1", "date": "2026-03-03", "type": "easy", "distance_km": 6.0}]}
        store.save_plan(plan)
        self.assertEqual(store.plan("plan-x")["sessions"][0]["id"], "s1")
        self.assertEqual(list(store.PLANS.glob("*.part")), [])
        bad = {"id": "plan-y", "sessions": [{"id": "s1", "date": "2026-13-01", "type": "jog", "distance_km": 99}]}
        self.assertEqual(len(store.validate_plan(bad)), 3)
        with self.assertRaises(ValueError):
            store.save_plan(bad)
        self.assertIsNone(store.plan("plan-y"))

    def test_corrupt_files_do_not_crash(self):
        store.PLANS.mkdir(parents=True)
        (store.PLANS / "broken.json").write_text("{not json", encoding="utf-8")
        store.RACES.write_text("[1, 2", encoding="utf-8")
        self.assertEqual(store.plans(), [])
        self.assertEqual(store.races(), [])


class Coach(TempStore):
    def test_flags_turn_a_hard_session_easy(self):
        runs, _, _, result = fixture()
        today = dt.date(2026, 3, 3)
        plan = {"sessions": [{"id": "s", "date": "2026-03-03", "type": "intervals", "status": "planned",
                              "title": "5×1000"}]}
        rough = daily("2026-02-20", 12, readiness=25.0, readiness_level="LOW", hrv_status="UNBALANCED",
                      sleep_h=5.0, rhr_deviation=6.0)
        verdict = coach.next_session(plan, runs, rough, result, today)
        self.assertEqual(verdict["action"], "zamień na spokojny")
        self.assertGreaterEqual(len(verdict["flags"]), 2)
        fine = daily("2026-02-20", 12, readiness=80.0, readiness_level="HIGH", hrv_status="BALANCED", sleep_h=8.0,
                     rhr_deviation=0.0)
        self.assertEqual(coach.next_session(plan, runs, fine, result, today)["action"], "jak w planie")

    def test_a_later_session_waits_for_its_own_morning(self):
        runs, _, _, result = fixture()
        today = dt.date(2026, 3, 3)
        plan = {"sessions": [{"id": "s", "date": "2026-03-04", "type": "intervals", "status": "planned",
                              "title": "5×1000"}]}
        rough = daily("2026-02-20", 12, readiness=25.0, readiness_level="LOW", hrv_status="UNBALANCED",
                      sleep_h=5.0, rhr_deviation=6.0)
        verdict = coach.next_session(plan, runs, rough, result, today)
        self.assertFalse(verdict["today"])
        self.assertEqual(verdict["action"], "decyzja rano")
        self.assertIn("rano", verdict["reasons"][0])

    def test_without_recovery_data_there_are_no_invented_flags(self):
        runs, _, _, result = fixture()
        signals = coach.recovery_signals(daily("2026-02-20", 12), dt.date(2026, 3, 3))
        self.assertEqual(signals["flags"], [])
        self.assertFalse(coach.recovery_signals(pd.DataFrame(), dt.date(2026, 3, 3))["available"])

    def test_brief_is_json_and_names_its_gaps(self):
        runs, efforts, days, _ = fixture()
        data = coach.brief(runs, efforts, days, today=dt.date(2026, 3, 1))
        text = json.dumps(data, ensure_ascii=False, default=str)
        self.assertIn("forecast", data)
        self.assertEqual(data["forecast"]["status"], "ok")
        self.assertTrue(any("RPE" in gap for gap in data["data_gaps"]))
        self.assertIn("Brief treningowy", coach.markdown(data))
        self.assertGreater(len(text), 500)


if __name__ == "__main__":
    unittest.main()


def laps_frame(activity_id, rows):
    """rows: (intensity, step_index, metres, seconds)"""
    return pd.DataFrame([
        {"activity_id": activity_id, "lap": i + 1, "intensity": kind, "step_index": step, "distance_m": m,
         "duration_s": s, "avg_hr": 170}
        for i, (kind, step, m, s) in enumerate(rows)
    ])


class Laps(unittest.TestCase):
    def test_auto_laps_of_one_rep_are_merged(self):
        # 2026-10-13 shape: 1.2 km reps cut by auto-lap into 1000 m + 200 m.
        laps = laps_frame(1, [("warmup", 0, 1000, 470), ("active", 1, 1000, 261), ("active", 1, 200, 53),
                              ("recovery", 2, 330, 150), ("active", 1, 1000, 268), ("active", 1, 200, 52),
                              ("cooldown", 3, 1000, 420)])
        blocks = planning.rep_blocks(laps)
        self.assertEqual([b["km"] for b in blocks], [1.2, 1.2])
        self.assertAlmostEqual(blocks[0]["pace"], (261 + 53) / 60 / 1.2, places=3)

    def test_plain_run_has_no_reps(self):
        laps = laps_frame(1, [("active", None, 1000, 360)] * 5)
        self.assertEqual(planning.rep_blocks(laps), [])

    def test_match_counts_reps_on_pace(self):
        session = {"id": "s1", "date": "2026-03-03", "type": "intervals", "status": "planned", "title": "I",
                   "distance_km": 8.0, "steps": [
                       {"kind": "warmup", "km": 2.0},
                       {"kind": "repeat", "reps": 4, "steps": [{"kind": "run", "km": 1.0, "pace": [4.5, 4.6]},
                                                               {"kind": "recovery", "s": 270}]},
                       {"kind": "cooldown", "km": 1.5}]}
        runs = sessions.select_runs(activities([run(7, "2026-03-03", 8.0, 5.5)])).assign(kind="intervals")
        reps = [("warmup", 0, 2000, 720)]
        for seconds in (272, 275, 290):  # 4:32, 4:35 on pace; 4:50 too slow; 4th rep not run
            reps += [("active", 1, 1000, seconds), ("recovery", 2, 600, 270)]
        laps = laps_frame(7, reps)
        row = planning.match({"sessions": [session]}, runs, dt.date(2026, 3, 4), laps=laps).iloc[0]
        self.assertEqual((row["reps_planned"], row["reps_done"], row["reps_on_pace"]), (4, 3, 2))
        without = planning.match({"sessions": [session]}, runs, dt.date(2026, 3, 4)).iloc[0]
        self.assertNotIn("reps_done", without.index)
