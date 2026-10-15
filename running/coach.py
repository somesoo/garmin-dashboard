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

from running import forecast, physio, plan as planning, sessions, store, units

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
    flags = []
    if out["readiness_level"] in LOW_READINESS or (out["readiness"] is not None and out["readiness"] < 35):
        flags.append(f"gotowość Garmina {out['readiness']:.0f} ({out['readiness_level']})"
                     if out["readiness"] is not None else f"gotowość {out['readiness_level']}")
    if out["hrv_status"] in LOW_HRV:
        flags.append(f"status HRV: {out['hrv_status']}")
    if out["sleep_h"] is not None and out["sleep_h"] < 6:
        flags.append(f"sen {out['sleep_h']:.1f} h")
    if out["rhr_deviation"] is not None and out["rhr_deviation"] >= 4:
        flags.append(f"tętno spoczynkowe +{out['rhr_deviation']:.0f} bpm ponad średnią 7 d")
    out["flags"] = flags
    out["stale_days"] = (today - pd.Timestamp(row["day"]).date()).days
    return out


def load_signals(runs: pd.DataFrame, today: dt.date) -> dict[str, Any]:
    end = pd.Timestamp(today)
    if runs is None or runs.empty:
        return {"km_7d": 0.0, "km_28d_weekly": 0.0, "ratio": None}
    last7 = runs[(runs["day"] > end - pd.Timedelta(days=7)) & (runs["day"] <= end)]
    last28 = runs[(runs["day"] > end - pd.Timedelta(days=28)) & (runs["day"] <= end)]
    chronic = float(last28["distance_km"].sum()) / 4
    hard = runs[runs["kind"].isin(sessions.HARD_KINDS) & (runs["day"] <= end)] if "kind" in runs else runs.iloc[0:0]
    longs = runs[(runs["kind"] == "long") & (runs["day"] <= end)] if "kind" in runs else runs.iloc[0:0]
    return {
        "km_7d": round(float(last7["distance_km"].sum()), 1),
        "km_28d_weekly": round(chronic, 1),
        "ratio": round(float(last7["distance_km"].sum()) / chronic, 2) if chronic > 0 else None,
        "hard_7d": int(last7["kind"].isin(sessions.HARD_KINDS).sum()) if "kind" in last7 else 0,
        "days_since_hard": int((end - hard["day"].max()).days) if not hard.empty else None,
        "days_since_long": int((end - longs["day"].max()).days) if not longs.empty else None,
        "days_since_run": int((end - runs[runs["day"] <= end]["day"].max()).days) if (runs["day"] <= end).any() else None,
    }


