"""Runs as training sessions: selection, classification, splits, best efforts.

Classification is rule-based and every label carries the reason it was given
and a confidence, because the inputs differ in quality run to run: a
structured watch workout states its own phases, a run with heart rate can be
placed by intensity, and a run with neither can only be guessed from pace and
distance. A label is a description of the session, not a judgement of it.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from running import physio, units

# Run kinds, internal key -> Polish label shown on the page.
KINDS: dict[str, str] = {
    "recovery": "regeneracyjny",
    "easy": "spokojny",
    "long": "długie wybieganie",
    "tempo": "tempo",
    "threshold": "próg",
    "intervals": "interwały",
    "race": "start / próba",
}
HARD_KINDS = ("tempo", "threshold", "intervals", "race")

# Below a kilometre or slower than a brisk walk is a recording left running
# (the same rule the efficiency table uses).
MIN_KM = 1.0
MAX_PACE = 12.0

RACE_WORDS = re.compile(
    r"\b(race|zawody|parkrun|maraton|półmaraton|polmaraton|marathon|half|start|"
    r"pb|test|time ?trial|tt)\b",
    re.IGNORECASE,
)
REPS = re.compile(r"\d+(?:[.,]\d+)?\s*[x×]\s*\d")

EFFORT_DISTANCES: dict[str, float] = {
    "1k": 1000.0,
    "mile": 1609.34,
    "3k": 3000.0,
    "5k": 5000.0,
    "10k": 10000.0,
    "hm": 21097.5,
    "m": 42195.0,
}
EFFORT_LABELS = {
    "block": "blok workoutu",
    "1k": "1 km",
    "mile": "1 mila",
    "3k": "3 km",
    "5k": "5 km",
    "10k": "10 km",
    "hm": "półmaraton",
    "m": "maraton",
}
GARMIN_SPLITS = {"1k": "best_1k_s", "mile": "best_mile_s", "5k": "best_5k_s"}


def select_runs(activities: pd.DataFrame) -> pd.DataFrame:
    """Running activities that are real runs, oldest first, with typed columns."""
    if activities is None or activities.empty or "sport" not in activities.columns:
        return pd.DataFrame()
    frame = activities[activities["sport"].astype(str).str.contains("running", na=False)].copy()
    if frame.empty:
        return frame
    for column in ("distance_km", "duration_min", "moving_min", "pace_min_km", "avg_hr", "max_hr",
                   "gap_speed", "training_load", "te_aerobic", "te_anaerobic", "elevation_gain_m",
                   "cadence"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["start_local"] = pd.to_datetime(frame["start_local"], errors="coerce")
    frame["day"] = frame["start_local"].dt.normalize()
    frame = frame[
        (frame["distance_km"] >= MIN_KM)
        & (frame["pace_min_km"] <= MAX_PACE)
        & frame["start_local"].notna()
    ]
    frame["activity_id"] = pd.to_numeric(frame["activity_id"], errors="coerce").astype("int64")
    return frame.sort_values("start_local").reset_index(drop=True)


# --------------------------------------------------------------------------
# classification


def _structure(segments: pd.DataFrame) -> dict[int, dict[str, Any]]:
    """Per activity: active reps, active distance/speed, and phase flags."""
    out: dict[int, dict[str, Any]] = {}
    if segments is None or segments.empty:
        return out
    frame = segments[segments["split_type"].astype(str).str.startswith("INTERVAL")]
    for activity_id, group in frame.groupby("activity_id"):
        types = dict(zip(group["split_type"], group.to_dict("records")))
        active = types.get("INTERVAL_ACTIVE")
        out[int(activity_id)] = {
            "reps": int(_zero(active["splits"])) if active else 0,
            "active_m": _zero(active["distance_m"]) if active else 0.0,
            "active_s": _zero(active["duration_s"]) if active else 0.0,
            "active_speed": _zero(active["avg_speed_ms"]) if active else 0.0,
            "warmup": "INTERVAL_WARMUP" in types,
            "cooldown": "INTERVAL_COOLDOWN" in types,
            "rests": "INTERVAL_REST" in types or "INTERVAL_RECOVERY" in types,
        }
    return out


def _zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if np.isnan(number) else number


def _speed_variability(routes: pd.DataFrame) -> dict[int, float]:
    """Coefficient of variation of smoothed speed per activity (interval detector)."""
    if routes is None or routes.empty or "speed_ms" not in routes.columns:
        return {}
    out = {}
    for activity_id, track in routes.groupby("activity_id"):
        speed = pd.to_numeric(track.sort_values("seq")["speed_ms"], errors="coerce")
        speed = speed[speed > 0.5].rolling(5, min_periods=3, center=True).median().dropna()
        if len(speed) >= 30 and speed.mean() > 0:
            out[int(activity_id)] = float(speed.std() / speed.mean())
    return out


def classify(
    runs: pd.DataFrame,
    segments: pd.DataFrame | None = None,
    routes: pd.DataFrame | None = None,
    hr_max: float | None = None,
    vdot_by_day: pd.Series | None = None,
    manual: dict[int, str] | None = None,
) -> pd.DataFrame:
    """Add ``kind``, ``kind_reason`` and ``kind_confidence`` to every run.

    ``vdot_by_day`` (optional) is the fitness estimate valid on each day; it
    lets a structured block be judged against the runner's own threshold pace
    instead of a fixed number. ``manual`` maps activity_id -> kind and wins
    over every rule (races entered on the *Zawody* page).
    """
    if runs.empty:
        return runs.assign(kind=pd.Series(dtype=str), kind_reason=pd.Series(dtype=str),
                           kind_confidence=pd.Series(dtype=str))
    structure = _structure(segments)
    variability = _speed_variability(routes)
    manual = manual or {}
    frame = runs.sort_values("start_local").copy()

    # Personal reference: median distance and pace of the 8 weeks before each run.
    medians_km, medians_pace = [], []
    for start in frame["start_local"]:
        prior = frame[(frame["start_local"] < start) & (frame["start_local"] >= start - pd.Timedelta(weeks=8))]
        medians_km.append(prior["distance_km"].median() if len(prior) >= 3 else np.nan)
        medians_pace.append(prior["pace_min_km"].median() if len(prior) >= 3 else np.nan)
    frame["ref_km"] = medians_km
    frame["ref_pace"] = medians_pace

    kinds, reasons, confidences = [], [], []
    for row in frame.itertuples(index=False):
        kind, reason, confidence = _classify_one(
            row._asdict(), structure.get(int(row.activity_id)), variability.get(int(row.activity_id)),
            hr_max, _vdot_on(vdot_by_day, row.day), manual.get(int(row.activity_id)),
        )
        kinds.append(kind)
        reasons.append(reason)
        confidences.append(confidence)
    frame["kind"] = kinds
    frame["kind_reason"] = reasons
    frame["kind_confidence"] = confidences
    return frame.drop(columns=["ref_km", "ref_pace"])


def _vdot_on(series: pd.Series | None, day: Any) -> float | None:
    if series is None or series.empty:
        return None
    before = series[series.index <= day].dropna()
    return float(before.iloc[-1]) if not before.empty else None


def _classify_one(
    row: dict[str, Any],
    block: dict[str, Any] | None,
    cv: float | None,
    hr_max: float | None,
    vdot_value: float | None,
    manual: str | None,
) -> tuple[str, str, str]:
    name = str(row.get("name") or "")
    km = row.get("distance_km") or 0.0
    minutes = row.get("duration_min") or 0.0
    avg_hr = row.get("avg_hr")
    ref_km = row.get("ref_km")
    pace = row.get("pace_min_km")
    paces = physio.training_paces(vdot_value) if vdot_value else {}
    hr_frac = float(avg_hr) / hr_max if hr_max and avg_hr and not pd.isna(avg_hr) else None
    long_enough = (
        ref_km is not None and not pd.isna(ref_km) and km >= 1.35 * ref_km and minutes >= 60
    ) or minutes >= 95

    if manual in KINDS:
        return manual, "oznaczone ręcznie na stronie Zawody", "wysoka"
    if RACE_WORDS.search(name):
        return "race", f"nazwa „{name}” wskazuje na start lub test", "średnia"

    if block:
        if block["reps"] >= 2 or (block["rests"] and block["reps"] >= 1):
            return "intervals", f"workout z zegarka: {block['reps']} powtórzeń z przerwami", "wysoka"
        if (block["warmup"] or block["cooldown"]) and block["active_m"] >= 1500 and block["active_speed"] > 0:
            block_pace = units.pace_from_speed(block["active_speed"])
            label = f"blok {block['active_m'] / 1000:.1f} km w {units.fmt_pace(block_pace)}"
            if "T" in paces:
                t_fast, t_slow = paces["T"]
                if block_pace <= t_slow * 1.02:
                    return "threshold", f"{label} — w tempie progowym lub szybciej", "wysoka"
                if "M" in paces and block_pace <= paces["M"][1] * 1.03:
                    return "tempo", f"{label} — między tempem maratońskim a progiem", "wysoka"
            elif ref_pace_ok(row) and block_pace < row["ref_pace"] * 0.88:
                return "threshold", f"{label} — wyraźnie szybciej niż zwykle", "średnia"
    if REPS.search(name):
        return "intervals", f"nazwa „{name}” opisuje powtórzenia", "średnia"
    if cv is not None and cv >= 0.22 and (row.get("te_anaerobic") or 0) >= 1.5:
        return "intervals", f"zmienność prędkości {cv:.0%} i TE beztlenowy {row.get('te_anaerobic'):.1f}", "średnia"

    if hr_frac is not None:
        # Heart rate says how hard it felt; pace says what was trained. A run
        # at tempo HR but easy pace (heat, fatigue, a hill route) is an easy
        # run with a high pulse, not a tempo session -- once the runner's own
        # paces are known, a quality label needs both.
        near_t = "T" not in paces or (pace is not None and pace <= paces["T"][1] * 1.04)
        near_m = "M" not in paces or (pace is not None and pace <= paces["M"][1] * 1.04)
        if hr_frac >= 0.87 and minutes >= 15 and near_m:
            kind = "threshold" if minutes <= 50 and near_t else "tempo"
            return kind, f"ciągły wysiłek na {hr_frac:.0%} HRmax przez {minutes:.0f} min", "średnia"
        if hr_frac >= 0.81 and minutes >= 20 and near_m and not long_enough:
            return "tempo", f"średnie tętno {hr_frac:.0%} HRmax — powyżej strefy spokojnej", "średnia"
        if hr_frac >= 0.81 and not near_m and not long_enough:
            return "easy", (f"tempo spokojne ({units.fmt_pace(pace)}), ale tętno {hr_frac:.0%} HRmax — "
                            "upał, zmęczenie albo teren"), "średnia"
        if long_enough:
            return "long", f"{km:.1f} km, wyraźnie dłużej niż zwykle ({ref_km or 0:.1f} km)", "wysoka"
        if hr_frac < 0.72 and minutes <= 50:
            return "recovery", f"krótko i lekko: {hr_frac:.0%} HRmax", "średnia"
        return "easy", f"średnie tętno {hr_frac:.0%} HRmax — strefa spokojna", "średnia"

    # No heart rate and no structure: only distance and pace are left.
    if long_enough:
        return "long", f"{km:.1f} km — dłużej niż zwykle (brak tętna)", "niska"
    if ref_pace_ok(row) and pace < row["ref_pace"] * 0.9 and minutes >= 15:
        return "tempo", "wyraźnie szybciej niż zwykle (brak tętna)", "niska"
    return "easy", "brak tętna i struktury — przyjęto bieg spokojny", "niska"


def ref_pace_ok(row: dict[str, Any]) -> bool:
    ref = row.get("ref_pace")
    return ref is not None and not pd.isna(ref) and row.get("pace_min_km") is not None


# --------------------------------------------------------------------------
# splits and best efforts from the sample stream


def _clock(track: pd.DataFrame) -> pd.DataFrame:
    """Cumulative (metres, seconds) along the track, monotone, from the start."""
    track = track.sort_values("seq")
    metres = pd.to_numeric(track["distance_km"], errors="coerce") * 1000
    if "duration_s" in track.columns and pd.to_numeric(track["duration_s"], errors="coerce").notna().sum() > 5:
        seconds = pd.to_numeric(track["duration_s"], errors="coerce")
    else:
        seconds = (pd.to_numeric(track["timestamp_ms"], errors="coerce") - track["timestamp_ms"].min()) / 1000
    frame = pd.DataFrame({"m": metres.values, "s": seconds.values})
    for column in ("hr", "elevation_m", "cadence"):
        frame[column] = pd.to_numeric(track[column], errors="coerce").values if column in track.columns else np.nan
    # directRunCadence counts one foot; the activity summary (and every
    # running coach) talks in steps of both feet per minute.
    if frame["cadence"].notna().any() and frame["cadence"].median() < 120:
        frame["cadence"] = frame["cadence"] * 2
    frame = frame.dropna(subset=["m", "s"])
    # Distance and timer never go backwards; a GPS hiccup that says otherwise is dropped.
    frame = frame[(frame["m"].diff().fillna(0) >= 0) & (frame["s"].diff().fillna(0) >= 0)]
    return frame.reset_index(drop=True)


def km_splits(track: pd.DataFrame) -> pd.DataFrame:
    """Kilometre splits interpolated from the sample stream.

    The stream is ~400 samples per run, so a boundary is placed between two
    samples a few seconds apart; the split times are accurate to a few seconds,
    not to the tenth the watch shows. The last, partial split is kept and
    marked by its length.
    """
    columns = ["km", "length_km", "seconds", "pace_min_km", "hr", "elev_gain_m", "elev_loss_m", "cadence"]
    if track is None or track.empty or "distance_km" not in track.columns:
        return pd.DataFrame(columns=columns)
    clock = _clock(track)
    if len(clock) < 5 or clock["m"].iloc[-1] < 500:
        return pd.DataFrame(columns=columns)
    total = float(clock["m"].iloc[-1])
    edges = list(np.arange(0, total, 1000.0)) + [total]
    times = np.interp(edges, clock["m"], clock["s"])
    rows = []
    for index in range(1, len(edges)):
        start, end = edges[index - 1], edges[index]
        length = (end - start) / 1000
        if length < 0.05:
            continue
        seconds = times[index] - times[index - 1]
        inside = clock[(clock["m"] >= start) & (clock["m"] <= end)]
        elevation = inside["elevation_m"].dropna().rolling(3, min_periods=1, center=True).mean()
        step = elevation.diff()
        rows.append(
            {
                "km": index,
                "length_km": round(length, 3),
                "seconds": round(float(seconds), 1),
                "pace_min_km": units.pace_from(seconds, length),
                "hr": round(float(inside["hr"].mean()), 0) if inside["hr"].notna().any() else None,
                "elev_gain_m": round(float(step.clip(lower=0).sum()), 1) if len(elevation) > 1 else None,
                "elev_loss_m": round(float(-step.clip(upper=0).sum()), 1) if len(elevation) > 1 else None,
                "cadence": round(float(inside["cadence"].mean()), 0) if inside["cadence"].notna().any() else None,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def best_segment(track: pd.DataFrame, metres: float) -> tuple[float, float] | None:
    """Fastest continuous ``metres`` inside the run: (seconds, avg HR or NaN)."""
    clock = _clock(track) if "s" not in track.columns else track
    if clock.empty or clock["m"].iloc[-1] < metres * 0.995:
        return None
    m, s = clock["m"].to_numpy(dtype=float), clock["s"].to_numpy(dtype=float)
    hr = clock["hr"].to_numpy(dtype=float) if "hr" in clock.columns else np.full(len(m), np.nan)
    targets = m + metres
    valid = targets <= m[-1]
    if not valid.any():
        return None
    seconds = np.interp(targets[valid], m, s) - s[valid]
    seconds = np.where(seconds > 0, seconds, np.inf)
    start = int(np.argmin(seconds))
    if not np.isfinite(seconds[start]):
        return None
    window = hr[(m >= m[start]) & (m <= targets[start])]
    return float(seconds[start]), float(np.nanmean(window)) if np.isfinite(window).any() else np.nan


def efforts(
    runs: pd.DataFrame,
    routes: pd.DataFrame | None = None,
    segments: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Best efforts per run and standard distance, with their source.

    Garmin's fastest 1 km / mile / 5 km are computed on the full-rate stream
    and are preferred; 3 km and 10 km+ come from the ~400-sample stream here.
    A whole run within 2% of a race distance counts as that effort too. Efforts
    faster than 2:30 /km are GPS artefacts, not running, and are dropped.
    """
    columns = ["activity_id", "day", "effort", "distance_m", "seconds", "pace_min_km", "avg_hr",
               "source", "vdot"]
    if runs is None or runs.empty:
        return pd.DataFrame(columns=columns)
    tracks = {}
    if routes is not None and not routes.empty:
        tracks = {int(a): g for a, g in routes.groupby("activity_id")}
    blocks = _structure(segments)
    rows = []
    for run in runs.itertuples(index=False):
        run_m = float(run.distance_km) * 1000
        clock = _clock(tracks[int(run.activity_id)]) if int(run.activity_id) in tracks else None
        for key, metres in EFFORT_DISTANCES.items():
            if run_m < metres * 0.98:
                continue
            seconds, hr, source = None, np.nan, None
            garmin_column = GARMIN_SPLITS.get(key)
            if garmin_column and hasattr(run, garmin_column):
                value = getattr(run, garmin_column)
                if value is not None and not pd.isna(value) and value > 0:
                    seconds, source = float(value), "Garmin (najszybszy odcinek)"
                    # Garmin gives the time only; the heart rate of (almost)
                    # the same stretch comes from the stream.
                    if clock is not None and not clock.empty:
                        found = best_segment(clock, metres)
                        hr = found[1] if found else np.nan
            if seconds is None and units.race_key(run.distance_km) == key:
                seconds, source = float(run.duration_min) * 60, "cały bieg"
                hr = float(run.avg_hr) if run.avg_hr is not None and not pd.isna(run.avg_hr) else np.nan
            if seconds is None and clock is not None and not clock.empty:
                found = best_segment(clock, metres)
                if found:
                    seconds, hr = found
                    source = "odcinek ze strumienia próbek"
            if seconds is None or seconds <= 0:
                continue
            pace = units.pace_from(seconds, metres / 1000)
            if pace is None or pace < 2.5:
                continue
            rows.append(
                {
                    "activity_id": int(run.activity_id),
                    "day": run.day,
                    "effort": key,
                    "distance_m": metres,
                    "seconds": round(seconds, 1),
                    "pace_min_km": round(pace, 3),
                    "avg_hr": hr,
                    "source": source,
                    "vdot": physio.vdot(metres, seconds),
                }
            )
        block = blocks.get(int(run.activity_id))
        # One continuous work block of a structured workout ("4 km @ 4:45") is
        # an effort in its own right, at its own odd distance.
        if block and block["reps"] == 1 and (block["warmup"] or block["cooldown"]) \
                and block["active_m"] >= 1500 and block["active_s"] > 0:
            hr = np.nan
            if clock is not None and not clock.empty:
                found = best_segment(clock, block["active_m"])
                hr = found[1] if found else np.nan
            pace = units.pace_from(block["active_s"], block["active_m"] / 1000)
            if pace is not None and pace >= 2.5:
                rows.append(
                    {
                        "activity_id": int(run.activity_id),
                        "day": run.day,
                        "effort": "block",
                        "distance_m": round(block["active_m"], 0),
                        "seconds": round(block["active_s"], 1),
                        "pace_min_km": round(pace, 3),
                        "avg_hr": hr,
                        "source": "blok workoutu z zegarka",
                        "vdot": physio.vdot(block["active_m"], block["active_s"]),
                    }
                )
    return pd.DataFrame(rows, columns=columns)


