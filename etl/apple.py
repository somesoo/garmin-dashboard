"""Apple Health as a data source: ``export.zip`` -> the same tables the Garmin loader builds.

    GARMIN_USER=y python -m etl.apple import data/users/y/import/export.zip
    GARMIN_USER=y python -m etl.apple            rebuild from what is already imported

``import`` copies the archive to ``raw/apple/exports/`` (raw stays the source
of truth, like ``raw/`` for Garmin) and rebuilds. The build reads the newest
export; ``etl/load.py`` hands over here for every person with ``source: apple``,
so ``fetch.rebuild``, ``etl.exclude`` and analytics work unchanged.

What the export is, and what it is not:

- **Health is a pool, not a device.** One person's export mixes the iPhone's
  pedometer, a watch, and apps that write into Health (Garmin Connect, Strava).
  Cumulative counts (steps, distance, energy, floors) overlap between sources,
  so each day takes **the largest single-source total**, never the sum -- the
  sum counts the same walk twice.
- **Sleep**: segments are grouped per source into sessions (gaps <= 90 min);
  each morning takes the session with the most sleep. Core -> ``light``. A
  source with only "in bed" (iPhone bedtime) gives ``sleep_h`` without stages,
  marked ``sleep_in_bed_only``.
- **HRV in Health is SDNN** (Apple Watch); Garmin's ``hrv_last_night`` is
  RMSSD. Different quantities -- SDNN goes to ``hrv_sdnn`` and never into the
  Garmin column.
- **No training load** in Health. Each workout with heart rate gets Banister's
  TRIMP (``training_load``, ``load_source = "trimp"``) so the performance chart,
  weekly load and the sport readiness have something to stand on. One person
  has one source, so the series is never mixed with Garmin's numbers.
- Workout heart rate comes from the workout's own statistics when present,
  otherwise from the heart-rate samples inside its time window.
- Times are local wall-clock times as written in the export (the offset is
  dropped), like ``start_local`` from Garmin.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from etl import schema  # noqa: E402

Q = "HKQuantityTypeIdentifier"
C = "HKCategoryTypeIdentifier"

# Cumulative per-day quantities: largest single-source total wins.
DAY_SUMS = {
    f"{Q}StepCount": "steps",
    f"{Q}DistanceWalkingRunning": "distance_m",
    f"{Q}ActiveEnergyBurned": "active_calories",
    f"{Q}BasalEnergyBurned": "bmr_calories",
    f"{Q}FlightsClimbed": "floors_up",
    f"{Q}AppleExerciseTime": "exercise_min",
}
# Point measurements averaged per day.
DAY_MEANS = {
    f"{Q}RestingHeartRate": "rhr",
    f"{Q}HeartRateVariabilitySDNN": "hrv_sdnn",
    f"{Q}VO2Max": "vo2max",
    f"{Q}RespiratoryRate": "sleep_respiration",
    f"{Q}OxygenSaturation": "spo2_avg",
}
DAY_MEANS[f"{Q}AppleSleepingWristTemperature"] = "wrist_temp_c"
# Measured overnight: an evening reading counts for the next morning.
NIGHT_TYPES = {f"{Q}AppleSleepingWristTemperature", f"{Q}RespiratoryRate", f"{Q}OxygenSaturation"}
DAY_LAST = {f"{Q}BodyMass": "weight_kg", f"{Q}BodyFatPercentage": "body_fat_pct"}
HEART_RATE = f"{Q}HeartRate"
HRV = f"{Q}HeartRateVariabilitySDNN"
STEPS = f"{Q}StepCount"
SLEEP = f"{C}SleepAnalysis"
# Apple Watch samples written during a workout, averaged over its time window.
WORKOUT_MEANS = {
    f"{Q}RunningPower": "avg_power",
    f"{Q}RunningStrideLength": "stride_m",
    f"{Q}RunningVerticalOscillation": "vertical_oscillation_cm",
    f"{Q}RunningGroundContactTime": "ground_contact_ms",
    f"{Q}WorkoutEffortScore": "effort_score",
    f"{Q}EstimatedWorkoutEffortScore": "effort_score_estimated",
}
HR_RECOVERY = f"{Q}HeartRateRecoveryOneMinute"
WANTED = set(DAY_SUMS) | set(DAY_MEANS) | set(DAY_LAST) | set(WORKOUT_MEANS) | {HEART_RATE, SLEEP, HR_RECOVERY}
NORM_NIGHTS, NORM_MIN = 60, 14

SLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleepCore": "light",
    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
    "HKCategoryValueSleepAnalysisAwake": "awake",
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "unknown",
    "HKCategoryValueSleepAnalysisAsleep": "unknown",
    "HKCategoryValueSleepAnalysisInBed": "in_bed",
}
ASLEEP = ("light", "deep", "rem", "unknown")
SESSION_GAP = dt.timedelta(minutes=90)

# Apple workout types -> the Garmin type keys the rest of the code knows
# (running/, sport/catalog.py). Unknown types keep a tidy snake_case name.
SPORTS = {
    "Running": "running", "Walking": "walking", "Hiking": "hiking", "Cycling": "cycling",
    "Swimming": "lap_swimming", "Rowing": "indoor_rowing", "Elliptical": "elliptical",
    "TraditionalStrengthTraining": "strength_training", "FunctionalStrengthTraining": "strength_training",
    "HighIntensityIntervalTraining": "hiit", "Yoga": "yoga", "Pilates": "pilates",
    "CrossCountrySkiing": "cross_country_skiing", "DownhillSkiing": "resort_skiing",
    "Snowboarding": "resort_snowboarding", "Climbing": "indoor_climbing", "Tennis": "tennis",
    "Soccer": "soccer", "Basketball": "basketball", "Volleyball": "volleyball",
    "SkatingSports": "inline_skating", "PaddleSports": "kayaking", "Kickboxing": "kickboxing",
    "Boxing": "boxing", "Dance": "dance", "MixedCardio": "cardio", "StairClimbing": "stair_climbing",
}
PACE_SPORTS = ("running", "treadmill_running", "walking", "hiking")


# ------------------------------------------------------------------ parsing


def _time(value: str | None) -> dt.datetime | None:
    """``2026-11-01 07:12:30 +0100`` -> local wall time (offset dropped)."""
    if not value:
        return None
    try:
        return dt.datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _convert(record_type: str, value: float, unit: str | None) -> float:
    """Units as Health writes them -> the units the warehouse uses."""
    unit = (unit or "").strip()
    if record_type == f"{Q}DistanceWalkingRunning":
        return value * {"km": 1000, "m": 1, "mi": 1609.344, "ft": 0.3048}.get(unit, 1)
    if record_type in (f"{Q}ActiveEnergyBurned", f"{Q}BasalEnergyBurned"):
        return value / 4.184 if unit == "kJ" else value
    if record_type == f"{Q}BodyMass":
        return value * 0.45359237 if unit == "lb" else value
    if record_type in (f"{Q}BodyFatPercentage", f"{Q}OxygenSaturation") and unit == "%" and value <= 1:
        return value * 100
    if record_type == f"{Q}HeartRateVariabilitySDNN" and unit == "s":
        return value * 1000
    return value


def _distance_km(value: float, unit: str | None) -> float:
    return value * {"km": 1, "m": 0.001, "mi": 1.609344, "ft": 0.0003048}.get((unit or "km").strip(), 1)


def _length_m(text: str | None) -> float | None:
    """Workout metadata like ``1234 cm`` / ``12.5 m`` -> metres."""
    if not text:
        return None
    parts = str(text).split()
    number = _number(parts[0])
    if number is None:
        return None
    unit = parts[1] if len(parts) > 1 else "m"
    return number * {"cm": 0.01, "m": 1, "km": 1000, "ft": 0.3048}.get(unit, 1)


@dataclass
class Export:
    """What one ``export.zip`` holds, reduced to what the warehouse needs."""

    records: pd.DataFrame  # type, source, start, end, value
    heart_rate: pd.DataFrame  # t, bpm, source
    sleep: pd.DataFrame  # source, start, end, stage
    workouts: list[dict[str, Any]]
    routes: dict[str, pd.DataFrame] = field(default_factory=dict)  # zip path -> lat, lon, elevation_m, t
    birth_date: dt.date | None = None
    sex: str | None = None
    exported_at: str | None = None


def _gpx(data: bytes) -> pd.DataFrame:
    root = ET.fromstring(data)
    rows = []
    for point in root.iter():
        if not point.tag.endswith("trkpt"):
            continue
        lat, lon = _number(point.get("lat")), _number(point.get("lon"))
        if lat is None or lon is None:
            continue
        row: dict[str, Any] = {"lat": lat, "lon": lon, "elevation_m": None, "t": None}
        for child in point:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "ele":
                row["elevation_m"] = _number(child.text)
            elif name == "time" and child.text:
                stamp = pd.Timestamp(child.text)
                # GPX time is UTC; the export's workout times are local wall time,
                # so routes keep their own clock and are aligned by elapsed seconds.
                row["t"] = stamp.tz_localize(None) if stamp.tzinfo is None else stamp.tz_convert(None)
        rows.append(row)
    return pd.DataFrame(rows, columns=["lat", "lon", "elevation_m", "t"])


def parse(path: Path) -> Export:
    records: list[tuple] = []
    heart: list[tuple] = []
    sleep: list[tuple] = []
    workouts: list[dict[str, Any]] = []
    birth = sex = exported = None
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        xml_name = next(n for n in names if n.endswith("/export.xml") or n == "export.xml")
        with archive.open(xml_name) as handle:
            for _, el in ET.iterparse(handle, events=("end",)):
                tag = el.tag
                if tag == "Record":
                    kind = el.get("type")
                    if kind in WANTED:
                        start, end = _time(el.get("startDate")), _time(el.get("endDate"))
                        source = el.get("sourceName") or "?"
                        if kind == SLEEP:
                            stage = SLEEP_VALUES.get(el.get("value"))
                            if stage and start and end and end > start:
                                sleep.append((source, start, end, stage))
                        else:
                            value = _number(el.get("value"))
                            if value is not None and start:
                                if kind == HEART_RATE:
                                    heart.append((start, value, source))
                                else:
                                    records.append((kind, source, start, end or start,
                                                    _convert(kind, value, el.get("unit"))))
                    el.clear()
                elif tag == "Workout":
                    workouts.append(_workout(el))
                    el.clear()
                elif tag == "Me":
                    birth_text = el.get("HKCharacteristicTypeIdentifierDateOfBirth")
                    birth = dt.date.fromisoformat(birth_text) if birth_text else None
                    sex = {"HKBiologicalSexMale": "male", "HKBiologicalSexFemale": "female"}.get(
                        el.get("HKCharacteristicTypeIdentifierBiologicalSex") or "")
                elif tag == "ExportDate":
                    exported = el.get("value")
        routes = {}
        for workout in workouts:
            ref = workout.get("route_file")
            if not ref:
                continue
            match = next((n for n in names if n.endswith(ref.lstrip("/"))), None)
            if match:
                track = _gpx(archive.read(match))
                if len(track) >= 5:
                    routes[ref] = track
    return Export(
        records=pd.DataFrame(records, columns=["type", "source", "start", "end", "value"]),
        heart_rate=pd.DataFrame(heart, columns=["t", "bpm", "source"]).sort_values("t", ignore_index=True),
        sleep=pd.DataFrame(sleep, columns=["source", "start", "end", "stage"]),
        workouts=workouts, routes=routes, birth_date=birth, sex=sex, exported_at=exported,
    )


def _workout(el: ET.Element) -> dict[str, Any]:
    kind = (el.get("workoutActivityType") or "").replace("HKWorkoutActivityType", "")
    duration = _number(el.get("duration"))
    if duration is not None and (el.get("durationUnit") or "min") == "s":
        duration /= 60
    item: dict[str, Any] = {
        "type": kind, "source": el.get("sourceName") or "?",
        "start": _time(el.get("startDate")), "end": _time(el.get("endDate")), "duration_min": duration,
        "distance_km": None, "calories": None, "avg_hr": None, "max_hr": None,
        "elevation_gain_m": None, "indoor": False, "route_file": None,
    }
    total = _number(el.get("totalDistance"))  # older exports carry it on the element
    if total is not None:
        item["distance_km"] = _distance_km(total, el.get("totalDistanceUnit"))
    energy = _number(el.get("totalEnergyBurned"))
    if energy is not None:
        item["calories"] = energy
    for child in el:
        if child.tag == "WorkoutStatistics":
            stat = child.get("type") or ""
            if stat.startswith(f"{Q}Distance") and _number(child.get("sum")) is not None:
                item["distance_km"] = _distance_km(_number(child.get("sum")), child.get("unit"))
            elif stat == f"{Q}ActiveEnergyBurned" and _number(child.get("sum")) is not None:
                item["calories"] = _number(child.get("sum"))
            elif stat == HEART_RATE:
                item["avg_hr"] = _number(child.get("average"))
                item["max_hr"] = _number(child.get("maximum"))
        elif child.tag == "MetadataEntry":
            key, value = child.get("key"), child.get("value")
            if key == "HKElevationAscended":
                item["elevation_gain_m"] = _length_m(value)
            elif key == "HKIndoorWorkout":
                item["indoor"] = value == "1"
        elif child.tag == "WorkoutRoute":
            for ref in child:
                if ref.tag == "FileReference" and ref.get("path"):
                    item["route_file"] = ref.get("path")
    return item


# ------------------------------------------------------------------ daily


def _day(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.normalize()


def daily_totals(records: pd.DataFrame) -> pd.DataFrame:
    """Per day and column: the largest single-source total (sums) / mean / last value."""
    frames = []
    if records.empty:
        return pd.DataFrame(columns=["day"])
    records = records.assign(day=_day(records["start"]))
    sums = records[records["type"].isin(list(DAY_SUMS))]
    if not sums.empty:
        per_source = sums.groupby(["day", "type", "source"])["value"].sum()
        best = per_source.groupby(["day", "type"]).max().unstack("type").rename(columns=DAY_SUMS)
        frames.append(best)
    means = records[records["type"].isin(list(DAY_MEANS))]
    if not means.empty:
        # A night's readings belong to its morning, like sleep: one taken at 23:30
        # is the same night as one at 03:00.
        evening = means["type"].isin(list(NIGHT_TYPES)) & (pd.to_datetime(means["start"]).dt.hour >= 18)
        means = means.assign(day=means["day"] + pd.to_timedelta(evening.astype(int), unit="D"))
        frames.append(means.groupby(["day", "type"])["value"].mean().unstack("type").rename(columns=DAY_MEANS))
    last = records[records["type"].isin(list(DAY_LAST))].sort_values("start")
    if not last.empty:
        frames.append(last.groupby(["day", "type"])["value"].last().unstack("type").rename(columns=DAY_LAST))
    out = pd.concat(frames, axis=1).reset_index().rename(columns={"index": "day"})
    return out


def heart_extremes(heart: pd.DataFrame) -> pd.DataFrame:
    if heart.empty:
        return pd.DataFrame(columns=["day", "hr_min", "hr_max"])
    days = heart.assign(day=_day(heart["t"])).groupby("day")["bpm"]
    return pd.DataFrame({"hr_min": days.min(), "hr_max": days.max()}).reset_index()


def sleep_sessions(sleep: pd.DataFrame) -> list[dict[str, Any]]:
    """Segments -> one session per source per stretch of sleep; the best session per morning."""
    if sleep.empty:
        return []
    sessions = []
    for source, rows in sleep.sort_values("start").groupby("source"):
        current: list[tuple] = []
        for row in rows.itertuples(index=False):
            if current and row.start - max(r.end for r in current) > SESSION_GAP:
                sessions.append(_session(source, current))
                current = []
            current.append(row)
        if current:
            sessions.append(_session(source, current))
    best: dict[pd.Timestamp, dict[str, Any]] = {}
    for session in sessions:
        score = (session["asleep_min"] or session["in_bed_min"] * 0.5)
        held = best.get(session["day"])
        if held is None or score > (held["asleep_min"] or held["in_bed_min"] * 0.5):
            best[session["day"]] = session
    return [best[day] for day in sorted(best)]


def _session(source: str, rows: list) -> dict[str, Any]:
    staged = [r for r in rows if r.stage != "in_bed"]
    minutes = {stage: 0.0 for stage in ("light", "deep", "rem", "awake", "unknown")}
    # Overlapping duplicates inside one source (a re-synced night) are clipped,
    # so a stage is never counted twice.
    covered_until: dt.datetime | None = None
    kept = []
    for r in sorted(staged, key=lambda r: r.start):
        start = r.start if covered_until is None else max(r.start, covered_until)
        if start >= r.end:
            continue
        minutes[r.stage] += (r.end - start).total_seconds() / 60
        kept.append((r.stage, start, r.end))
        covered_until = r.end if covered_until is None else max(covered_until, r.end)
    in_bed = [r for r in rows if r.stage == "in_bed"]
    start = min(r.start for r in rows)
    end = max(r.end for r in rows)
    return {
        "source": source, "start": start, "end": end, "day": pd.Timestamp(end.date()),
        "asleep_min": sum(minutes[s] for s in ASLEEP), "minutes": minutes, "segments": kept,
        "in_bed_min": sum((r.end - r.start).total_seconds() / 60 for r in in_bed),
    }


def sleep_daily(sessions: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for s in sessions:
        staged = s["asleep_min"] > 0
        hours = (s["asleep_min"] if staged else max(s["in_bed_min"] - s["minutes"]["awake"], 0)) / 60
        if hours <= 0:
            continue
        rows.append({
            "day": s["day"],
            "sleep_h": round(hours, 2),
            "sleep_deep_h": round(s["minutes"]["deep"] / 60, 2) if staged else None,
            "sleep_light_h": round(s["minutes"]["light"] / 60, 2) if staged else None,
            "sleep_rem_h": round(s["minutes"]["rem"] / 60, 2) if staged else None,
            "sleep_awake_h": round(s["minutes"]["awake"] / 60, 2) if staged else None,
            # Wall-clock times as epoch ms, the shape Garmin's columns have.
            "sleep_start": pd.Timestamp(s["start"]).value / 1e6,
            "sleep_end": pd.Timestamp(s["end"]).value / 1e6,
            "sleep_in_bed_only": not staged,
            "sleep_source": s["source"],
        })
    return pd.DataFrame(rows, columns=["day", "sleep_h", "sleep_deep_h", "sleep_light_h", "sleep_rem_h",
                                       "sleep_awake_h", "sleep_start", "sleep_end", "sleep_in_bed_only",
                                       "sleep_source"])


def sleep_stages(sessions: list[dict[str, Any]], skip: Iterable[dt.date] = ()) -> pd.DataFrame:
    skipped = set(skip)
    rows = []
    for s in sessions:
        if s["day"].date() in skipped:
            continue
        for index, (stage, start, end) in enumerate(s["segments"]):
            rows.append({"day": s["day"], "segment": index, "stage": stage, "start_local": start,
                         "end_local": end, "minutes": round((end - start).total_seconds() / 60, 1)})
    if not rows:
        return pd.DataFrame(columns=["day", "segment", "stage", "start_local", "end_local", "minutes"])
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ workouts


def hr_max_estimate(max_hrs: Iterable[float], birth_date: dt.date | None, today: dt.date) -> float | None:
    """The higher of the third-highest workout maximum (one-off sensor spikes
    skipped, as on the Garmin side) and Tanaka's 208 - 0.7 x age.

    With a dozen workouts the third-highest maximum is mostly easy runs and sits
    well under the real maximum; a low HRmax inflates every TRIMP. The age
    formula is the floor until the record shows more. Neither known: None --
    no constant stands in for a maximum nobody measured.
    """
    values = sorted((v for v in max_hrs if v and 120 <= v <= 230), reverse=True)
    observed = float(values[2]) if len(values) >= 3 else None
    by_age = round(208 - 0.7 * (today - birth_date).days / 365.25, 1) if birth_date else None
    candidates = [v for v in (observed, by_age) if v is not None]
    return max(candidates) if candidates else None


def trimp(duration_min: float | None, avg_hr: float | None, hr_rest: float, hr_max: float,
          sex: str | None) -> float | None:
    """Banister's training impulse: minutes x heart-rate reserve x an exponential weight."""
    if not duration_min or not avg_hr or not hr_max or hr_max <= hr_rest:
        return None
    reserve = min(max((avg_hr - hr_rest) / (hr_max - hr_rest), 0.0), 1.0)
    a, b = (0.86, 1.67) if sex == "female" else (0.64, 1.92)
    return round(duration_min * reserve * a * math.exp(b * reserve), 1)


