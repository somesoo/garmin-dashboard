"""Races and goals: upcoming starts with their forecast, past starts linked to runs."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bento
import i18n
import routing
import theme as tz
from running import forecast, plan as planning, store, units
from views import run_common as rc

def _priority_help() -> str:
    return i18n.tr(pl="A — start docelowy sezonu, B — ważny sprawdzian, C — start treningowy.",
                   en="A — the season's target race, B — an important test, C — a training race.")


def _goal_status(code: str) -> str:
    """``forecast.GOAL_STATUS`` in the interface language."""
    tr = i18n.tr
    return {"none": tr(pl="bez celu czasowego", en="no time goal"),
            "now": tr(pl="w zasięgu już dziś", en="within reach today"),
            "plan": tr(pl="realny po planie", en="realistic after the plan"),
            "ambitious": tr(pl="ambitny", en="ambitious"),
            "stretch": tr(pl="bardzo ambitny", en="very ambitious")}.get(code, code)


def render() -> None:
    bento.header(
        i18n.page("zawody"),
        i18n.tr(pl="Starty zapisane tutaj trafiają do prognozy („po planie”), do planu i do briefu dla asystenta. "
                   "Dane leżą w `data/coach/races.json` — prywatnie, poza gitem.",
                en="Races saved here feed the forecast (“after the plan”), the plan and the assistant's brief. "
                   "The data sits in `data/coach/races.json` — private, outside git."),
    )
    frame = rc.guard()
    if frame is None:
        return
    races = store.races()
    today = dt.date.today()
    upcoming = [r for r in races if r["date"] >= today.isoformat()]
    past = [r for r in races if r["date"] < today.isoformat()]

    result = rc.current_forecast()
    if not upcoming:
        st.info(i18n.tr(pl="Brak nadchodzących startów. Dodaj pierwszy poniżej.",
                        en="No upcoming races. Add the first one below."))
    for race in upcoming:
        _race_card(race, result, today)
    if past:
        left, right = bento.row(2, 2)
        with left:
            _add_form()
        with right:
            _past(past, frame)
    else:
        _add_form()


def _race_card(race: dict, result: dict, today: dt.date) -> None:
    date = dt.date.fromisoformat(race["date"])
    days = (date - today).days
    priority = race.get("priority", "A")
    caption = i18n.tr(pl=f"{date:%d.%m.%Y} · za {days} dni ({days / 7:.1f} tyg.) · priorytet {priority}",
                      en=f"{date:%d.%m.%Y} · in {days} days ({days / 7:.1f} wk) · priority {priority}")
    with bento.panel(
        f"{race['name']} — {rc.race_label(race['distance'])}", key=f"race_{race['id']}",
        caption=caption + (f" · {race['notes']}" if race.get("notes") else ""),
    ):
        left, right = st.columns(2, gap="medium")
        with left:
            _race_numbers(race, result)
        with right:
            item = result["distances"].get(race["distance"]) if result.get("status") == "ok" else None
            _trend(race, item)


def _race_numbers(race: dict, result: dict) -> None:
    item = result["distances"].get(race["distance"]) if result.get("status") == "ok" else None
    goal = race.get("goal_s")
    tr = i18n.tr
    columns = st.columns(4)
    columns[0].metric(tr(pl="Cel", en="Goal"), units.fmt_time(goal) if goal else "—",
                      help=tr(pl="Bez celu czasowego plan używa tempa z prognozy.",
                              en="Without a time goal the plan uses the forecast pace."))
    if item:
        gap = units.fmt_delta(item.realistic_s - goal) if goal else ""
        columns[1].metric(tr(pl="Prognoza dziś", en="Forecast today"), units.fmt_time(item.realistic_s),
                          tr(pl=f"{gap} do celu", en=f"{gap} to the goal") if goal else None,
                          delta_color="inverse")
        columns[2].metric(tr(pl="Po planie", en="After the plan"), units.fmt_time(item.target_s) if item.target_s
                          else "—",
                          help=tr(pl="Zakłada realizację planu: ~1 VDOT na 5 tygodni i przygotowanie, które plan "
                                     "osiąga.",
                                  en="Assumes the plan is followed: ~1 VDOT per 5 weeks and the preparation the "
                                     "plan reaches."))
        status = forecast.goal_status(item, goal)
        columns[3].metric(tr(pl="Status celu", en="Goal status"), _goal_status(status))
        band, sure = f"{units.fmt_time(item.low_s)}–{units.fmt_time(item.high_s)}", rc.confidence_label(item.confidence)
        prep = item.prep
        long_run = f"{prep['long_km']:.0f}/{prep['long_need']:.0f} km"
        week = f"{prep['weekly_km']:.0f}/{prep['weekly_need']:.0f} km"
        text = tr(pl=f"Przedział dziś: {band}, pewność {sure}; przygotowanie do dystansu {prep['score']:.0%} "
                     f"(długi bieg {long_run}, tydzień {week}).",
                  en=f"Range today: {band}, confidence {sure}; preparation for the distance {prep['score']:.0%} "
                     f"(long run {long_run}, week {week}).")
        if goal:
            pace = units.fmt_pace(units.pace_from(goal, units.RACES[race["distance"]]))
            text += tr(pl=f" Tempo celu: {pace}.", en=f" Goal pace: {pace}.")
        st.caption(text)
    else:
        st.caption(result.get("reason") or tr(pl="Brak prognozy.", en="No forecast."))

    plans = store.plans_for(race["id"])
    if plans:
        active = plans[0]
        summary = planning.compliance(planning.match(active, rc.runs()))
        name, s = active.get("name"), summary
        if s.get("due"):
            km = f"{s['actual_km']:.0f}/{s['planned_km']:.0f} km"
            quality = f"{s['quality_done']}/{s['quality_due']}"
            st.caption(tr(
                pl=f"Plan „{name}”: wykonane {s['done']}, zmodyfikowane {s['modified']}, pominięte {s['skipped']} "
                   f"z {s['due']} sesji do dziś · kilometry {km} · jakość {quality}.",
                en=f"Plan “{name}”: done {s['done']}, modified {s['modified']}, skipped {s['skipped']} of {s['due']} "
                   f"sessions so far · kilometres {km} · quality {quality}.",
            ))
        else:
            st.caption(tr(pl=f"Plan „{name}” — pierwsza sesja jeszcze przed nami.",
                          en=f"Plan “{name}” — the first session is still ahead."))
    columns = st.columns(3)
    if columns[0].button("Plan →" if plans else tr(pl="Utwórz plan →", en="Create a plan →"),
                         key=f"race_plan_{race['id']}", width="stretch"):
        routing.goto("plan", plan_race_request=race["id"])
    with columns[1].popover(tr(pl="Edytuj", en="Edit"), width="stretch"):
        _race_form(race, key=f"edit_{race['id']}")
    if columns[2].button(tr(pl="Usuń", en="Delete"), key=f"race_delete_{race['id']}", width="stretch"):
        store.delete_race(race["id"])
        st.rerun()


def _trend(race: dict, item) -> None:
    history = rc.history()
    if history.empty:
        return
    view = history[(history["distance"] == race["distance"])
                   & (history["day"] >= pd.Timestamp(dt.date.today()) - pd.Timedelta(days=180))]
    if len(view) < 3:
        return
    tr = i18n.tr
    t = tz.tokens()
    fig = go.Figure()
    name = tr(pl="prognoza", en="forecast")
    fig.add_scatter(x=view["day"], y=view["realistic_s"] / 60, mode="lines", name=name,
                    line=dict(width=2.4, color=t["series"][0]),
                    customdata=view["realistic_s"].map(units.fmt_time),
                    hovertemplate=f"%{{customdata}}<extra>{name}</extra>")
    if race.get("goal_s"):
        goal = units.fmt_time(race["goal_s"])
        fig.add_hline(y=race["goal_s"] / 60, line=dict(color=t["series"][1], width=1.4, dash="dash"),
                      annotation_text=tr(pl=f"cel {goal}", en=f"goal {goal}"),
                      annotation_font=dict(size=11, color=t["series"][1]), annotation_position="top left")
    fig.update_layout(**tz.base_layout(legend=False, height=260))
    values = pd.concat([view["realistic_s"] / 60, pd.Series([(race.get("goal_s") or view["realistic_s"].iloc[-1]) / 60])])
    low, high = float(values.min()), float(values.max())
    pad = max(0.5, (high - low) * 0.1)
    fig.update_yaxes(range=[high + pad, low - pad], tickformat=".0f", title_text="min")
    note = tr(pl="Prognoza z ostatnich 6 miesięcy; wyżej = szybciej.", en="Forecast over the last 6 months; higher = "
                                                                           "faster.")
    st.markdown(f"<div class='tile-caption'>{note}</div>", unsafe_allow_html=True)
    st.plotly_chart(tz.local_dates(tz.style_axes(fig), view["day"]), width="stretch",
                    key=f"race_trend_{race['id']}", config={"displayModeBar": False})


def _race_form(race: dict | None, key: str) -> None:
    tr = i18n.tr
    race = race or {}
    with st.form(key, clear_on_submit=race == {}):
        name = st.text_input(tr(pl="Nazwa", en="Name"), race.get("name", ""))
        columns = st.columns(2)
        date = columns[0].date_input(
            tr(pl="Data", en="Date"),
            dt.date.fromisoformat(race["date"]) if race.get("date") else dt.date.today() + dt.timedelta(days=70),
            format="DD.MM.YYYY",
        )
        distance = columns[1].selectbox(tr(pl="Dystans", en="Distance"), list(units.RACES), format_func=rc.race_label,
                                        index=list(units.RACES).index(race.get("distance", "10k")))
        columns = st.columns(2)
        goal_text = columns[0].text_input(tr(pl="Cel czasowy (opcjonalnie)", en="Time goal (optional)"),
                                          units.fmt_time(race["goal_s"]) if race.get("goal_s") else "",
                                          placeholder=tr(pl="np. 49:30 albo 1:52:00", en="e.g. 49:30 or 1:52:00"))
        priority = columns[1].selectbox(tr(pl="Priorytet", en="Priority"), store.PRIORITIES,
                                        index=store.PRIORITIES.index(race.get("priority", "A")), help=_priority_help())
        notes = st.text_input(tr(pl="Notatki", en="Notes"), race.get("notes", ""),
                              placeholder=tr(pl="trasa, przewyższenia, pogoda…", en="course, elevation, weather…"))
        if st.form_submit_button(tr(pl="Zapisz", en="Save")):
            goal = units.parse_time(goal_text) if goal_text.strip() else None
            if goal_text.strip() and goal is None:
                st.error(tr(pl="Nie rozumiem czasu — wpisz mm:ss albo g:mm:ss.",
                            en="I cannot read that time — enter mm:ss or h:mm:ss."))
                return
            try:
                store.save_race({**race, "name": name.strip(), "date": date.isoformat(), "distance": distance,
                                 "goal_s": goal, "priority": priority, "notes": notes.strip()})
            except ValueError as error:
                st.error(str(error))
                return
            st.rerun()


def _add_form() -> None:
    with bento.panel(i18n.tr(pl="Dodaj start", en="Add a race"), key="race_add_panel",
                     caption=i18n.tr(pl="Wiele startów naraz to norma: A na końcu sezonu, B i C po drodze.",
                                     en="Several races at once are the norm: A at the end of the season, B and C on "
                                        "the way.")):
        _race_form(None, key="race_add")


def _past(past: list[dict], frame: pd.DataFrame) -> None:
    with bento.panel(
        i18n.tr(pl="Starty, które już się odbyły", en="Races already run"), key="races_past",
        caption=i18n.tr(pl="Powiąż start z biegiem: wynik stanie się najmocniejszą kotwicą prognozy.",
                        en="Link a race to a run: the result becomes the forecast's strongest anchor."),
    ):
        _past_rows(past, frame)


def _past_rows(past: list[dict], frame: pd.DataFrame) -> None:
    for race in sorted(past, key=lambda r: r["date"], reverse=True):
        date = pd.Timestamp(race["date"])
        nearby = frame[(frame["day"] >= date - pd.Timedelta(days=1)) & (frame["day"] <= date + pd.Timedelta(days=1))]
        options = [None] + nearby["activity_id"].astype(int).tolist()

        def describe(activity_id):
            if activity_id is None:
                return i18n.tr(pl="— nie powiązano —", en="— not linked —")
            row = nearby[nearby["activity_id"] == activity_id].iloc[0]
            return f"{row['start_local']:%d.%m %H:%M} · {row['distance_km']:.2f} km · {units.fmt_time(row['duration_min'] * 60)}"

        current = race.get("result_activity_id")
        index = options.index(int(current)) if current and int(current) in options else 0
        columns = st.columns([3, 2])
        goal = i18n.tr(pl=" · cel ", en=" · goal ") + units.fmt_time(race["goal_s"]) if race.get("goal_s") else ""
        columns[0].markdown(f"**{race['name']}** — {rc.race_label(race['distance'])}, {date:%d.%m.%Y}{goal}")
        chosen = columns[1].selectbox(i18n.tr(pl="Bieg", en="Run"), options, index=index, format_func=describe,
                                      key=f"race_result_{race['id']}", label_visibility="collapsed")
        if (chosen or None) != (int(current) if current else None):
            store.save_race({**race, "result_activity_id": chosen})
            with st.spinner(i18n.tr(pl="Przeliczam tabele biegowe…", en="Rebuilding the running tables…")):
                from running import pipeline

                pipeline.rebuild()
            st.cache_data.clear()
            st.rerun()
        if not len(nearby):
            st.caption(i18n.tr(pl="Brak biegu w dniu startu (±1 dzień) — może nie był zsynchronizowany.",
                               en="No run on the race day (±1 day) — maybe it was not synced."))
