"""The data brief for an assistant, and a rule-based next-session suggestion.

There is no AI API in this project, and none is added: the assistant is
Claude Code working in this repository (see ``.claude/commands/trener.md``).
What the running module provides is the *contract*: one JSON brief with every
number an assistant should reason from -- forecast with its inputs, recent
sessions with their labels and reasons, load, recovery signals, the plan and
how it is being executed, and an explicit list of what is missing -- plus a
validated plan format it may edit. Recommendations made from the brief are
then grounded in the same numbers the dashboard shows.

``python -m running.coach``            prints the brief as Markdown
``python -m running.coach --json``     prints it as JSON
``python -m running.coach --validate PLAN_ID``  checks an edited plan file
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any

import pandas as pd

import i18n
from running import forecast, physio, plan as planning, sessions, store, text, units

LOW_READINESS = ("LOW", "POOR")
LOW_HRV = ("LOW", "UNBALANCED", "POOR")


def recovery_signals(daily: pd.DataFrame, today: dt.date) -> dict[str, Any]:
    """Last recorded day's recovery numbers, with the flags they raise."""
    if daily is None or daily.empty:
        return {"available": False, "flags": []}
    frame = daily[pd.to_datetime(daily["day"]).dt.date <= today].sort_values("day")
    frame = frame.dropna(subset=[c for c in ("readiness", "sleep_h", "hrv_status") if c in frame.columns], how="all")
    if frame.empty:
        return {"available": False, "flags": []}
    row = frame.iloc[-1]

    def value(column: str) -> Any:
        if column not in row.index or pd.isna(row[column]):
            return None
        item = row[column]
        return item.item() if hasattr(item, "item") else item

    out = {
        "available": True,
        "day": str(pd.Timestamp(row["day"]).date()),
        "readiness": value("readiness"),
        "readiness_level": value("readiness_level"),
        "hrv_status": value("hrv_status"),
        "hrv_deviation": value("hrv_deviation"),
        "rhr_deviation": value("rhr_deviation"),
        "sleep_h": value("sleep_h"),
        "sleep_score": value("sleep_score"),
        "bb_wake": value("bb_wake"),
    }
    tr = i18n.tr
    flags = []
    if out["readiness_level"] in LOW_READINESS or (out["readiness"] is not None and out["readiness"] < 35):
        level = out["readiness_level"]
        flags.append(tr(pl=f"gotowość Garmina {out['readiness']:.0f} ({level})",
                        en=f"Garmin readiness {out['readiness']:.0f} ({level})")
                     if out["readiness"] is not None else tr(pl=f"gotowość {level}", en=f"readiness {level}"))
    if out["hrv_status"] in LOW_HRV:
        flags.append(tr(pl=f"status HRV: {out['hrv_status']}", en=f"HRV status: {out['hrv_status']}"))
    if out["sleep_h"] is not None and out["sleep_h"] < 6:
        flags.append(tr(pl=f"sen {out['sleep_h']:.1f} h", en=f"sleep {out['sleep_h']:.1f} h"))
    if out["rhr_deviation"] is not None and out["rhr_deviation"] >= 4:
        rise = f"+{out['rhr_deviation']:.0f} bpm"
        flags.append(tr(pl=f"tętno spoczynkowe {rise} ponad średnią 7 d",
                        en=f"resting heart rate {rise} above the 7-day average"))
    out["flags"] = flags
    out["stale_days"] = (today - pd.Timestamp(row["day"]).date()).days
    return out


def spike_check(session: dict[str, Any], runs: pd.DataFrame, today: dt.date) -> dict[str, Any] | None:
    """When the plan assumed runs that did not happen, its next run can be a
    spike against the real record: the cap and a sentence saying so."""
    if session["type"] in ("race", "strength", "rest") or not session.get("distance_km"):
        return None
    date = dt.date.fromisoformat(session["date"])
    history = planning.run_history(runs, min(date, today + dt.timedelta(days=1)))
    longest, cap = planning.spike_cap(history, date)
    if session["distance_km"] <= cap + 0.05:
        return None
    tr = i18n.tr
    km, top, limit = f"{session['distance_km']:.1f}", f"{longest:.1f}", f"{cap:.1f}"
    return {"longest_km": round(longest, 1), "cap_km": round(cap, 1), "reason": tr(
        pl=f"Skróć do {limit} km (plan: {km} km): najdłuższy bieg z ostatnich 30 dni to {top} km, a pojedynczy bieg "
           "dłuższy o ponad 10% zwiększa ryzyko przeciążenia. Plan zakładał biegi, których nie było — "
           "„Przebuduj od jutra” dopasuje resztę.",
        en=f"Cut it to {limit} km (plan: {km} km): the longest run of the last 30 days is {top} km, and a single run "
           "more than 10% longer raises the risk of an overuse injury. The plan assumed runs that did not happen — "
           "“Rebuild from tomorrow” will fit the rest.")}


