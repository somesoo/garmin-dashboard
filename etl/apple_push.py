"""Daily pushes from the iPhone -> the same ``Export`` the full ``export.zip`` gives.

``POST /api/ingest/apple`` (api.py) stores each push body as it came, under
``raw/apple/push/`` -- raw stays the source of truth. The build (etl/apple.py)
reads the newest full export *and* every push and merges them; a sample present
in both, or pushed twice, counts once.

Two body formats are understood:

**``garmin-dashboard/1``** -- what the iOS Shortcut sends (DOSTEP.md, "Skrót")::

    {"format": "garmin-dashboard/1",
     "records":  [{"type": "HeartRate", "start": "2026-11-02T07:00:00+01:00",
                   "end": "...", "value": 61, "unit": "count/min", "source": "Apple Watch"}],
     "sleep":    [{"start": "...", "end": "...", "stage": "Core", "source": "Apple Watch"}],
     "workouts": [{"type": "Running", "start": "...", "end": "...", "duration_min": 45.2,
                   "distance_km": 8.1, "calories": 520, "avg_hr": 150, "max_hr": 172,
                   "source": "Apple Watch"}]}

``type`` is a HealthKit identifier, with or without its ``HKQuantityTypeIdentifier``
prefix. ``stage``: Core, Deep, REM, Awake, InBed, Asleep.

**Health Auto Export** (the iOS app's "REST API" automation, JSON v2): ``{"data":
{"metrics": [...], "workouts": [...]}}``. Mapped from its documented metric
names; checked against synthetic payloads only -- compare with a real one
before trusting a new metric.

Times: an offset in the string is the local clock and is kept as wall time
(like the export); a UTC time ("Z") is moved to ``GARMIN_TZ`` (Europe/Warsaw).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from etl import apple

Q, C = apple.Q, apple.C
FORMAT = "garmin-dashboard/1"
STAGES = {"core": "light", "deep": "deep", "rem": "rem", "awake": "awake", "inbed": "in_bed", "in bed": "in_bed",
          "asleep": "unknown", "asleepunspecified": "unknown", "unspecified": "unknown"}

# Health Auto Export metric name -> (HealthKit type, unit the value is in when the payload says nothing).
HAE_METRICS = {
    "heart_rate": (f"{Q}HeartRate", "count/min"),
    "resting_heart_rate": (f"{Q}RestingHeartRate", "count/min"),
    "heart_rate_variability": (f"{Q}HeartRateVariabilitySDNN", "ms"),
    "step_count": (f"{Q}StepCount", "count"),
    "walking_running_distance": (f"{Q}DistanceWalkingRunning", "km"),
    "active_energy": (f"{Q}ActiveEnergyBurned", "kcal"),
    "basal_energy_burned": (f"{Q}BasalEnergyBurned", "kcal"),
    "flights_climbed": (f"{Q}FlightsClimbed", "count"),
    "apple_exercise_time": (f"{Q}AppleExerciseTime", "min"),
    "respiratory_rate": (f"{Q}RespiratoryRate", "count/min"),
    "blood_oxygen_saturation": (f"{Q}OxygenSaturation", "%"),
    "vo2_max": (f"{Q}VO2Max", "mL/min·kg"),
    "weight_body_mass": (f"{Q}BodyMass", "kg"),
    "body_fat_percentage": (f"{Q}BodyFatPercentage", "%"),
    "apple_sleeping_wrist_temperature": (f"{Q}AppleSleepingWristTemperature", "degC"),
    "running_power": (f"{Q}RunningPower", "W"),
    "running_speed": (f"{Q}RunningSpeed", "km/hr"),
}
HAE_WORKOUTS = (("run", "Running"), ("walk", "Walking"), ("hik", "Hiking"), ("cycl", "Cycling"),
                ("bike", "Cycling"), ("swim", "Swimming"), ("strength", "TraditionalStrengthTraining"),
                ("yoga", "Yoga"), ("row", "Rowing"), ("hiit", "HighIntensityIntervalTraining"),
                ("elliptical", "Elliptical"))


def push_dir() -> Path:
    return apple.exports_dir().parent / "push"


# ------------------------------------------------------------------ storing


def store(body: bytes) -> tuple[Path, bool]:
    """Keep one push as received. Returns (file, new?) -- the same body twice is one file."""
    payload = json.loads(body)  # refuse what is not JSON before anything touches the disk
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    describe(payload)  # and what is not one of the two formats
    digest = hashlib.sha256(body).hexdigest()[:16]
    folder = push_dir()
    folder.mkdir(parents=True, exist_ok=True)
    existing = next(folder.glob(f"*-{digest}.json"), None)
    if existing is not None:
        return existing, False
    target = folder / f"{pd.Timestamp.now():%Y%m%dT%H%M%S}-{digest}.json"
    tmp = target.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(target)
    return target, True


def describe(payload: dict) -> dict[str, int]:
    """How much a push carries -- and a ValueError when it is neither format."""
    if payload.get("format") == FORMAT:
        return {k: len(payload.get(k) or []) for k in ("records", "sleep", "workouts")}
    data = payload.get("data")
    if isinstance(data, dict) and ("metrics" in data or "workouts" in data):
        metrics = data.get("metrics") or []
        return {"records": sum(len(m.get("data") or []) for m in metrics if isinstance(m, dict)),
                "sleep": 0, "workouts": len(data.get("workouts") or [])}
    raise ValueError(f'unknown push format (expected "format": "{FORMAT}" or Health Auto Export JSON)')


# ------------------------------------------------------------------ parsing


def _zone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("GARMIN_TZ", "Europe/Warsaw"))


def wall_time(value: Any):
    """Any of the time shapes iOS produces -> local wall-clock ``datetime`` (or None)."""
    if value in (None, ""):
        return None
    exact = apple._time(str(value))
    if exact is not None and str(value)[10:11] == " ":
        return exact
    try:
        stamp = pd.Timestamp(str(value))
    except (ValueError, TypeError):
        return None
    if stamp.tzinfo is not None:
        if stamp.utcoffset() == pd.Timedelta(0):
            stamp = stamp.tz_convert(_zone())
        stamp = stamp.tz_localize(None)
    return stamp.to_pydatetime()


def _kind(name: str) -> str:
    name = str(name or "")
    if name.startswith(("HKQuantityTypeIdentifier", "HKCategoryTypeIdentifier")):
        return name
    return f"{Q}{name}"


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("qty")
    return apple._number(value)


def _empty() -> dict[str, list]:
    return {"records": [], "heart": [], "sleep": [], "workouts": [], "routes": {}}


def _add_record(out: dict, kind: str, source: str, start, end, value: float, unit: str | None) -> None:
    if start is None or value is None:
        return
    if kind == apple.HEART_RATE:
        out["heart"].append((start, value, source))
    elif kind in apple.WANTED:
        out["records"].append((kind, source, start, end or start, apple._convert(kind, value, unit)))


def _ours(payload: dict, out: dict) -> None:
    for r in payload.get("records") or []:
        if isinstance(r, dict):
            _add_record(out, _kind(r.get("type")), str(r.get("source") or "Shortcut"), wall_time(r.get("start")),
                        wall_time(r.get("end")), _number(r.get("value")), r.get("unit"))
    for s in payload.get("sleep") or []:
        if not isinstance(s, dict):
            continue
        stage = STAGES.get(str(s.get("stage") or "").replace("_", "").lower())
        start, end = wall_time(s.get("start")), wall_time(s.get("end"))
        if stage and start and end and end > start:
            out["sleep"].append((str(s.get("source") or "Shortcut"), start, end, stage))
    for w in payload.get("workouts") or []:
        if isinstance(w, dict):
            out["workouts"].append(_workout(w.get("type"), w, str(w.get("source") or "Shortcut")))


def _workout(kind: Any, w: dict, source: str) -> dict[str, Any]:
    start, end = wall_time(w.get("start")), wall_time(w.get("end"))
    minutes = _number(w.get("duration_min"))
    if minutes is None and _number(w.get("duration")) is not None:
        minutes = _number(w.get("duration")) / 60  # Health Auto Export: seconds
    if minutes is None and start and end:
        minutes = (end - start).total_seconds() / 60
    distance = _number(w.get("distance_km"))
    if distance is None and isinstance(w.get("distance"), dict):
        distance = apple._distance_km(_number(w["distance"]), w["distance"].get("units"))
    calories = _number(w.get("calories")) or _number(w.get("activeEnergyBurned"))
    return {"type": str(kind or "Other").replace("HKWorkoutActivityType", ""), "source": source,
            "start": start, "end": end, "duration_min": minutes, "distance_km": distance, "calories": calories,
            "avg_hr": _number(w.get("avg_hr")) or _number(w.get("avgHeartRate")),
            "max_hr": _number(w.get("max_hr")) or _number(w.get("maxHeartRate")),
            "elevation_gain_m": _number(w.get("elevation_gain_m")) or _number(w.get("elevationUp")),
            "indoor": bool(w.get("indoor") or w.get("isIndoor")), "route_file": None}


def _hae_workout_type(name: str) -> str:
    lowered = name.lower()
    return next((kind for key, kind in HAE_WORKOUTS if key in lowered), name.replace(" ", "") or "Other")


def _hae(payload: dict, out: dict) -> None:
    data = payload.get("data") or {}
    for metric in data.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        name, unit = metric.get("name"), metric.get("units")
        if name == "sleep_analysis":
            _hae_sleep(metric.get("data") or [], out)
            continue
        if name not in HAE_METRICS:
            continue
        kind, default_unit = HAE_METRICS[name]
        for item in metric.get("data") or []:
            if not isinstance(item, dict):
                continue
            value = _number(item.get("qty"))
            if value is None:
                value = _number(item.get("Avg"))
            when = wall_time(item.get("date"))
            source = str(item.get("source") or "Health Auto Export")
            _add_record(out, kind, source, when, when, value, unit or default_unit)
    for index, w in enumerate(data.get("workouts") or []):
        if not isinstance(w, dict):
            continue
        item = _workout(_hae_workout_type(str(w.get("name") or "")), w, "Health Auto Export")
        route = w.get("route") or []
        if len(route) >= 5:
            key = f"push:{item['start']}:{index}"
            item["route_file"] = key
            out["routes"][key] = pd.DataFrame([
                {"lat": apple._number(p.get("lat") or p.get("latitude")),
                 "lon": apple._number(p.get("lon") or p.get("longitude")),
                 "elevation_m": apple._number(p.get("altitude") or p.get("elevation")),
                 "t": pd.Timestamp(p["timestamp"]).tz_localize(None) if p.get("timestamp") else None}
                for p in route if isinstance(p, dict)]).dropna(subset=["lat", "lon"])
        for sample in w.get("heartRateData") or []:
            if isinstance(sample, dict):
                _add_record(out, apple.HEART_RATE, "Health Auto Export", wall_time(sample.get("date")), None,
                            _number(sample.get("Avg") or sample.get("qty")), "count/min")
        out["workouts"].append(item)


def _hae_sleep(items: list, out: dict) -> None:
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "Health Auto Export")
        if "startDate" in item:  # one row per stage segment
            stage = STAGES.get(str(item.get("value") or "").replace("_", "").lower())
            start, end = wall_time(item.get("startDate")), wall_time(item.get("endDate"))
            if stage and start and end and end > start:
                out["sleep"].append((source, start, end, stage))
            continue
        # Aggregated night: hours per stage. Laid out back to back from sleepStart --
        # totals are right, the order inside the night is not known.
        start = wall_time(item.get("sleepStart") or item.get("inBedStart"))
        if start is None:
            continue
        t = start
        for key, stage in (("deep", "deep"), ("core", "light"), ("rem", "rem"), ("awake", "awake")):
            hours = _number(item.get(key))
            if hours:
                end = t + pd.Timedelta(hours=hours).to_pytimedelta()
                out["sleep"].append((source, t, end, stage))
                t = end
        asleep = _number(item.get("asleep"))
        if t == start and asleep:  # only a total
            out["sleep"].append((source, t, t + pd.Timedelta(hours=asleep).to_pytimedelta(), "unknown"))


def parse_push(payload: dict) -> apple.Export:
    out = _empty()
    if payload.get("format") == FORMAT:
        _ours(payload, out)
    else:
        _hae(payload, out)
    return apple.Export(
        records=pd.DataFrame(out["records"], columns=["type", "source", "start", "end", "value"]),
        heart_rate=pd.DataFrame(out["heart"], columns=["t", "bpm", "source"]),
        sleep=pd.DataFrame(out["sleep"], columns=["source", "start", "end", "stage"]),
        workouts=out["workouts"], routes=out["routes"])


def pushes() -> list[apple.Export]:
    found = []
    for path in sorted(push_dir().glob("*.json")) if push_dir().is_dir() else []:
        try:
            found.append(parse_push(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as exc:  # one bad file must not cost the rest
            print(f"pominięto {path.name}: {exc}", flush=True)
    return found


def combine(parts: list[apple.Export]) -> apple.Export:
    """One Export from a full export and any number of pushes; exact duplicates once."""
    if not parts:
        return apple.Export(records=pd.DataFrame(columns=["type", "source", "start", "end", "value"]),
                            heart_rate=pd.DataFrame(columns=["t", "bpm", "source"]),
                            sleep=pd.DataFrame(columns=["source", "start", "end", "stage"]), workouts=[])

    records =pd.concat([p.records for p in parts], ignore_index=True).drop_duplicates(
        subset=["type", "source", "start", "end", "value"], ignore_index=True)
    heart = pd.concat([p.heart_rate for p in parts], ignore_index=True).drop_duplicates(
        subset=["t", "bpm", "source"]).sort_values("t", ignore_index=True)
    sleep = pd.concat([p.sleep for p in parts], ignore_index=True).drop_duplicates(ignore_index=True)
    workouts, seen = [], set()
    for part in parts:
        for w in part.workouts:
            key = (w["type"], w["source"], w["start"])
            if key not in seen:
                seen.add(key)
                workouts.append(w)
    routes = {k: v for part in parts for k, v in part.routes.items()}
    first = next((p for p in parts if p.birth_date or p.sex), parts[0])
    return apple.Export(records=records, heart_rate=heart, sleep=sleep, workouts=workouts, routes=routes,
                        birth_date=first.birth_date, sex=first.sex, exported_at=first.exported_at)
