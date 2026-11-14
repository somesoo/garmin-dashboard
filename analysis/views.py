"""Small read-only views for other apps: one question, one compact JSON.

``summary.py`` is the whole phone app in one document; a dashboard elsewhere
(a home screen, a personal planner) wants one tile at a time and a way back
here for the detail. Each view answers one question with numbers this
dashboard already computes -- nothing is reimplemented:

- ``recovery``      last night and this morning (summary._today, coach.recovery_signals)
- ``last-workout``  the most recent activity, with its run classification
- ``next-workout``  the plan's next session and the morning decision (coach.next_session)
- ``forecast``      race-time predictions and upcoming race targets (forecast.forecast)

Every view names the dashboard page that holds the detail (``page``); api.py
turns it into an address. Cached on disk per build, day, language and view,
like the summary.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Callable

import pandas as pd

from analysis import summary
from core import db
from core import i18n
from core import tenant
from running import coach, forecast, plan as planning, store, units

# Where the detail lives: a url_path from app.py's PAGES (tests pin the pair).
PAGES = {"recovery": "regeneracja", "last-workout": "trasy", "next-workout": "plan", "forecast": "prognoza"}
NAMES = tuple(PAGES)


def _daily() -> pd.DataFrame:
    daily = db.table("daily")
    if not daily.empty:
        daily = daily.sort_values("day").reset_index(drop=True)
        daily["day"] = pd.to_datetime(daily["day"])
    return daily


def _recovery(today: dt.date) -> dict[str, Any]:
    daily = _daily()
    if daily.empty:
        return {"empty": True}
    signals = coach.recovery_signals(daily, today)
    out: dict[str, Any] = {"empty": False, "last_day": daily["day"].max(), **summary._today(daily)}
    out["signals"] = {key: signals.get(key) for key in (
        "day", "readiness", "readiness_level", "hrv_status", "sleep_score", "stale_days")}
    # Flags are sentences in the request's language, e.g. "sen 5.4 h"; an empty list means nothing stands out.
    out["flags"] = list(signals.get("flags", []))
    return out


def _last_workout(today: dt.date) -> dict[str, Any]:
    rows = summary._activities(db.table("activities"))
    if not rows:
        return {"empty": True}
    last = rows[0]
    start = pd.Timestamp(last["start"])
    out: dict[str, Any] = {"empty": False, "days_ago": (today - start.date()).days, **last}
    runs = db.table("run_sessions")
    if not runs.empty:
        runs["start_local"] = pd.to_datetime(runs["start_local"])
        match = runs[runs["start_local"] == start]
        if len(match):
            run = match.iloc[0]
            out["run"] = {"kind": run.get("kind"), "activity_id": int(run["activity_id"])}
            out["page"] = "bieg"
    return out


def _session(session: dict[str, Any] | None) -> dict[str, Any] | None:
    if not session:
        return None
    keys = ("date", "type", "title", "distance_km", "main", "hr", "duration_min")
    out = {key: session.get(key) for key in keys}
    out["pace"] = (f"{units.fmt_pace(session.get('pace_lo'), False)}–{units.fmt_pace(session.get('pace_hi'))}"
                   if session.get("pace_lo") else None)
    return out


def _running(today: dt.date) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any] | None]:
    runs, efforts, daily = coach.load_warehouse()
    hr_max = (float(runs["hr_max_used"].dropna().iloc[0])
              if "hr_max_used" in runs and runs["hr_max_used"].notna().any() else None)
    result = forecast.forecast(runs, efforts, daily, hr_max=hr_max)
    active = store.current_plan()
    if active is not None and planning.next_goal(active, today) is None:
        active = None
    return runs, daily, result, active


def _next_workout(today: dt.date) -> dict[str, Any]:
    runs, daily, result, active = _running(today)
    if runs.empty and active is None:
        return {"empty": True}
    suggestion = coach.next_session(active, runs, daily, result, today)
    session = suggestion.get("session")
    return {
        "empty": False,
        # "plan": a session of the saved plan; otherwise a suggestion from the record alone.
        "source": suggestion.get("source"),
        "is_today": bool(suggestion.get("today", False)),
        "in_days": (dt.date.fromisoformat(session["date"]) - today).days if session and session.get("date") else None,
        "action": suggestion.get("action"),
        "session": _session(session),
        "strength": _session(suggestion.get("strength")),
        "reasons": list(suggestion.get("reasons", []))[:4],
        "flags": list(suggestion.get("flags", [])),
        "plan": {"id": active["id"], "name": active.get("name")} if active else None,
    }


def _forecast(today: dt.date) -> dict[str, Any]:
    runs, _, result, active = _running(today)
    if result.get("status") != "ok":
        return {"empty": True, "reason": result.get("reason")}
    base = planning.baseline(runs, runs["day"].max(), result.get("vdot"))
    races = sorted((r for r in store.races() if r.get("date", "") >= today.isoformat()), key=lambda r: r["date"])
    return {
        "empty": False,
        "vdot": round(result["vdot"], 1),
        "data_through": runs["day"].max(),
        "distances": [
            {"key": key, "km": item.distance_km, "time": units.fmt_time(item.realistic_s),
             "seconds": round(item.realistic_s),
             "range": [units.fmt_time(item.low_s), units.fmt_time(item.high_s)],
             "pace": units.fmt_pace(item.pace, False), "confidence": item.confidence}
            for key, item in result["distances"].items()
        ],
        "races": [
            {"name": race.get("name"), "date": race.get("date"), "distance": race.get("distance"),
             "in_days": (dt.date.fromisoformat(race["date"]) - today).days,
             **coach._race_target(race, result, active, base, today)}
            for race in races[:3]
        ],
    }


BUILDERS: dict[str, Callable[[dt.date], dict[str, Any]]] = {
    "recovery": _recovery, "last-workout": _last_workout, "next-workout": _next_workout, "forecast": _forecast}


def build(person: tenant.User, name: str, lang: str, today: dt.date | None = None) -> dict[str, Any]:
    if name not in BUILDERS:
        raise KeyError(name)
    today = today or dt.date.today()
    with summary._LOCK, tenant.use(person.id):
        previous = i18n._forced
        i18n.force(lang)
        try:
            body = BUILDERS[name](today)
        finally:
            i18n.force(previous)
        page = body.pop("page", PAGES[name])
        return summary._clean({"view": name, "person": person.id, "lang": lang, "today": today,
                               "built_at": db.state().get("built_at"), "page": page, **body})


def cached(person: tenant.User, name: str, lang: str) -> tuple[bytes, str]:
    """(JSON bytes, etag) -- rebuilt when the warehouse is, and once a day."""
    lang = lang if lang in i18n.LANGS else i18n.DEFAULT
    try:
        built = json.loads(person.state_file.read_text(encoding="utf-8")).get("built_at", "")
    except (OSError, ValueError):
        built = ""
    # The plan and the races are edited by hand between builds: their files are part of the key.
    with tenant.use(person.id):
        stamps = [f"{path.name}:{path.stat().st_mtime_ns}" for path in sorted(
            [*store.plans_dir().glob("*.json"), store.races_path()]) if path.exists()]
    etag = hashlib.sha256("|".join([person.id, built, lang, str(dt.date.today()), name, *stamps]).encode()
                          ).hexdigest()[:24]
    folder = person.root / "cache"
    stem = f"view-{name}-{lang}"
    target = folder / f"{stem}-{etag}.json"
    if target.exists():
        return target.read_bytes(), etag
    body = json.dumps(build(person, name, lang), ensure_ascii=False, separators=(",", ":")).encode()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(target)
    for old in folder.glob(f"{stem}-*.json"):
        if old != target:
            old.unlink(missing_ok=True)
    return body, etag