def load_signals(runs: pd.DataFrame, today: dt.date) -> dict[str, Any]:
    end = pd.Timestamp(today)
    if runs is None or runs.empty:
        return {"km_7d": 0.0, "km_28d_weekly": 0.0, "ratio": None}
    last7 = runs[(runs["day"] > end - pd.Timedelta(days=7)) & (runs["day"] <= end)]
    last28 = runs[(runs["day"] > end - pd.Timedelta(days=28)) & (runs["day"] <= end)]
    chronic = float(last28["distance_km"].sum()) / 4
    hard = runs[runs["kind"].isin(sessions.HARD_KINDS) & (runs["day"] <= end)] if "kind" in runs else runs.iloc[0:0]
    longs = runs[(runs["kind"] == "long") & (runs["day"] <= end)] if "kind" in runs else runs.iloc[0:0]
    tomorrow = today + dt.timedelta(days=1)
    longest, cap = planning.spike_cap(planning.run_history(runs, tomorrow), tomorrow)
    return {
        "km_7d": round(float(last7["distance_km"].sum()), 1),
        "km_28d_weekly": round(chronic, 1),
        "ratio": round(float(last7["distance_km"].sum()) / chronic, 2) if chronic > 0 else None,
        "hard_7d": int(last7["kind"].isin(sessions.HARD_KINDS).sum()) if "kind" in last7 else 0,
        "days_since_hard": int((end - hard["day"].max()).days) if not hard.empty else None,
        "days_since_long": int((end - longs["day"].max()).days) if not longs.empty else None,
        "days_since_run": int((end - runs[runs["day"] <= end]["day"].max()).days) if (runs["day"] <= end).any() else None,
        # The rule the plan keeps (Garmin-RUNSAFE): tomorrow's run at most 1.1x the longest of 30 days.
        "longest_30d_km": round(longest, 1),
        "next_run_cap_km": round(cap, 1),
    }