def activity_id(source: str, start: dt.datetime | None) -> int:
    """Stable across rebuilds and exports: the same workout keeps its id."""
    digest = hashlib.sha1(f"{source}|{start}".encode()).hexdigest()
    return int(digest[:13], 16)  # < 2**52: survives JavaScript and float round-trips


def _dedupe(workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same session written by two apps (Strava and Garmin Connect): keep the richer one."""
    kept: list[dict[str, Any]] = []
    for w in sorted(workouts, key=lambda w: (w["start"] or dt.datetime.min)):
        twin = next((k for k in kept if k["type"] == w["type"] and k["start"] and w["start"]
                     and abs((k["start"] - w["start"]).total_seconds()) <= 120), None)
        if twin is None:
            kept.append(w)
            continue
        richness = lambda x: sum(x.get(f) is not None for f in ("distance_km", "avg_hr", "route_file", "calories"))
        if richness(w) > richness(twin):
            kept[kept.index(twin)] = w
    return kept


class _Timeline:
    """Rows sorted by time, sliced by a window in O(log n) -- a watch export has
    millions of samples and every workout asks for its own few minutes."""

    def __init__(self, frame: pd.DataFrame, column: str):
        self.frame = frame.sort_values(column, ignore_index=True)
        self.times = self.frame[column].to_numpy("datetime64[ns]")

    def between(self, start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
        lo = np.searchsorted(self.times, np.datetime64(start, "ns"), side="left")
        hi = np.searchsorted(self.times, np.datetime64(end, "ns"), side="right")
        return self.frame.iloc[lo:hi]


def _zone_seconds(samples: pd.DataFrame, end: dt.datetime, cuts: list[int] | None) -> list[float | None]:
    """Seconds in Z1..Z5 (lower edges ``cuts`` from hrzones.edges); each sample lasts until the next (<= 60 s)."""
    if len(samples) < 3 or not cuts:
        return [None] * 5
    times = samples["t"].to_numpy("datetime64[ns]")
    following = np.append(times[1:], np.datetime64(end, "ns"))
    seconds = np.clip((following - times).astype("timedelta64[s]").astype(float), 0, 60)
    zone = np.searchsorted(np.asarray(cuts, float), samples["bpm"].to_numpy(float), side="right")
    return [round(float(seconds[zone == z].sum())) for z in range(5)]


def _cadence(steps: pd.DataFrame, minutes: float | None) -> float | None:
    """Steps per minute (both feet) from the busiest step source inside the workout."""
    if steps.empty or not minutes:
        return None
    best = steps.groupby("source")["value"].sum().max()
    cadence = best / minutes
    return round(float(cadence), 1) if 60 <= cadence <= 240 else None


def activities(export: Export, hr_rest: float, today: dt.date) -> pd.DataFrame:
    heart = export.heart_rate
    heart_line = _Timeline(heart, "t")
    record_line = _Timeline(export.records, "start")
    rows, inside_hr = [], {}
    for w in _dedupe(export.workouts):
        if not w["start"]:
            continue
        end = w["end"] or w["start"] + dt.timedelta(minutes=w["duration_min"] or 0)
        avg_hr, max_hr = w["avg_hr"], w["max_hr"]
        samples = heart_line.between(w["start"], end)
        if avg_hr is None and len(samples) >= 3:
            avg_hr, max_hr = round(float(samples["bpm"].mean()), 1), float(samples["bpm"].max())
        window = record_line.between(w["start"], end)
        extras = {column: (round(float(v.mean()), 2) if len(v := window[window["type"] == kind]["value"]) else None)
                  for kind, column in WORKOUT_MEANS.items()}
        # The effort score may be rated (or estimated) a few minutes after the workout ends.
        late = record_line.between(w["start"], end + dt.timedelta(minutes=15))
        for kind in (f"{Q}WorkoutEffortScore", f"{Q}EstimatedWorkoutEffortScore"):
            scores = late[late["type"] == kind]["value"]
            if len(scores):
                extras[WORKOUT_MEANS[kind]] = float(scores.iloc[-1])
        after = record_line.between(end, end + dt.timedelta(minutes=10))
        recovery = after[after["type"] == HR_RECOVERY]["value"]
        extras["hr_recovery_1min"] = float(recovery.iloc[0]) if len(recovery) else None
        extras["cadence"] = _cadence(window[window["type"] == STEPS], w["duration_min"])
        if extras["stride_m"] is not None and extras["stride_m"] > 3:  # written in cm by some apps
            extras["stride_m"] = round(extras["stride_m"] / 100, 2)
        key = activity_id(w["source"], w["start"])
        inside_hr[key] = (samples, end)
        sport = SPORTS.get(w["type"], _snake(w["type"]))
        if sport == "running" and w["indoor"]:
            sport = "treadmill_running"
        distance, duration = w["distance_km"], w["duration_min"]
        speed = distance / (duration / 60) if distance and duration else None
        rows.append({
            **extras,
            "activity_id": key,
            "start_local": pd.Timestamp(w["start"]),
            "name": w["type"],
            "sport": sport,
            "distance_km": round(distance, 3) if distance else None,
            "duration_min": round(duration, 1) if duration else None,
            "moving_min": round(duration, 1) if duration else None,
            "pace_min_km": round(duration / distance, 2) if distance and duration and sport in PACE_SPORTS else None,
            "speed_kmh": round(speed, 2) if speed else None,
            "avg_hr": avg_hr, "max_hr": max_hr,
            "calories": round(w["calories"]) if w["calories"] else None,
            "elevation_gain_m": round(w["elevation_gain_m"], 1) if w["elevation_gain_m"] else None,
            "route_file": w["route_file"],
            "data_source": w["source"],
        })
    columns = ["activity_id", "start_local", "name", "sport", "distance_km", "duration_min", "moving_min",
               "pace_min_km", "speed_kmh", "avg_hr", "max_hr", "calories", "elevation_gain_m", "route_file",
               "data_source", *WORKOUT_MEANS.values(), "hr_recovery_1min", "cadence"]
    df = pd.DataFrame(rows, columns=columns)
    import hrzones

    # A maximum typed in from a test (Account) beats the estimate; zones from the thresholds (hrzones).
    hr_max = hrzones.settings().get("hr_max") or hr_max_estimate(df["max_hr"].dropna(), export.birth_date, today)
    df["hr_max_used"] = hr_max
    cuts = hrzones.edges(hrzones.anchors(hr_max=hr_max))
    zones = [_zone_seconds(*inside_hr[k], cuts) for k in df["activity_id"]]
    for index in range(5):
        df[f"hr_z{index + 1}_s"] = [z[index] for z in zones]
    df["training_load"] = [trimp(d, h, hr_rest, hr_max, export.sex) for d, h in zip(df["duration_min"], df["avg_hr"])]
    df["load_source"] = np.where(df["training_load"].notna(), "trimp", None)
    df["source"] = "apple"
    df["start_local"] = pd.to_datetime(df["start_local"])
    df["day"] = df["start_local"].dt.normalize()
    df["iso_week"] = df["start_local"].dt.strftime("%G-W%V")
    return df.sort_values("start_local", ascending=False).reset_index(drop=True)


def _snake(name: str) -> str:
    out = "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")
    return out or "other"


def _haversine_m(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lat1, lon1 = np.radians(lat[:-1]), np.radians(lon[:-1])
    lat2, lon2 = np.radians(lat[1:]), np.radians(lon[1:])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(a))


def routes(export: Export, acts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """GPX tracks -> ``routes`` (points with distance, pace, heart rate) and ``route_summary``."""
    from etl import load

    tracks, summaries = [], []
    with_route = acts.dropna(subset=["route_file"])
    # Strava names route files by the minute they were written, so several of
    # its workouts can point at one file (the last one written wins). A file
    # shared by two workouts belongs to neither with any certainty.
    shared = set(with_route["route_file"][with_route["route_file"].duplicated(keep=False)])
    for row in with_route.itertuples(index=False):
        track = export.routes.get(row.route_file)
        if track is None or track.empty or row.route_file in shared:
            continue
        track = track.copy()
        steps = np.concatenate([[0.0], _haversine_m(track["lat"].to_numpy(float), track["lon"].to_numpy(float))])
        track["distance_km"] = np.cumsum(steps) / 1000
        if row.distance_km and abs(track["distance_km"].iloc[-1] / row.distance_km - 1) > 0.25:
            continue  # not this workout's track
        stamps = pd.to_datetime(track["t"])
        if stamps.notna().all() and stamps.nunique() > len(track) // 2:
            seconds = (stamps - stamps.iloc[0]).dt.total_seconds()
        else:  # no usable timestamps (Strava writes one for all): spread the duration evenly
            seconds = pd.Series(np.linspace(0, (row.duration_min or 0) * 60, len(track)))
        track["duration_s"] = seconds.to_numpy()
        track["moving_s"] = track["duration_s"]
        speed = pd.Series(steps).rolling(5, min_periods=1).sum() / pd.Series(np.diff(seconds, prepend=0)).rolling(
            5, min_periods=1).sum().replace(0, np.nan)
        track["speed_ms"] = speed.to_numpy()
        track["pace_min_km"] = (1000 / track["speed_ms"] / 60).where(track["speed_ms"] > 0.5).round(2)
        track["hr"] = _hr_along(export.heart_rate, row.start_local, track["duration_s"])
        step = max(1, len(track) // config.ROUTE_POINTS)
        track = track.iloc[::step].reset_index(drop=True)
        track.insert(0, "seq", range(len(track)))
        track.insert(0, "activity_id", row.activity_id)
        tracks.append(track.drop(columns=["t"]))
        summaries.append({
            "activity_id": row.activity_id, "points": int(len(track)),
            "min_lat": track["lat"].min(), "max_lat": track["lat"].max(),
            "min_lon": track["lon"].min(), "max_lon": track["lon"].max(),
            "start_lat": track["lat"].iloc[0], "start_lon": track["lon"].iloc[0],
            "elevation_gain_m": load._elevation_gain(track),
        })
    if not tracks:
        return pd.DataFrame(columns=["activity_id"]), pd.DataFrame(columns=["activity_id"])
    return pd.concat(tracks, ignore_index=True), pd.DataFrame(summaries)


def _hr_along(heart: pd.DataFrame, start: pd.Timestamp, seconds: pd.Series) -> np.ndarray:
    if heart.empty:
        return np.full(len(seconds), np.nan)
    times = pd.DataFrame({"t": pd.Timestamp(start) + pd.to_timedelta(seconds.to_numpy(), unit="s")})
    times["t"] = times["t"].astype("datetime64[ns]")
    samples = heart[["t", "bpm"]].copy()
    samples["t"] = samples["t"].astype("datetime64[ns]")
    joined = pd.merge_asof(times, samples, on="t", direction="nearest", tolerance=pd.Timedelta(seconds=90))
    return joined["bpm"].to_numpy(float)


# ------------------------------------------------------------------ build


def exports_dir() -> Path:
    return config.raw() / "apple" / "exports"


def latest_export() -> Path | None:
    found = sorted(exports_dir().glob("*.zip"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def build(export: Export, today: dt.date | None = None, skip: Iterable[dt.date] = ()) -> dict[str, pd.DataFrame]:
    """Every table of the warehouse that Health can fill, in the Garmin schema."""
    from etl import load

    today = today or dt.date.today()
    sessions = sleep_sessions(export.sleep)
    parts = [daily_totals(export.records), heart_extremes(export.heart_rate), sleep_daily(sessions),
             nightly_hrv(sessions, export.records)]
    daily = parts[0]
    for part in parts[1:]:
        daily = daily.merge(part, on="day", how="outer") if not part.empty else daily
    if daily.empty:
        daily = pd.DataFrame(columns=["day"])
    daily["day"] = pd.to_datetime(daily["day"])
    if {"active_calories", "bmr_calories"} <= set(daily.columns):
        daily["calories"] = daily[["active_calories", "bmr_calories"]].sum(axis=1, min_count=1).round()
    for column in ("steps", "floors_up", "active_calories", "bmr_calories", "distance_m"):
        if column in daily.columns:
            daily[column] = daily[column].round()
    daily["source"] = "apple"
    daily = schema.daily(daily)
    daily = load.mask_nights(daily.sort_values("day").reset_index(drop=True), {d: "" for d in skip})
    daily = load.add_derived(hrv_norm(daily))

    rest = pd.to_numeric(daily.get("rhr"), errors="coerce").dropna() if "rhr" in daily.columns else pd.Series()
    hr_rest = float(rest.median()) if len(rest) else 60.0
    acts = activities(export, hr_rest, today)
    route_points, route_summary = routes(export, acts)
    if not route_summary.empty:
        starts = route_summary.set_index("activity_id")[["start_lat", "start_lon"]]
        acts = acts.join(starts, on="activity_id")
    return {
        "daily": daily,
        "activities": schema.activities(acts.drop(columns=["route_file"])),
        "sleep_stages": sleep_stages(sessions, skip),
        "night_series": night_series(sessions, export.heart_rate, export.records, skip),
        "routes": route_points,
        "route_summary": route_summary,
    }


def _session_window(session: dict[str, Any]) -> tuple[dt.datetime, dt.datetime]:
    margin = dt.timedelta(minutes=15)
    return session["start"] - margin, session["end"] + margin


def nightly_hrv(sessions: list[dict[str, Any]], records: pd.DataFrame) -> pd.DataFrame:
    """Overnight HRV per morning: the mean of the watch's SDNN readings inside the sleep.

    Daytime readings are left out on purpose -- after a walk or a coffee SDNN
    says something else, and Garmin's ``hrv_last_night`` is overnight too, so
    the pages read both the same way (each against the person's own norm).
    """
    columns = ["day", "hrv_last_night", "hrv_kind"]
    readings = records[records["type"] == HRV] if not records.empty else records
    if readings.empty or not sessions:
        return pd.DataFrame(columns=columns)
    line = _Timeline(readings, "start")
    rows = []
    for session in sessions:
        inside = line.between(*_session_window(session))["value"]
        if len(inside):
            rows.append({"day": session["day"], "hrv_last_night": round(float(inside.mean()), 1), "hrv_kind": "sdnn"})
    return pd.DataFrame(rows, columns=columns)


def hrv_norm(daily: pd.DataFrame) -> pd.DataFrame:
    """The person's own normal range for overnight HRV: 10th-90th percentile of the
    60 nights before (at least 14) -- Garmin's "balanced" band has no Apple twin."""
    out = daily.copy()
    nights = out.dropna(subset=["hrv_last_night"])
    if len(nights) < NORM_MIN + 1:
        return out
    values = nights["hrv_last_night"].astype(float).shift(1)
    rolling = values.rolling(NORM_NIGHTS, min_periods=NORM_MIN)
    out.loc[nights.index, "hrv_baseline_low"] = rolling.quantile(0.10).round(1).to_numpy()
    out.loc[nights.index, "hrv_baseline_high"] = rolling.quantile(0.90).round(1).to_numpy()
    out.loc[nights.index, "hrv_norm"] = np.where(out.loc[nights.index, "hrv_baseline_low"].notna(), "own", None)
    return out


def night_series(sessions: list[dict[str, Any]], heart: pd.DataFrame, records: pd.DataFrame,
                 skip: Iterable[dt.date] = ()) -> pd.DataFrame:
    """Overnight heart rate and HRV readings in the long format Garmin's night series has."""
    skipped = set(skip)
    heart_line = _Timeline(heart, "t") if not heart.empty else None
    readings = records[records["type"] == HRV] if not records.empty else records
    hrv_line = _Timeline(readings, "start") if not readings.empty else None
    rows = []
    for session in sessions:
        if session["day"].date() in skipped:
            continue
        window = _session_window(session)
        if heart_line is not None:
            for t, bpm in heart_line.between(*window)[["t", "bpm"]].itertuples(index=False):
                rows.append((session["day"], "hr", t, float(bpm)))
        if hrv_line is not None:
            for t, value in hrv_line.between(*window)[["start", "value"]].itertuples(index=False):
                rows.append((session["day"], "hrv", t, float(value)))
    df = pd.DataFrame(rows, columns=["day", "metric", "t_local", "value"])
    if df.empty:
        return df
    df["t_local"] = pd.to_datetime(df["t_local"])
    df["minutes_from_midnight"] = df["t_local"].dt.hour * 60 + df["t_local"].dt.minute
    return df


def main() -> int:
    """Rebuild the current person's base tables: the newest full export plus every daily push."""
    from etl import apple_push, load

    person = config._person()
    path = latest_export()
    pushed = apple_push.pushes()
    if path is None and not pushed:
        print(f"{person.id}: brak eksportu w {exports_dir()} i brak wysyłek z iPhone'a — najpierw "
              "`python -m etl.apple import <export.zip>` albo Skrót (DOSTEP.md)", flush=True)
        return 1
    skip = set(load.excluded_nights())
    tables = build(apple_push.combine(([parse(path)] if path else []) + pushed), skip=skip)
    for name, frame in tables.items():
        load.write_table(frame, name)
    # Garmin-only tables stay present and empty, so every view finds its table.
    for name, frame in (("activity_segments", pd.DataFrame(columns=["activity_id"])),
                        ("run_laps", pd.DataFrame(columns=["activity_id"])),
                        ("intraday", pd.DataFrame(columns=["t_local", "stress", "body_battery", "hour"]))):
        load.write_table(frame, name)
    daily, acts = tables["daily"], tables["activities"]
    state = {
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source": "apple",
        "export": path.name if path else None,
        "pushes": len(pushed),
        "days": int(len(daily)),
        "first_day": str(daily["day"].min().date()) if len(daily) else None,
        "last_day": str(daily["day"].max().date()) if len(daily) else None,
        "activities": int(len(acts)),
        "sleep_stage_rows": int(len(tables["sleep_stages"])),
        "route_points": int(len(tables["routes"])),
        "routes": int(len(tables["route_summary"])),
        "excluded_nights": sorted(str(d) for d in skip),
    }
    config.state_file().parent.mkdir(parents=True, exist_ok=True)
    config.state_file().write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"{person.id}: tabele z Apple Health: {state['days']} dni ({state['first_day']} .. {state['last_day']}), "
          f"{state['activities']} treningow, {state['routes']} tras", flush=True)
    return 0


def import_export(source: Path) -> Path:
    """Copy an export into raw/ under the date it was exported; rebuild."""
    with zipfile.ZipFile(source) as archive:  # refuse anything that is not an export
        if not any(n.endswith("export.xml") for n in archive.namelist()):
            raise ValueError(f"{source}: to nie jest eksport Apple Health (brak export.xml)")
    target = exports_dir() / f"export-{dt.date.today():%Y-%m-%d}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m etl.apple", description="Apple Health -> tabele osoby")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("import").add_argument("path", type=Path)
    args = parser.parse_args(argv)
    person = config._person()
    if person.source != "apple":
        print(f"{person.id} ma źródło {person.source}, nie apple (GARMIN_USER=<id>)")
        return 1
    if args.command == "import":
        print(f"zapisano {import_export(args.path)}")
    from etl import fetch

    fetch.rebuild()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
