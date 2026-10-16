"""Derived analytics: physiological models and statistics over the warehouse.

Everything here is materialised into its own parquet table, so the dashboard,
the SQL tab and the insight files all read the same numbers instead of each
recomputing them. Run after etl/load.py (fetch.rebuild does both).

Models implemented
------------------
* Performance Management Chart -- Banister impulse-response: CTL (42 d) /
  ATL (7 d) exponentially weighted load, form as TSB, 7-day ramp rate.
* Acute:chronic workload ratio, both the rolling-sum (Gabbett) and the
  exponentially-weighted (Williams) formulation, because they disagree.
* Foster monotony and strain: weekly mean/SD of daily load.
* Critical speed: linear d = CS*t + D' fit over best efforts in a window.
* Riegel endurance exponent: log t = log a + b * log d.
* Efficiency factor: grade-adjusted speed per heartbeat, the cheapest proxy
  for aerobic fitness that needs no lab.
* Banister two-component fit of performance against fitness and fatigue.
* Lagged Spearman correlations with Benjamini-Hochberg FDR control.
* Binary-segmentation change points on recovery series.
* Sleep Regularity Index and circadian midpoint stability.
* Per-night cardiac recovery shape: heart-rate nadir timing, overnight HRV
  slope, Body Battery recharge rate.
* Running: session classification, km splits, best efforts and the race
  forecast history -- the logic lives in the ``running`` package.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import db  # noqa: E402
from etl.load import write_table  # noqa: E402

# Time constants in days. 42/7 are the Banister/TrainingPeaks defaults and are
# kept so numbers line up with what other tools report.
CTL_DAYS = 42
ATL_DAYS = 7

RESPONSES = [
    "hrv_last_night",
    "hrv_deviation",
    "rhr",
    "sleep_score",
    "sleep_h",
    "readiness",
    "bb_high",
    "stress_avg",
]
DRIVERS = [
    "load_day",
    "ctl",
    "atl",
    "tsb",
    "steps",
    "intensity_vigorous",
    "distance_m",
    "sleep_h",
    "stress_avg",
    "alcohol_proxy_late_hr",
]
CHANGEPOINT_METRICS = ["hrv_last_night", "rhr", "vo2max", "sleep_h", "weight_kg"]
WEEKDAY_METRICS = ["hrv_last_night", "rhr", "sleep_h", "sleep_score", "readiness", "load_day", "steps"]
WEEKDAY_ORDER = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]


# --------------------------------------------------------------------------
# helpers


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _calendar(daily: pd.DataFrame, activities: pd.DataFrame) -> pd.DataFrame:
    """Daily frame with a gap-free date index and one training-load column.

    Rest days must exist as zeros: an exponentially weighted load that simply
    skips them decays far too slowly and every form number comes out wrong.
    """
    if daily.empty:
        return pd.DataFrame()
    frame = daily.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame.set_index("day").sort_index()

    full = pd.date_range(frame.index.min(), frame.index.max(), freq="D")
    frame = frame.reindex(full)
    frame.index.name = "day"

    load = pd.Series(0.0, index=full)
    if not activities.empty and "training_load" in activities.columns:
        acts = activities.copy()
        acts["day"] = pd.to_datetime(acts["day"])
        per_day = (
            acts.groupby("day")["training_load"].sum().reindex(full).fillna(0.0)
        )
        load = per_day.astype(float)
    frame["load_day"] = load
    return frame


# --------------------------------------------------------------------------
# training load models


def performance_chart(frame: pd.DataFrame) -> pd.DataFrame:
    """CTL / ATL / TSB plus both ACWR formulations, one row per day."""
    if frame.empty:
        return pd.DataFrame()
    load = frame["load_day"].astype(float)

    ctl = load.ewm(alpha=1 / CTL_DAYS, adjust=False).mean()
    atl = load.ewm(alpha=1 / ATL_DAYS, adjust=False).mean()
    # Form is yesterday's fitness minus yesterday's fatigue: today's session
    # has not been absorbed yet.
    tsb = ctl.shift(1) - atl.shift(1)

    acute_sum = load.rolling(7, min_periods=4).sum()
    chronic_sum = load.rolling(28, min_periods=14).sum() / 4
    acwr_rolling = acute_sum / chronic_sum.replace(0, np.nan)
    acwr_ewma = atl / ctl.replace(0, np.nan)

    out = pd.DataFrame(
        {
            "day": frame.index,
            "load_day": load.values,
            "load_7d": load.rolling(7, min_periods=3).sum().values,
            "load_28d": load.rolling(28, min_periods=10).sum().values,
            "ctl": ctl.round(2).values,
            "atl": atl.round(2).values,
            "tsb": tsb.round(2).values,
            "ramp_7d": ctl.diff(7).round(2).values,
            "acwr_rolling": acwr_rolling.round(3).values,
            "acwr_ewma": acwr_ewma.round(3).values,
        }
    )
    # Garmin's own view of the same thing, for comparison.
    for column in ("load_acute", "load_chronic", "load_ratio", "readiness", "vo2max"):
        if column in frame.columns:
            out[f"garmin_{column}"] = pd.to_numeric(
                frame[column], errors="coerce"
            ).values
    out["form_zone"] = pd.cut(
        out["tsb"],
        [-np.inf, -30, -10, 5, 25, np.inf],
        labels=["przetrenowanie", "budowanie", "neutralnie", "swiezosc", "roztrenowanie"],
    ).astype(str)
    return out


def weekly_load(frame: pd.DataFrame) -> pd.DataFrame:
    """Foster monotony and strain per ISO week.

    Monotony is the week's mean daily load over its standard deviation: a week
    of identical sessions scores high even at modest volume, and high monotony
    with high volume is the classic overreaching signature.
    """
    if frame.empty:
        return pd.DataFrame()
    grouped = frame.groupby(frame.index.strftime("%G-W%V"))["load_day"]
    stats = grouped.agg(["sum", "mean", "std", "count"])
    stats["monotony"] = (stats["mean"] / stats["std"].replace(0, np.nan)).round(2)
    stats["strain"] = (stats["sum"] * stats["monotony"]).round(0)
    stats = stats.rename(
        columns={"sum": "load_sum", "mean": "load_mean", "std": "load_sd", "count": "days"}
    )
    extra = frame.groupby(frame.index.strftime("%G-W%V")).agg(
        hrv=("hrv_last_night", "mean"),
        rhr=("rhr", "mean"),
        sleep_h=("sleep_h", "mean"),
        readiness=("readiness", "mean"),
        sessions=("load_day", lambda s: int((s > 0).sum())),
    )
    out = stats.join(extra).reset_index(names="iso_week")
    for column in ("hrv", "rhr", "sleep_h", "readiness"):
        if column in out.columns:
            out[column] = out[column].round(1)
    return out


# --------------------------------------------------------------------------
# physiology from best efforts


BEST_EFFORT_DISTANCES = {"best_1k_s": 1000.0, "best_mile_s": 1609.0, "best_5k_s": 5000.0}


def _best_efforts(activities: pd.DataFrame) -> pd.DataFrame:
    """Long frame of (day, distance, seconds) best efforts inside runs."""
    if activities.empty:
        return pd.DataFrame(columns=["day", "distance_m", "seconds"])
    runs = activities[activities["sport"].astype(str).str.contains("running", na=False)]
    rows = []
    for column, metres in BEST_EFFORT_DISTANCES.items():
        if column not in runs.columns:
            continue
        series = pd.to_numeric(runs[column], errors="coerce")
        for day, seconds in zip(runs["day"], series):
            if pd.notna(seconds) and seconds > 0:
                rows.append({"day": pd.to_datetime(day), "distance_m": metres, "seconds": float(seconds)})
    return pd.DataFrame(rows)


def critical_speed(activities: pd.DataFrame, window_days: int = 90, step_days: int = 7) -> pd.DataFrame:
    """Rolling two-parameter critical-speed fit: d = CS * t + D'.

    CS is the highest speed that is still (mostly) aerobically sustainable;
    D' is the finite distance available above it. Fitted on the window's best
    efforts, so it needs at least two distinct distances to mean anything.
    """
    efforts = _best_efforts(activities)
    if efforts.empty:
        return pd.DataFrame()

    start, end = efforts["day"].min(), efforts["day"].max()
    rows = []
    for anchor in pd.date_range(start + pd.Timedelta(days=window_days), end, freq=f"{step_days}D"):
        window = efforts[
            (efforts["day"] > anchor - pd.Timedelta(days=window_days))
            & (efforts["day"] <= anchor)
        ]
        if window.empty:
            continue
        bests = window.groupby("distance_m")["seconds"].min()
        if len(bests) < 2:
            continue
        times = bests.values.astype(float)
        distances = bests.index.values.astype(float)
        # Least squares on d = CS*t + D'
        design = np.column_stack([times, np.ones_like(times)])
        (cs, d_prime), *_ = np.linalg.lstsq(design, distances, rcond=None)
        if cs <= 0:
            continue
        predicted = design @ np.array([cs, d_prime])
        ss_res = float(np.sum((distances - predicted) ** 2))
        ss_tot = float(np.sum((distances - distances.mean()) ** 2))
        rows.append(
            {
                "day": anchor,
                "cs_ms": round(float(cs), 3),
                "cs_pace_min_km": round(1000 / float(cs) / 60, 2),
                "d_prime_m": round(float(d_prime), 1),
                "r2": round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None,
                "distances": int(len(bests)),
                "pred_5k_s": round(5000 / float(cs), 0) if cs else None,
                "pred_10k_s": round(10000 / float(cs), 0) if cs else None,
            }
        )
    return pd.DataFrame(rows)


def riegel_exponent(activities: pd.DataFrame, window_days: int = 180, step_days: int = 14) -> pd.DataFrame:
    """Rolling fit of log t = log a + b log d.

    The exponent b is an endurance signature: ~1.06 is a well-trained runner,
    values above ~1.12 mean speed holds up poorly as distance grows.
    """
    efforts = _best_efforts(activities)
    if efforts.empty:
        return pd.DataFrame()
    start, end = efforts["day"].min(), efforts["day"].max()
    rows = []
    for anchor in pd.date_range(start + pd.Timedelta(days=window_days), end, freq=f"{step_days}D"):
        window = efforts[
            (efforts["day"] > anchor - pd.Timedelta(days=window_days))
            & (efforts["day"] <= anchor)
        ]
        bests = window.groupby("distance_m")["seconds"].min()
        if len(bests) < 2:
            continue
        log_d = np.log(bests.index.values.astype(float))
        log_t = np.log(bests.values.astype(float))
        slope, intercept = np.polyfit(log_d, log_t, 1)
        rows.append(
            {
                "day": anchor,
                "riegel_b": round(float(slope), 4),
                "log_a": round(float(intercept), 4),
                "distances": int(len(bests)),
            }
        )
    return pd.DataFrame(rows)


def efficiency(activities: pd.DataFrame) -> pd.DataFrame:
    """Efficiency factor per run: grade-adjusted metres per heartbeat.

    Rising EF at a given heart rate is aerobic progress; it is noisy per
    session (heat, terrain, sleep), so the rolling median is the real signal.
    """
    if activities.empty:
        return pd.DataFrame()
    runs = activities[activities["sport"].astype(str).str.contains("running", na=False)].copy()
    if runs.empty:
        return pd.DataFrame()
    runs["day"] = pd.to_datetime(runs["day"])
    # A "run" of 0.6 km in 91 minutes is a watch left recording, not a run, and
    # at ~0.02 m/beat it flattens the axis for every real session. Keep efforts
    # of at least 1 km at faster than a walk (12 min/km).
    distance = _numeric(runs, "distance_km").reindex(runs.index)
    pace_speed = _numeric(runs, "speed_kmh").reindex(runs.index)
    runs = runs[(distance >= 1.0) & (pace_speed >= 5.0)]
    if runs.empty:
        return pd.DataFrame()
    # Grade-adjusted speed is the better input but only newer activities carry
    # it, so plain speed fills the gaps.
    speed = _numeric(runs, "gap_speed")
    plain = _numeric(runs, "speed_kmh") / 3.6
    speed = speed.reindex(runs.index).fillna(plain.reindex(runs.index))
    hr = _numeric(runs, "avg_hr").reindex(runs.index)
    runs["ef"] = (speed / hr * 60).round(3)  # metres per beat
    runs["hr_per_kmh"] = (hr / (speed * 3.6)).round(2)
    wanted = [
        "day", "activity_id", "distance_km", "duration_min", "avg_hr",
        "ef", "hr_per_kmh", "temperature_max",
    ]
    out = (
        runs[[c for c in wanted if c in runs.columns]]
        .dropna(subset=["ef"])
        .sort_values("day")
        .reset_index(drop=True)
    )
    out["ef_roll10"] = out["ef"].rolling(10, min_periods=4).median().round(3)
    out["ef_roll30"] = out["ef"].rolling(30, min_periods=10).median().round(3)
    return out


def banister_fit(frame: pd.DataFrame, performance: pd.DataFrame) -> dict[str, Any]:
    """Fit performance = p0 + k1*fitness - k2*fatigue with free time constants.

    This is the classic Banister model: the same training impulse builds a
    slow positive and a fast negative trace, and performance is their
    difference. Fitting the time constants on this athlete's own data says how
    long their taper should be, instead of assuming the textbook 42/7.
    """
    if frame.empty or performance.empty or len(performance) < 25:
        return {"fitted": False, "reason": "za malo pomiarow wydolnosci (min. 25)"}
    try:
        from scipy.optimize import least_squares
    except ImportError:
        return {"fitted": False, "reason": "brak scipy"}

    load = frame["load_day"].astype(float)
    perf = (
        performance.set_index(pd.to_datetime(performance["day"]))["ef"]
        .resample("D")
        .median()
        .reindex(load.index)
    )
    observed = perf.dropna()
    if len(observed) < 25:
        return {"fitted": False, "reason": "za malo pomiarow wydolnosci (min. 25)"}

    def traces(tau_fit: float, tau_fatigue: float) -> tuple[pd.Series, pd.Series]:
        fitness = load.ewm(alpha=1 / max(tau_fit, 1.0), adjust=False).mean()
        fatigue = load.ewm(alpha=1 / max(tau_fatigue, 1.0), adjust=False).mean()
        return fitness, fatigue

    def residual(params: np.ndarray) -> np.ndarray:
        p0, k1, k2, tau_fit, tau_fatigue = params
        fitness, fatigue = traces(tau_fit, tau_fatigue)
        model = p0 + k1 * fitness - k2 * fatigue
        return (model.reindex(observed.index) - observed).values

    guess = np.array([float(observed.mean()), 0.01, 0.01, 42.0, 7.0])
    bounds = ([0.0, 0.0, 0.0, 10.0, 2.0], [np.inf, 1.0, 1.0, 90.0, 30.0])
    try:
        result = least_squares(residual, guess, bounds=bounds, max_nfev=4000)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return {"fitted": False, "reason": f"dopasowanie nie zbieglo: {exc}"}

    p0, k1, k2, tau_fit, tau_fatigue = (float(v) for v in result.x)
    residuals = result.fun
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((observed.values - observed.values.mean()) ** 2))
    fitness, fatigue = traces(tau_fit, tau_fatigue)
    # Days to peak after the last session: when k1*fitness - k2*fatigue is
    # maximal if training stopped today.
    decay = np.arange(0, 60)
    last_fit, last_fatigue = float(fitness.iloc[-1]), float(fatigue.iloc[-1])
    projection = k1 * last_fit * np.exp(-decay / tau_fit) - k2 * last_fatigue * np.exp(
        -decay / tau_fatigue
    )
    return {
        "fitted": True,
        "p0": round(p0, 4),
        "k1": round(k1, 5),
        "k2": round(k2, 5),
        "tau_fitness_days": round(tau_fit, 1),
        "tau_fatigue_days": round(tau_fatigue, 1),
        "r2": round(1 - ss_res / ss_tot, 3) if ss_tot > 0 else None,
        "n": int(len(observed)),
        "taper_days_to_peak": int(decay[int(np.argmax(projection))]),
    }


# --------------------------------------------------------------------------
# statistics


def lagged_correlations(frame: pd.DataFrame, max_lag: int = 7, min_n: int = 25) -> pd.DataFrame:
    """Spearman correlation of each driver at day t-lag against each response.

    Spearman because these series are bounded, skewed and full of outliers.
    Hundreds of tests are run, so raw p-values are meaningless on their own --
    the Benjamini-Hochberg q-value is the column to read.
    """
    if frame.empty:
        return pd.DataFrame()
    try:
        from scipy import stats
    except ImportError:
        return pd.DataFrame()

    rows = []
    for driver in DRIVERS:
        if driver not in frame.columns:
            continue
        driver_values = pd.to_numeric(frame[driver], errors="coerce")
        if driver_values.notna().sum() < min_n:
            continue
        for response in RESPONSES:
            if response not in frame.columns or response == driver:
                continue
            response_values = pd.to_numeric(frame[response], errors="coerce")
            for lag in range(max_lag + 1):
                pair = pd.concat(
                    [driver_values.shift(lag), response_values], axis=1
                ).dropna()
                if len(pair) < min_n:
                    continue
                rho, p_value = stats.spearmanr(pair.iloc[:, 0], pair.iloc[:, 1])
                if not np.isfinite(rho):
                    continue
                rows.append(
                    {
                        "driver": driver,
                        "response": response,
                        "lag_days": lag,
                        "rho": round(float(rho), 3),
                        "p": float(p_value),
                        "n": int(len(pair)),
                    }
                )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["q"] = _benjamini_hochberg(out["p"].values).round(4)
    out["significant"] = out["q"] < 0.05
    out["p"] = out["p"].round(5)
    return out.sort_values("q").reset_index(drop=True)


def _benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Step-up FDR adjustment; returns q-values in the input order."""
    n = len(p_values)
    order = np.argsort(p_values)
    ranked = p_values[order] * n / (np.arange(n) + 1)
    # Enforce monotonicity from the largest p downwards.
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(ranked, 0, 1)
    return out


