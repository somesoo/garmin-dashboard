"""One sticky note per athlete on the coach's team page (views/team.py).

``card`` is pure pandas over one athlete's tables; ``load`` reads them as that
athlete (``tenant.use``). Like ``facts.py`` it says what happened against the
athlete's own norm and never what to do -- the coach decides. It returns codes
and numbers; the view words them. (The plan session's title is already in the
interface language, so a cached card has the language in its key.)

Never one athlete's raw value next to another's: recovery is the deviation from
the athlete's own 7-day mean (``hrv_deviation``, ``rhr_deviation``) and sleep
against their own 28-day median -- a Garmin RMSSD and an Apple Watch SDNN never
meet on this page.

``state`` -- the page sorts by it, in this order:

- ``attention``: two or more recovery flags, or two or more missed sessions in 7 days;
- ``watch``: one flag, one missed session, or the next run past the 30-day rule
  (``coach.spike_check``);
- ``silent``: no watch data for ``STALE_DAYS`` days or more -- a day without the
  watch looks like a day of zeros, so the note says "no data", not "bad night";
- ``ok``;
- ``empty``: nothing to read yet.

With ``scope="training"`` (core/team.py) the recovery half is not read at all:
the state comes from the plan and the runs only.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from core import tenant

STATES = ("attention", "watch", "silent", "ok", "empty")
STALE_DAYS = 2
MISSED_DAYS = 7
SLEEP_NORM_DAYS = 28


def _num(value: Any, digits: int = 1) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    return round(float(value), digits)


def _last_day(daily: pd.DataFrame, runs: pd.DataFrame) -> dt.date | None:
    """The last day the watch was worn: a night recorded, a real number of steps, or a run."""
    days = []
    if daily is not None and not daily.empty:
        frame = daily.copy()
        frame["day"] = pd.to_datetime(frame["day"])
        worn = frame["sleep_h"].notna() if "sleep_h" in frame else pd.Series(False, index=frame.index)
        if "steps" in frame:
            worn |= frame["steps"].fillna(0) >= 1000
        if worn.any():
            days.append(frame.loc[worn, "day"].max().date())
    if runs is not None and not runs.empty:
        days.append(pd.to_datetime(runs["day"]).max().date())
    return max(days) if days else None


def recovery(daily: pd.DataFrame, today: dt.date) -> dict[str, Any] | None:
    """The last night against the athlete's own norm, and the flags ``coach.recovery_signals`` raises."""
    from running import coach

    if daily is None or daily.empty:
        return None
    frame = daily.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    signals = coach.recovery_signals(frame, today)
    if not signals.get("available"):
        return None
    night = pd.Timestamp(signals["day"])
    before = frame[(frame["day"] < night) & (frame["day"] >= night - pd.Timedelta(days=SLEEP_NORM_DAYS))]
    norm = before["sleep_h"].dropna().median() if "sleep_h" in before else None
    return {
        "day": signals["day"],
        "hrv_deviation": _num(signals.get("hrv_deviation")),
        "rhr_deviation": _num(signals.get("rhr_deviation")),
        "sleep_h": _num(signals.get("sleep_h")),
        "sleep_norm_h": _num(norm),
        "flags": len(signals.get("flags") or []),
        "hrv_kind": str(frame["hrv_kind"].dropna().iloc[-1]) if "hrv_kind" in frame and frame["hrv_kind"].notna().any()
        else None,
    }


def _week(matched: pd.DataFrame | None, runs: pd.DataFrame, today: dt.date) -> dict[str, Any]:
    monday = today - dt.timedelta(days=today.weekday())
    done_km = 0.0
    if runs is not None and not runs.empty:
        days = pd.to_datetime(runs["day"]).dt.date
        done_km = float(runs.loc[(days >= monday) & (days <= today), "distance_km"].sum())
    out: dict[str, Any] = {"done_km": round(done_km, 1), "plan_km": None, "plan_n": 0, "done_n": 0}
    if matched is not None and not matched.empty:
        week = matched[(matched["date"] >= monday) & (matched["date"] < monday + dt.timedelta(days=7))]
        week = week[~week["type"].isin(("strength", "rest"))]
        out["plan_km"] = round(float(week["planned_km"].fillna(0).sum()), 1)
        out["plan_n"] = int(len(week))
        out["done_n"] = int(week["effective"].isin(("done", "modified")).sum())
    return out


def _missed(matched: pd.DataFrame | None, today: dt.date) -> int:
    if matched is None or matched.empty:
        return 0
    recent = matched[(matched["date"] < today) & (matched["date"] >= today - dt.timedelta(days=MISSED_DAYS))]
    return int(recent["effective"].isin(("missed", "skipped")).sum())