def next_session(
    active_plan: dict[str, Any] | None,
    runs: pd.DataFrame,
    daily: pd.DataFrame,
    result: dict[str, Any],
    today: dt.date | None = None,
) -> dict[str, Any]:
    """What to do next, with the reasons. Never more than the plan asked for."""
    tr = i18n.tr
    today = today or dt.date.today()
    recovery = recovery_signals(daily, today)
    load = load_signals(runs, today)
    reasons: list[str] = []
    # The 7:28-day ratio is not a recovery signal: in Garmin-RUNSAFE (BJSM 2025) it did not predict
    # injury, a single run over 1.1x the longest of 30 days did -- spike_check handles that.
    flags = list(recovery.get("flags", [])) if recovery.get("stale_days", 99) <= 1 else []

    session = None
    strength = None
    if active_plan:
        upcoming = [s for s in active_plan.get("sessions", [])
                    if s["date"] >= today.isoformat() and s.get("status") == "planned"
                    and s["type"] not in ("rest", "strength")]
        session = upcoming[0] if upcoming else None
        if session is not None:
            strength = next((s for s in active_plan.get("sessions", []) if s["type"] == "strength"
                             and s["date"] == session["date"] and s.get("status") == "planned"), None)

    if session is not None:
        hard = session["type"] in ("tempo", "threshold", "intervals", "long")
        if session["date"] > today.isoformat():
            # Tonight's sleep decides that day, not this morning's numbers.
            action = "decyzja rano"
            if hard and flags:
                reasons.append(tr(
                    pl=f"Dziś bez treningu. Regeneracja jest słabsza ({len(flags)} sygn.) — jeśli rano w dniu sesji "
                       "będzie podobnie, zamień ją na spokojny albo przesuń.",
                    en=f"No session today. Recovery is weaker ({len(flags)} signals) — if the morning of the session "
                       "looks the same, swap it for an easy run or move it."))
            else:
                reasons.append(tr(pl="Dziś bez treningu. Decyzja zapadnie rano w dniu sesji, po nocnych danych.",
                                  en="No session today. The decision is made on the morning of the session, after "
                                     "the night's data."))
        elif hard and len(flags) >= 2:
            action = "zamień na spokojny"  # i18n: key
            reasons.append(tr(
                pl="Dwa lub więcej sygnałów słabej regeneracji przy mocnej sesji w planie: jakość po złej nocy daje "
                   "mniej bodźca i więcej zmęczenia. Przesuń ją o 1–2 dni.",
                en="Two or more signals of weak recovery with a hard session planned: quality after a bad night "
                   "gives less stimulus and more fatigue. Move it by 1–2 days."))
        elif hard and flags:
            action = "jak w planie, z kontrolą"  # i18n: key
            reasons.append(tr(
                pl="Jeden sygnał słabszej regeneracji. Zacznij rozgrzewkę; jeśli tętno na spokojnym truchcie jest "
                   "wyraźnie wyższe niż zwykle, zrób wersję spokojną.",
                en="One signal of weaker recovery. Start the warm-up; if your heart rate on an easy jog is clearly "
                   "higher than usual, do the easy version."))
        elif load.get("days_since_hard") in (0, 1) and hard:
            action = "przesuń"  # i18n: key
            when = tr(pl="dziś", en="today") if load["days_since_hard"] == 0 else tr(pl="wczoraj", en="yesterday")
            reasons.append(tr(pl=f"Mocny trening był {when} — dwa mocne dni pod rząd to kumulacja zmęczenia, nie "
                                 "więcej formy.",
                              en=f"There was a hard session {when} — two hard days in a row pile up fatigue, not "
                                 "fitness."))
        else:
            action = "jak w planie"
            reasons.append(tr(pl="Brak sygnałów przeciw: regeneracja i obciążenie w normie.",
                              en="No signals against: recovery and load are normal."))
        spike = spike_check(session, runs, today)
        if spike:
            reasons.append(spike["reason"])
        if strength is not None:
            if action in ("zamień na spokojny", "przesuń"):  # i18n: key
                reasons.append(tr(pl="Siłownia z tego dnia też odpada — wraca z następnym akcentem.",
                                  en="That day's strength session goes too — it returns with the next quality day."))
            else:
                reasons.append(tr(pl=f"Po biegu: {strength.get('title')} (ok. {strength.get('duration_min')} min).",
                                  en=f"After the run: {strength.get('title')} (about {strength.get('duration_min')} "
                                     "min)."))
        reasons = text.why(session) + reasons
        return {"source": "plan", "session": session, "today": session["date"] == today.isoformat(),
                "action": action, "reasons": reasons, "flags": flags, "strength": strength, "spike": spike,
                "recovery": recovery, "load": load}

    # No plan: a suggestion from the record alone.
    paces = physio.training_paces(result.get("vdot")) if result.get("status") == "ok" else {}
    recent = runs[runs["day"] > pd.Timestamp(today) - pd.Timedelta(days=28)] if not runs.empty else runs
    easy_km = float(recent.loc[recent["kind"].isin(("easy", "recovery")), "distance_km"].median()) \
        if len(recent) and (recent["kind"].isin(("easy", "recovery"))).any() else 5.0
    if flags:
        kind, why = "easy", tr(pl="Sygnały słabszej regeneracji: ", en="Signals of weaker recovery: ") \
            + ", ".join(flags) + "."
    elif (load.get("days_since_hard") or 99) >= 3 and load.get("hard_7d", 0) < 2:
        days = load.get("days_since_hard")
        kind, why = "threshold", tr(pl=f"Ostatni mocny trening {days} dni temu, regeneracja w normie — miejsce na "
                                       "jakość.",
                                    en=f"The last hard session was {days} days ago, recovery is normal — room for "
                                       "quality.")
    elif (load.get("days_since_long") or 99) >= 7:
        days = load.get("days_since_long") or "—"
        kind, why = "long", tr(pl=f"Ostatnie długie wybieganie {days} dni temu.",
                               en=f"The last long run was {days} days ago.")
    else:
        kind, why = "easy", tr(pl="Po mocnych dniach — objętość tlenowa w spokojnym tempie.",
                               en="After hard days — aerobic volume at an easy pace.")
    band = paces.get({"easy": "E", "long": "E", "threshold": "T"}[kind])
    km = {"easy": easy_km, "long": max(easy_km * 1.5, 8.0), "threshold": easy_km + 2}[kind]
    suggestion = {
        "date": today.isoformat(),
        "type": kind,
        "title": f"{text.kind_label(kind).capitalize()} ~{km:.0f} km",
        "distance_km": round(km, 1),
        "pace_lo": band[0] if band else None,
        "pace_hi": band[1] if band else None,
        "main": tr(pl="3×10 min w tempie T, 1 min truchtu", en="3×10 min at T pace, 1 min jog")
        if kind == "threshold" else tr(pl=f"{km:.0f} km spokojnie", en=f"{km:.0f} km easy"),
    }
    return {"source": "dane", "session": suggestion, "today": True, "action": "propozycja", "reasons": [why],
            "flags": flags, "recovery": recovery, "load": load}


