"""Dzień: the start page -- the day in facts around a run.

A hero, not a mosaic: the run of the day (or the last one, faded, while today's
is still ahead) fills the middle, and what happened -- the run's key stretch,
its stops, last night against the week, the body this morning, the next race,
a piece of trivia -- is laid out in the free space around the track by the
browser (``ui/components/hero/``). The facts themselves come from ``hero.py``;
nothing here suggests what to do, that is *Dziś* one entry below.

The component is static, like the globe: the payload is built once per
warehouse build, day and language, and a click on a fact comes back as a page
to open.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from analysis import hero
from core import i18n
from ui import routing
from ui import shell
from ui import theme as tz
from running import store
from views import hubs, run_common as rc

COMPONENT = Path(__file__).resolve().parents[1] / "ui" / "components" / "hero"
_component = components.declare_component("garmin_hero", path=str(COMPONENT))


def _session(active: dict[str, Any] | None, today: dt.date) -> dict[str, Any] | None:
    """Today's planned run, if the plan has one (strength and rest are not runs)."""
    if not active:
        return None
    for session in active.get("sessions", []):
        if session.get("date") == today.isoformat() and session.get("type") not in ("rest", "strength"):
            return session
    return None


@st.cache_data(show_spinner=False)
def _payload(build: str, day: str, lang: str, stamp: str) -> dict[str, Any]:
    """The facts for one day; keyed by the warehouse build, the day, the language and the coach files."""
    today = dt.date.fromisoformat(day)
    runs = rc.runs()
    run, _ = hero.pick_run(runs, today)
    narrowed: dict[str, pd.DataFrame] = {}
    route = pd.DataFrame()
    if run is not None:
        activity = int(run["activity_id"])
        for name in ("run_splits", "run_stops", "run_efforts", "run_laps"):
            frame = shell.table(name)
            narrowed[name] = frame[frame["activity_id"] == activity] if not frame.empty else frame
        route = shell.query(f"SELECT seq, lat, lon, hr, distance_km FROM routes WHERE activity_id = {activity}")
    active = rc.active_plan(today)
    return hero.build(
        today, runs=runs, activities=shell.table("activities"), daily=shell.daily(),
        splits=narrowed.get("run_splits", pd.DataFrame()), stops=narrowed.get("run_stops", pd.DataFrame()),
        efforts=narrowed.get("run_efforts", pd.DataFrame()), laps=narrowed.get("run_laps", pd.DataFrame()),
        circadian=shell.table("circadian"), route=route, races=rc.upcoming_races(today),
        session=_session(active, today), has_plan=active is not None,
    )


def _theme() -> dict[str, Any]:
    t = tz.tokens()
    status = t["status"]
    # HR zones Z1..Z5: calm blues for the easy zones, the warning and critical
    # status colours for the two hard ones -- five neighbouring blues could not
    # be told apart on a thin line.
    zones = [t["sequential"][2], t["sequential"][4], t["sequential"][6], status["warning"], status["critical"]]
    return {"page": "#000000", "ink": t["ink"], "muted": t["muted"], "faint": t["axis"], "edge": t["axis"],
            "accent": t["sequential"][5], "zones": zones}


def _text() -> dict[str, str]:
    tr = i18n.tr
    return {"legend": tr(pl="strefy tętna", en="heart-rate zones"), "stop": tr(pl="postój", en="stop"),
            "reroll": tr(pl="↻ inna ciekawostka", en="↻ another one")}


def _open(go: dict[str, Any]) -> None:
    target = go.get("page")
    if target == "bieg" and go.get("activity"):
        routing.open_run(int(go["activity"]))
    elif target == "plan" and go.get("view"):
        routing.goto_view("plan", hubs.PLAN, str(go["view"]))
    elif target:
        routing.goto(str(target))


def render() -> None:
    today = dt.date.today()
    payload = _payload(shell.build_id(), today.isoformat(), i18n.lang(), rc.store_stamp() + store.segments_stamp())
    clicked = _component(payload=payload, theme=_theme(), text=_text(),
                         token=f"{shell.build_id()}-{today.isoformat()}-{i18n.lang()}", key="hero", default=None)
    # The component keeps its value across reruns; the counter tells a new click from the same value again.
    if clicked and int(clicked.get("clicks", 0)) > st.session_state.get("hero_clicks_seen", 0):
        st.session_state["hero_clicks_seen"] = int(clicked["clicks"])
        _open(clicked.get("go") or {})