def records(efforts_frame: pd.DataFrame, keys: tuple[str, ...] = ("5k", "10k", "hm", "m")) -> pd.DataFrame:
    """Personal bests per distance, with where they came from."""
    if efforts_frame is None or efforts_frame.empty:
        return pd.DataFrame()
    frame = efforts_frame[efforts_frame["effort"].isin(keys)]
    if frame.empty:
        return pd.DataFrame()
    best = frame.loc[frame.groupby("effort")["seconds"].idxmin()].copy()
    best["order"] = best["effort"].map({k: i for i, k in enumerate(keys)})
    return best.sort_values("order").drop(columns="order")


# --------------------------------------------------------------------------
# volume summaries


def window_summary(runs: pd.DataFrame, end: pd.Timestamp, days: int) -> dict[str, Any]:
    """Volume numbers for the ``days`` up to and including ``end``."""
    frame = runs[(runs["day"] > end - pd.Timedelta(days=days)) & (runs["day"] <= end)] if not runs.empty else runs
    if frame is None or frame.empty:
        return {"days": days, "runs": 0, "km": 0.0, "hours": 0.0, "avg_km": None, "pace": None,
                "longest_km": None, "longest_id": None}
    km = float(frame["distance_km"].sum())
    seconds = float(frame["duration_min"].sum()) * 60
    longest = frame.loc[frame["distance_km"].idxmax()]
    return {
        "days": days,
        "runs": int(len(frame)),
        "km": round(km, 1),
        "hours": round(seconds / 3600, 1),
        "avg_km": round(km / len(frame), 1),
        # Time-weighted: total time over total distance, not a mean of paces.
        "pace": units.pace_from(seconds, km),
        "longest_km": round(float(longest["distance_km"]), 1),
        "longest_id": int(longest["activity_id"]),
    }


