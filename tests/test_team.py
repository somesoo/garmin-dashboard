"""A coach and their athletes: the relation, consent (also a parent's), what a coach sees, notes, sticky notes,
sessions set by hand (core/team.py, ui/coaching.py, analysis/team.py, running/plan.edit_session)."""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

import pandas as pd

from analysis import team as cards
from core import audit
from core import privacy
from core import team
from core import tenant
from running import plan as planning
from running import store
from tests.helpers import consent, people
from tests.test_plan_store_coach import fixture

SQUAD = {"coach": {"admin": True, "identities": ["coach@example.com"]},
         "kid": {"coach": "coach", "identities": ["kid@example.com"]},
         "other": {"identities": ["other@example.com"]}}


class Relation(unittest.TestCase):
    def setUp(self):
        self.enterContext(people(SQUAD))

    def test_registry_names_the_coach_but_opens_nothing(self):
        kid = tenant.get("kid")
        self.assertEqual(kid.coach_id, "coach")
        self.assertEqual([p.id for p in team.athletes(tenant.get("coach"))], ["kid"])
        self.assertTrue(team.is_coach(tenant.get("coach")))
        self.assertFalse(team.is_coach(tenant.get("kid")))
        self.assertEqual(tenant.coached("coach", "kid"), kid)
        self.assertIsNone(tenant.coached("other", "kid"), "only the coach the registry names")
        self.assertIsNone(tenant.coached("coach", "other"))
        self.assertFalse(team.allowed("coach", kid), "named is not agreed")

    def test_all_three_halves_must_hold(self):
        kid = tenant.get("kid")
        team.give(kid, "all")
        self.assertFalse(team.allowed("coach", kid), "no consent to the dashboard yet")
        consent("kid")
        self.assertTrue(team.allowed("coach", kid))
        self.assertFalse(team.allowed("other", kid))
        self.assertEqual(team.scope(kid), "all")
        team.revoke(kid)
        self.assertFalse(team.allowed("coach", kid))
        events = [e["event"] for e in audit.events("kid")]
        self.assertIn("coach_grant", events)
        self.assertIn("coach_revoke", events)

    def test_a_new_policy_version_closes_the_view_until_asked_again(self):
        kid = tenant.get("kid")
        consent("kid")
        team.give(kid, "training")
        self.assertTrue(team.allowed("coach", kid))
        with unittest.mock.patch.object(privacy, "POLICY_VERSION", "2099-01-01"):
            self.assertFalse(team.allowed("coach", kid))

    def test_a_guardian_names_themselves(self):
        kid = tenant.get("kid")
        with self.assertRaises(ValueError):
            team.give(kid, "all", "guardian")
        record = team.give(kid, "all", "guardian", "  Anna   Nowak ")
        self.assertEqual((record["by"], record["guardian"]), ("guardian", "Anna Nowak"))
        with self.assertRaises(ValueError):
            privacy.accept(kid, "pl", agreed_by="guardian")
        given = privacy.accept(kid, "pl", agreed_by="guardian", guardian="Anna Nowak")
        self.assertEqual(given["guardian"], "Anna Nowak")
        self.assertEqual(privacy.consent(kid)["by"], "guardian")

    def test_cli_sets_and_drops_the_coach(self):
        self.assertEqual(tenant.main(["coach", "other", "coach"]), 0)
        self.assertEqual(tenant.get("other").coach_id, "coach")
        team.give(tenant.get("other"), "all")
        self.assertEqual(tenant.main(["coach", "other", "kid"]), 0)
        self.assertIsNone(team.grant(tenant.get("other")), "consent named the old coach: gone with them")
        self.assertEqual(tenant.main(["coach", "other", "--off"]), 0)
        self.assertIsNone(tenant.get("other").coach_id)
        self.assertEqual(tenant.main(["coach", "other", "nobody"]), 1)
        with self.assertRaises(RuntimeError):
            tenant._user("self", {"coach": "self"})

    def test_scope_decides_the_pages(self):
        for url in team.NEVER:
            self.assertFalse(team.page_allowed(url, "all"), url)
        self.assertTrue(team.page_allowed("sen", "all"))
        self.assertFalse(team.page_allowed("sen", "training"))
        self.assertFalse(team.page_allowed("regeneracja", "training"))
        self.assertFalse(team.page_allowed("dzien", "training"))
        self.assertTrue(team.page_allowed("plan", "training"))
        self.assertFalse(team.page_allowed("plan", None))
        # Pages that read recovery anywhere are out whole: load draws HRV, sport's readiness is built from it.
        self.assertFalse(team.page_allowed("obciazenie-biegowe", "training"))
        self.assertFalse(team.page_allowed("sport", "training"))

    def test_plan_reasons_quoting_recovery_hide_for_training_only(self):
        from running import text

        session = {"why": [{"key": "response", "decision": "hold", "signals": []}, {"key": "set_by", "coach": True}]}
        self.assertEqual(len(text.why(session)), 2)
        self.assertEqual(len(text.why(session, private=True)), 1)

    def test_notes_thread(self):
        kid, coach, other = (tenant.get(i) for i in ("kid", "coach", "other"))
        note = team.add_note(kid, coach, "  Spokojnie w czwartek  ")
        self.assertEqual(note["text"], "Spokojnie w czwartek")
        self.assertEqual([n["id"] for n in team.unread(kid, "kid")], [note["id"]])
        self.assertEqual(team.unread(kid, "coach"), [], "one's own note is read")
        team.mark_read(kid, "kid")
        self.assertEqual(team.unread(kid, "kid"), [])
        with self.assertRaises(PermissionError):
            team.add_note(kid, other, "hej")
        with self.assertRaises(ValueError):
            team.add_note(kid, coach, "   ")
        self.assertFalse(team.delete_note(kid, note["id"], tenant.get("kid")), "only the author deletes")
        self.assertTrue(team.delete_note(kid, note["id"], coach))
        self.assertEqual(team.notes(kid), [])
        self.assertIn("notes.json", tenant.OWNED)
        self.assertIn("coach.json", tenant.OWNED)


