"""Watch workouts rep by rep, and against the earlier workouts like them.

Everything comes from the watch's laps (``run_laps``), the only exact record
of a workout: a rep is a run of consecutive ``active`` laps of one workout
step (auto-lap cuts a 2 km rep into 1000 + 1000 m), the recovery after it is
the ``recovery``/``rest`` laps up to the next rep.

Comparing two workouts by pace alone says little -- 5x800 m is run faster
than 3x2 km. Two numbers travel between them:

* **the shape of the session** -- how much the last rep lost on the first
  (``fade_s``) and how much the heart rate climbed doing it (``hr_drift``);
* **pace at a given heart rate** -- a straight line pace ~ HR through the reps
  of the earlier workouts (last two years), and how far this session's reps sit
  off it. Negative = faster than the earlier reps at the same heart rate.
  Rep HR is an average that lags the effort (the first rep reads low), so the
  line describes reps, not a physiological curve.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

RECOVERY = ("recovery", "rest")
QUALITY = ("intervals", "threshold", "tempo", "race")
OPTIONAL = ("avg_hr", "max_hr", "cadence")
SIMILAR_REP = 0.35  # rep length within +-35% counts as "the same workout"
FIT_DAYS = 730
FIT_MIN_REPS, FIT_MIN_SESSIONS = 8, 3


def reps(laps: pd.DataFrame | None) -> pd.DataFrame:
    """One row per work rep: distance, time, pace, HR, cadence, the laps
    inside it and the recovery that followed it.

    A run without any warm-up / recovery laps was not a watch workout -- the
    whole run would be one "rep" -- so it has none.
    """
    if laps is None or laps.empty or not laps["intensity"].isin(("warmup", "cooldown", *RECOVERY)).any():
        return pd.DataFrame()
    laps = laps.reindex(columns=[*laps.columns, *(c for c in OPTIONAL if c not in laps.columns)])
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for lap in laps.sort_values("lap").itertuples(index=False):
        if lap.intensity == "active" and lap.distance_m:
            if current is None or lap.step_index != current["step"]:
                current = {"step": lap.step_index, "laps": [], "rest": []}
                blocks.append(current)
            current["laps"].append(lap)
            continue
        if lap.intensity in RECOVERY and blocks:
            blocks[-1]["rest"].append(lap)
        current = None

    rows = []
    for block in blocks:
        parts = block["laps"]
        metres = sum(float(p.distance_m) for p in parts)
        seconds = sum(float(p.duration_s or 0) for p in parts)
        if metres < 100 or seconds <= 0:
            continue
        rest = block["rest"]
        rest_s = sum(float(p.duration_s or 0) for p in rest)
        rest_m = sum(float(p.distance_m or 0) for p in rest)
        rows.append({
            "km": round(metres / 1000, 2),
            "seconds": seconds,
            "pace": seconds / 60 / (metres / 1000),
            "hr": _weighted(parts, "avg_hr"),
            "hr_max": max((float(p.max_hr) for p in parts if pd.notna(p.max_hr)), default=np.nan),
            "cadence": _weighted(parts, "cadence"),
            "laps": [(float(p.distance_m) / 1000, float(p.duration_s or 0) / 60 / (float(p.distance_m) / 1000))
                     for p in parts],
            "rest_s": rest_s if rest else np.nan,
            "rest_pace": rest_s / 60 / (rest_m / 1000) if rest and rest_m > 20 else np.nan,
            "rest_hr": _weighted(rest, "avg_hr") if rest else np.nan,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out.insert(0, "rep", range(1, len(out) + 1))
    return out


def _weighted(laps: list, column: str) -> float:
    pairs = [(float(getattr(p, column)), float(p.duration_s or 0)) for p in laps if pd.notna(getattr(p, column))]
    total = sum(w for _, w in pairs)
    return round(sum(v * w for v, w in pairs) / total, 1) if total else np.nan


def summary(table: pd.DataFrame) -> dict[str, Any]:
    """The shape of one workout: how even the reps were and what they cost."""
    if table.empty:
        return {"reps": 0}
    first, last = table.iloc[0], table.iloc[-1]
    speed_m_min = table["km"].sum() * 1000 / (table["seconds"].sum() / 60)
    hr = (table["hr"] * table["seconds"]).sum() / table["seconds"].sum() if table["hr"].notna().all() else np.nan
    return {
        "reps": len(table),
        "rep_km": float(table["km"].median()),
        "pace": table["seconds"].sum() / 60 / table["km"].sum(),
        "hr": hr,
        "fade_s": (last["pace"] - first["pace"]) * 60,
        "spread_s": (table["pace"].max() - table["pace"].min()) * 60,
        "hr_drift": last["hr"] - first["hr"],
        "m_per_beat": speed_m_min / hr if pd.notna(hr) and hr else np.nan,
        "rest_s": float(table["rest_s"].median()) if table["rest_s"].notna().any() else np.nan,
    }


def history(runs: pd.DataFrame, laps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every quality watch workout with at least two reps: one summary row
    per session, and all their reps (with ``activity_id`` and ``start_local``).
    A long run split into "steps" on the watch is not a workout to compare."""
    if runs is None or runs.empty or laps is None or laps.empty:
        return pd.DataFrame(), pd.DataFrame()
    starts = runs[runs["kind"].isin(QUALITY)].set_index("activity_id")["start_local"]
    sessions, all_reps = [], []
    for activity_id, mine in laps.groupby("activity_id"):
        if activity_id not in starts.index:
            continue
        table = reps(mine)
        if len(table) < 2:
            continue
        all_reps.append(table.assign(activity_id=activity_id, start_local=starts[activity_id]))
        sessions.append({"activity_id": activity_id, "start_local": starts[activity_id], **summary(table)})
    if not sessions:
        return pd.DataFrame(), pd.DataFrame()
    frame = pd.DataFrame(sessions).sort_values("start_local").reset_index(drop=True)
    every = pd.concat(all_reps, ignore_index=True)
    frame["vs_hr_s"] = [_offset(every, row.activity_id, row.start_local) for row in frame.itertuples()]
    return frame, every


