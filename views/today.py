"""Dziś: the morning answer on one screen -- what to run today and why.

Numbers and short lists with at most a sparkline; the full charts behind each
tile live on their own pages, one click away (the arrow in a tile's header).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import shell
import theme as tz
from running import coach, plan as planning, store, units
from views import run_common as rc

# coach.next_session names its decision with these codes (Polish, as data).
SOFTEN, POSTPONE = "zamień na spokojny", "przesuń"  # i18n: key
ACTION_ICONS = {
    "jak w planie": ":material/check_circle:",
    "jak w planie, z kontrolą": ":material/visibility:",  # i18n: key
    SOFTEN: ":material/pause_circle:",
    POSTPONE: ":material/event_repeat:",
    "propozycja": ":material/lightbulb:",
    "decyzja rano": ":material/schedule:",
}


def render() -> None:
    tr = i18n.tr
    today = dt.date.today()
    bento.header(i18n.page("dzis"), f"{i18n.weekdays(long=True)[today.weekday()].capitalize()}, {today:%d.%m.%Y}")

    days = shell.daily().sort_values("day")
    row = shell.latest_day()
    bento.kpis(row, shell.week_before(days), [
        ("readiness", "Readiness", ""),
        ("hrv_last_night", "HRV", "ms"),
        ("sleep_score", tr(pl="Sen", en="Sleep"), ""),
        ("rhr", tr(pl="Tętno spocz.", en="Resting HR"), "bpm", "inverse"),
    ])
    stale = shell.days_since(row)
    if stale is not None and stale > 1:
        st.caption(tr(pl=f"Ostatnia noc w danych: {row['day']:%d.%m} ({stale} dni temu) — zsynchronizuj zegarek "
                         "i uruchom aktualizację, zanim zaufasz decyzji niżej.",
                      en=f"Last night in the data: {row['day']:%d.%m} ({stale} days ago) — sync the watch and run "
                         "an update before you trust the decision below."))

    frame = rc.runs()
    result = rc.current_forecast() if not frame.empty else {"status": "insufficient"}
    active = rc.active_plan(today)
    suggestion = coach.next_session(active, frame, days, result, today) if not frame.empty else None

    left, right = bento.row(2, 2)
    with left:
        with bento.tile(tr(pl="Trening na dziś", en="Today's session"), key="today_decision",
                        terms=["today_decision", "run_kind"]):
            _decision(active, suggestion, today)
        with bento.tile(tr(pl="Obciążenie", en="Load"), key="today_load", terms=["run_ratio", "quality_sessions"]) as t:
            _load(t, suggestion)
    with right, bento.tile(i18n.page("regeneracja"), rows=2, key="today_recovery", terms=["hrv", "deviation"]) as t:
        _recovery(t, days, suggestion)

    with bento.tile(tr(pl="Ten tydzień", en="This week"), key="today_week", caption=_week_note(active)):
        if frame.empty:
            st.caption(tr(pl="Brak tabel biegowych.", en="No running tables."))
        else:
            rc.week_strip(active, frame, today)

    left, right = bento.row(2, 2)
    with left, bento.tile(tr(pl="Prognoza", en="Forecast"), key="today_forecast",
                          terms=["realistic", "interval80"]) as t:
        _forecast(t, result, active)
    with right, bento.tile(tr(pl="Ostatnie biegi", en="Recent runs"), key="today_recent", terms=["run_kind"]):
        _recent(frame)


def _week_note(active: dict | None) -> str:
    tr = i18n.tr
    if active is None:
        return tr(pl="Bez planu — pokazuję, co faktycznie przebiegłeś.", en="No plan — showing what you actually ran.")
    race = dt.date.fromisoformat(active["request"]["race_date"])
    name, left = active.get("name", active["id"]), (race - dt.date.today()).days
    return tr(pl=f"Plan „{name}” — start za {left} dni. ✓ wykonany · ≈ zmodyfikowany · ✗ pominięty · · zaplanowany.",
              en=f"Plan “{name}” — race in {left} days. ✓ done · ≈ modified · ✗ skipped · · planned.")


def _decision(active: dict | None, suggestion: dict | None, today: dt.date) -> None:
    tr = i18n.tr
    if suggestion is None or not suggestion.get("session"):
        st.caption(tr(pl="W planie nie ma już sesji.", en="There are no sessions left in the plan.") if active
                   else tr(pl="Brak danych biegowych do propozycji.", en="No running data for a suggestion."))
        if active is None and st.button(tr(pl="Ułóż plan →", en="Build a plan →"), key="today_new_plan"):
            routing.goto("plan")
        return
    session = suggestion["session"]
    date = dt.date.fromisoformat(session["date"])
    action = suggestion["action"]
    title = session.get("title")
    if suggestion.get("today", True):
        shown = rc.action_label(action)
        st.markdown(tr(pl=f"**{title}** · dziś · decyzja: **{shown}**", en=f"**{title}** · today · decision: **{shown}**"))
    else:
        when = f"{i18n.weekdays(long=True)[date.weekday()]} {date:%d.%m}"
        st.markdown(tr(pl=f"**Dziś wolne.** Następnie: **{title}** · {when}",
                       en=f"**Rest day today.** Next: **{title}** · {when}"))
    details = [session.get("main", "")]
    if session.get("pace_lo") and "/km" not in session.get("main", ""):
        band = f"{units.fmt_pace(session['pace_lo'], False)}–{units.fmt_pace(session.get('pace_hi'))}"
        details.append(tr(pl=f"tempo {band}", en=f"pace {band}"))
    if session.get("hr"):
        details.append(tr(pl=f"tętno {session['hr']}", en=f"HR {session['hr']}"))
    st.markdown("<div class='tile-caption'>" + " · ".join(d for d in details if d) + "</div>", unsafe_allow_html=True)
    if suggestion["reasons"]:
        st.markdown(f"<div class='tile-caption'>{suggestion['reasons'][0]}</div>", unsafe_allow_html=True)

    # Changing a later session on tonight's numbers would act on data the next night replaces.
    if suggestion["source"] != "plan" or active is None or not suggestion.get("today", True):
        return
    hard = session["type"] in planning.HARD_TYPES and session["type"] != "race"
    columns = st.columns(2)
    if hard and columns[0].button(tr(pl="Zamień na spokojny", en="Swap for an easy run"), key="today_soften",
                                  width="stretch", icon=ACTION_ICONS[SOFTEN],
                                  type="primary" if action == SOFTEN else "secondary"):
        _apply(planning.soften, active, session["id"], today)
    if columns[1].button(tr(pl="Przesuń o dzień", en="Move by a day"), key="today_postpone", width="stretch",
                         icon=ACTION_ICONS[POSTPONE], type="primary" if action == POSTPONE else "secondary"):
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
                     help=i18n.page("regeneracja")):
            routing.goto("regeneracja")
    tr = i18n.tr
    recovery = (suggestion or {}).get("recovery") or coach.recovery_signals(days, dt.date.today())
    flags = recovery.get("flags", [])
    if not recovery.get("available"):
        st.caption(tr(pl="Brak nocy z danymi.", en="No nights with data."))
    elif flags:
        bento.bullets(flags)
    else:
        st.caption(tr(pl="Brak sygnałów przeciw: HRV, sen i tętno spoczynkowe w normie.",
                      en="No signals against: HRV, sleep and resting heart rate within normal."))
    recent = days[days["day"] > days["day"].max() - pd.Timedelta(days=21)]
    for label, column, smooth, band, unit in (
        (tr(pl="HRV, 21 dni", en="HRV, 21 days"), "hrv_last_night", "hrv_last_night_roll7",
         ("hrv_baseline_low", "hrv_baseline_high"), "ms"),
        (tr(pl="Tętno spoczynkowe, 21 dni", en="Resting heart rate, 21 days"), "rhr", "rhr_roll7", None, "bpm"),
    ):
        figure = tz.spark(recent, "day", column, smooth=smooth, band=band, unit=unit, height=110)
        if figure is not None:
            st.markdown(f"<div class='tile-caption'>{label}</div>", unsafe_allow_html=True)
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False},
                            key=f"today_spark_{column}")


def _load(tile, suggestion: dict | None) -> None:
    with tile.header:
        if st.button("", icon=":material/arrow_forward:", type="tertiary", key="today_to_load",
                     help=i18n.page("obciazenie-biegowe")):
            routing.goto("obciazenie-biegowe")
    tr = i18n.tr
    load = (suggestion or {}).get("load")
    if not load:
        st.caption(tr(pl="Brak danych.", en="No data."))
        return
    columns = st.columns(3)
    columns[0].metric(tr(pl="km w 7 dni", en="km in 7 days"), f"{load['km_7d']:.0f}")
    columns[1].metric(tr(pl="iloraz 7/28", en="ratio 7/28"), f"{load['ratio']:.2f}" if load.get("ratio") is not None
                      else "—")
    columns[2].metric(tr(pl="mocne w 7 d", en="hard in 7 d"), f"{load.get('hard_7d', 0)}")
    since = []
    for key, label in (("days_since_hard", tr(pl="mocny", en="hard")), ("days_since_long", tr(pl="długi", en="long")),
                       ("days_since_run", tr(pl="ostatni bieg", en="last run"))):
        value = load.get(key)
        when = "—" if value is None else (tr(pl="dziś", en="today") if value == 0
                                          else tr(pl=f"{value} d temu", en=f"{value} d ago"))
        since.append(f"{label}: {when}")
    weekly = tr(pl=f"średnio {load['km_28d_weekly']:.0f} km/tydz. (28 d)",
                en=f"{load['km_28d_weekly']:.0f} km/week on average (28 d)")
    st.markdown(f"<div class='tile-caption'>{weekly} · " + " · ".join(since) + "</div>", unsafe_allow_html=True)


def _forecast(tile, result: dict, active: dict | None) -> None:
    with tile.header:
        if st.button("", icon=":material/arrow_forward:", type="tertiary", key="today_to_forecast",
                     help=i18n.page("prognoza")):
            routing.goto("prognoza")
    keys = [active["request"]["distance"]] if active else ["5k", "10k"]
    if result.get("status") == "ok" and active is None:
        keys = [k for k in ("5k", "10k") if k in result["distances"]]
    rc.forecast_tiles(result, keys, compact=True)
    if active and active["request"].get("goal_s"):
        goal = units.fmt_time(active["request"]["goal_s"])
        st.caption(i18n.tr(pl=f"Cel: {goal}", en=f"Goal: {goal}"))


def _recent(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.caption(i18n.tr(pl="Brak biegów.", en="No runs."))
        return
    for run in frame.sort_values("start_local", ascending=False).head(3).itertuples(index=False):
        label = (f"{run.start_local:%d.%m} · {rc.kind_label(run.kind)} · {run.distance_km:.1f} km · "
                 f"{units.fmt_pace(run.pace_min_km, False)}")
        if st.button(label, key=f"today_run_{run.activity_id}", type="tertiary"):
            routing.open_run(int(run.activity_id))
