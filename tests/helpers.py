"""Synthetic runs, tracks and daily rows with known answers."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run(activity_id: int, day: str, km: float, pace: float, *, hr: float | None = 145, max_hr: float = 175,
        name: str = "Easy Run", sport: str = "running", **extra) -> dict:
    row = {
        "activity_id": activity_id,
        "start_local": pd.Timestamp(day) + pd.Timedelta(hours=18),
        "name": name,
        "sport": sport,
        "distance_km": km,
        "duration_min": km * pace,
        "moving_min": km * pace,
        "pace_min_km": pace,
        "avg_hr": hr,
        "max_hr": max_hr,
        "gap_speed": 1000 / (pace * 60),
        "training_load": 50.0,
        "te_aerobic": 3.0,
        "te_anaerobic": 0.0,
        "elevation_gain_m": 20.0,
        "cadence": 168.0,
        "best_1k_s": None,
        "best_mile_s": None,
        "best_5k_s": None,
    }
    row.update(extra)
    return row


def activities(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["day"] = pd.to_datetime(frame["start_local"]).dt.normalize()
    return frame


def track(activity_id: int, km: float, pace: float | list[float], hr: float = 150, points: int = 400) -> pd.DataFrame:
    """Samples along a run. ``pace`` may be a list: one pace per equal part."""
    paces = pace if isinstance(pace, list) else [pace]
    metres = np.linspace(0, km * 1000, points)
    part = np.minimum((metres / (km * 1000) * len(paces)).astype(int), len(paces) - 1)
    seconds_per_m = np.array(paces)[part] * 60 / 1000
    seconds = np.concatenate([[0], np.cumsum(np.diff(metres) * seconds_per_m[1:])])
    return pd.DataFrame(
        {
            "activity_id": activity_id,
            "seq": np.arange(points),
            "distance_km": metres / 1000,
            "duration_s": seconds,
            "timestamp_ms": 1.7e12 + seconds * 1000,
            "hr": hr,
            "speed_ms": 1 / seconds_per_m,
            "elevation_m": 100.0,
            "cadence": 84.0,
        }
    )


def daily(start: str, days: int, rhr: float = 50, **columns) -> pd.DataFrame:
    frame = pd.DataFrame({"day": pd.date_range(start, periods=days, freq="D"), "rhr": rhr})
    for name, value in columns.items():
        frame[name] = value
    return frame


def training_block(start: str, weeks: int, *, easy_pace: float = 6.0, easy_hr: float = 145,
                   long_km: float = 12.0, first_id: int = 1) -> list[dict]:
    """Three easy runs and one long run per week, Tue/Thu/Sat + Sun."""
    rows = []
    monday = pd.Timestamp(start)
    activity_id = first_id
    for week in range(weeks):
        base = monday + pd.Timedelta(weeks=week)
        for offset, km in ((1, 6.0), (3, 7.0), (5, 6.0)):
            rows.append(run(activity_id, str((base + pd.Timedelta(days=offset)).date()), km, easy_pace, hr=easy_hr))
            activity_id += 1
        rows.append(run(activity_id, str((base + pd.Timedelta(days=6)).date()), long_km, easy_pace + 0.2,
                        hr=easy_hr + 3))
        activity_id += 1
    return rows
