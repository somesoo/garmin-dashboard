"""Dziś: the morning answer on one screen -- what to run today and why.

The one page laid out as a grid of cards rather than a document. Every card is
a number or a short list with at most a sparkline; nothing here is read off an
axis, so the half-width columns do not truncate any time scale. The full
charts behind each card live on their own pages, one click away.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

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
}


def render() -> None:
    today = dt.date.today()
    st.title("Dziś")
    st.caption(f"{DAY_NAMES[today.weekday()].capitalize()}, {today:%d.%m.%Y}")

    days = shell.daily().sort_values("day")
    row = shell.latest_day()
    shell.metrics(row, shell.week_before(days), [
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

    left, right = st.columns([3, 2], gap="medium")
    with left.container(border=True, key="card_today"):
        _decision(active, suggestion, today)
    with right.container(border=True, key="card_recovery"):
        _recovery(days, suggestion)

    with st.container(border=True, key="card_week"):
        shell.sub("Ten tydzień", _week_note(active))
        if frame.empty:
            st.caption("Brak tabel biegowych.")
        else:
            rc.week_strip(active, frame, today)

    load, outlook, recent = st.columns(3, gap="medium")
    with load.container(border=True, key="card_load"):
        _load(suggestion)
    with outlook.container(border=True, key="card_forecast"):
        _forecast(result, active)
    with recent.container(border=True, key="card_recent"):
        _recent(frame)


def _week_note(active: dict | None) -> str:
    if active is None:
        return "Bez planu — pokazuję, co faktycznie przebiegłeś."
    race = dt.date.fromisoformat(active["request"]["race_date"])
    return (f"Plan „{active.get('name', active['id'])}” — start za {(race - dt.date.today()).days} dni. "
            "✓ wykonany · ≈ zmodyfikowany · ✗ pominięty · · zaplanowany.")


def _decision(active: dict | None, suggestion: dict | None, today: dt.date) -> None:
    shell.sub("Trening na dziś", terms=["today_decision", "run_kind"])
    if suggestion is None or not suggestion.get("session"):
        st.caption("W planie nie ma już sesji." if active else "Brak danych biegowych do propozycji.")
        if active is None and st.button("Ułóż plan →", key="today_new_plan"):
            routing.goto("plan")
        return
    session = suggestion["session"]
    date = dt.date.fromisoformat(session["date"])
    when = "dziś" if date == today else f"{DAY_NAMES[date.weekday()]} {date:%d.%m}"
    st.markdown(f"#### {session.get('title')}")
    action = suggestion["action"]
    st.markdown(f"{when} · decyzja: **{action}**")
    details = [session.get("main", "")]
    if session.get("pace_lo"):
        details.append(f"tempo {units.fmt_pace(session['pace_lo'], False)}–{units.fmt_pace(session.get('pace_hi'))}"
                       + (f", tętno {session['hr']}" if session.get("hr") else ""))
    st.caption("  \n".join(d for d in details if d))
    for reason in suggestion["reasons"]:
        st.caption(reason)

    if suggestion["source"] != "plan" or active is None:
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


def _recovery(days: pd.DataFrame, suggestion: dict | None) -> None:
    shell.sub("Regeneracja", terms=["hrv", "deviation"])
    recovery = (suggestion or {}).get("recovery") or coach.recovery_signals(days, dt.date.today())
    flags = recovery.get("flags", [])
    if not recovery.get("available"):
        st.caption("Brak nocy z danymi.")
    elif flags:
        st.markdown("\n".join(f"- {flag}" for flag in flags))
    else:
        st.caption("Brak sygnałów przeciw: HRV, sen i tętno spoczynkowe w normie.")
    recent = days[days["day"] > days["day"].max() - pd.Timedelta(days=21)]
    for label, column, smooth, band, unit in (
        ("HRV, 21 dni", "hrv_last_night", "hrv_last_night_roll7", ("hrv_baseline_low", "hrv_baseline_high"), "ms"),
        ("Tętno spoczynkowe, 21 dni", "rhr", "rhr_roll7", None, "bpm"),
    ):
        figure = tz.spark(recent, "day", column, smooth=smooth, band=band, unit=unit)
        if figure is not None:
            st.caption(label)
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False, "staticPlot": False},
                            key=f"today_spark_{column}")
    if st.button("Regeneracja →", key="today_to_recovery", type="tertiary"):
        routing.goto("regeneracja")


def _load(suggestion: dict | None) -> None:
    shell.sub("Obciążenie", terms=["run_ratio", "quality_sessions"])
    load = (suggestion or {}).get("load")
    if not load:
        st.caption("Brak danych.")
        return
    columns = st.columns(2)
    columns[0].metric("km w 7 dni", f"{load['km_7d']:.0f}")
    columns[1].metric("iloraz 7/28", f"{load['ratio']:.2f}" if load.get("ratio") is not None else "—")
    since = []
    for key, label in (("days_since_hard", "mocny"), ("days_since_long", "długi"), ("days_since_run", "ostatni bieg")):
        value = load.get(key)
        since.append(f"{label}: {'—' if value is None else ('dziś' if value == 0 else f'{value} d temu')}")
    st.caption(f"Średnio {load['km_28d_weekly']:.0f} km/tydz. z 28 dni · mocne w 7 d: {load.get('hard_7d', 0)}  \n"
               + " · ".join(since))
    if st.button("Obciążenie biegowe →", key="today_to_load", type="tertiary"):
        routing.goto("obciazenie-biegowe")


def _forecast(result: dict, active: dict | None) -> None:
    shell.sub("Prognoza", terms=["realistic", "interval80"])
    keys = [active["request"]["distance"]] if active else ["5k", "10k"]
    if result.get("status") == "ok" and active is None:
        keys = [k for k in ("5k", "10k") if k in result["distances"]]
    rc.forecast_tiles(result, keys)
    if active and active["request"].get("goal_s"):
        st.caption(f"Cel: {units.fmt_time(active['request']['goal_s'])}")
    if st.button("Prognoza →", key="today_to_forecast", type="tertiary"):
        routing.goto("prognoza")


def _recent(frame: pd.DataFrame) -> None:
    shell.sub("Ostatnie biegi", terms=["run_kind"])
    if frame.empty:
        st.caption("Brak biegów.")
        return
    for run in frame.sort_values("start_local", ascending=False).head(3).itertuples(index=False):
        label = (f"{run.start_local:%d.%m} · {rc.kind_label(run.kind)} · {run.distance_km:.1f} km · "
                 f"{units.fmt_pace(run.pace_min_km, False)}")
        if st.button(label, key=f"today_run_{run.activity_id}", type="tertiary"):
            routing.open_run(int(run.activity_id))
