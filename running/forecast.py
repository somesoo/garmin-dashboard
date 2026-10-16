"""Race-time forecast for 5 km, 10 km, half and full marathon.

The model, in the order it is computed
--------------------------------------
1. **Documented performance (VDOT_A).** Every best effort of the last 120 days
   (and near-maximal ones up to a year back, faded by ``detraining``) is
   turned into a VDOT with Daniels' curves. An effort counts as
   *near-maximal* when it is labelled a race, or when its own stretch of the
   heart-rate stream averaged >= 91% HRmax for at least 6 minutes. Training
   splits that were not near-maximal are only a *lower bound* -- the runner
   could have gone faster -- and the forecast says so instead of pretending.
2. **Heart rate vs pace (VDOT_B).** Each steady run implies a VO2max through
   %HRR ~ %VO2R (Swain). The population cost curve does not fit any one
   runner's economy, so the absolute value is biased; it is calibrated by the
   ratio between near-maximal efforts and the HR estimate around them. What
   enters the point estimate is the *change* since the last documented
   effort (``hr_trend``), weighted by how old that effort is: a fresh test
   speaks for itself, a three-month-old one is carried forward by the trend.
   The calibrated level is shown, and widens the interval.
3. **Garmin** (Firstbeat's predictor) is kept as an outside reference: it
   enters the uncertainty, not the point estimate, because its inputs are not
   inspectable.
4. **Combined VDOT** -> Daniels time for each distance = *potential*: what the
   current aerobic power gives with distance-specific endurance fully built.
5. **Endurance correction.** Daniels' curve assumes training for the distance.
   A preparation score per distance (long run, weekly volume, regularity
   against the requirements in ``REQUIREMENTS``) raises the effective Riegel
   exponent by up to ``MAX_EXTRA_EXPONENT`` beyond the anchor distance:
   ``realistic = potential * (D / d_anchor) ** (0.08 * (1 - prep))``. A 5 km
   test therefore never extrapolates to a marathon without the endurance tax.
6. **Interval.** Log-time sigma from model error (grows with extrapolation
   distance), disagreement between methods, staleness of the anchor, and
   missing preparation for HM / M; reported as an 80% band, asymmetric when
   the anchor is only a lower bound.
7. **After the plan.** Daniels' own rule -- raise training VDOT about one
   point per 4-6 weeks of consistent training -- gives the expected gain to
   race day (range 1/6..1/4 point per week, at most 16 weeks counted), and the
   preparation the plan reaches replaces today's.

The requirements and constants are heuristics chosen for recreational runners;
they are shown on the page next to every number they influence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from running import physio, units
from running.sessions import HARD_KINDS

REQUIREMENTS: dict[str, dict[str, float]] = {
    # longest run in 6 weeks (km), mean weekly volume over 6 weeks (km),
    # runs per week the consistency check looks for
    "5k": {"long_km": 8, "weekly_km": 20, "runs": 3},
    "10k": {"long_km": 12, "weekly_km": 30, "runs": 3},
    "hm": {"long_km": 18, "weekly_km": 40, "runs": 4},
    "m": {"long_km": 30, "weekly_km": 55, "runs": 4},
}
MAX_EXTRA_EXPONENT = 0.08
PERF_WINDOW_DAYS = 120
HR_WINDOW_DAYS = 42
NEAR_MAX_HR = 0.91
NEAR_MAX_MINUTES = 6.0
Z80 = 1.2816  # two-sided 80% interval
GARMIN_COLUMNS = {"5k": "race_5k_s", "10k": "race_10k_s", "hm": "race_hm_s", "m": "race_marathon_s"}
STEADY_KINDS = ("easy", "long", "recovery", "tempo", "threshold")


@dataclass
class Inputs:
    """Everything the forecast reads, already restricted to <= anchor."""

    runs: pd.DataFrame
    efforts: pd.DataFrame
    daily: pd.DataFrame
    hr_max: float | None
    anchor: pd.Timestamp


@dataclass
class DistanceForecast:
    key: str
    distance_km: float
    realistic_s: float
    low_s: float
    high_s: float
    potential_s: float
    pace: float
    sigma: float
    confidence: str
    prep: dict[str, Any]
    methods: dict[str, float | None]
    sigma_parts: dict[str, float] = field(default_factory=dict)
    target_s: float | None = None
    target_low_s: float | None = None
    target_high_s: float | None = None
    advice: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# inputs


def effort_quality(efforts: pd.DataFrame, runs: pd.DataFrame, hr_max: float | None) -> pd.DataFrame:
    """Efforts with ``hr_frac``, ``minutes`` and the ``near_max`` flag."""
    if efforts is None or efforts.empty:
        return pd.DataFrame(columns=list(getattr(efforts, "columns", [])) + ["hr_frac", "minutes", "near_max"])
    frame = efforts.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame["minutes"] = frame["seconds"] / 60
    frame["hr_frac"] = pd.to_numeric(frame["avg_hr"], errors="coerce") / hr_max if hr_max else np.nan
    races = set()
    if runs is not None and not runs.empty and "kind" in runs.columns:
        races = set(runs.loc[runs["kind"] == "race", "activity_id"].astype("int64"))
    frame["near_max"] = frame["activity_id"].astype("int64").isin(races) | (
        (frame["hr_frac"] >= NEAR_MAX_HR) & (frame["minutes"] >= NEAR_MAX_MINUTES)
    )
    return frame


def detraining(age_days: float) -> float:
    """Multiplier for an old effort: -0.3% per week after four weeks, at most -12%.

    Deliberately gentle -- it stands for an unknown mix of continued training
    and loss, not for full cessation (where VO2max losses of 4-14% within
    1-3 months are reported). Its job is to keep a summer break from either
    freezing the last result or dropping the forecast to an easy jog.
    """
    weeks = max(0.0, age_days / 7 - 4)
    return max(0.88, 1 - 0.003 * weeks)


def performance_vdot(efforts: pd.DataFrame, anchor: pd.Timestamp) -> dict[str, Any] | None:
    """Best documented VDOT, preferring near-maximal efforts.

    Candidates: every effort of the last 120 days (training splits are lower
    bounds), plus near-maximal efforts up to a year old with ``detraining``
    applied. The higher of the two wins -- a slow jog cannot lower a real
    result, and an old result fades instead of standing forever.
    """
    if efforts is None or efforts.empty:
        return None
    usable = efforts[(efforts["day"] <= anchor) & efforts["vdot"].notna()].copy()
    usable["age_days"] = (anchor - usable["day"]).dt.days
    recent = usable[usable["age_days"] < PERF_WINDOW_DAYS].copy()
    older = usable[usable["near_max"] & (usable["age_days"] >= PERF_WINDOW_DAYS) & (usable["age_days"] <= 365)].copy()
    recent["value"] = recent["vdot"] * recent["age_days"].map(detraining)
    older["value"] = older["vdot"] * older["age_days"].map(detraining)
    pool = pd.concat([recent, older])
    if pool.empty:
        return None
    # One activity is one data point: its best effort.
    per_activity = pool.loc[pool.groupby("activity_id")["value"].idxmax()].sort_values("value", ascending=False)
    chosen = per_activity.iloc[0]
    # A lone outlier far above everything else is a GPS cut, not a breakthrough.
    if len(per_activity) >= 2 and chosen["value"] > per_activity.iloc[1]["value"] * 1.06:
        chosen = per_activity.iloc[1]
    near = per_activity[per_activity["near_max"]]
    best_near = near.iloc[0] if not near.empty else None
    if best_near is not None and best_near["value"] >= chosen["value"] * 0.985:
        chosen = best_near
    return {
        "vdot": float(chosen["value"]),
        "vdot_raw": float(chosen["vdot"]),
        "near_max": bool(chosen["near_max"]),
        "effort": chosen["effort"],
        "distance_m": float(chosen["distance_m"]),
        "seconds": float(chosen["seconds"]),
        "day": pd.Timestamp(chosen["day"]),
        "activity_id": int(chosen["activity_id"]),
        "source": chosen.get("source"),
        "hr_frac": None if pd.isna(chosen.get("hr_frac")) else float(chosen["hr_frac"]),
        "age_days": int(chosen["age_days"]),
        "n_efforts": int(len(recent["activity_id"].unique())),
        "n_near_max": int(len(near)),
    }


def hr_vdot_runs(runs: pd.DataFrame, daily: pd.DataFrame, hr_max: float | None) -> pd.DataFrame:
    """Per steady run: the raw (uncalibrated) VO2max implied by HR and pace."""
    columns = ["day", "activity_id", "vdot_hr"]
    if runs is None or runs.empty or not hr_max:
        return pd.DataFrame(columns=columns)
    frame = runs[(runs["duration_min"] >= 20) & runs["avg_hr"].notna()]
    if "kind" in frame.columns:
        frame = frame[frame["kind"].isin(STEADY_KINDS)]
    rows = []
    for run in frame.itertuples(index=False):
        rest = physio.resting_hr(daily, run.day)
        if rest is None:
            continue
        gap = getattr(run, "gap_speed", None)
        speed = gap if gap is not None and not pd.isna(gap) and gap > 0 else units.speed_ms(run.pace_min_km)
        value = physio.vo2max_from_hr(speed, float(run.avg_hr), hr_max, rest)
        if value is not None:
            rows.append({"day": run.day, "activity_id": int(run.activity_id), "vdot_hr": value})
    return pd.DataFrame(rows, columns=columns)


def hr_calibration(hr_runs: pd.DataFrame, efforts: pd.DataFrame, anchor: pd.Timestamp) -> dict[str, Any] | None:
    """Personal factor: near-maximal VDOT / median HR estimate in +-6 weeks."""
    if hr_runs is None or hr_runs.empty or efforts is None or efforts.empty:
        return None
    near = efforts[efforts["near_max"] & (efforts["day"] <= anchor) & efforts["vdot"].notna()]
    near = near.loc[near.groupby("activity_id")["vdot"].idxmax()] if not near.empty else near
    ratios = []
    for effort in near.itertuples(index=False):
        around = hr_runs[(hr_runs["day"] - effort.day).abs() <= pd.Timedelta(days=HR_WINDOW_DAYS)]
        around = around[around["day"] <= anchor]
        if len(around) >= 3:
            ratios.append(float(effort.vdot) / float(around["vdot_hr"].median()))
    if not ratios:
        return None
    return {"factor": float(np.median(ratios)), "n": len(ratios)}


def hr_vdot(hr_runs: pd.DataFrame, anchor: pd.Timestamp, calibration: dict[str, Any] | None) -> dict[str, Any] | None:
    if hr_runs is None or hr_runs.empty:
        return None
    window = hr_runs[(hr_runs["day"] <= anchor) & (hr_runs["day"] > anchor - pd.Timedelta(days=HR_WINDOW_DAYS))]
    if len(window) < 3:
        return None
    raw = float(window["vdot_hr"].median())
    spread = float(window["vdot_hr"].quantile(0.75) - window["vdot_hr"].quantile(0.25))
    factor = calibration["factor"] if calibration else None
    return {
        "raw": raw,
        "vdot": raw * factor if factor else None,
        "n": int(len(window)),
        "iqr": spread,
        "calibrated": factor is not None,
    }


def preparation(runs: pd.DataFrame, anchor: pd.Timestamp, key: str) -> dict[str, Any]:
    """Distance-specific preparation score in 0..1 with its components."""
    need = REQUIREMENTS[key]
    window = runs[(runs["day"] <= anchor) & (runs["day"] > anchor - pd.Timedelta(days=42))] if not runs.empty else runs
    long_km = float(window["distance_km"].max()) if window is not None and not window.empty else 0.0
    weekly_km = float(window["distance_km"].sum()) / 6 if window is not None and not window.empty else 0.0
    weeks_ok = 0
    for index in range(8):
        end = anchor - pd.Timedelta(days=7 * index)
        count = 0 if runs.empty else int(((runs["day"] <= end) & (runs["day"] > end - pd.Timedelta(days=7))).sum())
        weeks_ok += count >= max(2, need["runs"] - 1)
    consistency = weeks_ok / 8
    long_part = min(1.0, long_km / need["long_km"])
    volume_part = min(1.0, weekly_km / need["weekly_km"])
    score = 0.4 * long_part + 0.4 * volume_part + 0.2 * consistency
    return {
        "score": round(score, 3),
        "long_km": round(long_km, 1),
        "long_need": need["long_km"],
        "weekly_km": round(weekly_km, 1),
        "weekly_need": need["weekly_km"],
        "consistency": round(consistency, 2),
        "runs_need": need["runs"],
    }


def _penalty(distance_m: float, anchor_m: float, prep: float) -> float:
    if distance_m <= anchor_m:
        return 1.0
    return (distance_m / anchor_m) ** (MAX_EXTRA_EXPONENT * (1 - max(0.0, min(1.0, prep))))


def _garmin(daily: pd.DataFrame, anchor: pd.Timestamp) -> dict[str, float | None]:
    out: dict[str, float | None] = {key: None for key in GARMIN_COLUMNS}
    out["vo2max"] = None
    if daily is None or daily.empty:
        return out
    frame = daily[pd.to_datetime(daily["day"]) <= anchor]
    frame = frame[pd.to_datetime(frame["day"]) > anchor - pd.Timedelta(days=14)]
    for key, column in GARMIN_COLUMNS.items():
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            out[key] = float(values.iloc[-1]) if not values.empty else None
    if "vo2max" in frame.columns:
        values = pd.to_numeric(frame["vo2max"], errors="coerce").dropna()
        out["vo2max"] = float(values.iloc[-1]) if not values.empty else None
    return out


# --------------------------------------------------------------------------
# the forecast


def forecast(
    runs: pd.DataFrame,
    efforts: pd.DataFrame,
    daily: pd.DataFrame,
    anchor: pd.Timestamp | None = None,
    *,
    hr_max: float | None = None,
    weeks_to_race: dict[str, float] | None = None,
    plan_prep: dict[str, float] | None = None,
    hr_runs: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Forecast at ``anchor`` (default: the last run) using only data up to it.

    ``efforts`` must already carry ``near_max`` (``effort_quality``).
    ``weeks_to_race`` / ``plan_prep`` map distance keys to weeks remaining and
    the preparation score a plan reaches; with them a *target* is added.
    Returns ``{"status": "ok" | "insufficient", ...}`` -- never raises on thin data.
    """
    if runs is None or runs.empty:
        return {"status": "insufficient", "reason": "Brak biegów w danych."}
    anchor = pd.Timestamp(anchor) if anchor is not None else runs["day"].max()
    runs = runs[runs["day"] <= anchor]
    efforts = efforts[efforts["day"] <= anchor] if efforts is not None and not efforts.empty else efforts
    if hr_runs is None:
        hr_runs = hr_vdot_runs(runs, daily, hr_max)
    else:
        hr_runs = hr_runs[hr_runs["day"] <= anchor]

    perf = performance_vdot(efforts, anchor)
    calibration = hr_calibration(hr_runs, efforts, anchor)
    hr = hr_vdot(hr_runs, anchor, calibration)
    garmin = _garmin(daily, anchor)

    vdot_a = perf["vdot"] if perf else None
    vdot_b = hr["vdot"] if hr and hr["calibrated"] else None
    notes: list[str] = []
    if vdot_a is None and vdot_b is None:
        return {
            "status": "insufficient",
            "reason": (
                f"W ostatnich {PERF_WINDOW_DAYS} dniach nie ma biegu z mierzalnym najlepszym "
                "odcinkiem (≥ 1 km, ≥ 3,5 min), a tętno nie ma kalibracji. Jeden bieg testowy "
                "(np. 3–5 km na maksa) wystarczy, żeby zacząć."
            ),
            "anchor": anchor,
        }

    lower_bound = bool(perf and not perf["near_max"])
    stale_weeks = (perf["age_days"] / 7) if perf else 99.0
    trend = hr_trend(hr_runs, perf, anchor) if perf else None
    if vdot_a is not None:
        # The last documented effort, carried forward by how the HR-pace
        # relation moved since. Fresh test: the test speaks; after ~12 weeks
        # the trend has full say.
        age_weight = min(1.0, perf["age_days"] / 84)
        combined = vdot_a * (trend ** age_weight if trend else 1.0)
        weights = {"wyniki": round(1 - age_weight, 2), "trend tętna": round(age_weight, 2)} if trend else {"wyniki": 1.0}
        weights = {name: weight for name, weight in weights.items() if weight > 0}
        if lower_bound and vdot_b is not None and vdot_b > combined:
            # A lower bound can be raised by the HR estimate, never lowered.
            combined = 0.5 * combined + 0.5 * vdot_b
            weights = {"wyniki": 0.5, "tętno (poziom)": 0.5}
        if trend is None:
            notes.append("Brak trendu tętna (za mało spokojnych biegów z tętnem) — prognoza to ostatni wynik bez korekty.")
    else:
        weights = {"tętno (poziom)": 1.0}
        combined = vdot_b
        notes.append("Brak odcinków z ostatnich 120 dni — prognoza stoi wyłącznie na skalibrowanym tętnie.")
    if lower_bound:
        notes.append(
            "Najlepszy odcinek nie był wysiłkiem maksymalnym (tętno < 91% HRmax) — wynik z niego "
            "to dolna granica możliwości, więc przedział jest szerszy w stronę szybszych czasów."
        )

    anchor_m = perf["distance_m"] if perf else 5000.0
    distances: dict[str, DistanceForecast] = {}
    for key, km in units.RACES.items():
        metres = km * 1000
        prep = preparation(runs, anchor, key)
        penalty = _penalty(metres, anchor_m, prep["score"])
        potential = physio.race_time(combined, metres)
        if potential is None:
            continue
        realistic = potential * penalty
        methods: dict[str, float | None] = {
            "wyniki": physio.race_time(vdot_a, metres) * penalty if vdot_a else None,
            "tętno": physio.race_time(vdot_b, metres) * penalty if vdot_b else None,
            "Garmin": garmin.get(key),
        }
        spread = _disagreement(methods, perf)
        extrapolation = abs(math.log(metres / anchor_m))
        sigma_parts = {
            "baza": 0.02,
            "dystans": 0.015 * extrapolation,
            "wiek": min(0.04, 0.01 * max(0.0, stale_weeks - 4) / 4),
            "przygotowanie": 0.04 * (1 - prep["score"]) if key in ("hm", "m") else 0.0,
        }
        sigma_model = sum(sigma_parts.values())
        sigma = math.sqrt(sigma_model**2 + spread**2)
        sigma_parts["metody"] = spread
        sigma_fast = sigma + (0.02 if lower_bound else 0.0)
        low, high = realistic * math.exp(-Z80 * sigma_fast), realistic * math.exp(Z80 * sigma)
        confidence = _confidence(sigma, perf, hr)
        item = DistanceForecast(
            key=key,
            distance_km=km,
            realistic_s=realistic,
            low_s=low,
            high_s=high,
            potential_s=potential,
            pace=units.pace_from(realistic, km),
            sigma=sigma,
            confidence=confidence,
            prep=prep,
            methods=methods,
            sigma_parts=sigma_parts,
        )
        weeks = (weeks_to_race or {}).get(key)
        if weeks is not None and weeks > 0:
            counted = min(float(weeks), 16.0)
            reached = (plan_prep or {}).get(key, 1.0)
            target_penalty = _penalty(metres, anchor_m, reached)
            item.target_s = physio.race_time(combined + counted / 5, metres) * target_penalty
            item.target_low_s = physio.race_time(combined + counted / 4, metres) * target_penalty
            item.target_high_s = physio.race_time(combined + counted / 6, metres) * target_penalty
        if key == "m" and prep["score"] < 0.45:
            item.warnings.append(
                "Przygotowanie do maratonu jest dziś niskie — to prognoza ukończenia przy równym "
                "rozłożeniu sił, a nie wyniku, do którego warto startować."
            )
        if key == "hm" and prep["score"] < 0.35:
            item.warnings.append("Za mało długich biegów, żeby półmaraton był dziś testem formy.")
        distances[key] = item

    return {
        "status": "ok",
        "anchor": anchor,
        "vdot": combined,
        "vdot_perf": vdot_a,
        "vdot_hr": vdot_b,
        "vdot_hr_raw": hr["raw"] if hr else None,
        "weights": weights,
        "perf": perf,
        "hr": hr,
        "calibration": calibration,
        "garmin": garmin,
        "hr_max": hr_max,
        "lower_bound": lower_bound,
        "notes": notes,
        "distances": distances,
    }