def next_session(
    active_plan: dict[str, Any] | None,
    runs: pd.DataFrame,
    daily: pd.DataFrame,
    result: dict[str, Any],
    today: dt.date | None = None,
) -> dict[str, Any]:
    """What to do next, with the reasons. Never more than the plan asked for."""
    today = today or dt.date.today()
    recovery = recovery_signals(daily, today)
    load = load_signals(runs, today)
    reasons: list[str] = []
    flags = list(recovery.get("flags", [])) if recovery.get("stale_days", 99) <= 1 else []
    if load.get("ratio") is not None and load["ratio"] > 1.5 and load["km_28d_weekly"] >= 10:
        flags.append(f"ostatnie 7 dni to {load['ratio']:.1f}× średniej tygodniowej z 28 dni")

    session = None
    if active_plan:
        upcoming = [s for s in active_plan.get("sessions", [])
                    if s["date"] >= today.isoformat() and s.get("status") == "planned" and s["type"] != "rest"]
        session = upcoming[0] if upcoming else None

    if session is not None:
        hard = session["type"] in ("tempo", "threshold", "intervals", "long")
        if hard and len(flags) >= 2:
            action = "zamień na spokojny"
            reasons.append("Dwa lub więcej sygnałów słabej regeneracji przy mocnej sesji w planie: "
                           "jakość po złej nocy daje mniej bodźca i więcej zmęczenia. Przesuń ją o 1–2 dni.")
        elif hard and flags:
            action = "jak w planie, z kontrolą"
            reasons.append("Jeden sygnał słabszej regeneracji. Zacznij rozgrzewkę; jeśli tętno na spokojnym "
                           "truchcie jest wyraźnie wyższe niż zwykle, zrób wersję spokojną.")
        elif load.get("days_since_hard") == 0 and hard:
            action = "przesuń"
            reasons.append("Mocny trening był dziś — dwa mocne dni pod rząd to kumulacja zmęczenia.")
        else:
            action = "jak w planie"
            reasons.append("Brak sygnałów przeciw: regeneracja i obciążenie w normie.")
        return {"source": "plan", "session": session, "action": action, "reasons": reasons, "flags": flags,
                "recovery": recovery, "load": load}

    # No plan: a suggestion from the record alone.
    paces = physio.training_paces(result.get("vdot")) if result.get("status") == "ok" else {}
    recent = runs[runs["day"] > pd.Timestamp(today) - pd.Timedelta(days=28)] if not runs.empty else runs
    easy_km = float(recent.loc[recent["kind"].isin(("easy", "recovery")), "distance_km"].median()) \
        if len(recent) and (recent["kind"].isin(("easy", "recovery"))).any() else 5.0
    if flags:
        kind, why = "easy", "Sygnały słabszej regeneracji: " + ", ".join(flags) + "."
    elif (load.get("days_since_hard") or 99) >= 3 and load.get("hard_7d", 0) < 2:
        kind, why = "threshold", (f"Ostatni mocny trening {load.get('days_since_hard')} dni temu, regeneracja "
                                  "w normie — miejsce na jakość.")
    elif (load.get("days_since_long") or 99) >= 7:
        kind, why = "long", f"Ostatnie długie wybieganie {load.get('days_since_long') or '—'} dni temu."
    else:
        kind, why = "easy", "Po mocnych dniach — objętość tlenowa w spokojnym tempie."
    band = paces.get({"easy": "E", "long": "E", "threshold": "T"}[kind])
    km = {"easy": easy_km, "long": max(easy_km * 1.5, 8.0), "threshold": easy_km + 2}[kind]
    suggestion = {
        "date": today.isoformat(),
        "type": kind,
        "title": f"{planning.TYPE_LABELS[kind].capitalize()} ~{km:.0f} km",
        "distance_km": round(km, 1),
        "pace_lo": band[0] if band else None,
        "pace_hi": band[1] if band else None,
        "main": "3×10 min w tempie T, 1 min truchtu" if kind == "threshold" else f"{km:.0f} km spokojnie",
    }
    return {"source": "dane", "session": suggestion, "action": "propozycja", "reasons": [why],
            "flags": flags, "recovery": recovery, "load": load}


def observations(runs: pd.DataFrame, history: pd.DataFrame, today: dt.date) -> list[str]:
    """Three to five plain sentences on form, regularity, load and balance."""
    if runs is None or runs.empty:
        return []
    out = []
    end = pd.Timestamp(today)
    if history is not None and not history.empty:
        ten = history[history["distance"] == "10k"].sort_values("day")
        if len(ten) >= 2:
            change = forecast.trend(history, "10k", 8)
            vdot_now = float(ten.iloc[-1]["vdot"])
            if change is not None:
                direction = "szybciej" if change < -15 else "wolniej" if change > 15 else "bez zmian"
                out.append(
                    f"Forma (VDOT {vdot_now:.1f}): prognoza na 10 km w 8 tygodni "
                    + (f"{units.fmt_delta(change)} — {direction}." if direction != "bez zmian" else "bez wyraźnej zmiany.")
                )
    weeks = sessions.weekly(runs, end).tail(8)
    if len(weeks) >= 4:
        regular = int((weeks["runs"] >= 3).sum())
        out.append(f"Regularność: {regular} z ostatnich {len(weeks)} tygodni miało ≥ 3 biegi; "
                   f"średnio {weeks['km'].mean():.0f} km/tydz., ostatni pełny tydzień {weeks['km'].iloc[-2]:.0f} km.")
        empty = int((weeks["runs"] == 0).sum())
        if empty:
            out.append(f"{empty} z 8 tygodni bez biegania — przerwy kosztują więcej niż pojedyncze słabsze treningi.")
    load = load_signals(runs, today)
    if load.get("ratio") is not None:
        verdict = ("powyżej 1,3 — szybki przyrost" if load["ratio"] > 1.3
                   else "poniżej 0,8 — luźniejszy okres" if load["ratio"] < 0.8 else "w paśmie 0,8–1,3")
        out.append(f"Obciążenie: {load['km_7d']:.0f} km w 7 dni wobec {load['km_28d_weekly']:.0f} km/tydz. "
                   f"z 28 dni (iloraz {load['ratio']:.2f}, {verdict}).")
    recent = runs[runs["day"] > end - pd.Timedelta(days=28)]
    if len(recent) >= 4 and "kind" in recent:
        hard_km = float(recent.loc[recent["kind"].isin(sessions.HARD_KINDS), "distance_km"].sum())
        share = 1 - hard_km / float(recent["distance_km"].sum())
        out.append(f"Balans: {share:.0%} kilometrów z 4 tygodni to biegi spokojne"
                   + (" — mniej niż typowe ~75–80%." if share < 0.7 else "."))
    return out


