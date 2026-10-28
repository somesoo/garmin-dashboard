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
import i18n
from running import text

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
        errors.append(i18n.tr(pl="Brak nazwy zawodów.", en="The race has no name."))
    if race.get("distance") not in DISTANCES:
        errors.append(i18n.tr(pl=f"Dystans musi być jednym z {DISTANCES}.", en=f"The distance must be one of {DISTANCES}."))
    try:
        dt.date.fromisoformat(str(race.get("date")))
    except ValueError:
        errors.append(i18n.tr(pl="Data musi mieć format RRRR-MM-DD.", en="The date must be YYYY-MM-DD."))
    goal = race.get("goal_s")
    if goal is not None and (not isinstance(goal, (int, float)) or goal <= 0):
        errors.append(i18n.tr(pl="Cel czasowy musi być dodatnią liczbą sekund.",
                              en="The time goal must be a positive number of seconds."))
    if race.get("priority", "A") not in PRIORITIES:
        errors.append(i18n.tr(pl="Priorytet to A, B albo C.", en="The priority is A, B or C."))
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
    tr = i18n.tr
    errors = []
    if not plan.get("id"):
        errors.append(tr(pl="Plan nie ma id.", en="The plan has no id."))
    sessions = plan.get("sessions")
    if not isinstance(sessions, list):
        return errors + [tr(pl="`sessions` musi być listą.", en="`sessions` must be a list.")]
    seen = set()
    for index, session in enumerate(sessions):
        where = tr(pl=f"sesja {index + 1}", en=f"session {index + 1}")
        if not isinstance(session, dict):
            errors.append(tr(pl=f"{where}: to nie jest obiekt.", en=f"{where}: not an object."))
            continue
        if session.get("id") in seen:
            errors.append(tr(pl=f"{where}: powtórzone id {session.get('id')}.",
                             en=f"{where}: duplicate id {session.get('id')}."))
        seen.add(session.get("id"))
        try:
            dt.date.fromisoformat(str(session.get("date")))
        except ValueError:
            errors.append(tr(pl=f"{where}: zła data {session.get('date')!r}.", en=f"{where}: bad date {session.get('date')!r}."))
        if session.get("type") not in SESSION_TYPES:
            errors.append(tr(pl=f"{where}: typ {session.get('type')!r} spoza {SESSION_TYPES}.",
                             en=f"{where}: type {session.get('type')!r} outside {SESSION_TYPES}."))
        if session.get("status", "planned") not in STATUSES:
            errors.append(tr(pl=f"{where}: status {session.get('status')!r} spoza {STATUSES}.",
                             en=f"{where}: status {session.get('status')!r} outside {STATUSES}."))
        km = session.get("distance_km")
        if km is not None and (not isinstance(km, (int, float)) or km < 0 or km > 60):
            errors.append(tr(pl=f"{where}: dystans {km!r} poza zakresem 0–60 km.",
                             en=f"{where}: distance {km!r} outside 0–60 km."))
        spec = session.get("text")
        if spec is not None and (not isinstance(spec, dict) or spec.get("key") not in TEXT_KEYS):
            errors.append(tr(pl=f"{where}: `text` musi mieć `key` z {TEXT_KEYS}.",
                             en=f"{where}: `text` needs a `key` from {TEXT_KEYS}."))
        elif isinstance(spec, dict) and spec["key"] == "custom" and not isinstance(spec.get("pl"), dict):
            errors.append(tr(pl=f"{where}: `text` custom potrzebuje `pl` (i najlepiej `en`) z polami {PROSE}.",
                             en=f"{where}: custom `text` needs `pl` (and preferably `en`) with the fields {PROSE}."))
        if "steps" in session:
            errors.extend(f"{where}: {e}" for e in validate_steps(session["steps"]))
    return errors


# Session text codes (running/text.py writes the sentences from them).
TEXT_KEYS = ("easy", "recovery", "long", "threshold", "intervals", "tempo", "race", "sick", "adjusted", "softened",
             "custom")
PROSE = ("title", "warmup", "main", "cooldown", "purpose")


STEP_KINDS = ("warmup", "run", "recovery", "cooldown")