def hr_trend(hr_runs: pd.DataFrame, perf: dict[str, Any] | None, anchor: pd.Timestamp) -> float | None:
    """Ratio of the HR-implied fitness now to the same estimate at the anchor effort.

    Both medians are over 42-day windows, clipped to +-10%: a month of hot
    weather moves the HR estimate, and it should not move a race forecast by
    more than that.
    """
    if perf is None or hr_runs is None or hr_runs.empty:
        return None
    window = pd.Timedelta(days=HR_WINDOW_DAYS)
    now = hr_runs[(hr_runs["day"] <= anchor) & (hr_runs["day"] > anchor - window)]
    then = hr_runs[(hr_runs["day"] <= perf["day"]) & (hr_runs["day"] > perf["day"] - window)]
    if len(now) < 3 or len(then) < 3:
        return None
    ratio = float(now["vdot_hr"].median()) / float(then["vdot_hr"].median())
    return max(0.9, min(1.1, ratio))


def _disagreement(methods: dict[str, float | None], perf: dict[str, Any] | None) -> float:
    """Weighted SD of the methods' log-times.

    Documented performance carries most weight when it is a fresh near-max
    effort; the HR level and Garmin are outside opinions and only widen the
    band. With a single method the disagreement is an assumed 3%.
    """
    fresh = bool(perf and perf["near_max"] and perf["age_days"] <= 56)
    base = {"wyniki": 0.7 if fresh else 0.4, "tętno": 0.15 if fresh else 0.3, "Garmin": 0.15 if fresh else 0.3}
    pairs = [(base[name], math.log(value)) for name, value in methods.items() if value and name in base]
    if len(pairs) < 2:
        return 0.03
    weights = np.array([w for w, _ in pairs])
    logs = np.array([v for _, v in pairs])
    mean = float(np.average(logs, weights=weights))
    return float(math.sqrt(np.average((logs - mean) ** 2, weights=weights)))


