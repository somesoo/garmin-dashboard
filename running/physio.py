"""Physiological anchors: Daniels' VDOT model, training paces, heart-rate anchors.

The common currency of the forecast is VDOT (Daniels & Gilbert, *Oxygen
Power*, 1979; *Daniels' Running Formula*). Two empirical curves define it:

* oxygen cost of running at ``v`` m/min:
  ``VO2(v) = -4.60 + 0.182258 v + 0.000104 v^2``  (ml/kg/min)
* fraction of VO2max sustainable for ``t`` minutes:
  ``F(t) = 0.8 + 0.1894393 e^(-0.012778 t) + 0.2989558 e^(-0.1932605 t)``

A performance ``(d, t)`` gives ``VDOT = VO2(d/t) / F(t)``; the inverse finds the
time that matches a VDOT on another distance. The curve already encodes how
speed falls with duration for a runner *trained for the distance* -- which is
why the forecast adds its own endurance correction on top (see forecast.py).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def oxygen_cost(v_m_min: float) -> float:
    return -4.60 + 0.182258 * v_m_min + 0.000104 * v_m_min**2


def sustainable_fraction(t_min: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot(distance_m: float, seconds: float) -> float | None:
    """VDOT of a maximal effort over ``distance_m`` in ``seconds``.

    Only meaningful between ~3.5 and ~240 minutes, which is the range the
    curves were fitted on; outside it the function returns None rather than an
    extrapolated number.
    """
    if not distance_m or not seconds or distance_m <= 0 or seconds <= 0:
        return None
    t_min = seconds / 60
    if t_min < 3.5 or t_min > 300:
        return None
    value = oxygen_cost(distance_m / t_min) / sustainable_fraction(t_min)
    return float(value) if value > 0 else None


def race_time(vdot_value: float, distance_m: float) -> float | None:
    """Seconds for ``distance_m`` at ``vdot_value`` (bisection on a monotone curve)."""
    if vdot_value is None or not np.isfinite(vdot_value) or vdot_value <= 10 or distance_m <= 0:
        return None
    low, high = 60.0, 60.0 * 60 * 12  # 1 min .. 12 h
    for _ in range(80):
        mid = (low + high) / 2
        t_min = mid / 60
        implied = oxygen_cost(distance_m / t_min) / sustainable_fraction(t_min)
        # implied VDOT falls as time grows: too high -> we are too fast -> go slower
        if implied > vdot_value:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def speed_at_fraction(vdot_value: float, fraction: float) -> float | None:
    """Speed (m/s) whose oxygen cost is ``fraction`` of VDOT."""
    if vdot_value is None or vdot_value <= 0:
        return None
    a, b, c = 0.000104, 0.182258, -(4.60 + fraction * vdot_value)
    disc = b * b - 4 * a * c
    if disc <= 0:
        return None
    v_m_min = (-b + math.sqrt(disc)) / (2 * a)
    return v_m_min / 60


# Daniels' intensities as a fraction of VDOT. Easy is a range; the others are
# the centre of their band and get a +-1.5% window when shown as a pace range.
PACE_FRACTIONS = {
    "E": (0.62, 0.70),
    "T": (0.86, 0.885),
    "I": (0.96, 0.99),
    "R": (1.04, 1.08),
}


def training_paces(vdot_value: float | None) -> dict[str, tuple[float, float]]:
    """Pace bands (min/km, fast..slow) for E/M/T/I/R at the given VDOT.

    M is the predicted marathon pace itself rather than a fraction, matching
    how Daniels' tables are built.
    """
    if vdot_value is None or not np.isfinite(vdot_value):
        return {}
    out: dict[str, tuple[float, float]] = {}
    for name, (low, high) in PACE_FRACTIONS.items():
        fast, slow = speed_at_fraction(vdot_value, high), speed_at_fraction(vdot_value, low)
        if fast and slow:
            out[name] = (1000 / fast / 60, 1000 / slow / 60)
    marathon = race_time(vdot_value, 42195)
    if marathon:
        centre = marathon / 60 / 42.195
        out["M"] = (centre * 0.985, centre * 1.015)
    return out


# --------------------------------------------------------------------------
# heart-rate anchors


def robust_hr_max(max_hr: Any, recent_days: pd.Series | None = None, rank: int = 3) -> float | None:
    """Maximum heart rate as the ``rank``-th highest recorded run maximum.

    Optical sensors produce single spikes (cadence lock, a strap slipping);
    the third-highest of all recorded maxima is the cheapest defence that still
    tracks a true maximum hit a few times a year. With fewer than five values
    the estimate is not trusted at all.
    """
    values = pd.to_numeric(pd.Series(max_hr), errors="coerce").dropna()
    values = values[(values > 120) & (values < 230)]
    if len(values) < 5:
        return None
    ordered = values.sort_values(ascending=False).reset_index(drop=True)
    return float(ordered.iloc[min(rank - 1, len(ordered) - 1)])


def resting_hr(daily: pd.DataFrame, anchor: pd.Timestamp | None = None, days: int = 30) -> float | None:
    """Median resting HR over the last ``days`` before ``anchor`` (Garmin's daily RHR)."""
    if daily is None or daily.empty or "rhr" not in daily.columns:
        return None
    frame = daily[["day", "rhr"]].copy()
    frame["day"] = pd.to_datetime(frame["day"])
    if anchor is not None:
        frame = frame[(frame["day"] <= anchor) & (frame["day"] > anchor - pd.Timedelta(days=days))]
    else:
        frame = frame.tail(days)
    values = pd.to_numeric(frame["rhr"], errors="coerce").dropna()
    values = values[(values > 25) & (values < 110)]
    return float(values.median()) if len(values) >= 5 else None


def vo2max_from_hr(speed_ms_value: float, avg_hr: float, hr_max: float, hr_rest: float) -> float | None:
    """VO2max implied by a steady run, via %HRR ~ %VO2R (Swain & Leutholtz).

    ``VO2max = (VO2(v) - 3.5) / %HRR + 3.5``. Returns None outside 55-92%
    HRR, where the linear relation is least reliable (warm-up drift at the
    bottom, anaerobic contribution at the top).
    """
    if not all(x is not None and np.isfinite(x) for x in (speed_ms_value, avg_hr, hr_max, hr_rest)):
        return None
    if hr_max <= hr_rest or speed_ms_value <= 0:
        return None
    reserve = (avg_hr - hr_rest) / (hr_max - hr_rest)
    if reserve < 0.55 or reserve > 0.92:
        return None
    cost = oxygen_cost(speed_ms_value * 60)
    if cost <= 3.5:
        return None
    return (cost - 3.5) / reserve + 3.5


def hr_band(hr_max: float | None, low_pct: float, high_pct: float) -> str:
    if hr_max is None:
        return f"{low_pct:.0%}–{high_pct:.0%} HRmax"
    return f"{low_pct * hr_max:.0f}–{high_pct * hr_max:.0f} bpm"


# --------------------------------------------------------------------------
# zones from the lactate-threshold heart rate
#
# Percentages of HRmax put everyone's threshold at the same fraction of the
# maximum, while it really sits anywhere from ~85 to ~95%. Anchoring the zones
# on the threshold heart rate (LTHR) removes that error. LTHR is the average
# heart rate of a ~20-60 min near-maximal continuous effort (Friel's field test:
# the last 20 minutes of a 30-minute solo time trial); the zones are Friel's
# running zones as fractions of it: Z1 < 85%, Z2 85-89%, Z3 90-94%, Z4 95-99%,
# Z5 >= 100%. Daniels' E spans Z1-Z2, M is Z3, T is Z4 up to LTHR, I is Z5.

#
# The top of E is the first ventilatory threshold (VT1): typed in from a test,
# else ~0.91 x LTHR (Esteve-Lanao et al. 2026, 1411 runners: VT1 85.1% and VT2
# 93.5% of HRpeak). Without any threshold LTHR is estimated as 93.5% of HRmax.
# Both live in hrzones.py, which also gives the five display zones.

LTHR_FRACTIONS = {
    "E": (0.78, 0.90),
    "recovery": (0.70, 0.84),
    "M": (0.91, 0.94),
    "T": (0.95, 1.00),
    "I": (1.00, 1.06),
}
LTHR_MINUTES = (18.0, 60.0)
LTHR_DAYS = 120
# The median of this many hardest efforts: one hot day or one sensor spike no
# longer sets the zones for four months.
LTHR_TOP = 3
# With no hard effort in LTHR_DAYS the last measured threshold still holds --
# marked stale, with its age -- for this long; only then do the zones fall back
# to the estimate from HRmax. A training break must not make them jump.
LTHR_KEEP_DAYS = 365


def threshold_hr(efforts: pd.DataFrame | None, anchor: pd.Timestamp | None = None,
                 days: int = LTHR_DAYS) -> dict[str, Any] | None:
    """LTHR: the median heart rate of the ``LTHR_TOP`` hardest near-maximal 18-60 min efforts in ``days``.

    ``efforts`` is ``run_efforts`` (``near_max``, ``minutes``, ``avg_hr``).
    Without such an effort in ``days`` before ``anchor``, the same median over
    the ``days`` that ended with the last one, up to ``LTHR_KEEP_DAYS`` back,
    with ``stale`` set. None when there is none in a year either -- the zones
    then rest on HRmax (hrzones.anchors).

    ``bpm``, ``day`` (the newest effort used), ``minutes``/``effort`` (the one
    closest to the median), ``n`` (efforts used), ``stale``, ``age_days``.
    """
    if efforts is None or efforts.empty or not {"near_max", "minutes", "avg_hr", "day"} <= set(efforts.columns):
        return None
    frame = efforts.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    anchor = pd.Timestamp(anchor) if anchor is not None else frame["day"].max()
    low, high = LTHR_MINUTES
    frame = frame[frame["near_max"].fillna(False).astype(bool) & frame["minutes"].between(low, high)
                  & frame["avg_hr"].notna() & (frame["day"] <= anchor)
                  & (frame["day"] > anchor - pd.Timedelta(days=LTHR_KEEP_DAYS))]
    if frame.empty:
        return None
    window = frame[frame["day"] > anchor - pd.Timedelta(days=days)]
    stale = window.empty
    if stale:
        last = frame["day"].max()
        window = frame[frame["day"] > last - pd.Timedelta(days=days)]
    top = window.nlargest(LTHR_TOP, "avg_hr")
    bpm = float(top["avg_hr"].median())
    closest = top.iloc[int(np.argmin((top["avg_hr"] - bpm).abs().to_numpy()))]
    newest = top["day"].max()
    return {"bpm": int(math.floor(bpm + 0.5)), "day": str(newest.date()),
            "minutes": round(float(closest["minutes"]), 1), "effort": str(closest.get("effort", "")),
            "n": int(len(top)), "stale": bool(stale), "age_days": int((anchor - newest).days)}


def hr_zones(hr_max: float | None, lthr: float | None, vt1: float | None = None,
             basis: str | None = None) -> dict[str, tuple[int, int] | None]:
    """Heart-rate band (bpm) per intensity, hung on the thresholds (``hrzones``).

    ``lthr`` measured in the data (or typed in: ``basis="manual"``), else
    estimated from ``hr_max``; E tops just under VT1 (``vt1`` typed in, else
    ~0.91 x LTHR), M runs from VT1 to 94% LTHR. No anchor at all -> no bands.
    """
    import hrzones

    names = ("E", "recovery", "M", "T", "I")
    out: dict[str, tuple[int, int] | None] = {name: None for name in names}
    found = hrzones.anchors(lthr=lthr, hr_max=hr_max, manual={"vt1": int(vt1)} if vt1 else {})
    if found is None:
        out["basis"] = None  # type: ignore[assignment]
        return out
    top, first, cap = float(found["lthr"]), float(found["vt1"]), found.get("hr_max")

    def band(low: float, high: float) -> tuple[int, int]:
        return int(round(low)), int(round(min(high, cap) if cap else high))

    out["E"] = band(0.78 * top, first - 1)
    out["recovery"] = band(0.70 * top, min(0.84 * top, first - 1))
    out["M"] = band(first, 0.94 * top)
    out["T"] = band(0.95 * top, top)
    out["I"] = band(top, 1.06 * top)
    out["basis"] = basis or hrzones.basis(found)  # type: ignore[assignment]
    return out


def zone_text(zones: dict[str, Any] | None, name: str) -> str:
    band = (zones or {}).get(name)
    if band:
        return f"{band[0]}–{band[1]} bpm"
    low, high = LTHR_FRACTIONS.get(name, (0.6, 0.72))
    return f"{low:.0%}–{high:.0%} LTHR"


# --------------------------------------------------------------------------
# critical speed from clean efforts
#
# CS is the boundary between the heavy and severe domains: threshold training
# is meant to sit at or below it (Jones et al., Med Sci Sports Exerc 2019;
# Jones & Vanhatalo, Sports Med 2017). The two-parameter model d = CS*t + D'
# holds for maximal efforts of ~2-20 minutes. It must be fitted on clean
# efforts only: the "fastest 5 km" inside an interval session includes the
# recoveries and drags CS down. Clean = one continuous work block of a
# workout, or a whole near-maximal run (a race or a time trial).

CS_MINUTES = (2.0, 20.0)
CS_DAYS = 90
CS_SPREAD = 2.0  # the longest effort at least twice the shortest


def critical_speed(efforts: pd.DataFrame | None, anchor: pd.Timestamp | None = None,
                   days: int = CS_DAYS) -> dict[str, Any] | None:
    """CS (m/s), D' (m) and its pace from clean near-maximal efforts, or None.

    Needs two clean efforts whose durations differ at least ``CS_SPREAD``-fold
    (two points fix a line; a third gives a fit quality).
    """
    needed = {"near_max", "minutes", "seconds", "distance_m", "day", "source"}
    if efforts is None or efforts.empty or not needed <= set(efforts.columns):
        return None
    frame = efforts.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    anchor = pd.Timestamp(anchor) if anchor is not None else frame["day"].max()
    clean = frame["source"].isin(("block", "whole")) | (frame.get("kind", pd.Series(index=frame.index)) == "race")
    low, high = CS_MINUTES
    frame = frame[clean & frame["near_max"].fillna(False).astype(bool) & frame["minutes"].between(low, high)
                  & (frame["day"] <= anchor) & (frame["day"] > anchor - pd.Timedelta(days=days))]
    if frame.empty:
        return None
    # The best time per distance: a slower repeat of the same distance is not a maximum.
    bests = frame.sort_values("seconds").drop_duplicates("distance_m")
    if len(bests) < 2 or bests["seconds"].max() < CS_SPREAD * bests["seconds"].min():
        return None
    times = bests["seconds"].to_numpy(dtype=float)
    distances = bests["distance_m"].to_numpy(dtype=float)
    design = np.column_stack([times, np.ones_like(times)])
    (cs, d_prime), *_ = np.linalg.lstsq(design, distances, rcond=None)
    if cs <= 0 or d_prime < 0:
        return None
    r2 = None
    if len(bests) >= 3:
        predicted = design @ np.array([cs, d_prime])
        total = float(np.sum((distances - distances.mean()) ** 2))
        r2 = round(1 - float(np.sum((distances - predicted) ** 2)) / total, 3) if total > 0 else None
    return {"cs_ms": round(float(cs), 3), "pace": round(1000 / float(cs) / 60, 3), "d_prime_m": round(float(d_prime)),
            "efforts": int(len(bests)), "r2": r2, "days": [str(d.date()) for d in bests["day"]]}


def cap_threshold(paces: dict[str, tuple[float, float]], cs: dict[str, Any] | None) -> dict[str, tuple[float, float]]:
    """T no faster than critical speed: when the VDOT band's fast end is quicker
    than CS pace, the band moves back so that it starts at CS."""
    if not cs or "T" not in paces or cs.get("r2") is not None and cs["r2"] < 0.95:
        return paces
    fast, slow = paces["T"]
    if fast >= cs["pace"]:
        return paces
    shift = cs["pace"] - fast
    return {**paces, "T": (fast + shift, slow + shift)}