class Cards(unittest.TestCase):
    TODAY = dt.date(2026, 3, 2)

    def setUp(self):
        self.runs, _, self.days, self.result = fixture()
        request = planning.PlanRequest("10k", dt.date(2026, 5, 10), run_days=[1, 3, 5, 6], long_day=6,
                                       start=dt.date(2026, 2, 2))
        self.plan = planning.generate(request, self.runs, self.result, anchor=pd.Timestamp("2026-02-01"))

    def daily(self, last: str, **night):
        frame = self.days[self.days["day"] <= pd.Timestamp(last)].copy()
        frame["sleep_h"] = 7.5
        frame["hrv_deviation"] = 0.0
        frame["rhr_deviation"] = 0.0
        for column, value in night.items():
            frame.loc[frame.index[-1], column] = value
        return frame

    def card(self, runs, daily, scope="all"):
        matched = planning.match(self.plan, runs, self.TODAY)
        return cards.card(daily, runs, self.plan, matched, [{"name": "Wiosna", "distance": "10k", "date": "2026-05-10"}],
                          self.TODAY, scope)

    def test_on_track(self):
        card = self.card(self.runs, self.daily("2026-03-01"))
        self.assertEqual(card["state"], "ok", card["reasons"])
        self.assertEqual(card["race"]["days"], (dt.date(2026, 5, 10) - self.TODAY).days)
        self.assertIsNotNone(card["recovery"])
        self.assertEqual(card["recovery"]["sleep_norm_h"], 7.5)

    def test_missed_sessions_and_a_bad_night_ask_for_attention(self):
        runs = self.runs[self.runs["day"] < pd.Timestamp("2026-02-24")]
        card = self.card(runs, self.daily("2026-03-01", sleep_h=4.5, rhr_deviation=6.0))
        self.assertEqual(card["state"], "attention")
        keys = {r["key"] for r in card["reasons"]}
        self.assertIn("missed", keys)
        self.assertIn("recovery", keys)

    def test_no_watch_is_silence_not_a_bad_night(self):
        runs = self.runs[self.runs["day"] < pd.Timestamp("2026-02-28")]
        card = self.card(runs, self.daily("2026-02-27"))
        self.assertEqual(card["reasons"][0]["key"], "silent")
        self.assertGreaterEqual(card["reasons"][0]["days"], cards.STALE_DAYS)

    def test_training_scope_reads_no_recovery(self):
        card = self.card(self.runs, self.daily("2026-03-01", sleep_h=4.0, rhr_deviation=9.0), scope="training")
        self.assertIsNone(card["recovery"])
        self.assertNotIn("recovery", {r["key"] for r in card["reasons"]})

    def test_order_puts_attention_first(self):
        ordered = cards.order([("b", {"state": "ok", "reasons": []}), ("a", {"state": "silent", "reasons": [1]}),
                               ("c", {"state": "attention", "reasons": [1, 2]})])
        self.assertEqual([name for name, _ in ordered], ["c", "a", "b"])

    def test_empty(self):
        self.assertEqual(cards.card(pd.DataFrame(), pd.DataFrame(), None, None, [], self.TODAY)["state"], "empty")


