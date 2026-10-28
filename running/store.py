"""Races and training plans as JSON files under ``data/coach/``.

The warehouse is rebuilt from raw files on every ETL run, so anything the
runner *enters* (a race, a plan, a session marked as skipped) cannot live in
it. These files are the only state the running module owns. They sit inside
``data/`` -- private, never committed, copied with the rest by ``scp`` -- and
are plain JSON on purpose: an assistant (Claude Code in this repo) can read
and edit a plan with the same tools as a person, and ``validate_plan`` is the
contract both have to satisfy.

Writes go through a temp file and a rename, so a page reading a plan while it
is being saved never sees half a file.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any

import config

ROOT = config.DATA / "coach"
RACES = ROOT / "races.json"
PLANS = ROOT / "plans"
SEGMENTS = ROOT / "segments.json"

DISTANCES = ("5k", "10k", "hm", "m")
SESSION_TYPES = ("rest", "recovery", "easy", "long", "tempo", "threshold", "intervals", "race")
STATUSES = ("planned", "done", "skipped", "modified")
PRIORITIES = ("A", "B", "C")


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.part")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------
# races


def validate_race(race: dict[str, Any]) -> list[str]:
    errors = []
    if not str(race.get("name") or "").strip():
        errors.append("Brak nazwy zawodów.")
    if race.get("distance") not in DISTANCES:
        errors.append(f"Dystans musi być jednym z {DISTANCES}.")
    try:
        dt.date.fromisoformat(str(race.get("date")))
    except ValueError:
        errors.append("Data musi mieć format RRRR-MM-DD.")
    goal = race.get("goal_s")
    if goal is not None and (not isinstance(goal, (int, float)) or goal <= 0):
        errors.append("Cel czasowy musi być dodatnią liczbą sekund.")
    if race.get("priority", "A") not in PRIORITIES:
        errors.append("Priorytet to A, B albo C.")
    return errors


def races() -> list[dict[str, Any]]:
    data = _read(RACES, [])
    return sorted((r for r in data if isinstance(r, dict)), key=lambda r: str(r.get("date")))


def save_race(race: dict[str, Any]) -> dict[str, Any]:
    errors = validate_race(race)
    if errors:
        raise ValueError(" ".join(errors))
    race = dict(race)
    race.setdefault("id", new_id("race"))
    race.setdefault("priority", "A")
    race.setdefault("created", dt.datetime.now().isoformat(timespec="seconds"))
    others = [r for r in races() if r.get("id") != race["id"]]
    _write(RACES, others + [race])
    return race


def delete_race(race_id: str) -> None:
    _write(RACES, [r for r in races() if r.get("id") != race_id])


def race(race_id: str | None) -> dict[str, Any] | None:
    return next((r for r in races() if r.get("id") == race_id), None)


def manual_kinds() -> dict[int, str]:
    """Activities the runner linked to a race as its result -> ``race`` kind."""
    out = {}
    for item in races():
        activity = item.get("result_activity_id")
        if activity:
            try:
                out[int(activity)] = "race"
            except (TypeError, ValueError):
                continue
    return out


# --------------------------------------------------------------------------
# plans


def validate_plan(plan: dict[str, Any]) -> list[str]:
    """The contract a plan file must meet, whoever wrote it."""
    errors = []
    if not plan.get("id"):
        errors.append("Plan nie ma id.")
    sessions = plan.get("sessions")
    if not isinstance(sessions, list):
        return errors + ["`sessions` musi być listą."]
    seen = set()
    for index, session in enumerate(sessions):
        where = f"sesja {index + 1}"
        if not isinstance(session, dict):
            errors.append(f"{where}: to nie jest obiekt.")
            continue
        if session.get("id") in seen:
            errors.append(f"{where}: powtórzone id {session.get('id')}.")
        seen.add(session.get("id"))
        try:
            dt.date.fromisoformat(str(session.get("date")))
        except ValueError:
            errors.append(f"{where}: zła data {session.get('date')!r}.")
        if session.get("type") not in SESSION_TYPES:
            errors.append(f"{where}: typ {session.get('type')!r} spoza {SESSION_TYPES}.")
        if session.get("status", "planned") not in STATUSES:
            errors.append(f"{where}: status {session.get('status')!r} spoza {STATUSES}.")
        km = session.get("distance_km")
        if km is not None and (not isinstance(km, (int, float)) or km < 0 or km > 60):
            errors.append(f"{where}: dystans {km!r} poza zakresem 0–60 km.")
        if "steps" in session:
            errors.extend(f"{where}: {e}" for e in validate_steps(session["steps"]))
    return errors


STEP_KINDS = ("warmup", "run", "recovery", "cooldown")


def validate_steps(steps: Any, nested: bool = False) -> list[str]:
    """Optional structured workout: ``[{"kind", "km" | "s", "pace": [lo, hi]}]``
    plus ``{"kind": "repeat", "reps", "steps": [...]}`` one level deep."""
    if not isinstance(steps, list):
        return ["`steps` musi być listą."]
    errors = []
    for number, step in enumerate(steps, 1):
        where = f"krok {number}"
        if not isinstance(step, dict):
            errors.append(f"{where}: to nie jest obiekt.")
            continue
        if step.get("kind") == "repeat":
            if nested:
                errors.append(f"{where}: powtórzenie w powtórzeniu.")
            reps = step.get("reps")
            if not isinstance(reps, int) or not 1 <= reps <= 30:
                errors.append(f"{where}: `reps` {reps!r} poza 1–30.")
            errors.extend(f"{where}/{e}" for e in validate_steps(step.get("steps"), nested=True))
            continue
        if step.get("kind") not in STEP_KINDS:
            errors.append(f"{where}: rodzaj {step.get('kind')!r} spoza {STEP_KINDS + ('repeat',)}.")
        km, seconds = step.get("km"), step.get("s")
        if (km is None) == (seconds is None):
            errors.append(f"{where}: podaj dokładnie jedno z `km` albo `s`.")
        elif km is not None and (not isinstance(km, (int, float)) or not 0 < km <= 60):
            errors.append(f"{where}: `km` {km!r} poza 0–60.")
        elif seconds is not None and (not isinstance(seconds, (int, float)) or not 0 < seconds <= 6 * 3600):
            errors.append(f"{where}: `s` {seconds!r} poza 0–21600.")
        pace = step.get("pace")
        if pace is not None and not (
            isinstance(pace, list) and len(pace) == 2 and all(isinstance(v, (int, float)) for v in pace)
            and 2.5 <= pace[0] <= pace[1] <= 15
        ):
            errors.append(f"{where}: `pace` {pace!r} — oczekiwane [szybciej, wolniej] w min/km, 2,5–15.")
    return errors


def plans() -> list[dict[str, Any]]:
    if not PLANS.is_dir():
        return []
    out = []
    for path in sorted(PLANS.glob("*.json")):
        plan = _read(path, None)
        if isinstance(plan, dict) and plan.get("id"):
            out.append(plan)
    return sorted(out, key=lambda p: str(p.get("created")), reverse=True)


def plan(plan_id: str | None) -> dict[str, Any] | None:
    if not plan_id:
        return None
    payload = _read(PLANS / f"{plan_id}.json", None)
    return payload if isinstance(payload, dict) else None


def save_plan(payload: dict[str, Any]) -> dict[str, Any]:
    errors = validate_plan(payload)
    if errors:
        raise ValueError(" ".join(errors[:5]))
    payload = dict(payload)
    payload["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    _write(PLANS / f"{payload['id']}.json", payload)
    return payload


def delete_plan(plan_id: str) -> None:
    (PLANS / f"{plan_id}.json").unlink(missing_ok=True)


def plans_for(race_id: str) -> list[dict[str, Any]]:
    return [p for p in plans() if p.get("race_id") == race_id]


# --------------------------------------------------------------------------
# segments (private Strava: stretches cut out of a run, see running/segments.py)


def validate_segment(segment: dict[str, Any]) -> list[str]:
    errors = []
    if not str(segment.get("name") or "").strip():
        errors.append("Brak nazwy segmentu.")
    points = segment.get("points")
    if not isinstance(points, list) or len(points) < 2 or not all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p) for p in points):
        errors.append("Segment potrzebuje co najmniej dwóch punktów [lat, lon].")
    length = segment.get("length_m")
    if not isinstance(length, (int, float)) or length < 100:
        errors.append("Segment musi mieć co najmniej 100 m.")
    return errors


def segments() -> list[dict[str, Any]]:
    data = _read(SEGMENTS, [])
    return sorted((s for s in data if isinstance(s, dict)), key=lambda s: str(s.get("name")).lower())


def save_segment(segment: dict[str, Any]) -> dict[str, Any]:
    errors = validate_segment(segment)
    if errors:
        raise ValueError(" ".join(errors))
    segment = dict(segment, name=str(segment["name"]).strip())
    segment.setdefault("id", new_id("seg"))
    segment.setdefault("created", dt.datetime.now().isoformat(timespec="seconds"))
    others = [s for s in segments() if s.get("id") != segment["id"]]
    _write(SEGMENTS, others + [segment])
    return segment


def delete_segment(segment_id: str) -> None:
    _write(SEGMENTS, [s for s in segments() if s.get("id") != segment_id])


def segments_stamp() -> str:
    return str(SEGMENTS.stat().st_mtime_ns) if SEGMENTS.exists() else "none"