def data_gaps(runs: pd.DataFrame, daily: pd.DataFrame, result: dict[str, Any]) -> list[str]:
    """What the analysis cannot see -- said explicitly so nobody fills it in."""
    gaps = []
    if runs is None or runs.empty:
        return ["Brak biegów."]
    recent = runs[runs["day"] > runs["day"].max() - pd.Timedelta(days=90)]
    if recent["avg_hr"].isna().mean() > 0.3:
        gaps.append("Ponad 30% biegów z 90 dni nie ma tętna — klasyfikacja i trend tętna są mniej pewne.")
    if not (runs.get("kind") == "race").any():
        gaps.append("Żaden bieg nie jest oznaczony jako start — prognoza opiera się na odcinkach treningowych. "
                    "Wynik z zawodów dopisz na stronie Zawody (powiązanie z aktywnością).")
    gaps.append("Odczuwane zmęczenie (RPE), ból i dolegliwości nie są zapisywane — nie ma ich w Garminie.")
    gaps.append("Okrążenia (laps) nie są pobierane; splity kilometrowe są liczone ze strumienia ~400 próbek "
                "na trening (dokładność kilku sekund).")
    if daily is None or daily.empty or "hrv_status" not in daily.columns:
        gaps.append("Brak HRV / gotowości — sygnały regeneracji pominięte.")
    if result.get("status") != "ok":
        gaps.append(str(result.get("reason")))
    return gaps


def _session_brief(session: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "date", "type", "title", "distance_km", "pace_lo", "pace_hi", "hr", "main", "status", "note")
    out = {k: session.get(k) for k in keys}
    out["pace"] = (f"{units.fmt_pace(session.get('pace_lo'), False)}–{units.fmt_pace(session.get('pace_hi'))}"
                   if session.get("pace_lo") else None)
    return out


