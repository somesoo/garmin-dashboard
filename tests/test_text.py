"""Stored codes read in both languages, and old Polish plans read back into codes."""

from __future__ import annotations

import copy
import datetime as dt
import json
import unittest

import pandas as pd

import i18n
from running import garmin_workout as gw, plan as planning, sessions, store, text
from tests.test_plan_store_coach import TempStore, fixture


def make_plan(distance="hm", goal_s=None):
    runs, _, _, result = fixture()
    request = planning.PlanRequest(distance, dt.date(2026, 6, 14), run_days=[1, 3, 5, 6], long_day=6,
                                   start=dt.date(2026, 3, 2), goal_s=goal_s)
    return planning.generate(request, runs, result, anchor=pd.Timestamp("2026-03-01"))


def old_format(plan):
    """The same plan as the generator wrote it before codes: Polish sentences, no ``text``."""
    old = copy.deepcopy(plan)
    i18n.force("pl")
    text.fill(old)
    old["warnings"] = text.warnings(old)
    for session in old["sessions"]:
        session.pop("text")
    return old


class Codes(unittest.TestCase):
    def tearDown(self):
        i18n.force("pl")

    def test_session_reads_in_both_languages(self):
        plan = make_plan()
        threshold = next(s for s in plan["sessions"] if s["type"] == "threshold")
        self.assertTrue(threshold["title"].startswith("Próg"))
        i18n.force("en")
        english = text.session_text(threshold)
        self.assertTrue(english["title"].startswith("Threshold"))
        self.assertIn("jog recovery", english["main"])
        self.assertNotRegex(" ".join(english.values()), "[ąćęłńóśźż]")

    def test_reason_and_source_codes(self):
        code = text.reason_code("easy_hot", pace=6.6, hr=0.89)
        self.assertIn("upał", text.reason(code))
        i18n.force("en")
        self.assertIn("heat", text.reason(code))
        self.assertEqual(text.source("whole"), "the whole run")
        self.assertEqual(text.reason("an old sentence"), "an old sentence")

    def test_every_reason_key_renders(self):
        for key in ("manual", "name_race", "watch_reps", "block_threshold", "block_tempo", "block_faster", "name_reps",
                    "variability", "hr_continuous", "hr_above_easy", "easy_hot", "long_hr", "recovery", "easy_hr",
                    "long_nohr", "tempo_nohr", "easy_nohr"):
            code = text.reason_code(key, name="x", reps=3, km=4.0, pace=5.0, cv=0.3, te=2.0, hr=0.8, min=30.0, ref=8.0)
            for lang in ("pl", "en"):
                i18n.force(lang)
                self.assertNotIn("{", text.reason(code), (key, lang))

    def test_classification_stores_a_code(self):
        _, reason, sure = sessions._classify_one({"name": "Morning run", "distance_km": 6.0, "duration_min": 36.0,
                                                  "avg_hr": 140, "pace_min_km": 6.0}, None, None, 190, None, None)
        self.assertEqual(json.loads(reason)["key"], "easy_hr")
        self.assertIn(sure, text.CONFIDENCE_ICON)

    def test_fingerprint_ignores_the_language(self):
        session = next(s for s in make_plan()["sessions"] if s["type"] == "threshold")
        polish = gw.fingerprint(session)
        i18n.force("en")
        session.update(text.session_text(session))
        self.assertEqual(gw.fingerprint(session), polish)


class Migration(unittest.TestCase):
    def tearDown(self):
        i18n.force("pl")

    def test_old_plan_reads_back_into_the_same_codes(self):
        for distance, goal in (("hm", None), ("10k", None), ("m", 3 * 3600), ("5k", 600)):
            plan = make_plan(distance, goal)
            old = old_format(plan)
            self.assertTrue(text.migrate_plan(old))
            self.assertEqual([s["text"] for s in old["sessions"]], [s["text"] for s in plan["sessions"]], distance)
            self.assertEqual(old["warnings"], plan["warnings"], distance)
            self.assertFalse(text.migrate_plan(old))

    def test_softened_and_adjusted_sessions(self):
        plan = make_plan()
        today = dt.date(2026, 3, 2)
        hard = next(s for s in plan["sessions"] if s["type"] in ("threshold", "intervals"))
        planning.soften(plan, hard["id"], today=today)
        planning.adjust(plan, "fatigue", today=today)
        old = old_format(plan)
        for session in old["sessions"]:
            if session.get("adjusted") == "fatigue":
                session["note"] = "moja notatka [zmęczenie — 7 dni bez jakości, objętość −20%]"
        text.migrate_plan(old)
        self.assertEqual([s["text"] for s in old["sessions"]], [s["text"] for s in plan["sessions"]])
        self.assertIn("moja notatka", {s["note"] for s in old["sessions"]})
        softened = next(s for s in old["sessions"] if s["text"]["key"] == "softened")
        i18n.force("en")
        self.assertIn("instead of: ", text.session_text(softened)["title"])

    def test_unknown_text_is_kept_as_custom(self):
        session = {"type": "easy", "title": "Bieg z psem", "main": "spokojnie po lesie", "purpose": "frajda"}
        spec = text.infer(session)
        self.assertEqual(spec["key"], "custom")
        self.assertEqual(text.session_text({**session, "text": spec})["title"], "Bieg z psem")


class Files(TempStore):
    def test_file_holds_codes_and_old_files_are_rewritten(self):
        plan = make_plan()
        store.save_plan(plan)
        raw = json.loads((store.PLANS / f"{plan['id']}.json").read_text(encoding="utf-8"))
        self.assertNotIn("title", raw["sessions"][0])
        self.assertIn("text", raw["sessions"][0])

        old = old_format(plan)
        (store.PLANS / f"{plan['id']}.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        loaded = store.plan(plan["id"])
        self.assertTrue(loaded["sessions"][0]["title"])
        raw = json.loads((store.PLANS / f"{plan['id']}.json").read_text(encoding="utf-8"))
        self.assertIn("text", raw["sessions"][0])
        self.assertNotIn("title", raw["sessions"][0])
        i18n.force("en")
        try:
            english = store.plan(plan["id"])
        finally:
            i18n.force("pl")
        self.assertNotRegex(" ".join(s["title"] for s in english["sessions"]), "[ąćęłńóśźż]")


if __name__ == "__main__":
    unittest.main()
