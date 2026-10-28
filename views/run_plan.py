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
from running import coach, forecast, garmin_workout as gw, plan as planning, store, text, units
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
        tr(pl="Jeden plan przez wszystkie starty ze strony Zawody. Startuje od tego, co faktycznie biegasz, rośnie do "
              "szczytu dystansu (≤ 1,3× średniej z 4 tygodni), co 3.–4. tydzień odpuszcza i przed każdym startem "
              "schodzi z objętości. Tempa z aktualnej formy, nie z celu.",
           en="One plan through every race on the Races page. It starts from what you actually run, grows to the "
              "distance's peak (≤ 1.3× the 4-week average), backs off every 3rd–4th week and eases off before each "
              "race. Paces from your current form, not from the goal."),
    )
    frame = rc.guard()
    if frame is None:
        return
    active = rc.active_plan()  # first: rebuilt here when the races changed
    result = rc.current_forecast()
    with st.expander(tr(pl="Ustawienia planu", en="Plan settings") if active else tr(pl="Nowy plan", en="New plan"),
                     expanded=active is None):
        _create(frame, result, active)
    if active is None:
        return
    errors = store.validate_plan(active)
    if errors:
        st.error(tr(pl="Plik planu nie przechodzi walidacji: ", en="The plan file fails validation: ")
                 + " ".join(errors[:3]))
        return

    matched = planning.match(active, frame, laps=shell.table("run_laps"))
    _header(active, result, matched)
    _explain(active, result)
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


def _create(frame: pd.DataFrame, result: dict, active: dict | None) -> None:
    """One plan through every race ahead; here only what holds for the whole plan."""
    tr = i18n.tr
    if result.get("status") != "ok":
        st.warning(tr(pl="Bez prognozy formy nie da się dobrać temp: ",
                      en="Without a fitness forecast the paces cannot be set: ") + str(result.get("reason", "")))
        return
    races = rc.upcoming_races(dt.date.today() + dt.timedelta(days=1))
    if not races:
        st.info(tr(pl="Plan buduje się do startów — dodaj pierwszy na stronie Zawody.",
                   en="The plan builds toward races — add the first one on the Races page."))
        if st.button(tr(pl="Zawody →", en="Races →"), key="plan_to_races"):
            routing.goto("zawody")
        return
    st.markdown(tr(pl="**Cele** (ze strony Zawody; dodanie, zmiana albo usunięcie startu przebudowuje plan od jutra):",
                   en="**Goals** (from the Races page; adding, changing or removing a race rebuilds the plan from "
                      "tomorrow):"))
    st.markdown("\n".join(
        f"- **{r['name']}** · {rc.race_label(r['distance'])} · {dt.date.fromisoformat(r['date']):%d.%m.%Y} · "
        + tr(pl=f"priorytet {r.get('priority', 'A')}", en=f"priority {r.get('priority', 'A')}")
        + (tr(pl=" · cel ", en=" · goal ") + units.fmt_time(r["goal_s"]) if r.get("goal_s") else "")
        for r in races))
    st.caption(tr(pl="A — pełny taper i tydzień regeneracji po starcie; B i C — tylko lżejszy tydzień startu, "
                     "budowa idzie dalej.",
                  en="A — a full taper and a recovery week after the race; B and C — only a lighter race week, the "
                     "build goes on."))
    request = (active or {}).get("request", {})
    day_names = i18n.weekdays(long=True)
    with st.form("plan_create"):
        columns = st.columns(3)
        days = columns[0].multiselect(tr(pl="Dni biegowe", en="Running days"), list(range(7)),
                                      default=request.get("run_days") or [1, 3, 5, 6],
                                      format_func=lambda d: day_names[d])
        long_day = columns[1].selectbox(tr(pl="Dzień długiego biegu", en="Long run day"), list(range(7)),
                                        index=int(request.get("long_day", 6)), format_func=lambda d: day_names[d])
        cap = columns[2].number_input(tr(pl="Maks. km/tydz. (0 = auto)", en="Max km/week (0 = auto)"), min_value=0,
                                      max_value=200, value=int(request.get("max_weekly_km") or 0), step=5,
                                      help=tr(pl="Górna granica wynikająca z czasu, zdrowia, doświadczenia.",
                                              en="An upper limit set by time, health, experience."))
        submitted = st.form_submit_button(
            tr(pl="Przebuduj plan z tymi ustawieniami", en="Rebuild the plan with these settings") if active
            else tr(pl="Wygeneruj plan", en="Generate the plan"))
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
    if not 2 <= len(set(days)) <= 7:
        st.error(tr(pl="Wybierz od 2 do 7 dni biegowych w tygodniu.", en="Pick 2 to 7 running days a week."))
        return
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    settings = planning.PlanSettings(run_days=sorted(days), long_day=long_day, start=tomorrow,
                                     max_weekly_km=cap or None)
    goals = [planning.goal_of(r) for r in races]
    try:
        if active:
            active = {**active, "request": {**active["request"], "run_days": sorted(days), "long_day": long_day,
                                            "max_weekly_km": cap or None}}
            payload = planning.replan(active, frame, result, today=tomorrow, goals=goals)
        else:
            payload = planning.generate_goals(settings, goals, frame, result)
        store.save_only_plan(payload)
    except ValueError as error:
        st.error(str(error))
        return
    st.rerun()