CONFIDENCE_SIGMA = {"wysoka": 0.04, "średnia": 0.075}


def _confidence(sigma: float, perf: dict[str, Any] | None, hr: dict[str, Any] | None) -> str:
    fresh_max = bool(perf and perf["near_max"] and perf["age_days"] <= 42)
    if sigma <= CONFIDENCE_SIGMA["wysoka"] and fresh_max:
        return "wysoka"
    if sigma <= CONFIDENCE_SIGMA["średnia"] and perf is not None:
        return "średnia"
    return "niska"


def confidence_reasons(item: DistanceForecast, perf: dict[str, Any] | None) -> list[str]:
    """Why the confidence is not one level higher, largest cause first.

    Plain sentences for the forecast page: the label alone ("średnia") says
    nothing about what would raise it.
    """
    if item.confidence == "wysoka":
        return []
    reasons: list[tuple[float, str]] = []
    if perf is None:
        reasons.append((1.0, "brak udokumentowanego mocnego biegu z 120 dni — prognoza stoi na samym tętnie"))
    else:
        if not perf["near_max"]:
            reasons.append((0.9, "najlepszy odcinek nie był wysiłkiem maksymalnym (tętno < 91% HRmax), "
                                 "więc to tylko dolna granica"))
        elif perf["age_days"] > 42:
            reasons.append((0.8, f"ostatni maksymalny wysiłek ma {perf['age_days'] // 7} tyg. — "
                                 "wysoka pewność wymaga świeżego (≤ 6 tyg.)"))
    parts = item.sigma_parts
    anchor_km = f"{(perf or {}).get('distance_m', 5000) / 1000:.1f}".rstrip("0").rstrip(".")
    names = {"wyniki": "wysiłki", "tętno": "tętno", "Garmin": "Garmin"}
    times = ", ".join(f"{names[name]} {units.fmt_time(value)}" for name, value in item.methods.items() if value)
    labels = {
        "dystans": f"przeliczenie z {anchor_km} km na {units.RACE_LABELS.get(item.key, item.key)}",
        "metody": f"metody dają różne czasy ({times})",
        "wiek": "wysiłek, na którym stoi prognoza, się starzeje",
        "przygotowanie": "niskie przygotowanie do dystansu (długie biegi, kilometry)",
    }
    for name, label in labels.items():
        share = parts.get(name, 0.0)
        if share >= 0.01:
            reasons.append((share, f"{label} (ok. ±{Z80 * share:.0%})"))
    reasons.sort(key=lambda pair: pair[0], reverse=True)
    return [text for _, text in reasons]