def brief(
    runs: pd.DataFrame,
    efforts: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    today: dt.date | None = None,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Everything an assistant needs, as plain JSON-serialisable data."""
    today = today or dt.date.today()
    hr_max = float(runs["hr_max_used"].dropna().iloc[0]) if "hr_max_used" in runs and runs["hr_max_used"].notna().any() else None
    races = [r for r in store.races() if r.get("date", "") >= today.isoformat()]
    weeks_to = {}
    for item in races:
        weeks = (dt.date.fromisoformat(item["date"]) - today).days / 7
        weeks_to.setdefault(item["distance"], weeks)
    result = forecast.forecast(runs, efforts, daily, hr_max=hr_max, weeks_to_race=weeks_to)

    plans = store.plans()
    active = store.plan(plan_id) if plan_id else next(
        (p for p in plans if p["request"].get("race_date", "") >= today.isoformat()), None)

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
                "kind": r.kind, "kind_reason": r.kind_reason, "km": round(float(r.distance_km), 2),
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
        "races": races,
        "plan": None,
        "next_session": None,
        "data_gaps": data_gaps(runs, daily, result),
        "how_to_change_the_plan": (
            "Plan to plik data/coach/plans/<id>.json. Zmieniaj tylko sesje z datą >= dziś; "
            "pola: type ∈ " + ", ".join(store.SESSION_TYPES) + ", distance_km, pace_lo/pace_hi (min/km), "
            "main, purpose, note. Po edycji: .venv/bin/python -m running.coach --validate <id>."
        ),
    }
    if active:
        matched = planning.match(active, runs, today)
        out["plan"] = {
            "id": active["id"],
            "name": active.get("name"),
            "race_date": active["request"].get("race_date"),
            "distance": active["request"].get("distance"),
            "goal_s": active["request"].get("goal_s"),
            "compliance": planning.compliance(matched),
            "last_14_days": [
                {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in row.items()
                 if k in ("date", "type", "title", "planned_km", "actual_km", "actual_kind", "effective")}
                for row in matched[(matched["date"] < today) & (matched["date"] >= today - dt.timedelta(days=14))]
                .to_dict("records")
            ] if not matched.empty else [],
            "upcoming": [_session_brief(s) for s in active.get("sessions", []) if s["date"] >= today.isoformat()][:10],
            "warnings": active.get("warnings", []),
        }
    suggestion = next_session(active, runs, daily, result, today)
    out["next_session"] = {**suggestion, "session": _session_brief(suggestion["session"]) if suggestion.get("session") else None}
    return out


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
            "hr_frac": None if perf.get("hr_frac") is None else round(perf["hr_frac"], 3),
            "age_days": perf.get("age_days"),
        } if perf else None,
        "notes": result.get("notes", []),
        "distances": {
            key: {
                "realistic": units.fmt_time(item.realistic_s),
                "range_80": [units.fmt_time(item.low_s), units.fmt_time(item.high_s)],
                "potential": units.fmt_time(item.potential_s),
                "target_after_plan": units.fmt_time(item.target_s) if item.target_s else None,
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
    lines = [f"# Brief treningowy — {data['today']} (dane do {data['data_through']})", ""]
    athlete = data["athlete"]
    lines.append(f"HRmax {athlete['hr_max_bpm']} · HRspocz {athlete['hr_rest_bpm']} · VDOT {athlete['vdot']}")
    if athlete["training_paces_min_km"]:
        lines.append("Tempa: " + ", ".join(f"{k} {a}–{b}" for k, (a, b) in athlete["training_paces_min_km"].items()))
    lines += ["", "## Prognoza"]
    fc = data["forecast"]
    if fc["status"] == "ok":
        for key, item in fc["distances"].items():
            lines.append(f"- {units.RACE_LABELS[key]}: {item['realistic']} ({item['range_80'][0]}–{item['range_80'][1]}, "
                         f"pewność {item['confidence']}), potencjał {item['potential']}, przygotowanie "
                         f"{item['preparation']['score']:.2f}")
        lines += [f"- uwaga: {note}" for note in fc["notes"]]
    else:
        lines.append(f"- brak: {fc['reason']}")
    lines += ["", "## Obciążenie i regeneracja", f"- {json.dumps(data['load'], ensure_ascii=False)}",
              f"- {json.dumps(data['recovery'], ensure_ascii=False, default=str)}", "", "## Ostatnie 21 dni"]
    for run in data["recent_runs"]:
        lines.append(f"- {run['date']} {run['kind']} {run['km']} km @ {run['pace']} HR {run['avg_hr']} — {run['kind_reason']}")
    if data["plan"]:
        plan = data["plan"]
        lines += ["", f"## Plan: {plan['name']} ({plan['id']})", f"- realizacja: {json.dumps(plan['compliance'], ensure_ascii=False)}"]
        for session in plan["upcoming"]:
            lines.append(f"- {session['date']} {session['type']}: {session['title']} — {session['main']}")
    nxt = data["next_session"]
    if nxt and nxt.get("session"):
        lines += ["", "## Następny trening", f"- {nxt['action']}: {nxt['session']['title']}"]
        lines += [f"- {reason}" for reason in nxt["reasons"]]
    lines += ["", "## Czego dane nie widzą"] + [f"- {gap}" for gap in data["data_gaps"]]
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
    parser = argparse.ArgumentParser(description="Brief treningowy dla asystenta")
    parser.add_argument("--json", action="store_true", help="wypisz JSON zamiast Markdown")
    parser.add_argument("--plan", help="id planu (domyślnie: najbliższy aktywny)")
    parser.add_argument("--validate", metavar="PLAN_ID", help="sprawdź plik planu i zakończ")
    args = parser.parse_args(argv)
    if args.validate:
        payload = store.plan(args.validate)
        if payload is None:
            print(f"Nie ma planu {args.validate} w {store.PLANS}")
            return 1
        errors = store.validate_plan(payload)
        print("OK" if not errors else "\n".join(errors))
        return 0 if not errors else 1
    runs, efforts, daily = load_warehouse()
    if runs.empty:
        print("Brak tabeli run_sessions — uruchom analytics.py.")
        return 1
    data = brief(runs, efforts, daily, plan_id=args.plan)
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str) if args.json else markdown(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
