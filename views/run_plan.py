"""Training plan: create from data, view as calendar and weeks, track and adjust."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import shell
import theme as tz
import config
from running import coach, garmin_workout as gw, plan as planning, store, text, units
from views import run_common as rc

STATUS_ICONS = rc.STATUS_ICONS


def _status_labels() -> dict[str, str]:
    tr = i18n.tr
    return {"planned": tr(pl="zaplanowany", en="planned"), "done": tr(pl="wykonany", en="done"),
            "modified": tr(pl="zmodyfikowany", en="modified"), "skipped": tr(pl="pominięty", en="skipped"),
            "missed": tr(pl="brak biegu", en="no run")}


_phase_label = text.phase_label
_adjustment = text.adjustment_label


def render() -> None:
    tr = i18n.tr
    bento.header(
        i18n.page("plan"),
        tr(pl="Startuje od tego, co faktycznie biegasz, rośnie do szczytu dystansu (≤ 1,3× średniej z 4 tygodni), co "
              "3.–4. tydzień odpuszcza i kończy się taperem. Tempa z aktualnej formy, nie z celu.",
           en="It starts from what you actually run, grows to the distance's peak (≤ 1.3× the 4-week average), backs "
              "off every 3rd–4th week and ends with a taper. Paces from your current form, not from the goal."),
    )
    frame = rc.guard()
    if frame is None:
        return
    result = rc.current_forecast()
    plans = store.plans()

    requested_race = st.session_state.pop("plan_race_request", None)
    if requested_race:
        existing = store.plans_for(requested_race)
        if existing:
            st.session_state["plan_choice"] = existing[0]["id"]
        else:
            st.session_state["plan_new_race"] = requested_race

    with st.expander(tr(pl="Nowy plan", en="New plan"),
                     expanded=not plans or bool(st.session_state.get("plan_new_race"))):
        _create(frame, result)

    if not plans:
        return
    ids = [p["id"] for p in plans]
    if st.session_state.get("plan_choice") not in ids:
        st.session_state["plan_choice"] = ids[0]
    chosen = st.selectbox("Plan", ids, format_func=lambda i: next(p.get("name", i) for p in plans if p["id"] == i),
                          key="plan_choice", label_visibility="collapsed")
    active = store.plan(chosen)
    if active is None:
        st.error(tr(pl="Plik planu nie istnieje albo jest uszkodzony.", en="The plan file is missing or damaged."))
        return
    errors = store.validate_plan(active)
    if errors:
        st.error(tr(pl="Plik planu nie przechodzi walidacji: ", en="The plan file fails validation: ")
                 + " ".join(errors[:3]))
        return

    matched = planning.match(active, frame, laps=shell.table("run_laps"))
    _header(active, result, matched)
    left, right = bento.row(2, 2)
    with left:
        _weekly_chart(active, frame)
    with right:
        _next(active, frame, result)
        _actions(active, frame, result)
    with bento.panel(tr(pl="Kalendarz", en="Calendar"), key="plan_calendar",
                     caption=tr(pl="✓ wykonany · ≈ zmodyfikowany · ✗ pominięty · · zaplanowany · ↓ tydzień odciążenia",
                                en="✓ done · ≈ modified · ✗ skipped · · planned · ↓ recovery week")):
        _calendar(active, matched)
    with bento.panel(tr(pl="Tydzień", en="Week"), key="plan_week",
                     caption=tr(pl="Szczegóły sesji i ich status. Status ustawiony ręcznie wygrywa z automatycznym.",
                                en="Session details and their status. A status set by hand wins over the automatic "
                                   "one.")):
        _week(active, matched)
    with bento.panel(
        tr(pl="Współpraca z asystentem", en="Working with the assistant"), key="plan_assistant",
        caption=tr(pl="Brief: prognoza z wejściami, biegi z etykietami, obciążenie, regeneracja, plan i luki w danych.",
                   en="The brief: the forecast with its inputs, labelled runs, load, recovery, the plan and the gaps "
                      "in the data."),
    ):
        _assistant(active)


# --------------------------------------------------------------------------
# creation


def _create(frame: pd.DataFrame, result: dict) -> None:
    tr = i18n.tr
    if result.get("status") != "ok":
        st.warning(tr(pl="Bez prognozy formy nie da się dobrać temp: ",
                      en="Without a fitness forecast the paces cannot be set: ") + str(result.get("reason", "")))
        return
    races = [r for r in store.races() if r["date"] > dt.date.today().isoformat()]
    race_ids = [None] + [r["id"] for r in races]
    preselect = st.session_state.pop("plan_new_race", None)
    day_names = i18n.weekdays(long=True)

    def describe(race_id):
        if race_id is None:
            return tr(pl="— bez zapisanego startu —", en="— no saved race —")
        race = next(r for r in races if r["id"] == race_id)
        return f"{race['name']} · {rc.race_label(race['distance'])} · {race['date']}"

    with st.form("plan_create"):
        race_id = st.selectbox(tr(pl="Start", en="Race"), race_ids, format_func=describe,
                               index=race_ids.index(preselect) if preselect in race_ids else 0,
                               help=tr(pl="Starty dodajesz na stronie Zawody.", en="Races are added on the Races page."))
        race = next((r for r in races if r["id"] == race_id), None)
        columns = st.columns(3)
        distance = columns[0].selectbox(tr(pl="Dystans", en="Distance"), list(units.RACES), format_func=rc.race_label,
                                        index=list(units.RACES).index(race["distance"]) if race else 1,
                                        disabled=race is not None)
        date = columns[1].date_input(
            tr(pl="Data startu", en="Race date"),
            dt.date.fromisoformat(race["date"]) if race else dt.date.today() + dt.timedelta(weeks=10),
            format="DD.MM.YYYY", disabled=race is not None)
        goal_text = columns[2].text_input(
            tr(pl="Cel (czas lub tempo /km)", en="Goal (time or pace /km)"),
            units.fmt_time(race["goal_s"]) if race and race.get("goal_s") else "",
            placeholder=tr(pl="np. 49:30 albo 4:55/km", en="e.g. 49:30 or 4:55/km"))
        columns = st.columns(3)
        days = columns[0].multiselect(tr(pl="Dni biegowe", en="Running days"), list(range(7)), default=[1, 3, 5, 6],
                                      format_func=lambda d: day_names[d])
        long_day = columns[1].selectbox(tr(pl="Dzień długiego biegu", en="Long run day"), list(range(7)), index=6,
                                        format_func=lambda d: day_names[d])
        cap = columns[2].number_input(tr(pl="Maks. km/tydz. (0 = auto)", en="Max km/week (0 = auto)"), min_value=0,
                                      max_value=200, value=0, step=5,
                                      help=tr(pl="Górna granica wynikająca z czasu, zdrowia, doświadczenia.",
                                              en="An upper limit set by time, health, experience."))
        submitted = st.form_submit_button(tr(pl="Wygeneruj plan", en="Generate the plan"))
    if not submitted:
        base = planning.baseline(frame, frame["day"].max(), result.get("vdot"))
        weekly, runs, long_run = f"{base['weekly_km_4w']:.0f}", f"{base['runs_per_week_4w']:.1f}", f"{base['long_km_6w']:.0f}"
        regular = f"{base['consistency_8w']:.0%}"
        st.caption(tr(
            pl=f"Punkt wyjścia z danych: {weekly} km/tydz. (4 tyg.), {runs} biegu/tydz., najdłuższy bieg w 6 tyg. "
               f"{long_run} km, regularność 8 tyg. {regular}, VDOT {base['vdot']}.",
            en=f"Starting point from the data: {weekly} km/week (4 wk), {runs} runs/week, longest run in 6 wk "
               f"{long_run} km, 8-week consistency {regular}, VDOT {base['vdot']}.",
        ))
        return
    distance = race["distance"] if race else distance
    date = dt.date.fromisoformat(race["date"]) if race else date
    goal = _parse_goal(goal_text, distance)
    if goal_text.strip() and goal is None:
        st.error(tr(pl="Nie rozumiem celu — wpisz czas (49:30, 1:52:00) albo tempo (4:55/km).",
                    en="I cannot read the goal — enter a time (49:30, 1:52:00) or a pace (4:55/km)."))
        return
    request = planning.PlanRequest(
        distance=distance, race_date=date, goal_s=goal, run_days=sorted(days), long_day=long_day,
        start=dt.date.today() + dt.timedelta(days=1), max_weekly_km=cap or None,
        race_id=race_id, name=f"{race['name'] if race else rc.race_label(distance)} — {date:%d.%m.%Y}",
    )
    try:
        payload = planning.generate(request, frame, result)
        store.save_plan(payload)
    except ValueError as error:
        st.error(str(error))
        return
    st.session_state["plan_choice"] = payload["id"]
    st.rerun()


def _parse_goal(text: str, distance: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    # Under ten minutes no race distance here is possible, so "4:55" is a pace.
    seconds = units.parse_time(text.replace("/km", "").strip())
    if "/km" in text or (seconds is not None and seconds < 600):
        pace = units.parse_pace(text.replace(" ", ""))
        return units.time_from(pace, units.RACES[distance]) if pace else None
    return units.parse_time(text)


# --------------------------------------------------------------------------
# reading the plan


def _header(active: dict, result: dict, matched: pd.DataFrame) -> None:
    request = active["request"]
    race_date = dt.date.fromisoformat(request["race_date"])
    days = (race_date - dt.date.today()).days
    weeks = planning.week_table(active)
    build = weeks[weeks["phase"].isin(("base", "build", "peak"))] if not weeks.empty else weeks
    tr = i18n.tr
    columns = bento.row(1, 1, 1, 1)
    summary = planning.compliance(matched)
    left = (f"{days} {i18n.plural(days, pl=('dzień', 'dni', 'dni'), en=('day', 'days'))}" if days >= 0
            else tr(pl="po starcie", en="after the race"))
    bento.stat(columns[0], tr(pl="Do startu", en="To the race"), left, key="p_days", note=f"{race_date:%d.%m.%Y}")
    bento.stat(columns[1], tr(pl="Szczyt objętości", en="Peak volume"),
               f"{build['planned_km'].max():.0f} km" if len(build) else "—", key="p_peak")
    bento.stat(columns[2], tr(pl="Najdłuższy bieg", en="Longest run"),
               f"{weeks['long_km'].max():.0f} km" if len(weeks) else "—", key="p_long")
    note = None
    if summary.get("due"):
        km, quality = f"{summary['actual_km']:.0f}/{summary['planned_km']:.0f} km", \
            f"{summary['quality_done']}/{summary['quality_due']}"
        note = tr(pl=f"{km} · jakość {quality}", en=f"{km} · quality {quality}")
    bento.stat(columns[3], tr(pl="Realizacja", en="Completion"),
               f"{summary['done'] + summary['modified']}/{summary['due']}" if summary.get("due") else "—",
               key="p_done", help=tr(pl="Sesje wykonane lub zmodyfikowane / sesje do dziś.",
                                     en="Sessions done or modified / sessions so far."),
               note=note)
    created = active.get("forecast", {})
    now = result["distances"].get(request["distance"]) if result.get("status") == "ok" else None
    then = f"{units.fmt_time(created.get('realistic_s'))} (VDOT {created.get('vdot')})"
    line = tr(pl=f"Prognoza przy tworzeniu planu: {then}", en=f"Forecast when the plan was made: {then}")
    if now:
        today = f"{units.fmt_time(now.realistic_s)} (VDOT {result['vdot']:.1f})"
        line += tr(pl=f" · dziś: {today}", en=f" · today: {today}")
    if request.get("goal_s"):
        goal = units.fmt_time(request["goal_s"])
        line += tr(pl=f" · cel: {goal}", en=f" · goal: {goal}")
    st.caption(line + ".")
    for warning in text.warnings(active):
        st.warning(warning)


def _next(active: dict, frame: pd.DataFrame, result: dict) -> None:
    tr = i18n.tr
    suggestion = coach.next_session(active, frame, shell.daily(), result)
    session = suggestion.get("session")
    date = dt.date.fromisoformat(session["date"]) if session else None
    caption = None
    if session:
        action = rc.action_label(suggestion["action"])
        decision = tr(pl=f"decyzja: <b>{action}</b>", en=f"decision: <b>{action}</b>") \
            if suggestion.get("today", True) else tr(pl="decyzja rano w dniu sesji",
                                                      en="decided on the morning of the session")
        caption = f"{date:%d.%m} ({i18n.weekdays(long=True)[date.weekday()]}) · {decision}"
    how = list(suggestion["reasons"])
    if suggestion["flags"]:
        how.append(tr(pl="Sygnały: ", en="Signals: ") + "; ".join(suggestion["flags"]) + ".")
    if session and session.get("purpose"):
        how.append(tr(pl="Po co: ", en="Why: ") + session["purpose"])
    with bento.tile(
        tr(pl="Następny trening", en="Next session"), key="plan_next", terms=["today_decision"],
        caption=caption, how=" ".join(how) or None,
    ):
        if not session:
            st.caption(tr(pl="W planie nie ma już sesji.", en="There are no sessions left in the plan."))
            return
        st.markdown(f"**{session.get('title')}**")
        band = f"{units.fmt_pace(session.get('pace_lo'), False)}–{units.fmt_pace(session.get('pace_hi'))}"
        st.markdown("<div class='tile-caption'>" + " · ".join(filter(None, [
            session.get("main", ""),
            tr(pl=f"tempo {band}", en=f"pace {band}")
            if session.get("pace_lo") and "/km" not in session.get("main", "") else None,
            tr(pl=f"tętno {session.get('hr')}", en=f"HR {session.get('hr')}") if session.get("hr") else None,
        ])) + "</div>", unsafe_allow_html=True)
        if suggestion["reasons"]:
            st.markdown(f"<div class='tile-caption'>{suggestion['reasons'][0]}</div>", unsafe_allow_html=True)


def _weekly_chart(active: dict, frame: pd.DataFrame) -> None:
    weeks = planning.week_table(active)
    if weeks.empty:
        return
    weeks = weeks.assign(monday=pd.to_datetime(weeks["monday"]))
    actual = []
    for monday in weeks["monday"]:
        mask = (frame["day"] >= monday) & (frame["day"] < monday + pd.Timedelta(days=7))
        actual.append(float(frame.loc[mask, "distance_km"].sum()) if monday <= pd.Timestamp(dt.date.today()) else None)
    weeks["actual_km"] = actual
    tr = i18n.tr
    with bento.tile(
        tr(pl="Plan a wykonanie — tygodnie", en="Plan against what was done — weeks"), rows=2, key="plan_weeks",
        caption=tr(pl="Linia: zaplanowane km; punkty: przebiegnięte; pasy: fazy bloku.",
                   en="Line: planned km; points: run; bands: the block's phases."),
        how=tr(pl="Spadki co kilka tygodni to tygodnie odciążenia. Pionowa linia to dziś.",
               en="Dips every few weeks are recovery weeks. The vertical line is today."),
    ) as tile:
        _weekly_figure(tile, weeks)


def _weekly_figure(tile, weeks: pd.DataFrame) -> None:
    tr = i18n.tr
    figure = tz.timeseries(weeks, "monday", {"plan": "planned_km", tr(pl="wykonane", en="done"): "actual_km"},
                           markers=True, y_title=tr(pl="km / tydzień", en="km / week"), height=280)
    if figure is not None:
        spans = []
        for phase, block in weeks.groupby((weeks["phase"] != weeks["phase"].shift()).cumsum()):
            spans.append((block["monday"].iloc[0] - pd.Timedelta(days=3.5),
                          block["monday"].iloc[-1] + pd.Timedelta(days=3.5), _phase_label(block["phase"].iloc[0])))
        today = pd.Timestamp(dt.date.today())
        inside = weeks["monday"].min() - pd.Timedelta(days=3.5) <= today <= weeks["monday"].max() + pd.Timedelta(days=3.5)
        tz.periods(figure, spans, today=today if inside else None)
    tile.chart(
        figure,
        table=weeks.assign(phase_label=weeks["phase"].map(_phase_label))[
            ["week", "monday", "phase_label", "volume_km", "planned_km", "actual_km", "long_km", "quality"]]
        .rename(columns={"week": tr(pl="tydzień", en="week"), "monday": tr(pl="od", en="from"),
                         "phase_label": tr(pl="faza", en="phase"), "volume_km": tr(pl="cel km", en="target km"),
                         "planned_km": tr(pl="plan km", en="plan km"), "actual_km": tr(pl="wykonane km", en="done km"),
                         "long_km": tr(pl="długi", en="long"), "quality": tr(pl="jakość", en="quality")}),
    )


def _calendar(active: dict, matched: pd.DataFrame) -> None:
    if matched.empty:
        return
    tr = i18n.tr
    names = i18n.weekdays()
    weeks = {w["week"]: w for w in active.get("weeks", [])}
    grid: dict[int, dict[str, str]] = {}
    for row in matched.itertuples(index=False):
        icon = STATUS_ICONS.get(row.effective, "·")
        cell = f"{icon} {row.title}"
        grid.setdefault(row.week, {})[names[row.date.weekday()]] = cell
    rows = []
    for number in sorted(weeks):
        week = weeks[number]
        line = {tr(pl="tydz.", en="wk"): number,
                tr(pl="od", en="from"): dt.date.fromisoformat(week["monday"]).strftime("%d.%m"),
                tr(pl="faza", en="phase"): _phase_label(week["phase"]) + (" ↓" if week.get("recovery") else "")}
        for day in names:
            line[day] = grid.get(number, {}).get(day, "")
        line["km"] = week.get("planned_km")
        rows.append(line)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"km": st.column_config.NumberColumn("km", format="%.0f")})


def _week(active: dict, matched: pd.DataFrame) -> None:
    if matched.empty:
        return
    today = dt.date.today()
    numbers = sorted(matched["week"].unique())
    current = next((w["week"] for w in active.get("weeks", [])
                    if dt.date.fromisoformat(w["monday"]) <= today < dt.date.fromisoformat(w["monday"]) + dt.timedelta(days=7)),
                   numbers[0])
    tr = i18n.tr
    labels = _status_labels()
    number = st.select_slider(tr(pl="Tydzień planu", en="Plan week"), numbers,
                              value=current if current in numbers else numbers[0], key=f"plan_week_{active['id']}")
    week = matched[matched["week"] == number]
    sessions_by_id = {s["id"]: s for s in active["sessions"]}
    for row in week.itertuples(index=False):
        session = sessions_by_id[row.id]
        icon = STATUS_ICONS.get(row.effective, "·")
        with st.expander(f"{icon} {i18n.weekdays(long=True)[row.date.weekday()]} {row.date:%d.%m} — {row.title}"):
            warmup, main, cooldown = (session.get(k, "—") for k in ("warmup", "main", "cooldown"))
            st.markdown(tr(pl=f"**Rozgrzewka:** {warmup}  \n**Część główna:** {main}  \n**Schłodzenie:** {cooldown}",
                           en=f"**Warm-up:** {warmup}  \n**Main set:** {main}  \n**Cool-down:** {cooldown}"))
            if session.get("pace_lo"):
                band = f"{units.fmt_pace(session['pace_lo'], False)}–{units.fmt_pace(session['pace_hi'])}"
                hr, minutes = session.get("hr", "—"), session.get("duration_min") or "—"
                st.caption(tr(pl=f"Tempo {band} · tętno {hr} · ok. {minutes} min",
                              en=f"Pace {band} · HR {hr} · about {minutes} min"))
            st.caption(tr(pl="Po co: ", en="Why: ") + session.get("purpose", "—"))
            if row.activity_id:
                kind, auto = rc.kind_label(row.actual_kind), labels.get(row.auto, row.auto)
                done_km, pace = f"{row.actual_km:.1f} km", units.fmt_pace(row.actual_pace)
                st.caption(tr(pl=f"Wykonanie: {done_km} w {pace}, rozpoznany typ „{kind}” — automatycznie: {auto}.",
                              en=f"Done: {done_km} at {pace}, recognised as “{kind}” — automatically: {auto}."))
                done = getattr(row, "reps_done", None)
                if done is not None and not pd.isna(done):
                    paces = ", ".join(units.fmt_pace(p, False) for p in row.rep_paces)
                    reps = f"{done:.0f}/{row.reps_planned:.0f}"
                    if pd.isna(row.reps_on_pace):
                        on_pace = ""
                    else:
                        on_pace = tr(pl=f", w tempie {row.reps_on_pace:.0f}", en=f", on pace {row.reps_on_pace:.0f}")
                    st.caption(tr(pl=f"Odcinki z okrążeń zegarka: {reps}{on_pace} (±3% od pasma) — {paces}.",
                                  en=f"Reps from the watch laps: {reps}{on_pace} (±3% of the band) — {paces}."))
                if st.button(tr(pl="Otwórz trening", en="Open the session"), key=f"plan_open_{row.id}"):
                    routing.open_run(int(row.activity_id))
            elif row.auto == "missed":
                st.caption(tr(pl="Nie znaleziono biegu w tym dniu ani dzień obok.",
                              en="No run found on that day or the day next to it."))

    day, name, planned = tr(pl="dzień", en="day"), tr(pl="sesja", en="session"), tr(pl="plan km", en="plan km")
    done_km, note = tr(pl="wykonane km", en="done km"), tr(pl="notatka", en="note")
    names = i18n.weekdays()
    editor = pd.DataFrame(
        {
            "id": week["id"],
            day: week["date"].map(lambda d: f"{names[d.weekday()]} {d:%d.%m}"),
            name: week["title"],
            planned: week["planned_km"],
            done_km: week["actual_km"],
            "status": week["status"].map(labels),
            note: week["note"].fillna(""),
        }
    )
    edited = st.data_editor(
        editor, hide_index=True, width="stretch", key=f"plan_editor_{active['id']}_{number}",
        disabled=["id", day, name, planned, done_km],
        column_config={
            "id": None,
            "status": st.column_config.SelectboxColumn(
                "status", options=[labels[s] for s in store.STATUSES], required=True,
                help=tr(pl="„zaplanowany” = status liczony automatycznie z dopasowanego biegu.",
                        en="“planned” = the status is worked out automatically from the matched run.")),
            planned: st.column_config.NumberColumn(format="%.1f"),
            done_km: st.column_config.NumberColumn(format="%.1f"),
        },
    )
    if st.button(tr(pl="Zapisz statusy tygodnia", en="Save the week's statuses"), key=f"plan_save_{active['id']}_{number}"):
        reverse = {label: key for key, label in labels.items()}
        for row in edited.to_dict("records"):
            planning.set_status(active, row["id"], reverse.get(row["status"], "planned"), note=row[note])
        store.save_plan(active)
        st.success(tr(pl="Zapisano.", en="Saved."))
        st.rerun()


# --------------------------------------------------------------------------
# changing the plan


def _actions(active: dict, frame: pd.DataFrame, result: dict) -> None:
    with bento.tile(
        i18n.tr(pl="Dostosuj plan", en="Adjust the plan"), key="plan_actions",
        caption=i18n.tr(pl="Przebudowa: wszystko od jutra z najnowszych danych. Korekta: tylko najbliższe dni.",
                        en="Rebuild: everything from tomorrow on the latest data. Correction: the next days only."),
    ):
        _actions_body(active, frame, result)


def _actions_body(active: dict, frame: pd.DataFrame, result: dict) -> None:
    tr = i18n.tr
    columns = st.columns([2, 2, 1])
    if columns[0].button(tr(pl="Przebuduj od jutra", en="Rebuild from tomorrow"), width="stretch", key="plan_replan",
                         help=tr(pl="Po pominiętych treningach, po teście, po zmianie formy.",
                                 en="After skipped sessions, after a test, after a change in form.")):
        try:
            fresh = planning.replan(active, frame, result, today=dt.date.today() + dt.timedelta(days=1))
            store.save_plan(fresh)
        except ValueError as error:
            st.error(str(error))
        else:
            st.rerun()
    with columns[1].popover(tr(pl="Korekta dyspozycji", en="Adjust for how you are"), width="stretch"):
        reason = st.radio(tr(pl="Powód", en="Reason"), list(planning.ADJUSTMENTS), format_func=_adjustment,
                          key="plan_adjust_reason")
        if st.button(tr(pl="Zastosuj", en="Apply"), key="plan_adjust_apply"):
            store.save_plan(planning.adjust(active, reason))
            st.rerun()
    with columns[2].popover(tr(pl="Usuń", en="Delete"), width="stretch"):
        st.caption(tr(pl="Plan zniknie razem ze statusami sesji.", en="The plan goes together with the session "
                                                                      "statuses."))
        if st.button(tr(pl="Usuń plan", en="Delete the plan"), key="plan_delete", type="primary"):
            store.delete_plan(active["id"])
            st.session_state.pop("plan_choice", None)
            st.rerun()
    _garmin(active)
    history = active.get("history", [])
    if history:
        st.caption(tr(pl="Historia zmian: ", en="Change history: ")
                   + " · ".join(f"{h['at'][:16].replace('T', ' ')} {text.history_action(h['action'])}"
                                for h in history[-5:]))


def _garmin(active: dict) -> None:
    """Push the next week to the Garmin calendar. Local only: it needs the
    tokens etl/fetch.py uses, which a server without them does not have."""
    from pathlib import Path

    if not (Path(config.TOKENSTORE).expanduser() / "garmin_tokens.json").exists():
        return
    today = dt.date.today()
    actions = gw.sync_actions(active, today, 7)
    pushed = active.get("garmin") or {}
    tr = i18n.tr
    count = len(actions)
    label = (tr(pl=f"Wyślij najbliższy tydzień na zegarek ({count} zmian)",
                en=f"Send the coming week to the watch ({count} changes)") if actions
             else tr(pl="Kalendarz Garmin aktualny na 7 dni", en="Garmin calendar up to date for 7 days"))
    if st.button(label, key="plan_push", disabled=not actions, icon=":material/watch:",
                 help=tr(pl="Treningi trafiają do kalendarza Garmin Connect z tempem docelowym na każdym kroku; "
                            "po synchronizacji są na zegarku. Zmienione sesje są podmieniane, pominięte usuwane.",
                         en="Sessions go to the Garmin Connect calendar with a target pace on every step; after a "
                            "sync they are on the watch. Changed sessions are replaced, skipped ones removed.")):
        from etl import push_plan
        from etl.fetch import connect

        with st.status(tr(pl="Wysyłam do Garmin Connect…", en="Sending to Garmin Connect…"), expanded=True) as status:
            try:
                push_plan.push(active, connect(), today, 7, log=st.write)
            except Exception as error:  # noqa: BLE001 - network / auth: show it, keep the page
                status.update(label=tr(pl=f"Przerwane: {error}", en=f"Stopped: {error}"), state="error")
                return
            status.update(label=tr(pl="Wysłane — zsynchronizuj zegarek.", en="Sent — sync the watch."),
                          state="complete")
        st.rerun()
    if pushed:
        upcoming = sorted(e["date"] for e in pushed.values() if e.get("date", "") >= today.isoformat())
        if upcoming:
            first = f"{upcoming[0][8:10]}.{upcoming[0][5:7]}"
            st.caption(tr(pl=f"Na zegarku: {len(upcoming)} treningów od {first}.",
                          en=f"On the watch: {len(upcoming)} sessions from {first}."))


def _assistant(active: dict) -> None:
    rc.download_brief("plan")
    path, check = f"`data/coach/plans/{active['id']}.json`", f"`.venv/bin/python -m running.coach --validate {active['id']}`"
    st.markdown(i18n.tr(
        pl="W Claude Code w tym repozytorium: **`/trener`** — przeczyta brief i ten plan, zaproponuje zmiany, "
           f"a po akceptacji zapisze je w pliku planu i sprawdzi walidację.\n\nPlik planu: {path} · walidacja: {check}",
        en="In Claude Code in this repository: **`/trener`** — it reads the brief and this plan, proposes changes, "
           f"and once accepted writes them to the plan file and checks validation.\n\nPlan file: {path} · "
           f"validation: {check}",
    ))