GOAL_STATUS = {
    "none": "bez celu czasowego",
    "now": "w zasięgu już dziś",
    "plan": "realny po planie",
    "ambitious": "ambitny",
    "stretch": "bardzo ambitny",
}


def goal_status(item: DistanceForecast | None, goal_s: float | None) -> str:
    """Where a goal time sits against today's forecast and the post-plan target."""
    if item is None or goal_s is None:
        return "none"
    if goal_s >= item.realistic_s:
        return "now"
    target = item.target_s or item.potential_s
    if goal_s >= target:
        return "plan"
    edge = item.target_low_s or item.low_s
    return "ambitious" if goal_s >= edge else "stretch"


def trend(history_frame: pd.DataFrame, key: str, weeks: int) -> float | None:
    """Change of the realistic forecast over ``weeks`` (seconds, negative = faster)."""
    if history_frame is None or history_frame.empty:
        return None
    frame = history_frame[history_frame["distance"] == key].sort_values("day")
    if len(frame) < 2:
        return None
    now = frame.iloc[-1]
    before = frame[frame["day"] <= now["day"] - pd.Timedelta(weeks=weeks)]
    if before.empty:
        return None
    return float(now["realistic_s"] - before.iloc[-1]["realistic_s"])


# --------------------------------------------------------------------------
# what to train


