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

PRIORITY_HELP = "A — start docelowy sezonu, B — ważny sprawdzian, C — start treningowy."


def render() -> None:
    bento.header(
        i18n.page("zawody"),
        "Starty zapisane tutaj trafiają do prognozy („po planie”), do planu i do briefu dla asystenta. "
        "Dane leżą w `data/coach/races.json` — prywatnie, poza gitem.",
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
        st.info("Brak nadchodzących startów. Dodaj pierwszy poniżej.")
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
    with bento.panel(
        f"{race['name']} — {units.RACE_LABELS[race['distance']]}", key=f"race_{race['id']}",
        caption=f"{date:%d.%m.%Y} · za {days} dni ({days / 7:.1f} tyg.) · priorytet {race.get('priority', 'A')}"
        + (f" · {race['notes']}" if race.get("notes") else ""),
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
    columns = st.columns(4)
    columns[0].metric("Cel", units.fmt_time(goal) if goal else "—",
                      help="Bez celu czasowego plan używa tempa z prognozy.")
    if item:
        columns[1].metric("Prognoza dziś", units.fmt_time(item.realistic_s),
                          f"{units.fmt_delta(item.realistic_s - goal)} do celu" if goal else None,
                          delta_color="inverse")
        columns[2].metric("Po planie", units.fmt_time(item.target_s) if item.target_s else "—",
                          help="Zakłada realizację planu: ~1 VDOT na 5 tygodni i przygotowanie, które plan osiąga.")
        status = forecast.goal_status(item, goal)
        columns[3].metric("Status celu", forecast.GOAL_STATUS[status])
        st.caption(
            f"Przedział dziś: {units.fmt_time(item.low_s)}–{units.fmt_time(item.high_s)}, pewność {item.confidence}; "
            f"przygotowanie do dystansu {item.prep['score']:.0%} (długi bieg {item.prep['long_km']:.0f}/"
            f"{item.prep['long_need']:.0f} km, tydzień {item.prep['weekly_km']:.0f}/{item.prep['weekly_need']:.0f} km)."
            + (f" Tempo celu: {units.fmt_pace(units.pace_from(goal, units.RACES[race['distance']]))}." if goal else "")
        )
    else:
        st.caption(result.get("reason", "Brak prognozy."))

    plans = store.plans_for(race["id"])
    if plans:
        active = plans[0]
        summary = planning.compliance(planning.match(active, rc.runs()))
        if summary.get("due"):
            st.caption(
                f"Plan „{active.get('name')}”: wykonane {summary['done']}, zmodyfikowane {summary['modified']}, "
                f"pominięte {summary['skipped']} z {summary['due']} sesji do dziś · kilometry "
                f"{summary['actual_km']:.0f}/{summary['planned_km']:.0f} km · jakość "
                f"{summary['quality_done']}/{summary['quality_due']}."
            )
        else:
            st.caption(f"Plan „{active.get('name')}” — pierwsza sesja jeszcze przed nami.")
    columns = st.columns(3)
    if columns[0].button("Plan →" if plans else "Utwórz plan →", key=f"race_plan_{race['id']}", width="stretch"):
        routing.goto("plan", plan_race_request=race["id"])
    with columns[1].popover("Edytuj", width="stretch"):
        _race_form(race, key=f"edit_{race['id']}")
    if columns[2].button("Usuń", key=f"race_delete_{race['id']}", width="stretch"):
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
    t = tz.tokens()
    fig = go.Figure()
    fig.add_scatter(x=view["day"], y=view["realistic_s"] / 60, mode="lines", name="prognoza",
                    line=dict(width=2.4, color=t["series"][0]),
                    customdata=view["realistic_s"].map(units.fmt_time),
                    hovertemplate="%{customdata}<extra>prognoza</extra>")
    if race.get("goal_s"):
        fig.add_hline(y=race["goal_s"] / 60, line=dict(color=t["series"][1], width=1.4, dash="dash"),
                      annotation_text=f"cel {units.fmt_time(race['goal_s'])}",
                      annotation_font=dict(size=11, color=t["series"][1]), annotation_position="top left")
    fig.update_layout(**tz.base_layout(legend=False, height=260))
    values = pd.concat([view["realistic_s"] / 60, pd.Series([(race.get("goal_s") or view["realistic_s"].iloc[-1]) / 60])])
    low, high = float(values.min()), float(values.max())
    pad = max(0.5, (high - low) * 0.1)
    fig.update_yaxes(range=[high + pad, low - pad], tickformat=".0f", title_text="min")
    st.markdown("<div class='tile-caption'>Prognoza z ostatnich 6 miesięcy; wyżej = szybciej.</div>",
                unsafe_allow_html=True)
    st.plotly_chart(tz.local_dates(tz.style_axes(fig), view["day"]), width="stretch",
                    key=f"race_trend_{race['id']}", config={"displayModeBar": False})


def _race_form(race: dict | None, key: str) -> None:
    race = race or {}
    with st.form(key, clear_on_submit=race == {}):
        name = st.text_input("Nazwa", race.get("name", ""))
        columns = st.columns(2)
        date = columns[0].date_input(
            "Data", dt.date.fromisoformat(race["date"]) if race.get("date") else dt.date.today() + dt.timedelta(days=70),
            format="DD.MM.YYYY",
        )
        distance = columns[1].selectbox("Dystans", list(units.RACES), format_func=units.RACE_LABELS.get,
                                        index=list(units.RACES).index(race.get("distance", "10k")))
        columns = st.columns(2)
        goal_text = columns[0].text_input("Cel czasowy (opcjonalnie)", units.fmt_time(race["goal_s"]) if race.get("goal_s") else "",
                                          placeholder="np. 49:30 albo 1:52:00")
        priority = columns[1].selectbox("Priorytet", store.PRIORITIES,
                                        index=store.PRIORITIES.index(race.get("priority", "A")), help=PRIORITY_HELP)
        notes = st.text_input("Notatki", race.get("notes", ""), placeholder="trasa, przewyższenia, pogoda…")
        if st.form_submit_button("Zapisz"):
            goal = units.parse_time(goal_text) if goal_text.strip() else None
            if goal_text.strip() and goal is None:
                st.error("Nie rozumiem czasu — wpisz mm:ss albo g:mm:ss.")
                return
            try:
                store.save_race({**race, "name": name.strip(), "date": date.isoformat(), "distance": distance,
                                 "goal_s": goal, "priority": priority, "notes": notes.strip()})
            except ValueError as error:
                st.error(str(error))
                return
            st.rerun()


def _add_form() -> None:
    with bento.panel("Dodaj start", key="race_add_panel",
                     caption="Wiele startów naraz to norma: A na końcu sezonu, B i C po drodze."):
        _race_form(None, key="race_add")


def _past(past: list[dict], frame: pd.DataFrame) -> None:
    with bento.panel(
        "Starty, które już się odbyły", key="races_past",
        caption="Powiąż start z biegiem: wynik stanie się najmocniejszą kotwicą prognozy.",
    ):
        _past_rows(past, frame)


def _past_rows(past: list[dict], frame: pd.DataFrame) -> None:
    for race in sorted(past, key=lambda r: r["date"], reverse=True):
        date = pd.Timestamp(race["date"])
        nearby = frame[(frame["day"] >= date - pd.Timedelta(days=1)) & (frame["day"] <= date + pd.Timedelta(days=1))]
        options = [None] + nearby["activity_id"].astype(int).tolist()

        def describe(activity_id):
            if activity_id is None:
                return "— nie powiązano —"
            row = nearby[nearby["activity_id"] == activity_id].iloc[0]
            return f"{row['start_local']:%d.%m %H:%M} · {row['distance_km']:.2f} km · {units.fmt_time(row['duration_min'] * 60)}"

        current = race.get("result_activity_id")
        index = options.index(int(current)) if current and int(current) in options else 0
        columns = st.columns([3, 2])
        columns[0].markdown(f"**{race['name']}** — {units.RACE_LABELS[race['distance']]}, {date:%d.%m.%Y}"
                            + (f" · cel {units.fmt_time(race['goal_s'])}" if race.get("goal_s") else ""))
        chosen = columns[1].selectbox("Bieg", options, index=index, format_func=describe,
                                      key=f"race_result_{race['id']}", label_visibility="collapsed")
        if (chosen or None) != (int(current) if current else None):
            store.save_race({**race, "result_activity_id": chosen})
            with st.spinner("Przeliczam tabele biegowe…"):
                from running import pipeline

                pipeline.rebuild()
            st.cache_data.clear()
            st.rerun()
        if not len(nearby):
            st.caption("Brak biegu w dniu startu (±1 dzień) — może nie był zsynchronizowany.")