# --------------------------------------------------------------------------
# reading the plan


def _header(active: dict, result: dict, matched: pd.DataFrame) -> None:
    goal = planning.next_goal(active)
    race_date = dt.date.fromisoformat(goal["date"])
    days = (race_date - dt.date.today()).days
    weeks = planning.week_table(active)
    build = weeks[weeks["phase"].isin(("base", "build", "peak"))] if not weeks.empty else weeks
    tr = i18n.tr
    columns = bento.row(1, 1, 1, 1)
    summary = planning.compliance(matched)
    left = (f"{days} {i18n.plural(days, pl=('dzień', 'dni', 'dni'), en=('day', 'days'))}" if days >= 0
            else tr(pl="po starcie", en="after the race"))
    bento.stat(columns[0], tr(pl="Do startu", en="To the race"), left, key="p_days",
               note=f"{goal.get('name') or rc.race_label(goal['distance'])} · {race_date:%d.%m.%Y}")
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
    now = result["distances"].get(goal["distance"]) if result.get("status") == "ok" else None
    then = f"{units.fmt_time(created.get('realistic_s'))} (VDOT {created.get('vdot')})"
    line = tr(pl=f"Prognoza przy tworzeniu planu: {then}", en=f"Forecast when the plan was made: {then}")
    if now:
        today = f"{units.fmt_time(now.realistic_s)} (VDOT {result['vdot']:.1f})"
        line += tr(pl=f" · dziś: {today}", en=f" · today: {today}")
    if goal.get("goal_s"):
        time = units.fmt_time(goal["goal_s"])
        line += tr(pl=f" · cel: {time}", en=f" · goal: {time}")
    st.caption(line + ".")
    for warning in text.warnings(active):
        st.warning(warning)