class SetByHand(unittest.TestCase):
    def setUp(self):
        self.runs, _, _, self.result = fixture()
        request = planning.PlanRequest("10k", dt.date(2026, 5, 10), run_days=[1, 3, 5, 6], long_day=6,
                                       start=dt.date(2026, 2, 2))
        self.plan = planning.generate(request, self.runs, self.result, anchor=pd.Timestamp("2026-02-01"))
        self.today = dt.date(2026, 3, 2)

    def future(self, kind=None):
        return next(s for s in self.plan["sessions"] if s["date"] > "2026-03-10" and s["type"] not in ("race", "strength")
                    and (kind is None or s["type"] == kind))

    def test_a_coach_session_survives_a_rebuild(self):
        session = self.future("easy")
        edited = planning.edit_session(self.plan, session["id"], "intervals", date=session["date"], by_id="coach",
                                       by_name="Trener", coach=True, today=self.today)
        mine = next(s for s in edited["sessions"] if s["id"] == session["id"])
        self.assertEqual(mine["type"], "intervals")
        self.assertTrue(mine["locked"])
        self.assertEqual(mine["why"][0]["key"], "set_by")
        self.assertEqual(store.validate_plan(edited), [])
        self.assertEqual(edited["history"][-1]["action"], "edit")
        fresh = planning.replan(edited, self.runs, self.result, today=self.today)
        kept = [s for s in fresh["sessions"] if s["id"] == session["id"]]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["type"], "intervals")
        same_day = [s for s in fresh["sessions"] if s["date"] == session["date"] and s["type"] != "strength"]
        self.assertEqual(len(same_day), 1, "the generator leaves a day set by hand alone")
        self.assertEqual(store.validate_plan(fresh), [])

    def test_rest_distance_and_the_rules(self):
        session = self.future()
        rest = planning.edit_session(self.plan, session["id"], "rest", by_id="kid", today=self.today)
        mine = next(s for s in rest["sessions"] if s["id"] == session["id"])
        self.assertEqual((mine["type"], mine["distance_km"], mine["text"]["key"]), ("rest", 0.0, "rest"))
        self.assertEqual(store.validate_plan(rest), [])
        longer = planning.edit_session(self.plan, session["id"], "long", km=14, by_id="kid", today=self.today)
        self.assertEqual(next(s for s in longer["sessions"] if s["id"] == session["id"])["distance_km"], 14.0)
        with self.assertRaises(ValueError):
            planning.edit_session(self.plan, session["id"], "easy", by_id="kid", today=self.today)  # no km
        with self.assertRaises(ValueError):
            planning.edit_session(self.plan, session["id"], "easy", km=5, date="2026-03-01", by_id="kid",
                                  today=self.today)  # the past
        past = next(s for s in self.plan["sessions"] if s["date"] < "2026-03-01")
        with self.assertRaises(ValueError):
            planning.edit_session(self.plan, past["id"], "easy", km=5, by_id="kid", today=self.today)
        unlocked = planning.unlock_session(longer, session["id"])
        self.assertNotIn("locked", next(s for s in unlocked["sessions"] if s["id"] == session["id"]))