def validate_steps(steps: Any, nested: bool = False) -> list[str]:
    """Optional structured workout: ``[{"kind", "km" | "s", "pace": [lo, hi]}]``
    plus ``{"kind": "repeat", "reps", "steps": [...]}`` one level deep."""
    tr = i18n.tr
    if not isinstance(steps, list):
        return [tr(pl="`steps` musi być listą.", en="`steps` must be a list.")]
    errors = []
    for number, step in enumerate(steps, 1):
        where = tr(pl=f"krok {number}", en=f"step {number}")
        if not isinstance(step, dict):
            errors.append(tr(pl=f"{where}: to nie jest obiekt.", en=f"{where}: not an object."))
            continue
        if step.get("kind") == "repeat":
            if nested:
                errors.append(tr(pl=f"{where}: powtórzenie w powtórzeniu.", en=f"{where}: a repeat inside a repeat."))
            reps = step.get("reps")
            if not isinstance(reps, int) or not 1 <= reps <= 30:
                errors.append(tr(pl=f"{where}: `reps` {reps!r} poza 1–30.", en=f"{where}: `reps` {reps!r} outside 1–30."))
            errors.extend(f"{where}/{e}" for e in validate_steps(step.get("steps"), nested=True))
            continue
        if step.get("kind") not in STEP_KINDS:
            errors.append(tr(pl=f"{where}: rodzaj {step.get('kind')!r} spoza {STEP_KINDS + ('repeat',)}.",
                             en=f"{where}: kind {step.get('kind')!r} outside {STEP_KINDS + ('repeat',)}."))
        km, seconds = step.get("km"), step.get("s")
        if (km is None) == (seconds is None):
            errors.append(tr(pl=f"{where}: podaj dokładnie jedno z `km` albo `s`.",
                             en=f"{where}: give exactly one of `km` or `s`."))
        elif km is not None and (not isinstance(km, (int, float)) or not 0 < km <= 60):
            errors.append(tr(pl=f"{where}: `km` {km!r} poza 0–60.", en=f"{where}: `km` {km!r} outside 0–60."))
        elif seconds is not None and (not isinstance(seconds, (int, float)) or not 0 < seconds <= 6 * 3600):
            errors.append(tr(pl=f"{where}: `s` {seconds!r} poza 0–21600.", en=f"{where}: `s` {seconds!r} outside 0–21600."))
        pace = step.get("pace")
        if pace is not None and not (
            isinstance(pace, list) and len(pace) == 2 and all(isinstance(v, (int, float)) for v in pace)
            and 2.5 <= pace[0] <= pace[1] <= 15
        ):
            errors.append(tr(pl=f"{where}: `pace` {pace!r} — oczekiwane [szybciej, wolniej] w min/km, 2,5–15.",
                             en=f"{where}: `pace` {pace!r} — expected [faster, slower] in min/km, 2.5–15."))
    return errors


def _load_plan(path: Path) -> dict[str, Any] | None:
    """A plan file with its session prose in the interface language.

    The file holds codes (``running/text.py``); a file from before the codes
    is converted on the way in and written back, so every old plan is
    migrated the first time anything reads it."""
    plan = _read(path, None)
    if not isinstance(plan, dict) or not plan.get("id"):
        return None
    if text.migrate_plan(plan):
        _write(path, text.strip(plan))
    return text.fill(plan)


def plans() -> list[dict[str, Any]]:
    if not PLANS.is_dir():
        return []
    out = [plan for plan in map(_load_plan, sorted(PLANS.glob("*.json"))) if plan is not None]
    return sorted(out, key=lambda p: str(p.get("created")), reverse=True)


def plan(plan_id: str | None) -> dict[str, Any] | None:
    if not plan_id:
        return None
    path = PLANS / f"{plan_id}.json"
    return _load_plan(path) if path.exists() else None


def save_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Write a plan: codes only, the prose is regenerated on every read."""
    errors = validate_plan(payload)
    if errors:
        raise ValueError(" ".join(errors[:5]))
    payload = dict(payload)
    payload["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    _write(PLANS / f"{payload['id']}.json", text.strip(payload))
    return text.fill(payload)


def delete_plan(plan_id: str) -> None:
    (PLANS / f"{plan_id}.json").unlink(missing_ok=True)


def plans_for(race_id: str) -> list[dict[str, Any]]:
    return [p for p in plans() if p.get("race_id") == race_id]


def current_plan() -> dict[str, Any] | None:
    """The plan. There is one (with several goals); of older plan files the newest wins."""
    found = plans()
    return found[0] if found else None


def save_only_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Save ``payload`` as the one plan, removing every other plan file."""
    saved = save_plan(payload)
    for other in plans():
        if other["id"] != saved["id"]:
            delete_plan(other["id"])
    return saved


# --------------------------------------------------------------------------
# segments (private Strava: stretches cut out of a run, see running/segments.py)


def validate_segment(segment: dict[str, Any]) -> list[str]:
    errors = []
    if not str(segment.get("name") or "").strip():
        errors.append(i18n.tr(pl="Brak nazwy segmentu.", en="The segment has no name."))
    points = segment.get("points")
    if not isinstance(points, list) or len(points) < 2 or not all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p) for p in points):
        errors.append(i18n.tr(pl="Segment potrzebuje co najmniej dwóch punktów [lat, lon].",
                              en="A segment needs at least two points [lat, lon]."))
    length = segment.get("length_m")
    if not isinstance(length, (int, float)) or length < 100:
        errors.append(i18n.tr(pl="Segment musi mieć co najmniej 100 m.", en="A segment must be at least 100 m long."))
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
