"""Readiness for any training, not just a run.

One number 0-100 from six parts, each scored on the same scale where ~65 is an
ordinary day for this person:

* ``garmin``  -- Garmin's training readiness as recorded.
* ``hrv``     -- last night's HRV against 60 nights before it (z of ln HRV).
* ``rhr``     -- resting heart rate against its 60-day median.
* ``sleep``   -- hours against 7.5 h, averaged with Garmin's sleep score.
* ``load``    -- acute:chronic load of **all** sports (7 d vs 28 d per week);
                 Garmin's own ratio counts only what it calls training.
* ``fresh``   -- hours since the last hard session of any kind.

The score is their weighted mean (Garmin and HRV count 1.5x); night parts older
than a day are dropped rather than trusted. Two night parts below 35 cap the
day at ``easy`` whatever the mean says -- that pattern is illness or a bad night,
and a high load score must not average it away.

``systems`` is local fatigue: each session of the last four days leaves load on
``impact``/``legs``/``upper`` (catalog weights x its load relative to a typical
session), fading exponentially. 1.0 is roughly "one typical hard hit today".
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import numpy as np
import pandas as pd

from sport import catalog

WEIGHTS = {"garmin": 1.5, "hrv": 1.5, "rhr": 1.0, "sleep": 1.0, "load": 1.0, "fresh": 1.0}
NIGHT_PARTS = ("garmin", "hrv", "rhr", "sleep")
BASELINE_DAYS = 60
THRESHOLDS = [(68, "hard"), (52, "moderate"), (38, "easy")]  # else "recover"
TAU_H = {"impact": 30.0, "legs": 24.0, "upper": 24.0}
FATIGUE_WINDOW_H = 96
LOAD_PER_MIN = 1.0  # stand-in training load per minute when Garmin left it empty


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(min(high, max(low, value)))


def _num(row: pd.Series, column: str) -> float | None:
    if column not in row.index or pd.isna(row[column]):
        return None
    return float(row[column])


def sessions(activities: pd.DataFrame) -> pd.DataFrame:
    """Activities with the discipline, an end time and a load (estimated when missing)."""
    if activities is None or activities.empty:
        return pd.DataFrame(columns=["activity_id", "start_local", "end_local", "sport", "discipline", "minutes",
                                     "load", "hard", "day"])
    frame = activities.copy()
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    frame["minutes"] = pd.to_numeric(frame.get("duration_min"), errors="coerce").fillna(0.0)
    frame["end_local"] = frame["start_local"] + pd.to_timedelta(frame["minutes"], unit="min")
    frame["discipline"] = [catalog.discipline_of(s) or str(s) for s in frame["sport"]]
    load = pd.to_numeric(frame.get("training_load"), errors="coerce")
    frame["load"] = load.where(load.notna(), frame["minutes"] * LOAD_PER_MIN)
    typical = typical_load(frame)
    aerobic = pd.to_numeric(frame.get("te_aerobic"), errors="coerce").fillna(0)
    anaerobic = pd.to_numeric(frame.get("te_anaerobic"), errors="coerce").fillna(0)
    frame["hard"] = (aerobic >= 4.0) | (anaerobic >= 2.5) | (frame["load"] >= 1.6 * typical)
    frame["day"] = frame["start_local"].dt.normalize()
    return frame.sort_values("start_local").reset_index(drop=True)


def typical_load(frame: pd.DataFrame) -> float:
    """Median load of a session in the last year of the record (80 when there is none)."""
    if frame.empty:
        return 80.0
    recent = frame[frame["start_local"] >= frame["start_local"].max() - pd.Timedelta(days=365)]
    value = recent["load"].median()
    return float(value) if pd.notna(value) and value > 0 else 80.0


def _night(daily: pd.DataFrame, today: dt.date) -> tuple[pd.Series | None, pd.DataFrame]:
    if daily is None or daily.empty:
        return None, pd.DataFrame()
    frame = daily.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame[frame["day"].dt.date <= today].sort_values("day")
    present = [c for c in ("readiness", "hrv_last_night", "sleep_h", "rhr") if c in frame.columns]
    nights = frame.dropna(subset=present, how="all") if present else frame.iloc[0:0]
    if nights.empty:
        return None, frame
    return nights.iloc[-1], frame


def _hrv(row: pd.Series, history: pd.DataFrame) -> dict | None:
    value = _num(row, "hrv_last_night")
    if value is None or value <= 0 or "hrv_last_night" not in history:
        return None
    past = history["hrv_last_night"].dropna()
    past = np.log(past[past > 0])
    if len(past) < 14 or past.std() <= 0:
        return None
    z = (math.log(value) - past.mean()) / past.std()
    return {"score": _clip(65 + 20 * z), "value": value, "z": round(float(z), 2)}


def _rhr(row: pd.Series, history: pd.DataFrame) -> dict | None:
    value = _num(row, "rhr")
    if value is None or "rhr" not in history:
        return None
    past = history["rhr"].dropna()
    if len(past) < 14:
        return None
    diff = value - float(past.median())
    return {"score": _clip(65 - 6 * diff), "value": value, "diff": round(diff, 1)}


def _sleep(row: pd.Series) -> dict | None:
    hours, garmin = _num(row, "sleep_h"), _num(row, "sleep_score")
    if hours is None and garmin is None:
        return None
    parts = []
    if hours is not None:
        parts.append(_clip(65 + 15 * (hours - 7.5)))
    if garmin is not None:
        parts.append(garmin)
    return {"score": float(np.mean(parts)), "value": hours, "sleep_score": garmin}


def load_ratio(frame: pd.DataFrame, now: pd.Timestamp) -> dict | None:
    """All-sport acute (7 d) against chronic (28 d per week) load."""
    past = frame[frame["start_local"] <= now]
    chronic_window = past[past["start_local"] > now - pd.Timedelta(days=28)]
    if len(chronic_window) < 3:
        return None
    acute = float(past[past["start_local"] > now - pd.Timedelta(days=7)]["load"].sum())
    chronic = float(chronic_window["load"].sum()) / 4
    if chronic <= 0:
        return None
    ratio = acute / chronic
    if ratio <= 0.8:
        score = 75.0
    elif ratio <= 1.3:
        score = 75 - (ratio - 0.8) * 30
    else:
        score = 60 - (ratio - 1.3) * 80
    return {"score": _clip(score, 15, 80), "value": round(ratio, 2), "acute": round(acute), "chronic": round(chronic)}


def freshness(frame: pd.DataFrame, now: pd.Timestamp) -> dict:
    past = frame[(frame["end_local"] <= now) & frame["hard"]]
    past = past[past["end_local"] > now - pd.Timedelta(days=14)]
    if past.empty:
        return {"score": 80.0, "hours": None, "discipline": None}
    last = past.iloc[-1]
    hours = (now - last["end_local"]).total_seconds() / 3600
    score = 35.0 if hours < 18 else 50.0 if hours < 36 else 65.0 if hours < 60 else 75.0
    return {"score": score, "hours": round(hours), "discipline": last["discipline"]}


def systems(frame: pd.DataFrame, now: pd.Timestamp) -> dict[str, float]:
    """Fatigue per body system, 0 = fresh, 1 = one typical session's full hit right now."""
    out = {name: 0.0 for name in catalog.SYSTEMS}
    if frame.empty:
        return out
    typical = typical_load(frame)
    recent = frame[(frame["start_local"] <= now) & (frame["end_local"] > now - pd.Timedelta(hours=FATIGUE_WINDOW_H))]
    for item in recent.itertuples(index=False):
        if item.discipline not in catalog.DISCIPLINES:
            continue
        weights = catalog.get(item.discipline).load
        age = max(0.0, (now - min(item.end_local, now)).total_seconds() / 3600)
        size = min(2.0, float(item.load) / typical)
        for name in catalog.SYSTEMS:
            out[name] += size * weights.get(name, 0.0) * math.exp(-age / TAU_H[name])
    return {name: round(min(1.5, value), 2) for name, value in out.items()}