ROOT = Path(__file__).resolve().parents[1]
CONSENT = f"""
import sys; sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from core import tenant
st.session_state[tenant.SESSION_KEY] = "kid"
from views import consent
consent.gate()
st.write("PAST THE GATE")
"""
VIEW = f"""
import sys; sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from core import tenant
st.session_state[tenant.SESSION_KEY] = "coach"
if st.session_state.get("start"):
    st.session_state[tenant.VIEW_KEY] = "kid"
    st.session_state["start"] = False
from ui import coaching
coaching.gate()
st.write(f"DATA={{tenant.current().id}} VIEWER={{tenant.viewer().id}}")
"""


class Screens(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest

        self.AppTest = AppTest
        self.base = self.enterContext(people(SQUAD))

    def text(self, at) -> str:
        return " ".join(str(m.value) for m in at.markdown)

    def test_a_parent_consents_and_lets_the_coach_in_separately(self):
        at = self.AppTest.from_string(CONSENT).run(timeout=30)
        self.assertFalse(at.exception)
        self.assertIn("consent_coach", [c.key for c in at.checkbox], "a person with a coach gets the second box")
        at.radio(key="consent_by").set_value("guardian").run()
        at.checkbox(key="consent_check").check().run()
        self.assertTrue(at.button(key="consent_accept").disabled, "a parent's consent needs the parent's name")
        at.text_input(key="consent_guardian").input("Anna Nowak").run()
        at.radio(key="consent_coach_scope").set_value("training").run()
        at.checkbox(key="consent_coach").check().run()
        at.button(key="consent_accept").click().run()
        self.assertIn("PAST THE GATE", self.text(at))
        kid = tenant.get("kid")
        self.assertEqual(privacy.consent(kid)["guardian"], "Anna Nowak")
        self.assertEqual(team.valid(kid)["scope"], "training")
        self.assertEqual(team.valid(kid)["by"], "guardian")

    def test_the_coach_box_is_never_a_condition(self):
        at = self.AppTest.from_string(CONSENT).run(timeout=30)
        at.checkbox(key="consent_check").check().run()
        at.button(key="consent_accept").click().run()
        self.assertIn("PAST THE GATE", self.text(at))
        self.assertIsNone(team.grant(tenant.get("kid")))

    def test_a_coach_looks_until_consent_is_withdrawn(self):
        kid = tenant.get("kid")
        consent("kid")
        team.give(kid, "all")
        kid.tables.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"day": pd.date_range("2026-03-01", periods=3), "sleep_h": 7.0}).to_parquet(
            kid.tables / "daily.parquet")
        at = self.AppTest.from_string(VIEW)
        at.session_state["start"] = True
        at.run(timeout=30)
        self.assertFalse(at.exception)
        self.assertIn("DATA=kid VIEWER=coach", self.text(at))
        self.assertIn("coach_view", [e["event"] for e in audit.events("kid")])
        team.revoke(kid)
        at.run(timeout=30)
        self.assertIn("DATA=coach VIEWER=coach", self.text(at), "a withdrawal works on the next click")

    def test_someone_who_is_not_the_coach_cannot_look(self):
        consent("kid")
        team.give(tenant.get("kid"), "all")
        script = VIEW.replace('st.session_state[tenant.SESSION_KEY] = "coach"',
                              'st.session_state[tenant.SESSION_KEY] = "other"')
        at = self.AppTest.from_string(script)
        at.session_state["start"] = True
        at.run(timeout=30)
        self.assertIn("DATA=other VIEWER=other", self.text(at))


if __name__ == "__main__":
    unittest.main()
