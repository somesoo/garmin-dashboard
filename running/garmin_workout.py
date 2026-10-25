"""Plan sessions as Garmin Connect workouts, and what to send to keep them in sync.

Pure functions: ``to_garmin`` builds the JSON ``Garmin.upload_workout`` posts
(the same structure the Connect web editor saves), ``sync_actions`` compares
the plan with what was pushed before. The network part is ``etl/push_plan.py``.

What was pushed lives in the plan file itself, ``plan["garmin"]``, keyed by
session id: ``{"workout_id", "schedule_id", "fingerprint", "date"}``. It is
plan-level rather than per session on purpose -- ``replan`` regenerates every
future session with a new id, and the registry is what lets the next push
find and remove the workouts those sessions left behind instead of leaving
duplicates in the watch calendar.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any


RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
STEP_TYPES = {
    "warmup": (1, "warmup"),
    "cooldown": (2, "cooldown"),
    "run": (3, "interval"),
    "recovery": (4, "recovery"),
    "repeat": (6, "repeat"),
}
CONDITIONS = {
    "time": (2, "time", True),
    "distance": (3, "distance", True),
    "iterations": (7, "iterations", False),
}
NAME_PREFIX = "Plan · "
DEFAULT_PACE = 6.5  # min/km, only for the duration estimate of untargeted timed steps


def mps(pace_min_km: float) -> float:
    """Pace in min/km as speed in m/s (Garmin's unit for pace targets)."""
    return round(1000.0 / (pace_min_km * 60.0), 4)


def _condition(kind: str) -> dict[str, Any]:
    number, key, shown = CONDITIONS[kind]
    return {"conditionTypeId": number, "conditionTypeKey": key, "displayOrder": number, "displayable": shown}


def _step_type(kind: str) -> dict[str, Any]:
    number, key = STEP_TYPES[kind]
    return {"stepTypeId": number, "stepTypeKey": key, "displayOrder": number}


class _Order:
    """Garmin numbers every step in one sequence, nested ones included."""

    def __init__(self) -> None:
        self.value = 0
        self.child = 0

    def next(self) -> int:
        self.value += 1
        return self.value


def _executable(step: dict[str, Any], order: _Order, child: int | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order.next(),
        "stepType": _step_type(step["kind"]),
    }
    if "km" in step:
        out.update(endCondition=_condition("distance"), endConditionValue=round(step["km"] * 1000.0, 1))
    else:
        out.update(endCondition=_condition("time"), endConditionValue=float(step["s"]))
    pace = step.get("pace")
    if pace:
        # The slower pace is the lower speed: targetValueOne < targetValueTwo.
        out.update(
            targetType={"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6},
            targetValueOne=mps(pace[1]),
            targetValueTwo=mps(pace[0]),
        )
    else:
        out["targetType"] = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
    if child is not None:
        out["childStepId"] = child
    return out


def _steps(steps: list[dict[str, Any]], order: _Order, child: int | None = None) -> list[dict[str, Any]]:
    out = []
    for step in steps:
        if step["kind"] != "repeat":
            out.append(_executable(step, order, child))
            continue
        order.child += 1
        group = {
            "type": "RepeatGroupDTO",
            "stepOrder": order.next(),
            "stepType": _step_type("repeat"),
            "childStepId": order.child,
            "numberOfIterations": step["reps"],
            "endCondition": _condition("iterations"),
            "endConditionValue": float(step["reps"]),
            "smartRepeat": False,
        }
        group["workoutSteps"] = _steps(step["steps"], order, order.child)
        out.append(group)
    return out


def _seconds(steps: list[dict[str, Any]]) -> float:
    total = 0.0
    for step in steps:
        if step["kind"] == "repeat":
            total += step["reps"] * _seconds(step["steps"])
        elif "s" in step:
            total += step["s"]
        else:
            pace = sum(step["pace"]) / 2 if step.get("pace") else DEFAULT_PACE
            total += step["km"] * pace * 60
    return total


def to_garmin(session: dict[str, Any]) -> dict[str, Any] | None:
    """The workout for one plan session; None for rest days and sessions
    without structured steps (older plan files)."""
    steps = session.get("steps") or []
    if session.get("type") == "rest" or not steps:
        return None
    date = dt.date.fromisoformat(session["date"])
    description = " ".join(filter(None, [session.get("main"), session.get("purpose")]))
    return {
        "workoutName": f"{NAME_PREFIX}{session.get('title', session['type'])} ({date:%d.%m})"[:80],
        "description": description[:1000],
        "sportType": RUNNING,
        "estimatedDurationInSecs": int(round(_seconds(steps))),
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": RUNNING, "workoutSteps": _steps(steps, _Order())}
        ],
    }


def fingerprint(session: dict[str, Any]) -> str:
    """Changes whenever what the watch would show changes."""
    payload = json.dumps([session.get("date"), session.get("title"), session.get("steps")], sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def sync_actions(plan: dict[str, Any], today: dt.date, days: int = 7) -> list[dict[str, Any]]:
    """What to do so the Garmin calendar matches the plan for the next ``days``.

    Actions: ``upload`` (new), ``replace`` (changed since pushed), ``remove``
    (pushed, but the session is gone, skipped, turned into rest or lost its
    steps). Workouts on past dates are left alone: they are history now.
    """
    pushed: dict[str, dict[str, Any]] = plan.get("garmin") or {}
    horizon = today + dt.timedelta(days=days)
    sessions = {s["id"]: s for s in plan.get("sessions", [])}
    actions = []
    for session_id, entry in pushed.items():
        if entry.get("date", "") < today.isoformat():
            continue
        session = sessions.get(session_id)
        if session is None or session.get("status", "planned") != "planned" or to_garmin(session) is None:
            actions.append({"action": "remove", "session_id": session_id, "entry": entry})
        elif fingerprint(session) != entry.get("fingerprint"):
            actions.append({"action": "replace", "session_id": session_id, "entry": entry, "session": session})
    for session in plan.get("sessions", []):
        date = dt.date.fromisoformat(session["date"])
        if session["id"] in pushed or not today <= date < horizon:
            continue
        if session.get("status", "planned") == "planned" and to_garmin(session) is not None:
            actions.append({"action": "upload", "session_id": session["id"], "session": session})
    return sorted(actions, key=lambda a: (a.get("session") or a["entry"]).get("date", ""))


def describe(action: dict[str, Any]) -> str:
    session = action.get("session") or {}
    entry = action.get("entry") or {}
    label = {"upload": "wyślij", "replace": "podmień", "remove": "usuń"}[action["action"]]
    return f"{label}: {session.get('date') or entry.get('date')} {session.get('title') or entry.get('title', '')}".strip()


def pending(plan: dict[str, Any], today: dt.date | None = None, days: int = 7) -> int:
    """How many changes the next push would send; the page shows it on the button."""
    return len(sync_actions(plan, today or dt.date.today(), days))