def observations(runs: pd.DataFrame, history: pd.DataFrame, today: dt.date) -> list[str]:
    """Three to five plain sentences on form, regularity, load and balance."""
    if runs is None or runs.empty:
        return []
    tr = i18n.tr
    out = []
    end = pd.Timestamp(today)
    if history is not None and not history.empty:
        ten = history[history["distance"] == "10k"].sort_values("day")
        if len(ten) >= 2:
            change = forecast.trend(history, "10k", 8)
            vdot_now = float(ten.iloc[-1]["vdot"])
            if change is not None:
                head = tr(pl=f"Forma (VDOT {vdot_now:.1f}): prognoza na 10 km w 8 tygodni ",
                          en=f"Form (VDOT {vdot_now:.1f}): the 10 km forecast over 8 weeks ")
                delta = units.fmt_delta(change)
                if change < -15:
                    tail = tr(pl=f"{delta} — szybciej.", en=f"{delta} — faster.")
                elif change > 15:
                    tail = tr(pl=f"{delta} — wolniej.", en=f"{delta} — slower.")
                else:
                    tail = tr(pl="bez wyraźnej zmiany.", en="no clear change.")
                out.append(head + tail)
    weeks = sessions.weekly(runs, end).tail(8)
    if len(weeks) >= 4:
        regular, count = int((weeks["runs"] >= 3).sum()), len(weeks)
        mean, last = f"{weeks['km'].mean():.0f}", f"{weeks['km'].iloc[-2]:.0f}"
        out.append(tr(pl=f"Regularność: {regular} z ostatnich {count} tygodni miało ≥ 3 biegi; średnio {mean} km/tydz., "
                         f"ostatni pełny tydzień {last} km.",
                      en=f"Consistency: {regular} of the last {count} weeks had ≥ 3 runs; {mean} km/week on average, "
                         f"the last full week {last} km."))
        empty = int((weeks["runs"] == 0).sum())
        if empty:
            out.append(tr(pl=f"{empty} z 8 tygodni bez biegania — przerwy kosztują więcej niż pojedyncze słabsze "
                             "treningi.",
                          en=f"{empty} of 8 weeks without running — breaks cost more than single weaker sessions."))
    load = load_signals(runs, today)
    if load.get("ratio") is not None:
        km7, km28, ratio = f"{load['km_7d']:.0f}", f"{load['km_28d_weekly']:.0f}", f"{load['ratio']:.2f}"
        out.append(tr(pl=f"Obciążenie: {km7} km w 7 dni wobec {km28} km/tydz. z 28 dni (iloraz {ratio} — informacyjnie, "
                         "nie przewiduje kontuzji).",
                      en=f"Load: {km7} km in 7 days against {km28} km/week over 28 days (ratio {ratio} — for "
                         "information, it does not predict injury)."))
    if load.get("longest_30d_km"):
        longest, cap = f"{load['longest_30d_km']:.1f}", f"{load['next_run_cap_km']:.1f}"
        out.append(tr(pl=f"Najdłuższy bieg z 30 dni: {longest} km — kolejny bieg najwyżej {cap} km (reguła 1,1×).",
                      en=f"Longest run of 30 days: {longest} km — the next run at most {cap} km (the 1.1× rule)."))
    recent = runs[runs["day"] > end - pd.Timedelta(days=28)]
    if len(recent) >= 4 and "kind" in recent:
        hard_km = float(recent.loc[recent["kind"].isin(sessions.HARD_KINDS), "distance_km"].sum())
        share = f"{1 - hard_km / float(recent['distance_km'].sum()):.0%}"
        low = 1 - hard_km / float(recent["distance_km"].sum()) < 0.7
        out.append(tr(pl=f"Balans: {share} kilometrów z 4 tygodni to biegi spokojne", en=f"Balance: {share} of the "
                                                                                         "kilometres in 4 weeks were "
                                                                                         "easy runs")
                   + (tr(pl=" — mniej niż typowe ~75–80%.", en=" — less than the typical ~75–80%.") if low else "."))
    return out


