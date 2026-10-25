"""Training plan: create from data, view as calendar and weeks, track and adjust."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import routing
import shell
import theme as tz
import config
from running import coach, garmin_workout as gw, plan as planning, store, units
from views import run_common as rc

STATUS_LABELS = {
    "planned": "zaplanowany",
    "done": "wykonany",
    "modified": "zmodyfikowany",
    "skipped": "pominięty",
    "missed": "brak biegu",
}
STATUS_ICONS = rc.STATUS_ICONS
DAY_NAMES = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def render() -> None:
    st.title("Plan treningowy")
    st.caption(
        "Plan startuje od tego, co faktycznie biegasz (średnia z 4 tygodni), rośnie krokami do szczytu "
        "właściwego dla dystansu, nie przekracza 1,3× średniej z czterech poprzednich tygodni, co 3.–4. "
        "tydzień odpuszcza i kończy się taperem. Tempa liczone z aktualnej formy, nie z celu — przebudowa "
        "planu przelicza je z najnowszych danych."
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

    with st.expander("Nowy plan", expanded=not plans or bool(st.session_state.get("plan_new_race"))):
        _create(frame, result)

    if not plans:
        return
    ids = [p["id"] for p in plans]
    if st.session_state.get("plan_choice") not in ids:
        st.session_state["plan_choice"] = ids[0]
    chosen = st.selectbox("Plan", ids, format_func=lambda i: next(p.get("name", i) for p in plans if p["id"] == i),
                          key="plan_choice")
    active = store.plan(chosen)
    if active is None:
        st.error("Plik planu nie istnieje albo jest uszkodzony.")
        return
    errors = store.validate_plan(active)
    if errors:
        st.error("Plik planu nie przechodzi walidacji: " + " ".join(errors[:3]))
        return

    matched = planning.match(active, frame, laps=shell.table("run_laps"))
    _header(active, result, matched)
    _next(active, frame, result)
    _weekly_chart(active, frame)
    _calendar(active, matched)
    _week(active, matched)
    _actions(active, frame, result)
    _assistant(active)


# --------------------------------------------------------------------------
# creation


def _create(frame: pd.DataFrame, result: dict) -> None:
    if result.get("status") != "ok":
        st.warning("Bez prognozy formy nie da się dobrać temp: " + str(result.get("reason", "")))
        return
    races = [r for r in store.races() if r["date"] > dt.date.today().isoformat()]
    race_ids = [None] + [r["id"] for r in races]
    preselect = st.session_state.pop("plan_new_race", None)

    def describe(race_id):
        if race_id is None:
            return "— bez zapisanego startu —"
        race = next(r for r in races if r["id"] == race_id)
        return f"{race['name']} · {units.RACE_LABELS[race['distance']]} · {race['date']}"

    with st.form("plan_create"):
        race_id = st.selectbox("Start", race_ids, format_func=describe,
                               index=race_ids.index(preselect) if preselect in race_ids else 0,
                               help="Starty dodajesz na stronie Zawody.")
        race = next((r for r in races if r["id"] == race_id), None)
        columns = st.columns(3)
        distance = columns[0].selectbox("Dystans", list(units.RACES), format_func=units.RACE_LABELS.get,
                                        index=list(units.RACES).index(race["distance"]) if race else 1,
                                        disabled=race is not None)
        date = columns[1].date_input(
            "Data startu", dt.date.fromisoformat(race["date"]) if race else dt.date.today() + dt.timedelta(weeks=10),
            format="DD.MM.YYYY", disabled=race is not None)
        goal_text = columns[2].text_input(
            "Cel (czas lub tempo /km)", units.fmt_time(race["goal_s"]) if race and race.get("goal_s") else "",
            placeholder="np. 49:30 albo 4:55/km")
        columns = st.columns(3)
        days = columns[0].multiselect("Dni biegowe", list(range(7)), default=[1, 3, 5, 6],
                                      format_func=lambda d: DAY_NAMES[d])
        long_day = columns[1].selectbox("Dzień długiego biegu", list(range(7)), index=6,
                                        format_func=lambda d: DAY_NAMES[d])
        cap = columns[2].number_input("Maks. km/tydz. (0 = auto)", min_value=0, max_value=200, value=0, step=5,
                                      help="Górna granica wynikająca z czasu, zdrowia, doświadczenia.")
        submitted = st.form_submit_button("Wygeneruj plan")
    if not submitted:
        base = planning.baseline(frame, frame["day"].max(), result.get("vdot"))
        st.caption(
            f"Punkt wyjścia z danych: {base['weekly_km_4w']:.0f} km/tydz. (4 tyg.), "
            f"{base['runs_per_week_4w']:.1f} biegu/tydz., najdłuższy bieg w 6 tyg. {base['long_km_6w']:.0f} km, "
            f"regularność 8 tyg. {base['consistency_8w']:.0%}, VDOT {base['vdot']}."
        )
        return
    distance = race["distance"] if race else distance
    date = dt.date.fromisoformat(race["date"]) if race else date
    goal = _parse_goal(goal_text, distance)
    if goal_text.strip() and goal is None:
        st.error("Nie rozumiem celu — wpisz czas (49:30, 1:52:00) albo tempo (4:55/km).")
        return
    request = planning.PlanRequest(
        distance=distance, race_date=date, goal_s=goal, run_days=sorted(days), long_day=long_day,
        start=dt.date.today() + dt.timedelta(days=1), max_weekly_km=cap or None,
        race_id=race_id, name=f"{race['name'] if race else units.RACE_LABELS[distance]} — {date:%d.%m.%Y}",
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
    columns = st.columns(4)
    columns[0].metric("Do startu", f"{days} dni" if days >= 0 else "po starcie")
    columns[1].metric("Szczyt objętości", f"{build['planned_km'].max():.0f} km" if len(build) else "—")
    columns[2].metric("Najdłuższy bieg", f"{weeks['long_km'].max():.0f} km" if len(weeks) else "—")
    summary = planning.compliance(matched)
    columns[3].metric("Realizacja", f"{summary['done'] + summary['modified']}/{summary['due']}" if summary.get("due") else "—",
                      help="Sesje wykonane lub zmodyfikowane / sesje do dziś.")
    created = active.get("forecast", {})
    now = result["distances"].get(request["distance"]) if result.get("status") == "ok" else None
    text = (f"Prognoza przy tworzeniu planu: {units.fmt_time(created.get('realistic_s'))} (VDOT {created.get('vdot')})")
    if now:
        text += f" · dziś: {units.fmt_time(now.realistic_s)} (VDOT {result['vdot']:.1f})"
    if request.get("goal_s"):
        text += f" · cel: {units.fmt_time(request['goal_s'])}"
    st.caption(text + ".")
    if summary.get("due"):
        st.caption(
            f"Do dziś: {summary['actual_km']:.0f} z {summary['planned_km']:.0f} planowanych km, jakość "
            f"{summary['quality_done']}/{summary['quality_due']}, pominięte {summary['skipped']}."
        )
    for warning in active.get("warnings", []):
        st.warning(warning)


def _next(active: dict, frame: pd.DataFrame, result: dict) -> None:
    suggestion = coach.next_session(active, frame, shell.daily(), result)
    session = suggestion.get("session")
    shell.lead("Następny trening", "Sesja z planu zestawiona z dzisiejszą regeneracją i obciążeniem.")
    if not session:
        st.caption("W planie nie ma już sesji.")
        return
    date = dt.date.fromisoformat(session["date"])
    st.markdown(
        f"**{date:%d.%m} ({DAY_NAMES[date.weekday()]}) — {session.get('title')}** · decyzja: **{suggestion['action']}**  \n"
        f"{session.get('main', '')}"
        + (f"  \nTempo {units.fmt_pace(session.get('pace_lo'), False)}–{units.fmt_pace(session.get('pace_hi'))}"
           f", tętno {session.get('hr')}" if session.get("pace_lo") else "")
    )
    for reason in suggestion["reasons"]:
        st.caption(reason)
    if suggestion["flags"]:
        st.caption("Sygnały: " + "; ".join(suggestion["flags"]) + ".")
    if session.get("purpose"):
        st.caption(f"Po co: {session['purpose']}")


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
    shell.lead(
        "Plan a wykonanie — tygodnie",
        "Linia: kilometry zaplanowane; punkty: przebiegnięte. Spadki co kilka tygodni to tygodnie odciążenia.",
    )
    figure = tz.timeseries(weeks, "monday", {"plan": "planned_km", "wykonane": "actual_km"}, markers=True,
                           y_title="km / tydzień", height=280)
    tz.show(
        figure,
        table=weeks[["week", "monday", "phase_label", "volume_km", "planned_km", "actual_km", "long_km", "quality"]]
        .rename(columns={"week": "tydzień", "monday": "od", "phase_label": "faza", "volume_km": "cel km",
                         "planned_km": "plan km", "actual_km": "wykonane km", "long_km": "długi", "quality": "jakość"}),
        key="plan_weeks",
    )


def _calendar(active: dict, matched: pd.DataFrame) -> None:
    shell.lead("Kalendarz", "✓ wykonany · ≈ zmodyfikowany · ✗ pominięty · · zaplanowany. Puste pole = odpoczynek.")
    if matched.empty:
        return
    weeks = {w["week"]: w for w in active.get("weeks", [])}
    grid: dict[int, dict[str, str]] = {}
    for row in matched.itertuples(index=False):
        icon = STATUS_ICONS.get(row.effective, "·")
        cell = f"{icon} {row.title}"
        grid.setdefault(row.week, {})[planning.WEEKDAYS[row.date.weekday()]] = cell
    rows = []
    for number in sorted(weeks):
        week = weeks[number]
        line = {"tydz.": number, "od": dt.date.fromisoformat(week["monday"]).strftime("%d.%m"),
                "faza": planning.PHASE_LABELS.get(week["phase"], week["phase"]) + (" ↓" if week.get("recovery") else "")}
        for day in planning.WEEKDAYS:
            line[day] = grid.get(number, {}).get(day, "")
        line["km"] = week.get("planned_km")
        rows.append(line)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"km": st.column_config.NumberColumn("km", format="%.0f")})
    st.caption("↓ = tydzień odciążenia.")


def _week(active: dict, matched: pd.DataFrame) -> None:
    if matched.empty:
        return
    today = dt.date.today()
    numbers = sorted(matched["week"].unique())
    current = next((w["week"] for w in active.get("weeks", [])
                    if dt.date.fromisoformat(w["monday"]) <= today < dt.date.fromisoformat(w["monday"]) + dt.timedelta(days=7)),
                   numbers[0])
    shell.lead("Tydzień", "Szczegóły sesji i ich status. Status ustawiony ręcznie wygrywa z automatycznym.")
    number = st.select_slider("Tydzień planu", numbers, value=current if current in numbers else numbers[0],
                              key=f"plan_week_{active['id']}")
    week = matched[matched["week"] == number]
    sessions_by_id = {s["id"]: s for s in active["sessions"]}
    for row in week.itertuples(index=False):
        session = sessions_by_id[row.id]
        icon = STATUS_ICONS.get(row.effective, "·")
        with st.expander(f"{icon} {DAY_NAMES[row.date.weekday()]} {row.date:%d.%m} — {row.title}"):
            st.markdown(
                f"**Rozgrzewka:** {session.get('warmup', '—')}  \n**Część główna:** {session.get('main', '—')}  \n"
                f"**Schłodzenie:** {session.get('cooldown', '—')}"
            )
            if session.get("pace_lo"):
                st.caption(f"Tempo {units.fmt_pace(session['pace_lo'], False)}–{units.fmt_pace(session['pace_hi'])} · "
                           f"tętno {session.get('hr', '—')} · ok. {session.get('duration_min') or '—'} min")
            st.caption(f"Po co: {session.get('purpose', '—')}")
            if row.activity_id:
                st.caption(f"Wykonanie: {row.actual_km:.1f} km w {units.fmt_pace(row.actual_pace)}, "
                           f"rozpoznany typ „{rc.kind_label(row.actual_kind)}” — automatycznie: "
                           f"{STATUS_LABELS.get(row.auto, row.auto)}.")
                done = getattr(row, "reps_done", None)
                if done is not None and not pd.isna(done):
                    paces = ", ".join(units.fmt_pace(p, False) for p in row.rep_paces)
                    on_pace = "" if pd.isna(row.reps_on_pace) else f", w tempie {row.reps_on_pace:.0f}"
                    st.caption(f"Odcinki z okrążeń zegarka: {done:.0f}/{row.reps_planned:.0f}{on_pace} "
                               f"(±3% od pasma) — {paces}.")
                if st.button("Otwórz trening", key=f"plan_open_{row.id}"):
                    routing.open_run(int(row.activity_id))
            elif row.auto == "missed":
                st.caption("Nie znaleziono biegu w tym dniu ani dzień obok.")

    editor = pd.DataFrame(
        {
            "id": week["id"],
            "dzień": week["date"].map(lambda d: f"{planning.WEEKDAYS[d.weekday()]} {d:%d.%m}"),
            "sesja": week["title"],
            "plan km": week["planned_km"],
            "wykonane km": week["actual_km"],
            "status": week["status"].map(STATUS_LABELS),
            "notatka": week["note"].fillna(""),
        }
    )
    edited = st.data_editor(
        editor, hide_index=True, width="stretch", key=f"plan_editor_{active['id']}_{number}",
        disabled=["id", "dzień", "sesja", "plan km", "wykonane km"],
        column_config={
            "id": None,
            "status": st.column_config.SelectboxColumn(
                "status", options=[STATUS_LABELS[s] for s in store.STATUSES], required=True,
                help="„zaplanowany” = status liczony automatycznie z dopasowanego biegu."),
            "plan km": st.column_config.NumberColumn(format="%.1f"),
            "wykonane km": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    if st.button("Zapisz statusy tygodnia", key=f"plan_save_{active['id']}_{number}"):
        reverse = {label: key for key, label in STATUS_LABELS.items()}
        for row in edited.itertuples(index=False):
            planning.set_status(active, row.id, reverse.get(row.status, "planned"), note=row.notatka)
        store.save_plan(active)
        st.success("Zapisano.")
        st.rerun()


# --------------------------------------------------------------------------
# changing the plan


def _actions(active: dict, frame: pd.DataFrame, result: dict) -> None:
    shell.lead(
        "Dostosuj plan",
        "Przebudowa liczy wszystko od jutra z najnowszych danych (objętość, forma, tempa); przeszłość zostaje. "
        "Korekta zmienia tylko najbliższe dni.",
    )
    columns = st.columns([2, 2, 1])
    if columns[0].button("Przebuduj od jutra", width="stretch", key="plan_replan",
                         help="Po pominiętych treningach, po teście, po zmianie formy."):
        try:
            fresh = planning.replan(active, frame, result, today=dt.date.today() + dt.timedelta(days=1))
            store.save_plan(fresh)
        except ValueError as error:
            st.error(str(error))
        else:
            st.rerun()
    with columns[1].popover("Korekta dyspozycji", width="stretch"):
        reason = st.radio("Powód", list(planning.ADJUSTMENTS), format_func=planning.ADJUSTMENTS.get,
                          key="plan_adjust_reason")
        if st.button("Zastosuj", key="plan_adjust_apply"):
            store.save_plan(planning.adjust(active, reason))
            st.rerun()
    with columns[2].popover("Usuń", width="stretch"):
        st.caption("Plan zniknie razem ze statusami sesji.")
        if st.button("Usuń plan", key="plan_delete", type="primary"):
            store.delete_plan(active["id"])
            st.session_state.pop("plan_choice", None)
            st.rerun()
    _garmin(active)
    history = active.get("history", [])
    if history:
        st.caption("Historia zmian: " + " · ".join(f"{h['at'][:16].replace('T', ' ')} {h['action']}" for h in history[-5:]))


def _garmin(active: dict) -> None:
    """Push the next week to the Garmin calendar. Local only: it needs the
    tokens etl/fetch.py uses, which a server without them does not have."""
    from pathlib import Path

    if not (Path(config.TOKENSTORE).expanduser() / "garmin_tokens.json").exists():
        return
    today = dt.date.today()
    actions = gw.sync_actions(active, today, 7)
    pushed = active.get("garmin") or {}
    label = (f"Wyślij najbliższy tydzień na zegarek ({len(actions)} zmian)" if actions
             else "Kalendarz Garmin aktualny na 7 dni")
    if st.button(label, key="plan_push", disabled=not actions, icon=":material/watch:",
                 help="Treningi trafiają do kalendarza Garmin Connect z tempem docelowym na każdym kroku; "
                      "po synchronizacji są na zegarku. Zmienione sesje są podmieniane, pominięte usuwane."):
        from etl import push_plan
        from etl.fetch import connect

        with st.status("Wysyłam do Garmin Connect…", expanded=True) as status:
            try:
                push_plan.push(active, connect(), today, 7, log=st.write)
            except Exception as error:  # noqa: BLE001 - network / auth: show it, keep the page
                status.update(label=f"Przerwane: {error}", state="error")
                return
            status.update(label="Wysłane — zsynchronizuj zegarek.", state="complete")
        st.rerun()
    if pushed:
        upcoming = sorted(e["date"] for e in pushed.values() if e.get("date", "") >= today.isoformat())
        if upcoming:
            st.caption(f"Na zegarku: {len(upcoming)} treningów od {upcoming[0][8:10]}.{upcoming[0][5:7]}.")


def _assistant(active: dict) -> None:
    shell.lead(
        "Współpraca z asystentem",
        "Brief zawiera wszystko, z czego asystent ma rozumować: prognozę z wejściami, ostatnie biegi z etykietami, "
        "obciążenie, regenerację, ten plan i jego realizację oraz listę tego, czego dane nie widzą.",
    )
    rc.download_brief("plan")
    st.markdown(
        "W Claude Code w tym repozytorium: **`/trener`** — przeczyta brief i ten plan, zaproponuje zmiany, "
        "a po akceptacji zapisze je w pliku planu i sprawdzi walidację.\n\n"
        f"Plik planu: `data/coach/plans/{active['id']}.json` · walidacja: "
        f"`.venv/bin/python -m running.coach --validate {active['id']}`"
    )