def level_of(score: float) -> str:
    for edge, level in THRESHOLDS:
        if score >= edge:
            return level
    return "recover"


def assess(daily: pd.DataFrame, activities: pd.DataFrame, today: dt.date,
           now: pd.Timestamp | None = None, *, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    """Today's readiness for any training: score, level, parts and fatigue per system.

    ``frame`` is ``sessions(activities)`` when the caller already has it."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp(dt.datetime.combine(today, dt.time(12)))
    frame = sessions(activities) if frame is None else frame
    row, days = _night(daily, today)
    parts: dict[str, dict] = {}
    stale = None
    if row is not None:
        stale = (today - pd.Timestamp(row["day"]).date()).days
        if stale <= 1:
            start = row["day"] - pd.Timedelta(days=BASELINE_DAYS)
            history = days[(days["day"] < row["day"]) & (days["day"] >= start)]
            if "night_excluded" in history.columns:
                history = history[~history["night_excluded"].fillna(False).astype(bool)]
            readiness = _num(row, "readiness")
            if readiness is not None:
                parts["garmin"] = {"score": readiness, "value": readiness,
                                   "level": row.get("readiness_level") if pd.notna(row.get("readiness_level")) else None}
            for key, part in (("hrv", _hrv(row, history)), ("rhr", _rhr(row, history)), ("sleep", _sleep(row))):
                if part is not None:
                    parts[key] = part
    ratio = load_ratio(frame, now)
    if ratio is not None:
        parts["load"] = ratio
    parts["fresh"] = freshness(frame, now)
    for part in parts.values():
        part["score"] = round(float(part["score"]))

    total = sum(WEIGHTS[k] for k in parts)
    score = round(sum(WEIGHTS[k] * p["score"] for k, p in parts.items()) / total) if total else None
    level = level_of(score) if score is not None else "moderate"
    low_nights = [k for k in NIGHT_PARTS if k in parts and parts[k]["score"] < 35]
    capped = len(low_nights) >= 2 and catalog.LEVELS.index(level) > catalog.LEVELS.index("easy")
    if capped:
        level = "easy"
    return {
        "score": score,
        "level": level,
        "capped": capped,
        "parts": parts,
        "night_day": str(pd.Timestamp(row["day"]).date()) if row is not None else None,
        "stale_days": stale,
        "night_used": any(k in parts for k in NIGHT_PARTS),
        "systems": systems(frame, now),
        "typical_load": round(typical_load(frame)),
    }


def history(daily: pd.DataFrame, activities: pd.DataFrame, days: int = 90,
            end: dt.date | None = None) -> pd.DataFrame:
    """The score day by day (as of noon), for the trend of the last ``days``."""
    if daily is None or daily.empty:
        return pd.DataFrame(columns=["day", "score"])
    last = end or pd.to_datetime(daily["day"]).max().date()
    frame = sessions(activities)
    rows = []
    for offset in range(days - 1, -1, -1):
        day = last - dt.timedelta(days=offset)
        result = assess(daily, activities, day, frame=frame)
        if result["night_used"] and result["score"] is not None:
            rows.append({"day": pd.Timestamp(day), "score": result["score"], "level": result["level"]})
    return pd.DataFrame(rows, columns=["day", "score", "level"])