def data_gaps(runs: pd.DataFrame, daily: pd.DataFrame, result: dict[str, Any],
              laps: pd.DataFrame | None = None) -> list[str]:
    """What the analysis cannot see -- said explicitly so nobody fills it in."""
    tr = i18n.tr
    gaps = []
    if runs is None or runs.empty:
        return [tr(pl="Brak biegów.", en="No runs.")]
    recent = runs[runs["day"] > runs["day"].max() - pd.Timedelta(days=90)]
    if recent["avg_hr"].isna().mean() > 0.3:
        gaps.append(tr(pl="Ponad 30% biegów z 90 dni nie ma tętna — klasyfikacja i trend tętna są mniej pewne.",
                       en="Over 30% of the runs in 90 days have no heart rate — the classification and the heart "
                          "rate trend are less certain."))
    if not (runs.get("kind") == "race").any():
        gaps.append(tr(pl="Żaden bieg nie jest oznaczony jako start — prognoza opiera się na odcinkach treningowych. "
                          "Wynik z zawodów dopisz na stronie Zawody (powiązanie z aktywnością).",
                       en="No run is marked as a race — the forecast rests on training stretches. Add a race result "
                          "on the Races page (linked to the activity)."))
    gaps.append(tr(pl="Odczuwane zmęczenie (RPE), ból i dolegliwości nie są zapisywane — nie ma ich w Garminie.",
                   en="Perceived exertion (RPE), pain and complaints are not recorded — Garmin does not have them."))
    if laps is None or laps.empty:
        gaps.append(tr(pl="Okrążenia (laps) nie są pobrane — uruchom aktualizację; do tego czasu splity kilometrowe "
                          "są ze strumienia ~400 próbek (dokładność kilku sekund), a odcinki workoutów nieocenione.",
                       en="Laps are not fetched — run an update; until then kilometre splits come from a stream of "
                          "~400 samples (a few seconds of accuracy) and workout reps are not assessed."))
    else:
        gaps.append(tr(pl="Splity kilometrowe są ze strumienia ~400 próbek (kilka sekund dokładności). Dokładne są "
                          "tylko okrążenia — odcinki workoutów z zegarka (`reps_*` w realizacji planu).",
                       en="Kilometre splits come from a stream of ~400 samples (a few seconds of accuracy). Only "
                          "laps are exact — the watch workout reps (`reps_*` in the plan's execution)."))
    if daily is None or daily.empty or "hrv_status" not in daily.columns:
        gaps.append(tr(pl="Brak HRV / gotowości — sygnały regeneracji pominięte.",
                       en="No HRV / readiness — recovery signals skipped."))
    if result.get("status") != "ok":
        gaps.append(str(result.get("reason")))
    return gaps


def _present(value: Any) -> bool:
    """Drops the NaN a rep column has for sessions without laps."""
    return isinstance(value, list) or not pd.isna(value)


def _session_brief(session: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "date", "type", "title", "distance_km", "pace_lo", "pace_hi", "hr", "main", "status", "note")
    out = {k: session.get(k) for k in keys}
    out["pace"] = (f"{units.fmt_pace(session.get('pace_lo'), False)}–{units.fmt_pace(session.get('pace_hi'))}"
                   if session.get("pace_lo") else None)
    if session.get("why"):
        out["why"] = text.why(session)
    return out