def hr_fit(every: pd.DataFrame, activity_id: int, before: pd.Timestamp) -> tuple[float, float] | None:
    """``(intercept, slope)`` of pace ~ HR over the reps of earlier workouts
    in the last two years; None when there are too few to draw a line."""
    pool = every[(every["activity_id"] != activity_id) & (every["start_local"] < before)
                 & (every["start_local"] >= before - pd.Timedelta(days=FIT_DAYS))].dropna(subset=["hr", "pace"])
    if len(pool) < FIT_MIN_REPS or pool["activity_id"].nunique() < FIT_MIN_SESSIONS or pool["hr"].std() < 2:
        return None
    slope, intercept = np.polyfit(pool["hr"], pool["pace"], 1)
    # Faster at a higher heart rate, or the line says nothing.
    return (float(intercept), float(slope)) if slope < 0 else None


def _offset(every: pd.DataFrame, activity_id: int, before: pd.Timestamp) -> float:
    """Mean seconds/km this session's reps sit off the earlier reps' line."""
    fit = hr_fit(every, activity_id, before)
    mine = every[every["activity_id"] == activity_id].dropna(subset=["hr"])
    if fit is None or mine.empty:
        return np.nan
    expected = fit[0] + fit[1] * mine["hr"]
    return float(((mine["pace"] - expected) * 60).mean())


def peers(sessions: pd.DataFrame, activity_id: int) -> pd.DataFrame:
    """The session itself and every other workout, ``similar`` when its reps
    are about as long (+-35%)."""
    if sessions.empty or activity_id not in set(sessions["activity_id"]):
        return pd.DataFrame()
    target = sessions[sessions["activity_id"] == activity_id].iloc[0]
    ratio = sessions["rep_km"] / target["rep_km"]
    return sessions.assign(similar=ratio.between(1 - SIMILAR_REP, 1 + SIMILAR_REP),
                           current=sessions["activity_id"] == activity_id)
