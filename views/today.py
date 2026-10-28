"""Dziś: the morning answer on one screen -- what to run today and why.

Numbers and short lists with at most a sparkline; the full charts behind each
tile live on their own pages, one click away (the arrow in a tile's header).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import bento
import routing
import shell
import theme as tz
from running import coach, plan as planning, store, units
from views import run_common as rc

DAY_NAMES = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
ACTION_ICONS = {
    "jak w planie": ":material/check_circle:",
    "jak w planie, z kontrolą": ":material/visibility:",
    "zamień na spokojny": ":material/pause_circle:",
    "przesuń": ":material/event_repeat:",
    "propozycja": ":material/lightbulb:",
    "decyzja rano": ":material/schedule:",
}


def render() -> None:
    today = dt.date.today()
    bento.header("Dziś", f"{DAY_NAMES[today.weekday()].capitalize()}, {today:%d.%m.%Y}")

    days = shell.daily().sort_values("day")
    row = shell.latest_day()
    bento.kpis(row, shell.week_before(days), [
        ("readiness", "Readiness", ""),
        ("hrv_last_night", "HRV", "ms"),
        ("sleep_score", "Sen", ""),
        ("rhr", "Tętno spocz.", "bpm", "inverse"),
    ])
    stale = shell.days_since(row)
    if stale is not None and stale > 1:
        st.caption(f"Ostatnia noc w danych: {row['day']:%d.%m} ({stale} dni temu) — zsynchronizuj zegarek "
                   "i uruchom aktualizację, zanim zaufasz decyzji niżej.")

    frame = rc.runs()
    result = rc.current_forecast() if not frame.empty else {"status": "insufficient"}
    active = rc.active_plan(today)
    suggestion = coach.next_session(active, frame, days, result, today) if not frame.empty else None

    left, right = bento.row(2, 2)
    with left:
        with bento.tile("Trening na dziś", key="today_decision", terms=["today_decision", "run_kind"]):
            _decision(active, suggestion, today)
        with bento.tile("Obciążenie", key="today_load", terms=["run_ratio", "quality_sessions"]) as t:
            _load(t, suggestion)
    with right, bento.tile("Regeneracja", rows=2, key="today_recovery", terms=["hrv", "deviation"]) as t:
        _recovery(t, days, suggestion)

    with bento.tile("Ten tydzień", key="today_week", caption=_week_note(active)):
        if frame.empty:
            st.caption("Brak tabel biegowych.")
        else:
            rc.week_strip(active, frame, today)

    left, right = bento.row(2, 2)
    with left, bento.tile("Prognoza", key="today_forecast", terms=["realistic", "interval80"]) as t:
        _forecast(t, result, active)
    with right, bento.tile("Ostatnie biegi", key="today_recent", terms=["run_kind"]):
        _recent(frame)


def _week_note(active: dict | None) -> str:
    if active is None:
        return "Bez planu — pokazuję, co faktycznie przebiegłeś."
    race = dt.date.fromisoformat(active["request"]["race_date"])
    return (f"Plan „{active.get('name', active['id'])}” — start za {(race - dt.date.today()).days} dni. "
            "✓ wykonany · ≈ zmodyfikowany · ✗ pominięty · · zaplanowany.")


def _decision(active: dict | None, suggestion: dict | None, today: dt.date) -> None:
    if suggestion is None or not suggestion.get("session"):
        st.caption("W planie nie ma już sesji." if active else "Brak danych biegowych do propozycji.")
        if active is None and st.button("Ułóż plan →", key="today_new_plan"):
            routing.goto("plan")
        return
    session = suggestion["session"]
    date = dt.date.fromisoformat(session["date"])
    action = suggestion["action"]
    if suggestion.get("today", True):
        st.markdown(f"**{session.get('title')}** · dziś · decyzja: **{action}**")
    else:
        st.markdown(f"**Dziś wolne.** Następnie: **{session.get('title')}** · {DAY_NAMES[date.weekday()]} {date:%d.%m}")
    details = [session.get("main", "")]
    if session.get("pace_lo") and "/km" not in session.get("main", ""):
        details.append(f"tempo {units.fmt_pace(session['pace_lo'], False)}–{units.fmt_pace(session.get('pace_hi'))}")
    if session.get("hr"):
        details.append(f"tętno {session['hr']}")
    st.markdown("<div class='tile-caption'>" + " · ".join(d for d in details if d) + "</div>", unsafe_allow_html=True)
    if suggestion["reasons"]:
        st.markdown(f"<div class='tile-caption'>{suggestion['reasons'][0]}</div>", unsafe_allow_html=True)

    # Changing a later session on tonight's numbers would act on data the next night replaces.
    if suggestion["source"] != "plan" or active is None or not suggestion.get("today", True):
        return
    hard = session["type"] in planning.HARD_TYPES and session["type"] != "race"
    columns = st.columns(2)
    if hard and columns[0].button("Zamień na spokojny", key="today_soften", width="stretch",
                                  icon=ACTION_ICONS["zamień na spokojny"],
                                  type="primary" if action == "zamień na spokojny" else "secondary"):
        _apply(planning.soften, active, session["id"], today)
    if columns[1].button("Przesuń o dzień", key="today_postpone", width="stretch",
                         icon=ACTION_ICONS["przesuń"], type="primary" if action == "przesuń" else "secondary"):
        _apply(planning.postpone, active, session["id"], today)


def _apply(change, active: dict, session_id: str, today: dt.date) -> None:
    try:
        store.save_plan(change(active, session_id, today=today))
    except ValueError as error:
        st.warning(str(error))
    else:
        st.rerun()


def _recovery(tile, days: pd.DataFrame, suggestion: dict | None) -> None:
    with tile.header:
        if st.button("", icon=":material/arrow_forward:", type="tertiary", key="today_to_recovery",
                     help="Strona Regeneracja"):
            routing.goto("regeneracja")
    recovery = (suggestion or {}).get("recovery") or coach.recovery_signals(days, dt.date.today())
    flags = recovery.get("flags", [])
    if not recovery.get("available"):
        st.caption("Brak nocy z danymi.")
    elif flags:
        bento.bullets(flags)
    else:
        st.caption("Brak sygnałów przeciw: HRV, sen i tętno spoczynkowe w normie.")
    recent = days[days["day"] > days["day"].max() - pd.Timedelta(days=21)]
    for label, column, smooth, band, unit in (
        ("HRV, 21 dni", "hrv_last_night", "hrv_last_night_roll7", ("hrv_baseline_low", "hrv_baseline_high"), "ms"),
        ("Tętno spoczynkowe, 21 dni", "rhr", "rhr_roll7", None, "bpm"),
    ):
        figure = tz.spark(recent, "day", column, smooth=smooth, band=band, unit=unit, height=110)
        if figure is not None:
            st.markdown(f"<div class='tile-caption'>{label}</div>", unsafe_allow_html=True)
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False},
                            key=f"today_spark_{column}")


def _load(tile, suggestion: dict | None) -> None:
    with tile.header:
        if st.button("", icon=":material/arrow_forward:", type="tertiary", key="today_to_load",
                     help="Strona Obciążenie biegowe"):
            routing.goto("obciazenie-biegowe")
    load = (suggestion or {}).get("load")
    if not load:
        st.caption("Brak danych.")
        return
    columns = st.columns(3)
    columns[0].metric("km w 7 dni", f"{load['km_7d']:.0f}")
    columns[1].metric("iloraz 7/28", f"{load['ratio']:.2f}" if load.get("ratio") is not None else "—")
    columns[2].metric("mocne w 7 d", f"{load.get('hard_7d', 0)}")
    since = []
    for key, label in (("days_since_hard", "mocny"), ("days_since_long", "długi"), ("days_since_run", "ostatni bieg")):
        value = load.get(key)
        since.append(f"{label}: {'—' if value is None else ('dziś' if value == 0 else f'{value} d temu')}")
    st.markdown(f"<div class='tile-caption'>średnio {load['km_28d_weekly']:.0f} km/tydz. (28 d) · "
                + " · ".join(since) + "</div>", unsafe_allow_html=True)


def _forecast(tile, result: dict, active: dict | None) -> None:
    with tile.header:
        if st.button("", icon=":material/arrow_forward:", type="tertiary", key="today_to_forecast",
                     help="Strona Prognoza"):
            routing.goto("prognoza")
    keys = [active["request"]["distance"]] if active else ["5k", "10k"]
    if result.get("status") == "ok" and active is None:
        keys = [k for k in ("5k", "10k") if k in result["distances"]]
    rc.forecast_tiles(result, keys, compact=True)
    if active and active["request"].get("goal_s"):
        st.caption(f"Cel: {units.fmt_time(active['request']['goal_s'])}")


def _recent(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.caption("Brak biegów.")
        return
    for run in frame.sort_values("start_local", ascending=False).head(3).itertuples(index=False):
        label = (f"{run.start_local:%d.%m} · {rc.kind_label(run.kind)} · {run.distance_km:.1f} km · "
                 f"{units.fmt_pace(run.pace_min_km, False)}")
        if st.button(label, key=f"today_run_{run.activity_id}", type="tertiary"):
            routing.open_run(int(run.activity_id))