def autocorrelation(frame: pd.DataFrame, nlags: int = 28) -> pd.DataFrame:
    """ACF of the recovery series: how long yesterday still predicts today."""
    if frame.empty:
        return pd.DataFrame()
    try:
        from statsmodels.tsa.stattools import acf
    except ImportError:
        return pd.DataFrame()
    # statsmodels 0.15 warns that acf() will start returning an object; ask
    # for the tuple explicitly where the switch exists (0.14 has no such
    # argument and returns the tuple anyway).
    import inspect

    legacy = {"result_object": False} if "result_object" in inspect.signature(acf).parameters else {}
    rows = []
    for column in ["hrv_last_night", "rhr", "sleep_h", "readiness", "load_day", "stress_avg"]:
        series = _numeric(frame, column).interpolate(limit=3).dropna()
        if len(series) < nlags * 3:
            continue
        values, confint = acf(series, nlags=nlags, alpha=0.05, fft=True, **legacy)
        for lag in range(len(values)):
            rows.append(
                {
                    "metric": column,
                    "lag_days": lag,
                    "acf": round(float(values[lag]), 4),
                    "ci_low": round(float(confint[lag][0]), 4),
                    "ci_high": round(float(confint[lag][1]), 4),
                    "n": int(len(series)),
                }
            )
    return pd.DataFrame(rows)