def advice(result: dict[str, Any], runs: pd.DataFrame, key: str) -> list[str]:
    """Training elements most likely to move the forecast for ``key``, from the data."""
    if result.get("status") != "ok" or key not in result["distances"]:
        return []
    item: DistanceForecast = result["distances"][key]
    prep = item.prep
    anchor = result["anchor"]
    recent = runs[(runs["day"] <= anchor) & (runs["day"] > anchor - pd.Timedelta(days=28))]
    kinds = recent["kind"].value_counts() if "kind" in recent.columns else pd.Series(dtype=int)
    tips: list[tuple[float, str]] = []

    if prep["long_km"] < prep["long_need"]:
        gap = prep["long_need"] - prep["long_km"]
        tips.append((gap / prep["long_need"],
                     f"Długie wybieganie: najdłuższy bieg w 6 tyg. to {prep['long_km']:.0f} km, dla tego "
                     f"dystansu przyjęto ≥ {prep['long_need']:.0f} km. Wydłużaj o 1–2 km na tydzień, "
                     "w spokojnym tempie."))
    if prep["weekly_km"] < prep["weekly_need"]:
        tips.append(((prep["weekly_need"] - prep["weekly_km"]) / prep["weekly_need"],
                     f"Objętość: średnio {prep['weekly_km']:.0f} km/tydz. przy założonych "
                     f"{prep['weekly_need']:.0f} km. Dokładaj spokojne kilometry, nie tempo."))
    if prep["consistency"] < 0.75:
        tips.append((0.75 - prep["consistency"],
                     f"Regularność: tylko {prep['consistency']:.0%} z ostatnich 8 tygodni miało "
                     f"≥ {max(2, prep['runs_need'] - 1)} biegi. Stała liczba biegów w tygodniu daje "
                     "więcej niż pojedyncze mocne tygodnie."))
    if key in ("10k", "hm", "m") and kinds.get("threshold", 0) + kinds.get("tempo", 0) == 0:
        tips.append((0.35, "Próg: w 4 tygodniach nie było biegu progowego ani tempa. Jedna sesja "
                           "tygodniowo (np. 3×10 min w tempie T) podnosi tempo, które utrzymasz godzinę."))
    if key in ("5k", "10k") and kinds.get("intervals", 0) == 0:
        tips.append((0.3, "Interwały VO₂max: brak w 4 tygodniach. Np. 5×1000 m w tempie I z 2–3 min "
                          "truchtu — dla 5 i 10 km to najbardziej specyficzny bodziec."))
    if key == "m":
        tips.append((0.2, "Specyfika maratonu: w ostatnich 8 tygodniach przed startem część długich "
                          "wybiegań kończ odcinkiem w tempie maratońskim (8–14 km)."))
    if result.get("lower_bound") or (result.get("perf") or {}).get("age_days", 0) > 42:
        tips.append((0.25, "Test: prognoza opiera się na odcinkach treningowych. Bieg na maksa na 3–5 km "
                           "(np. parkrun) zawęzi przedział bardziej niż jakikolwiek wykres."))
    hard_share = (recent["kind"].isin(HARD_KINDS).sum() / len(recent)) if len(recent) and "kind" in recent else 0
    if hard_share > 0.45:
        tips.append((0.3, f"Rozkład: {hard_share:.0%} biegów z 4 tygodni to sesje mocne. Przy przewadze "
                          "spokojnych kilometrów (~75–80%) jakość mocnych sesji zwykle rośnie."))
    tips.sort(key=lambda pair: -pair[0])
    return [text for _, text in tips[:4]]


