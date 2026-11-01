"""Menu entries that hold two views behind one switch.

Each pair answers one question from two sides, so it has one place in the
menu: the plan and the races it builds toward, running load and the load of
every sport, today's readiness and the disciplines behind it. The views stay
their own modules; this file only picks one. ``bento.switch`` explains how
another page opens a given view.
"""

from __future__ import annotations

import bento
import i18n
from views import form, run_load, run_plan, run_races, sport, sport_disciplines

PLAN, LOAD, SPORT = "plan_view", "load_view", "sport_view"


def plan() -> None:
    choice = bento.switch(PLAN, {"plan": i18n.view("plan"), "races": i18n.view("zawody")})
    (run_races if choice == "races" else run_plan).render()


def load() -> None:
    choice = bento.switch(LOAD, {"run": i18n.view("obciazenie-biegowe"), "all": i18n.view("forma")})
    (form if choice == "all" else run_load).render()


def sports() -> None:
    choice = bento.switch(SPORT, {"today": i18n.view("sport"), "disciplines": i18n.view("dyscypliny")})
    (sport_disciplines if choice == "disciplines" else sport).render()