def brief(
    runs: pd.DataFrame,
    efforts: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    today: dt.date | None = None,
    plan_id: str | None = None,
    laps: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Everything an assistant needs, as plain JSON-serialisable data."""
    today = today or dt.date.today()
    hr_max = float(runs["hr_max_used"].dropna().iloc[0]) if "hr_max_used" in runs and runs["hr_max_used"].notna().any() else None
    races = sorted((r for r in store.races() if r.get("date", "") >= today.isoformat()), key=lambda r: r["date"])
    result = forecast.forecast(runs, efforts, daily, hr_max=hr_max)

    active = store.plan(plan_id) if plan_id else store.current_plan()
    if active is not None and planning.next_goal(active, today) is None and not plan_id:
        active = None
    base = planning.baseline(runs, runs["day"].max(), result.get("vdot")) if not runs.empty else {}

    out: dict[str, Any] = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "data_through": str(runs["day"].max().date()) if not runs.empty else None,
        "athlete": {
            "hr_max_bpm": hr_max,
            "hr_rest_bpm": physio.resting_hr(daily),
            "vdot": None if result.get("status") != "ok" else round(result["vdot"], 1),
            "training_paces_min_km": {
                k: [units.fmt_pace(a, False), units.fmt_pace(b, False)]
                for k, (a, b) in physio.training_paces(result.get("vdot")).items()
            } if result.get("status") == "ok" else {},
        },
        "forecast": _forecast_brief(result),
        "recent_runs": [
            {
                "date": str(r.day.date()), "activity_id": int(r.activity_id), "name": r.name,
                "kind": r.kind, "kind_reason": text.reason(r.kind_reason), "km": round(float(r.distance_km), 2),
                "pace": units.fmt_pace(r.pace_min_km, False),
                "avg_hr": None if pd.isna(r.avg_hr) else int(r.avg_hr),
                "training_load": None if pd.isna(r.training_load) else round(float(r.training_load)),
            }
            for r in runs[runs["day"] > pd.Timestamp(today) - pd.Timedelta(days=21)].itertuples(index=False)
        ],
        "weekly": [
            {"week": w.iso_week, "km": w.km, "runs": int(w.runs), "hard": int(w.hard), "long_km": w.long_km}
            for w in sessions.weekly(runs, pd.Timestamp(today)).tail(8).itertuples(index=False)
        ],
        "load": load_signals(runs, today),
        "recovery": recovery_signals(daily, today),
        "races": [{**race, **_race_target(race, result, active, base, today)} for race in races],
        "plan": None,
        "next_session": None,
        "data_gaps": data_gaps(runs, daily, result, laps),
        "how_to_change_the_plan": i18n.tr(
            pl="Plan to plik data/coach/plans/<id>.json. Zmieniaj tylko sesje z datą >= dziś; pola: type ∈ "
               + ", ".join(store.SESSION_TYPES) + ", distance_km, pace_lo/pace_hi (min/km), note, text (opis "
               "sesji jako kod: {key: easy|recovery|long|threshold|intervals|tempo|race|…, parametry} albo własny "
               "{key: custom, pl: {title, warmup, main, cooldown, purpose}, en: {…}} — zawsze w obu językach), "
               "steps (kroki dla zegarka: [{kind: warmup|run|recovery|cooldown, km albo s, pace: [lo, hi]}, "
               "{kind: repeat, reps, steps: [...]}] — zmieniając sesję, zmień też steps, inaczej zegarek dostanie "
               "starą wersję). Po edycji: .venv/bin/python -m running.coach --validate <id>.",
            en="The plan is the file data/coach/plans/<id>.json. Change only sessions dated >= today; fields: type ∈ "
               + ", ".join(store.SESSION_TYPES) + ", distance_km, pace_lo/pace_hi (min/km), note, text (the "
               "session description as a code: {key: easy|recovery|long|threshold|intervals|tempo|race|…, "
               "parameters} or your own {key: custom, pl: {title, warmup, main, cooldown, purpose}, en: {…}} — "
               "always in both languages), steps (watch steps: [{kind: warmup|run|recovery|cooldown, km or s, pace: "
               "[lo, hi]}, {kind: repeat, reps, steps: [...]}] — when changing a session change its steps too, or "
               "the watch gets the old version). After editing: .venv/bin/python -m running.coach --validate <id>.",
        ),
    }
    if active:
        matched = planning.match(active, runs, today, laps=laps)
        out["plan"] = {
            "id": active["id"],
            "name": active.get("name"),
            "goals": planning.plan_goals(active),
            "next_goal": planning.next_goal(active, today),
            "goals_out_of_date": planning.stale(active, races, today),
            "compliance": planning.compliance(matched),
            "last_14_days": [
                {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in row.items()
                 if k in ("date", "type", "title", "planned_km", "actual_km", "actual_kind", "effective",
                          "reps_planned", "reps_done", "reps_on_pace", "rep_paces") and _present(v)}
                for row in matched[(matched["date"] < today) & (matched["date"] >= today - dt.timedelta(days=14))]
                .to_dict("records")
            ] if not matched.empty else [],
            "upcoming": [_session_brief(s) for s in active.get("sessions", []) if s["date"] >= today.isoformat()][:10],
            "warnings": text.warnings(active),
        }
    suggestion = next_session(active, runs, daily, result, today)
    out["next_session"] = {**suggestion, "session": _session_brief(suggestion["session"]) if suggestion.get("session") else None}
    return out


def _race_target(race: dict[str, Any], result: dict[str, Any], plan: dict[str, Any] | None,
                 base: dict[str, Any], today: dt.date) -> dict[str, Any]:
    """Race-day target: after the plan when it covers the race ("plan"), else
    with the current training going on ("steady")."""
    item = result["distances"].get(race["distance"]) if result.get("status") == "ok" else None
    if item is None or not base:
        return {"target": None, "target_basis": None}
    item = planning.race_outlook(item, race, plan, base, today)
    return {"target": units.fmt_time(item.target_s) if item.target_s else None, "target_basis": item.target_basis}


def _forecast_brief(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "ok":
        return {"status": "insufficient", "reason": result.get("reason")}
    perf = result.get("perf") or {}
    return {
        "status": "ok",
        "vdot": round(result["vdot"], 1),
        "weights": result["weights"],
        "anchor_effort": {
            "date": str(perf["day"].date()) if perf.get("day") is not None else None,
            "distance_m": perf.get("distance_m"),
            "time": units.fmt_time(perf.get("seconds")),
            "near_max": perf.get("near_max"),
            "source": text.source(perf.get("source")),
            "hr_frac": None if perf.get("hr_frac") is None else round(perf["hr_frac"], 3),
            "age_days": perf.get("age_days"),
        } if perf else None,
        "notes": result.get("notes", []),
        "distances": {
            key: {
                "realistic": units.fmt_time(item.realistic_s),
                "range_80": [units.fmt_time(item.low_s), units.fmt_time(item.high_s)],
                "potential": units.fmt_time(item.potential_s),
                "pace": units.fmt_pace(item.pace, False),
                "confidence": item.confidence,
                "preparation": item.prep,
                "methods": {k: units.fmt_time(v) if v else None for k, v in item.methods.items()},
                "warnings": item.warnings,
            }
            for key, item in result["distances"].items()
        },
    }


def markdown(data: dict[str, Any]) -> str:
    """The brief as text to paste into a conversation."""
    tr = i18n.tr
    today, through = data["today"], data["data_through"]
    lines = [tr(pl=f"# Brief treningowy — {today} (dane do {through})",
                en=f"# Training brief — {today} (data through {through})"), ""]
    athlete = data["athlete"]
    lines.append(tr(pl=f"HRmax {athlete['hr_max_bpm']} · HRspocz {athlete['hr_rest_bpm']} · VDOT {athlete['vdot']}",
                    en=f"HRmax {athlete['hr_max_bpm']} · HRrest {athlete['hr_rest_bpm']} · VDOT {athlete['vdot']}"))
    if athlete["training_paces_min_km"]:
        lines.append(tr(pl="Tempa: ", en="Paces: ")
                     + ", ".join(f"{k} {a}–{b}" for k, (a, b) in athlete["training_paces_min_km"].items()))
    lines += ["", tr(pl="## Prognoza", en="## Forecast")]
    fc = data["forecast"]
    if fc["status"] == "ok":
        for key, item in fc["distances"].items():
            band = f"{item['range_80'][0]}–{item['range_80'][1]}"
            sure, prep = text.confidence_label(item["confidence"]), f"{item['preparation']['score']:.2f}"
            lines.append(tr(pl=f"- {text.race_label(key)}: {item['realistic']} ({band}, pewność {sure}), potencjał "
                               f"{item['potential']}, przygotowanie {prep}",
                            en=f"- {text.race_label(key)}: {item['realistic']} ({band}, confidence {sure}), potential "
                               f"{item['potential']}, preparation {prep}"))
        lines += [tr(pl=f"- uwaga: {note}", en=f"- note: {note}") for note in fc["notes"]]
    else:
        lines.append(tr(pl=f"- brak: {fc['reason']}", en=f"- none: {fc['reason']}"))
    if data["races"]:
        lines += ["", tr(pl="## Starty (cele planu)", en="## Races (the plan's goals)")]
        for race in data["races"]:
            goal = race.get("goal_s") and units.fmt_time(race["goal_s"])
            basis = {"plan": tr(pl="po planie", en="after the plan"),
                     "steady": tr(pl="przy obecnym treningu", en="with the current training")}.get(race["target_basis"])
            target = f"{race['target']} ({basis})" if race["target"] else "—"
            lines.append(tr(pl=f"- {race['date']} {race['name']} — {text.race_label(race['distance'])}, priorytet "
                               f"{race.get('priority', 'A')}, cel {goal or '—'}, na dzień startu {target}",
                            en=f"- {race['date']} {race['name']} — {text.race_label(race['distance'])}, priority "
                               f"{race.get('priority', 'A')}, goal {goal or '—'}, on race day {target}"))
    lines += ["", tr(pl="## Obciążenie i regeneracja", en="## Load and recovery"),
              f"- {json.dumps(data['load'], ensure_ascii=False)}",
              f"- {json.dumps(data['recovery'], ensure_ascii=False, default=str)}", "",
              tr(pl="## Ostatnie 21 dni", en="## The last 21 days")]
    for run in data["recent_runs"]:
        lines.append(f"- {run['date']} {run['kind']} {run['km']} km @ {run['pace']} HR {run['avg_hr']} — {run['kind_reason']}")
    if data["plan"]:
        plan = data["plan"]
        lines += ["", f"## Plan: {plan['name']} ({plan['id']})",
                  tr(pl="- realizacja: ", en="- completion: ") + json.dumps(plan["compliance"], ensure_ascii=False)]
        for session in plan["upcoming"]:
            lines.append(f"- {session['date']} {session['type']}: {session['title']} — {session['main']}")
    nxt = data["next_session"]
    if nxt and nxt.get("session"):
        lines += ["", tr(pl="## Następny trening", en="## Next session"),
                  f"- {text.action_label(nxt['action'])}: {nxt['session']['title']}"]
        lines += [f"- {reason}" for reason in nxt["reasons"]]
    lines += ["", tr(pl="## Czego dane nie widzą", en="## What the data cannot see")] \
        + [f"- {gap}" for gap in data["data_gaps"]]
    lines += ["", data["how_to_change_the_plan"]]
    return "\n".join(lines)


def load_warehouse() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Materialised running tables, typed (for the CLI and the pages)."""
    import db  # repository root module; imported lazily to keep the package pure

    runs = db.table("run_sessions")
    efforts = db.table("run_efforts")
    daily = db.table("daily")
    for frame in (runs, efforts, daily):
        if not frame.empty and "day" in frame.columns:
            frame["day"] = pd.to_datetime(frame["day"])
    if not runs.empty:
        runs["start_local"] = pd.to_datetime(runs["start_local"])
    return runs, efforts, daily


def main(argv: list[str] | None = None) -> int:
    tr = i18n.tr
    parser = argparse.ArgumentParser(description=tr(pl="Brief treningowy dla asystenta",
                                                    en="The training brief for the assistant"))
    parser.add_argument("--json", action="store_true", help=tr(pl="wypisz JSON zamiast Markdown",
                                                               en="print JSON instead of Markdown"))
    parser.add_argument("--plan", help=tr(pl="id planu (domyślnie: bieżący plan)",
                                          en="plan id (default: the current plan)"))
    parser.add_argument("--validate", metavar="PLAN_ID", help=tr(pl="sprawdź plik planu i zakończ",
                                                                 en="check a plan file and exit"))
    parser.add_argument("--lang", choices=list(i18n.LANGS),
                        help=tr(pl="język briefu (domyślnie: wybrany w aplikacji)",
                                en="the brief's language (default: the one chosen in the app)"))
    args = parser.parse_args(argv)
    if args.lang:
        i18n.force(args.lang)
    if args.validate:
        payload = store.plan(args.validate)
        if payload is None:
            print(tr(pl=f"Nie ma planu {args.validate} w {store.PLANS}", en=f"No plan {args.validate} in {store.PLANS}"))
            return 1
        errors = store.validate_plan(payload)
        if not errors:
            runs, _, _ = load_warehouse()
            errors = [tr(pl=f"{item['date']}: {item['km']:g} km > {item['cap']:g} km (1,1× najdłuższego z 30 dni: "
                            f"{item['longest']:g} km) — skróć albo wydłuż wcześniejsze biegi.",
                         en=f"{item['date']}: {item['km']:g} km > {item['cap']:g} km (1.1× the longest of 30 days: "
                            f"{item['longest']:g} km) — shorten it or lengthen the runs before.")
                      for item in planning.spikes(payload, runs)]
        print("OK" if not errors else "\n".join(errors))
        return 0 if not errors else 1
    runs, efforts, daily = load_warehouse()
    if runs.empty:
        print(tr(pl="Brak tabeli run_sessions — uruchom analytics.py.", en="No run_sessions table — run analytics.py."))
        return 1
    import db

    data = brief(runs, efforts, daily, plan_id=args.plan, laps=db.table("run_laps"))
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str) if args.json else markdown(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