# --------------------------------------------------------------------------
# history and back-test


def history(
    runs: pd.DataFrame,
    efforts: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    hr_max: float | None,
    step_days: int = 7,
) -> pd.DataFrame:
    """Forecast snapshots every ``step_days``, each using only the data before it."""
    columns = ["day", "distance", "realistic_s", "low_s", "high_s", "potential_s", "garmin_s",
               "vdot", "vdot_perf", "vdot_hr", "prep", "confidence", "near_max"]
    if runs is None or runs.empty:
        return pd.DataFrame(columns=columns)
    hr_runs = hr_vdot_runs(runs, daily, hr_max)
    end = runs["day"].max()
    start = runs["day"].min() + pd.Timedelta(days=28)
    anchors = list(pd.date_range(end=end, start=start, freq=f"{step_days}D"))
    if not anchors or anchors[-1] != end:
        anchors.append(end)
    rows = []
    for anchor in anchors:
        result = forecast(runs, efforts, daily, anchor, hr_max=hr_max, hr_runs=hr_runs)
        if result.get("status") != "ok":
            continue
        for key, item in result["distances"].items():
            rows.append(
                {
                    "day": anchor,
                    "distance": key,
                    "realistic_s": round(item.realistic_s, 0),
                    "low_s": round(item.low_s, 0),
                    "high_s": round(item.high_s, 0),
                    "potential_s": round(item.potential_s, 0),
                    "garmin_s": item.methods.get("Garmin"),
                    "vdot": round(result["vdot"], 2),
                    "vdot_perf": None if result["vdot_perf"] is None else round(result["vdot_perf"], 2),
                    "vdot_hr": None if result["vdot_hr"] is None else round(result["vdot_hr"], 2),
                    "prep": item.prep["score"],
                    "confidence": item.confidence,
                    "near_max": not result["lower_bound"],
                }
            )
    return pd.DataFrame(rows, columns=columns)