def change_points(frame: pd.DataFrame, max_splits: int = 4, min_segment: int = 21) -> pd.DataFrame:
    """Binary segmentation on z-scored series: where did the baseline shift?

    Each candidate split must cut the residual sum of squares by more than a
    BIC-style penalty, which keeps noise from being read as a regime change.
    """
    if frame.empty:
        return pd.DataFrame()
    rows = []
    for metric in CHANGEPOINT_METRICS:
        series = _numeric(frame, metric).dropna()
        if len(series) < min_segment * 3:
            continue
        values = series.values.astype(float)
        values = (values - values.mean()) / (values.std() or 1.0)
        index = series.index

        segments = [(0, len(values))]
        splits: list[int] = []
        penalty = 2.0 * np.log(len(values))
        for _ in range(max_splits):
            best = None
            for start, stop in segments:
                if stop - start < 2 * min_segment:
                    continue
                block = values[start:stop]
                base_cost = float(((block - block.mean()) ** 2).sum())
                for cut in range(start + min_segment, stop - min_segment):
                    left = values[start:cut]
                    right = values[cut:stop]
                    cost = float(
                        ((left - left.mean()) ** 2).sum() + ((right - right.mean()) ** 2).sum()
                    )
                    gain = base_cost - cost
                    if gain > penalty and (best is None or gain > best[0]):
                        best = (gain, start, cut, stop)
            if best is None:
                break
            _, start, cut, stop = best
            splits.append(cut)
            segments = [s for s in segments if s != (start, stop)] + [(start, cut), (cut, stop)]

        for cut in sorted(splits):
            before = series.iloc[max(0, cut - 28) : cut]
            after = series.iloc[cut : cut + 28]
            if before.empty or after.empty:
                continue
            rows.append(
                {
                    "metric": metric,
                    "day": index[cut],
                    "before_mean": round(float(before.mean()), 2),
                    "after_mean": round(float(after.mean()), 2),
                    "delta": round(float(after.mean() - before.mean()), 2),
                    "n_before": int(len(before)),
                    "n_after": int(len(after)),
                }
            )
    return pd.DataFrame(rows)