def _today(plan: dict[str, Any] | None, today: dt.date) -> dict[str, Any] | None:
    from running import text

    if not plan:
        return None
    sessions = [s for s in plan.get("sessions", []) if s.get("date") == today.isoformat() and s.get("type") != "strength"]
    if not sessions:
        return {"type": "rest", "title": None, "km": None, "coach": False}
    session = sessions[0]
    return {"type": session.get("type"), "title": text.table_title(session), "km": _num(session.get("distance_km")),
            "coach": bool(session.get("locked"))}


def _spike(plan: dict[str, Any] | None, runs: pd.DataFrame, today: dt.date) -> dict[str, Any] | None:
    from running import coach

    if not plan or runs is None or runs.empty:
        return None
    upcoming = [s for s in plan.get("sessions", []) if s.get("date", "") >= today.isoformat()
                and s.get("status", "planned") == "planned" and s.get("type") not in ("rest", "strength", "race")]
    if not upcoming:
        return None
    session = min(upcoming, key=lambda s: s["date"])
    found = coach.spike_check(session, runs, today)
    if not found:
        return None
    return {"date": session["date"], "km": _num(session.get("distance_km")), "cap_km": found["cap_km"]}


def _last_run(runs: pd.DataFrame, matched: pd.DataFrame | None) -> dict[str, Any] | None:
    if runs is None or runs.empty:
        return None
    row = runs.sort_values("start_local" if "start_local" in runs else "day").iloc[-1]
    verdict = None
    if matched is not None and not matched.empty and "activity_id" in matched:
        hit = matched[matched["activity_id"] == int(row["activity_id"])]
        if not hit.empty:
            verdict = str(hit.iloc[0]["effective"])
    return {"day": pd.Timestamp(row["day"]).date().isoformat(), "km": _num(row.get("distance_km")),
            "pace": _num(row.get("pace_min_km"), 3), "kind": row.get("kind"), "activity_id": int(row["activity_id"]),
            "verdict": verdict}


def _race(races: list[dict[str, Any]], today: dt.date) -> dict[str, Any] | None:
    ahead = sorted((r for r in races or [] if str(r.get("date", "")) >= today.isoformat()), key=lambda r: r["date"])
    if not ahead:
        return None
    race = ahead[0]
    return {"name": race.get("name"), "distance": race.get("distance"),
            "days": (dt.date.fromisoformat(race["date"]) - today).days}


def card(daily: pd.DataFrame, runs: pd.DataFrame, plan: dict[str, Any] | None, matched: pd.DataFrame | None,
         races: list[dict[str, Any]], today: dt.date, scope: str = "all") -> dict[str, Any]:
    """Everything on one note, as codes and numbers (see the module docstring)."""
    last = _last_day(daily, runs)
    if last is None and not plan:
        return {"state": "empty", "reasons": [], "last_day": None}
    body = recovery(daily, today) if scope == "all" else None
    missed = _missed(matched, today)
    spike = _spike(plan, runs, today)
    reasons: list[dict[str, Any]] = []
    flags = body["flags"] if body else 0
    if flags:
        reasons.append({"key": "recovery", "n": flags})
    if missed:
        reasons.append({"key": "missed", "n": missed})
    if spike:
        reasons.append({"key": "spike", **spike})
    silent_days = (today - last).days if last else None
    if silent_days is not None and silent_days >= STALE_DAYS:
        reasons.insert(0, {"key": "silent", "days": silent_days})
    if not plan:
        reasons.append({"key": "no_plan"})
    if flags >= 2 or missed >= 2:
        state = "attention"
    elif flags or missed or spike:
        state = "watch"
    elif silent_days is not None and silent_days >= STALE_DAYS:
        state = "silent"
    else:
        state = "ok"
    return {
        "state": state,
        "reasons": reasons,
        "last_day": last.isoformat() if last else None,
        "today": _today(plan, today),
        "recovery": body,
        "week": _week(matched, runs, today),
        "last_run": _last_run(runs, matched),
        "race": _race(races, today),
        "has_plan": bool(plan),
    }


def load(person: tenant.User, today: dt.date, scope: str) -> dict[str, Any]:
    """The note of ``person``, read from their own tables and plan files."""
    from core import db
    from running import plan as planning
    from running import store

    with tenant.use(person.id):
        daily = db.table("daily")
        runs = db.table("run_sessions")
        if not runs.empty:
            runs["day"] = pd.to_datetime(runs["day"])
            runs["start_local"] = pd.to_datetime(runs["start_local"])
        plan = store.current_plan()
        races = store.races()
        matched = planning.match(plan, runs, today) if plan else None
    return card(daily, runs, plan, matched, races, today, scope)


def order(cards: list[tuple[Any, dict[str, Any]]]) -> list[tuple[Any, dict[str, Any]]]:
    """Who needs a look first: by state, then by how many reasons, then by name."""
    return sorted(cards, key=lambda item: (STATES.index(item[1].get("state", "empty")),
                                           -len(item[1].get("reasons") or []),
                                           str(getattr(item[0], "name", item[0])).lower()))