def backtest(history_frame: pd.DataFrame, efforts: pd.DataFrame) -> pd.DataFrame:
    """Near-maximal efforts >= 3 km against the VDOT forecast a week before them.

    Compares like with like: the effort's own distance at the earlier VDOT
    (potential, no endurance correction -- these are short of race distance).
    """
    if history_frame is None or history_frame.empty or efforts is None or efforts.empty:
        return pd.DataFrame()
    tests = efforts[efforts["near_max"] & (efforts["distance_m"] >= 3000)]
    if tests.empty:
        return pd.DataFrame()
    tests = tests.loc[tests.groupby("activity_id")["vdot"].idxmax()]
    snapshots = history_frame.drop_duplicates("day")[["day", "vdot"]].sort_values("day")
    rows = []
    for test in tests.itertuples(index=False):
        before = snapshots[snapshots["day"] <= test.day - pd.Timedelta(days=6)]
        if before.empty:
            continue
        predicted = physio.race_time(float(before["vdot"].iloc[-1]), float(test.distance_m))
        if predicted is None:
            continue
        rows.append(
            {
                "day": test.day,
                "activity_id": int(test.activity_id),
                "distance_m": float(test.distance_m),
                "actual_s": float(test.seconds),
                "predicted_s": round(predicted, 0),
                "error_pct": round(100 * (predicted / float(test.seconds) - 1), 1),
            }
        )
    return pd.DataFrame(rows)