def weekly(runs: pd.DataFrame, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Gap-free ISO weeks: volume, sessions, long run, hard sessions, easy share."""
    columns = ["week", "iso_week", "km", "easy_km", "hard_km", "runs", "hours", "long_km", "hard",
               "easy_km_pct", "load"]
    if runs is None or runs.empty:
        return pd.DataFrame(columns=columns)
    frame = runs.copy()
    frame["week"] = frame["day"] - pd.to_timedelta(frame["day"].dt.weekday, unit="D")
    last = end if end is not None else frame["day"].max()
    last_week = last - pd.Timedelta(days=int(last.weekday()))
    weeks = pd.date_range(frame["week"].min(), last_week, freq="7D")
    if "kind" not in frame.columns:
        frame["kind"] = "easy"
    frame["hard"] = frame["kind"].isin(HARD_KINDS).astype(int)
    frame["easy_km"] = frame["distance_km"].where(frame["kind"].isin(("easy", "recovery", "long")), 0)
    grouped = frame.groupby("week").agg(
        km=("distance_km", "sum"),
        runs=("activity_id", "count"),
        minutes=("duration_min", "sum"),
        long_km=("distance_km", "max"),
        hard=("hard", "sum"),
        easy_km=("easy_km", "sum"),
        load=("training_load", "sum"),
    )
    grouped = grouped.reindex(weeks).fillna({"km": 0, "runs": 0, "minutes": 0, "hard": 0, "easy_km": 0, "load": 0})
    grouped = grouped[grouped.index <= last_week]
    out = pd.DataFrame(
        {
            "week": grouped.index,
            "iso_week": grouped.index.strftime("%G-W%V"),
            "km": grouped["km"].round(1).values,
            "easy_km": grouped["easy_km"].round(1).values,
            "hard_km": (grouped["km"] - grouped["easy_km"]).round(1).values,
            "runs": grouped["runs"].astype(int).values,
            "hours": (grouped["minutes"] / 60).round(1).values,
            "long_km": grouped["long_km"].round(1).values,
            "hard": grouped["hard"].astype(int).values,
            "easy_km_pct": (100 * grouped["easy_km"] / grouped["km"].replace(0, np.nan)).round(0).values,
            "load": grouped["load"].round(0).values,
        }
    )
    return out


def km_ratio(runs: pd.DataFrame, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Daily acute:chronic ratio on running kilometres (7 d sum / mean 7 d of 28 d).

    The same construction as the rolling ACWR on the *Forma* page, but on
    distance run, so it isolates the running load from cycling or squash.
    """
    columns = ["day", "km", "acute_km", "chronic_km", "ratio"]
    if runs is None or runs.empty:
        return pd.DataFrame(columns=columns)
    end = end if end is not None else runs["day"].max()
    days = pd.date_range(runs["day"].min(), end, freq="D")
    km = runs.groupby("day")["distance_km"].sum().reindex(days).fillna(0.0)
    acute = km.rolling(7, min_periods=7).sum()
    chronic = km.rolling(28, min_periods=28).sum() / 4
    ratio = (acute / chronic.where(chronic >= 5)).round(2)
    return pd.DataFrame({"day": days, "km": km.values, "acute_km": acute.values,
                         "chronic_km": chronic.round(1).values, "ratio": ratio.values})


def gaps(runs: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    """Rest days and breaks between ``start`` and ``end`` (inclusive)."""
    days = pd.date_range(start.normalize(), end.normalize(), freq="D")
    run_days = set(runs["day"]) if runs is not None and not runs.empty else set()
    active = np.array([day in run_days for day in days])
    longest, current = 0, 0
    for flag in active:
        current = 0 if flag else current + 1
        longest = max(longest, current)
    since_last = None
    if run_days:
        before = [d for d in run_days if d <= end]
        if before:
            since_last = int((end.normalize() - max(before)).days)
    return {
        "days": int(len(days)),
        "run_days": int(active.sum()),
        "rest_days": int((~active).sum()),
        "longest_break": int(longest),
        "days_since_last": since_last,
    }


def similar(runs: pd.DataFrame, activity_id: int, limit: int = 8) -> pd.DataFrame:
    """Earlier runs of the same kind and comparable distance (+-25%)."""
    if runs is None or runs.empty:
        return pd.DataFrame()
    target = runs[runs["activity_id"] == activity_id]
    if target.empty:
        return pd.DataFrame()
    row = target.iloc[0]
    pool = runs[(runs["activity_id"] != activity_id)
                & (runs["distance_km"].between(row["distance_km"] * 0.75, row["distance_km"] * 1.25))]
    if "kind" in runs.columns:
        pool = pool[pool["kind"] == row["kind"]]
    return pool.sort_values("start_local", ascending=False).head(limit)