def weekday_effects(frame: pd.DataFrame) -> pd.DataFrame:
    """Day-of-week means with a Kruskal-Wallis test for any real difference."""
    if frame.empty:
        return pd.DataFrame()
    try:
        from scipy import stats
    except ImportError:
        stats = None
    weekday = frame.index.day_name()
    rows = []
    for metric in WEEKDAY_METRICS:
        series = _numeric(frame, metric)
        if series.notna().sum() < 40:
            continue
        groups = [series[weekday == name].dropna().values for name in WEEKDAY_ORDER]
        p_value = None
        if stats is not None and all(len(g) >= 3 for g in groups):
            try:
                p_value = float(stats.kruskal(*groups).pvalue)
            except ValueError:
                p_value = None
        overall = float(series.mean())
        for name, values in zip(WEEKDAY_ORDER, groups):
            if len(values) == 0:
                continue
            rows.append(
                {
                    "metric": metric,
                    "weekday": name,
                    "mean": round(float(np.mean(values)), 2),
                    "sd": round(float(np.std(values, ddof=1)), 2) if len(values) > 1 else None,
                    "n": int(len(values)),
                    "delta_vs_overall": round(float(np.mean(values) - overall), 2),
                    "kruskal_p": round(p_value, 5) if p_value is not None else None,
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# sleep and circadian structure


def _local_timestamp(values: pd.Series) -> pd.Series:
    """Garmin's ``*TimestampLocal`` fields: epoch milliseconds on the local clock.

    Numbers have to be read with ``unit="ms"`` -- left to the default they are
    taken as nanoseconds and every night lands at 1970-01-01 00:29.
    """
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().any():
        return pd.to_datetime(numeric, unit="ms", errors="coerce")
    return pd.to_datetime(values, errors="coerce", format="mixed")


def _rolling_spread(values: pd.Series, window: int = 30) -> pd.Series:
    rolling = values.rolling(window, min_periods=10)
    return ((rolling.quantile(0.75) - rolling.quantile(0.25)) / 1.349).round(2)


def circadian(daily: pd.DataFrame, stages: pd.DataFrame) -> pd.DataFrame:
    """Bedtime, wake time, midpoint and their stability per night."""
    if daily.empty or "sleep_start" not in daily.columns:
        return pd.DataFrame()
    frame = daily.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    start = _local_timestamp(frame["sleep_start"])
    end = _local_timestamp(frame["sleep_end"])
    rows = pd.DataFrame(
        {
            "day": frame["day"],
            "bedtime": start,
            "waketime": end,
            # Hours past midnight, allowed to run past 24 so a 01:30 bedtime
            # is 25.5 and averages next to a 23:45 one instead of cancelling it.
            "bed_hour": start.dt.hour + start.dt.minute / 60,
            "wake_hour": end.dt.hour + end.dt.minute / 60,
        }
    ).dropna(subset=["bedtime", "waketime"])
    if rows.empty:
        return pd.DataFrame()
    rows["bed_hour_cont"] = np.where(rows["bed_hour"] < 12, rows["bed_hour"] + 24, rows["bed_hour"])
    rows["midpoint_hour"] = (
        rows["bed_hour_cont"] + (rows["waketime"] - rows["bedtime"]).dt.total_seconds() / 7200
    )
    rows["weekday"] = rows["day"].dt.day_name()
    rows["is_weekend"] = rows["day"].dt.dayofweek >= 4  # Fri/Sat nights
    # Robust spread (IQR / 1.349 equals the SD for normal data): one jet-lagged
    # afternoon sleep would otherwise read as a 2.4 h scatter for a whole month.
    rows["midpoint_sd_30d"] = _rolling_spread(rows["midpoint_hour"])
    rows["bed_sd_30d"] = _rolling_spread(rows["bed_hour_cont"])
    for column in ("bed_hour", "wake_hour", "bed_hour_cont", "midpoint_hour"):
        rows[column] = rows[column].round(2)
    return rows.reset_index(drop=True)


def sleep_regularity(stages: pd.DataFrame) -> pd.DataFrame:
    """Sleep Regularity Index: chance of the same sleep/wake state 24 h apart.

    Computed on the minute-level hypnogram, so it measures timing consistency
    independently of how long each night lasted. 100 is perfectly identical
    nights, 0 is a coin flip.
    """
    if stages.empty or "start_local" not in stages.columns:
        return pd.DataFrame()
    frame = stages.copy()
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    frame["end_local"] = pd.to_datetime(frame["end_local"])

    # Minute-of-day occupancy per calendar date, asleep = any non-awake stage.
    occupancy: dict[pd.Timestamp, np.ndarray] = {}
    for row in frame.itertuples(index=False):
        asleep = row.stage in ("deep", "light", "rem")
        if not asleep:
            continue
        current = row.start_local
        while current < row.end_local:
            date = pd.Timestamp(current.date())
            grid = occupancy.setdefault(date, np.zeros(1440, dtype=np.int8))
            grid[current.hour * 60 + current.minute] = 1
            current += pd.Timedelta(minutes=1)

    dates = sorted(occupancy)
    rows = []
    for earlier, later in zip(dates, dates[1:]):
        if (later - earlier).days != 1:
            continue
        match = float((occupancy[earlier] == occupancy[later]).mean())
        rows.append(
            {
                "day": later,
                "sri_pair": round(100 * (2 * match - 1), 1),
                "minutes_asleep": int(occupancy[later].sum()),
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["sri_30d"] = out["sri_pair"].rolling(30, min_periods=10).mean().round(1)
    return out


def night_profile() -> pd.DataFrame:
    """Per-night cardiac recovery shape from the overnight samples.

    Two markers that a nightly average hides. The heart-rate nadir is the
    lowest point of the night and *when* it falls matters: a nadir early in
    the night means the body settled quickly, a late one means recovery was
    still running when the alarm went off. The HRV slope across the night
    separates nights that recovered progressively from nights that stalled.
    """
    nights = db.table("night_series")
    if nights.empty:
        return pd.DataFrame()
    frame = nights.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame["t_local"] = pd.to_datetime(frame["t_local"])

    rows = []
    for day, group in frame.groupby("day"):
        hr = group[group["metric"] == "hr"].sort_values("t_local")
        hrv = group[group["metric"] == "hrv"].sort_values("t_local")
        battery = group[group["metric"] == "body_battery"].sort_values("t_local")
        if len(hr) < 20:
            continue

        onset = hr["t_local"].iloc[0]
        span_min = (hr["t_local"].iloc[-1] - onset).total_seconds() / 60
        if span_min < 120:
            continue

        nadir_at = hr.loc[hr["value"].idxmin(), "t_local"]
        row = {
            "day": day,
            "hr_min": float(hr["value"].min()),
            "hr_mean": round(float(hr["value"].mean()), 1),
            "hr_first_hour": round(
                float(hr[hr["t_local"] <= onset + pd.Timedelta(hours=1)]["value"].mean()), 1
            ),
            # Share of the night already elapsed when heart rate bottomed out.
            "nadir_at_pct": round(
                100 * (nadir_at - onset).total_seconds() / 60 / span_min, 1
            ),
            "nadir_after_min": round((nadir_at - onset).total_seconds() / 60, 1),
            "night_minutes": round(span_min, 0),
        }
        row["hr_drop"] = round(row["hr_first_hour"] - row["hr_min"], 1)

        if len(hrv) >= 6:
            thirds = np.array_split(hrv["value"].values, 3)
            row["hrv_first_third"] = round(float(np.mean(thirds[0])), 1)
            row["hrv_last_third"] = round(float(np.mean(thirds[2])), 1)
            row["hrv_trend"] = round(row["hrv_last_third"] - row["hrv_first_third"], 1)
            minutes = (hrv["t_local"] - hrv["t_local"].iloc[0]).dt.total_seconds() / 60
            if minutes.iloc[-1] > 0:
                slope, _ = np.polyfit(minutes.values, hrv["value"].values, 1)
                row["hrv_slope_per_h"] = round(float(slope) * 60, 2)
        if len(battery) >= 4:
            row["bb_gain"] = round(
                float(battery["value"].iloc[-1] - battery["value"].iloc[0]), 1
            )
            row["bb_gain_per_h"] = round(row["bb_gain"] / (span_min / 60), 2)
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("day").reset_index(drop=True)
    daily = db.table("daily")
    if not daily.empty:
        join_cols = [
            c for c in ("day", "sleep_score", "sleep_h", "readiness", "hrv_last_night")
            if c in daily.columns
        ]
        extra = daily[join_cols].copy()
        extra["day"] = pd.to_datetime(extra["day"])
        out = out.merge(extra, on="day", how="left")
    return out


def intensity_distribution(activities: pd.DataFrame) -> pd.DataFrame:
    """Weekly time-in-zone split with a rule-of-thumb training-model label.

    Classification follows the usual descriptive thresholds (polarised:
    mostly easy with a real hard block and little in between), not a published
    index -- it is a label for the distribution, not a score.
    """
    if activities.empty:
        return pd.DataFrame()
    zones = [f"hr_z{i}_s" for i in range(1, 6)]
    present = [z for z in zones if z in activities.columns]
    if not present:
        return pd.DataFrame()
    frame = activities.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame["iso_week"] = frame["day"].dt.strftime("%G-W%V")
    weekly = frame.groupby("iso_week")[present].sum(min_count=1)
    total = weekly.sum(axis=1).replace(0, np.nan)
    out = pd.DataFrame(index=weekly.index)
    for zone in present:
        out[zone.replace("_s", "_min")] = (weekly[zone] / 60).round(1)
        out[zone.replace("_s", "_pct")] = (100 * weekly[zone] / total).round(1)
    out["total_min"] = (total / 60).round(1)
    easy = out.get("hr_z1_pct", 0).fillna(0) + out.get("hr_z2_pct", 0).fillna(0)
    middle = out.get("hr_z3_pct", 0).fillna(0)
    hard = out.get("hr_z4_pct", 0).fillna(0) + out.get("hr_z5_pct", 0).fillna(0)
    out["easy_pct"] = easy.round(1)
    out["middle_pct"] = middle.round(1)
    out["hard_pct"] = hard.round(1)
    out["model"] = np.select(
        [
            (easy >= 70) & (hard >= 10) & (middle < 15),
            (easy >= 70) & (hard < 10),
            (middle >= 25),
            hard >= 25,
        ],
        ["spolaryzowany", "piramidalny", "progowy", "wysokointensywny"],
        default="mieszany",
    )
    return out.reset_index()


def recovery_quadrants(frame: pd.DataFrame) -> pd.DataFrame:
    """Classify each day in HRV/RHR space relative to the 60-day baseline.

    HRV down with RHR up is the pattern worth acting on; HRV down alone is
    usually noise. Baselines are rolling, so a long-term fitness change does
    not push every day into one corner.
    """
    if frame.empty:
        return pd.DataFrame()
    hrv = _numeric(frame, "hrv_last_night")
    rhr = _numeric(frame, "rhr")
    if hrv.notna().sum() < 40 or rhr.notna().sum() < 40:
        return pd.DataFrame()
    hrv_z = (hrv - hrv.rolling(60, min_periods=20).mean()) / hrv.rolling(60, min_periods=20).std()
    rhr_z = (rhr - rhr.rolling(60, min_periods=20).mean()) / rhr.rolling(60, min_periods=20).std()
    out = pd.DataFrame(
        {
            "day": frame.index,
            "hrv_z": hrv_z.round(2).values,
            "rhr_z": rhr_z.round(2).values,
            "load_day": frame["load_day"].values,
            "readiness": _numeric(frame, "readiness").values,
            "sleep_h": _numeric(frame, "sleep_h").values,
        }
    ).dropna(subset=["hrv_z", "rhr_z"])
    out["quadrant"] = np.select(
        [
            (out["hrv_z"] >= 0) & (out["rhr_z"] <= 0),
            (out["hrv_z"] < 0) & (out["rhr_z"] > 0),
            (out["hrv_z"] >= 0) & (out["rhr_z"] > 0),
        ],
        ["zregenerowany", "obciazony", "pobudzony"],
        default="stlumiony",
    )
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------
# entry point


def main() -> int:
    daily = db.table("daily")
    activities = db.table("activities")
    stages = db.table("sleep_stages")

    frame = _calendar(daily, activities)
    if frame.empty:
        print("brak danych do analizy", flush=True)
        return 1

    pmc = performance_chart(frame)
    # The models below want the load column, so they read the merged frame.
    merged = frame.copy()
    for column in ("ctl", "atl", "tsb"):
        merged[column] = pmc.set_index("day")[column].reindex(merged.index)
    # Late-evening heart rate is the cheapest available stand-in for "rough
    # evening" (alcohol, late meal, hard session): the first hour of sleep HR
    # relative to the night's minimum.
    merged["alcohol_proxy_late_hr"] = _late_night_hr().reindex(merged.index)

    ef = efficiency(activities)
    tables = {
        "pmc": pmc,
        "load_weekly": weekly_load(frame),
        "critical_speed": critical_speed(activities),
        "riegel": riegel_exponent(activities),
        "efficiency": ef,
        "correlations": lagged_correlations(merged),
        "acf": autocorrelation(merged),
        "changepoints": change_points(merged),
        "weekday_effects": weekday_effects(merged),
        "circadian": circadian(daily, stages),
        "sleep_regularity": sleep_regularity(stages),
        "night_profile": night_profile(),
        "intensity_distribution": intensity_distribution(activities),
        "quadrants": recovery_quadrants(merged),
    }
    # Running module: classified sessions, km splits, best efforts and the
    # weekly race-forecast history (see running/pipeline.py). Its own guard,
    # so a modelling error there never costs the tables above.
    try:
        from running import pipeline, store

        tables.update(
            pipeline.build(
                activities, daily, db.table("routes"), db.table("activity_segments"),
                manual=store.manual_kinds(),
            )
        )
    except Exception as exc:  # noqa: BLE001 - reported, the rest is written
        print(f"  bieganie pominiete: {type(exc).__name__}: {exc}", flush=True)

    written = {}
    for name, table in tables.items():
        if table is None or table.empty:
            written[name] = 0
            continue
        write_table(table, name)
        written[name] = int(len(table))

    models = {"banister": banister_fit(frame, ef)}
    (config.TABLES / "models.json").write_text(
        json.dumps(models, indent=2, default=str), encoding="utf-8"
    )

    summary = ", ".join(f"{name}={rows}" for name, rows in written.items())
    print(f"analityka: {summary}", flush=True)
    banister = models["banister"]
    if banister.get("fitted"):
        print(
            "  model Banistera: tau_fitness="
            f"{banister['tau_fitness_days']}d, tau_fatigue={banister['tau_fatigue_days']}d, "
            f"R2={banister['r2']}, szczyt po {banister['taper_days_to_peak']} dniach",
            flush=True,
        )
    return 0


def _late_night_hr() -> pd.Series:
    """First-hour-of-sleep heart rate minus the night's minimum, per day."""
    nights = db.table("night_series")
    if nights.empty:
        return pd.Series(dtype=float)
    hr = nights[nights["metric"] == "hr"].copy()
    if hr.empty:
        return pd.Series(dtype=float)
    hr["day"] = pd.to_datetime(hr["day"])
    hr["t_local"] = pd.to_datetime(hr["t_local"])
    rows = {}
    for day, group in hr.groupby("day"):
        group = group.sort_values("t_local")
        if len(group) < 10:
            continue
        first_hour = group[group["t_local"] <= group["t_local"].iloc[0] + pd.Timedelta(hours=1)]
        if first_hour.empty:
            continue
        rows[day] = float(first_hour["value"].mean() - group["value"].min())
    return pd.Series(rows, dtype=float).round(2)


if __name__ == "__main__":
    raise SystemExit(main())
