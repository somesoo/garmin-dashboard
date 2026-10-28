"""Plan sessions as Garmin workouts, and the push that keeps the calendar in sync."""

from __future__ import annotations

import datetime as dt
import json
import unittest

from etl import push_plan
from running import garmin_workout as gw, plan as planning, store
import pandas as pd

from tests.test_plan_store_coach import TempStore, fixture


class FakeGarmin:
    def __init__(self):
        self.calls = []
        self.next_id = 100

    def upload_workout(self, payload):
        self.next_id += 1
        self.calls.append(("upload", payload["workoutName"]))
        return {"workoutId": self.next_id}

    def schedule_workout(self, workout_id, date):
        self.calls.append(("schedule", workout_id, date))
        return {"workoutScheduleId": workout_id * 10}

    def unschedule_workout(self, schedule_id):
        self.calls.append(("unschedule", schedule_id))

    def delete_workout(self, workout_id):
        self.calls.append(("delete", workout_id))


def threshold_session():
    return {
        "id": "s1", "date": "2026-11-03", "type": "threshold", "status": "planned", "title": "Próg 3×2 km",
        "main": "3×2 km w tempie T", "purpose": "próg",
        "steps": [
            {"kind": "warmup", "km": 2.0, "pace": [6.0, 6.6]},
            {"kind": "repeat", "reps": 3, "steps": [
                {"kind": "run", "km": 2.0, "pace": [5.0, 5.2]},
                {"kind": "recovery", "s": 60},
            ]},
            {"kind": "cooldown", "km": 1.5},
        ],
    }


class Conversion(unittest.TestCase):
    def test_pace_becomes_speed_with_the_slower_pace_as_the_lower_limit(self):
        self.assertAlmostEqual(gw.mps(5.0), 3.3333, places=3)
        workout = gw.to_garmin(threshold_session())
        steps = workout["workoutSegments"][0]["workoutSteps"]
        warmup = steps[0]
        self.assertEqual(warmup["stepType"]["stepTypeKey"], "warmup")
        self.assertEqual(warmup["endCondition"]["conditionTypeKey"], "distance")
        self.assertEqual(warmup["endConditionValue"], 2000.0)
        self.assertLess(warmup["targetValueOne"], warmup["targetValueTwo"])
        self.assertEqual(steps[2]["targetType"]["workoutTargetTypeKey"], "no.target")
        json.dumps(workout)

    def test_repeat_group_and_step_order(self):
        steps = gw.to_garmin(threshold_session())["workoutSegments"][0]["workoutSteps"]
        group = steps[1]
        self.assertEqual(group["type"], "RepeatGroupDTO")
        self.assertEqual(group["numberOfIterations"], 3)
        inner = group["workoutSteps"]
        self.assertEqual([s["stepType"]["stepTypeKey"] for s in inner], ["interval", "recovery"])
        self.assertEqual(inner[1]["endCondition"]["conditionTypeKey"], "time")
        self.assertTrue(all(s["childStepId"] == group["childStepId"] for s in inner))
        orders = [steps[0]["stepOrder"], group["stepOrder"], *[s["stepOrder"] for s in inner], steps[2]["stepOrder"]]
        self.assertEqual(orders, [1, 2, 3, 4, 5])

    def test_rest_and_old_sessions_are_not_workouts(self):
        self.assertIsNone(gw.to_garmin({"id": "r", "date": "2026-11-03", "type": "rest", "steps": []}))
        old = threshold_session()
        del old["steps"]
        self.assertIsNone(gw.to_garmin(old))


class Sync(TempStore):
    def setUp(self):
        super().setUp()
        self.runs, _, _, self.result = fixture()
        request = planning.PlanRequest("hm", dt.date(2026, 6, 14), run_days=[1, 3, 5, 6], long_day=6,
                                       start=dt.date(2026, 3, 2))
        self.plan = store.save_plan(planning.generate(request, self.runs, self.result,
                                                      anchor=pd.Timestamp("2026-03-01")))
        self.today = dt.date(2026, 3, 2)
        self.sleep, push_plan.time.sleep = push_plan.time.sleep, lambda *_: None

    def tearDown(self):
        push_plan.time.sleep = self.sleep
        super().tearDown()

    def push(self, api):
        self.plan = push_plan.push(self.plan, api, self.today, 7, log=lambda *_: None)

    def test_push_is_idempotent(self):
        api = FakeGarmin()
        expected = len([s for s in self.plan["sessions"] if gw.to_garmin(s) is not None
                        and self.today <= dt.date.fromisoformat(s["date"]) < self.today + dt.timedelta(days=7)])
        self.push(api)
        self.assertEqual(sum(1 for c in api.calls if c[0] == "upload"), expected)
        self.assertEqual(len(self.plan["garmin"]), expected)
        self.assertEqual(gw.sync_actions(store.plan(self.plan["id"]), self.today), [])

    def test_changed_session_is_replaced_and_skipped_one_removed(self):
        self.push(FakeGarmin())
        pushed = list(self.plan["garmin"])
        hard = next((s for s in self.plan["sessions"] if s["id"] in pushed
                     and s["type"] in ("threshold", "intervals", "tempo")), None)
        other = next(s for s in self.plan["sessions"] if s["id"] in pushed and (hard is None or s["id"] != hard["id"]))
        if hard is not None:
            planning.soften(self.plan, hard["id"], today=self.today)
        planning.set_status(self.plan, other["id"], "skipped")
        actions = {a["session_id"]: a["action"] for a in gw.sync_actions(self.plan, self.today)}
        self.assertEqual(actions[other["id"]], "remove")
        if hard is not None:
            self.assertEqual(actions[hard["id"]], "replace")
        old_workout = self.plan["garmin"][other["id"]]["workout_id"]
        api = FakeGarmin()
        self.push(api)
        self.assertIn(("delete", old_workout), api.calls)
        self.assertNotIn(other["id"], self.plan["garmin"])

    def test_replan_cleans_up_the_old_sessions(self):
        self.push(FakeGarmin())
        old_ids = set(self.plan["garmin"])
        fresh = planning.replan(self.plan, self.runs, self.result, today=self.today)
        actions = gw.sync_actions(fresh, self.today)
        removed = {a["session_id"] for a in actions if a["action"] == "remove"}
        self.assertEqual(removed, old_ids)  # every old workout goes, nothing is left as a duplicate
        self.assertTrue(any(a["action"] == "upload" for a in actions))