def _explain(active: dict, result: dict) -> None:
    """The rules, each with the runner's own numbers: what the plan does and why."""
    tr = i18n.tr
    base, weeks = active.get("baseline", {}), active.get("weeks", [])
    request = active["request"]
    built = [w for w in weeks if w["phase"] in ("base", "build", "peak")]
    if not built:
        return
    days = len(request.get("run_days") or [])
    first, peak = built[0], max(built, key=lambda w: w["volume_km"])
    longest = max(w["long_km"] for w in weeks)
    two = [w["week"] for w in weeks if planning.quality_count(days, w) == 2]
    lines = [
        tr(pl=f"**Start od Twojej realnej objętości.** Pierwszy tydzień budowy: {first['volume_km']:.0f} km; średnia "
              f"z Twoich ostatnich 4 tygodni: {base.get('weekly_km_4w', 0):.0f} km. Szczyt {peak['volume_km']:.0f} km "
              f"w tygodniu {peak['week']}; żaden tydzień nie przekracza 1,3× średniej z 4 poprzednich (ACWR — powyżej "
              "rośnie ryzyko kontuzji), co 3.–4. tydzień jest lżejszy.",
           en=f"**It starts from your real volume.** First build week: {first['volume_km']:.0f} km; your average over "
              f"the last 4 weeks: {base.get('weekly_km_4w', 0):.0f} km. Peak {peak['volume_km']:.0f} km in week "
              f"{peak['week']}; no week exceeds 1.3× the average of the 4 before it (ACWR — above that the injury risk "
              "rises), every 3rd–4th week is lighter."),
        tr(pl=f"**Jeden akcent + długi bieg w tygodniu.** Długi bieg to też mocny dzień (u Danielsa jeden z akcentów "
              f"tygodnia). Drugi akcent dopiero przy 5+ dniach biegowych i {planning.QUALITY_ROOM_KM:.0f}+ km — "
              f"biegasz {days} dni, więc inaczej 3 z {days} dni byłyby mocne"
              + (f" (dwa akcenty w tygodniach: {', '.join(map(str, two))})." if two else ".")
              + " Akcenty nigdy nie sąsiadują ze sobą ani z długim biegiem.",
           en="**One quality session + the long run a week.** The long run is a hard day too (Daniels counts it as one "
              f"of the week's quality sessions). A second one only with 5+ running days and "
              f"{planning.QUALITY_ROOM_KM:.0f}+ km — you run {days} days, otherwise 3 of {days} days would be hard"
              + (f" (two quality sessions in weeks: {', '.join(map(str, two))})." if two else ".")
              + " Quality sessions never sit next to each other or to the long run."),
        tr(pl="**Plan czyta Twoje biegi.** Akcent albo długi bieg zrobiony już w tym tygodniu liczy się do tygodnia, "
              "a akcent nie ląduje obok mocnego dnia, który naprawdę się odbył. Każda sesja, którą reguła zmieniła, "
              "ma przy sobie powód („Dlaczego tu”).",
           en="**The plan reads your runs.** A quality session or long run already done this week counts toward the "
              "week, and quality never lands next to a hard day that really happened. Every session a rule changed "
              "carries its reason (“Why here”)."),
        tr(pl=f"**Długi bieg** rośnie od {base.get('long_km_6w', 0):.0f} do {longest:.0f} km o 1–2 km na tydzień, "
              "maks. ~2,5 h.",
           en=f"**The long run** grows from {base.get('long_km_6w', 0):.0f} to {longest:.0f} km by 1–2 km a week, "
              "max. ~2.5 h."),
        tr(pl=f"**Wokół startów.** Długi bieg najpóźniej {planning.LONG_GAP_DAYS + 1} dni przed startem, akcent "
              f"najpóźniej {planning.QUALITY_GAP_DAYS + 1} dni przed. Dzień przed startem: "
              + (f"rozruch, jeśli to Twój dzień biegowy (biegasz {days} dni w tygodniu, wolne zmieniłoby rytm), "
                 "inaczej wolne." if days >= planning.SHAKEOUT_MIN_DAYS else
                 f"wolne — biegasz {days} dni w tygodniu, więc dzień przerwy przed startem to Twój zwykły rytm "
                 f"(rozruch dopiero przy {planning.SHAKEOUT_MIN_DAYS}+ dniach).")
              + " Po starcie krótkie biegi regeneracyjne, a akcent i długi bieg dopiero po jednym spokojnym dniu na "
              "każde 3 km startu. A: pełny taper dystansu i tydzień regeneracji po; B/C: lżejszy tydzień startu.",
           en=f"**Around races.** The long run at least {planning.LONG_GAP_DAYS + 1} days before a race, quality at "
              f"least {planning.QUALITY_GAP_DAYS + 1} days before. The day before: "
              + (f"a shakeout if it is one of your running days (you run {days} days a week, a day off would break "
                 "the rhythm), otherwise rest." if days >= planning.SHAKEOUT_MIN_DAYS else
                 f"rest — you run {days} days a week, so a day off before the race is your usual rhythm (a shakeout "
                 f"only with {planning.SHAKEOUT_MIN_DAYS}+ days).")
              + " After the race short recovery runs, and quality and the long run only after one easy day per 3 km "
              "raced. A: the distance's full taper and a recovery week after; B/C: a lighter race week."),
        tr(pl=f"**Tempa z dzisiejszej formy** (VDOT {active.get('forecast', {}).get('vdot')}), nie z celu. "
              "„Przebuduj od jutra” przelicza je z nowych danych; samopoczucie dnia ocenia rano decyzja na stronie "
              "Dziś (HRV, sen, tętno spoczynkowe).",
           en=f"**Paces from today's form** (VDOT {active.get('forecast', {}).get('vdot')}), not from the goal. "
              "“Rebuild from tomorrow” recalculates them from new data; how you feel on the day is judged each "
              "morning by the decision on the Today page (HRV, sleep, resting HR)."),
    ]
    frame = rc.runs()
    base_now = planning.baseline(frame, frame["day"].max(), result.get("vdot")) if result.get("status") == "ok" else None
    gains = []
    for race in rc.upcoming_races():
        item = result["distances"].get(race["distance"]) if base_now else None
        if item is None or not planning.covers(active, race):
            continue
        weeks_to = (dt.date.fromisoformat(race["date"]) - dt.date.today()).days / 7
        planned = planning.race_outlook(item, race, active, base_now, dt.date.today())
        steady = forecast.steady(item, weeks_to, base_now["consistency_8w"])
        if planned.target_s and steady.target_s:
            gains.append(f"{race['name']}: {units.fmt_time(planned.target_s)} "
                         + tr(pl=f"vs {units.fmt_time(steady.target_s)} jak teraz",
                              en=f"vs {units.fmt_time(steady.target_s)} as now"))
    if gains:
        lines.append(tr(pl="**Co daje plan** (prognoza na dzień startu): ", en="**What the plan adds** (race-day "
                                                                               "forecast): ") + " · ".join(gains)
                     + ".")
    with bento.panel(tr(pl="Jak działa ten plan", en="How this plan works"), key="plan_explain",
                     caption=tr(pl="Reguły z Twoimi liczbami — jeśli któraś nie pasuje, zmień ustawienia albo "
                                   "powiedz asystentowi (/trener).",
                                en="The rules with your numbers — if one does not fit, change the settings or tell "
                                   "the assistant (/trener).")):
        st.markdown("\n".join(f"- {line}" for line in lines))


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
            for line in text.why(session):
                st.caption(tr(pl="Dlaczego tu: ", en="Why here: ") + line)
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
            fresh = planning.replan(active, frame, result, today=dt.date.today() + dt.timedelta(days=1),
                                    goals=[planning.goal_of(r) for r in rc.upcoming_races()])
            store.save_only_plan(fresh)
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
