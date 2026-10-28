"""Workout library: what a quality session or a strength session contains, and
how it progresses through a plan.

Every quality family is a ladder of rungs. The plan counts how many sessions
of a family it has already scheduled and takes the next rung; a lighter week
repeats the rung below, a taper week does the current rung shortened. A rung
never exceeds its family's cap, which follows the weekly volume:

* **threshold** (Daniels T pace) -- cruise intervals that lengthen into a
  continuous tempo run (5x4 min ... 2x15 min, 20 min continuous). Daniels:
  T work up to ~10% of the week's distance per session; the 20-minute steady
  tempo is his standard session at any volume, so it is the floor.
* **intervals** (I pace) -- reps of 2-5 min with an equal jog. Daniels: I work
  up to ~8% of the week and never above 10 km; 12 minutes is the floor.
* **hills** -- 60-90 s uphill by effort (no pace on a gradient), jog back down.
  The base-phase session: strength and running economy at a low impact cost.
* **race_pace** -- the specific block: the volume at race pace grows toward a
  continuous stretch (HM 3x2 km ... 8 km). Up to 20% of the week for HM / M
  (Daniels' M-pace ceiling), 10% / 8% for 10 / 5 km.
* **tempo** -- steady marathon-pace running (5 ... 14 km), the marathon base.

When the cap is lower than a rung, the rung keeps its rep length and drops
reps; when even its minimum number of reps does not fit, the rung below is
used. So a low-volume runner still progresses -- the reps get longer and the
rests shorter -- without the total running ahead of the volume.

Strength (Blagrove et al., Sports Med 2018; Llanos-Lagos et al., Sports Med
2024: heavy resistance and plyometric training improve running economy):
an adaptation stage first (moderate loads, 2-3x10-12), then heavy work
(3-4x4-6 at ~80-85% 1RM, 2-3 reps in reserve) with low-dose plyometrics,
one maintenance session a week in the peak, a light one in the taper and
none in the last week before an A race.
"""

from __future__ import annotations

import math
from typing import Any

# (reps, minutes per rep, recovery seconds)
THRESHOLD = [(5, 4, 60), (4, 6, 60), (3, 8, 90), (3, 10, 120), (2, 15, 120), (1, 20, 0)]
INTERVALS = [(6, 2, 120), (5, 3, 180), (6, 3, 150), (5, 4, 180), (4, 5, 180)]
# (reps, seconds uphill); the jog back down takes twice as long
HILLS = [(6, 60), (8, 60), (6, 90), (8, 90), (10, 90)]
# (reps, km per rep, recovery seconds)
RACE_PACE = {
    "5k": [(6, 0.6, 90), (5, 0.8, 120), (4, 1.0, 120), (3, 1.2, 150)],
    "10k": [(5, 1.0, 90), (4, 1.5, 90), (3, 2.0, 120), (2, 3.0, 120)],
    "hm": [(3, 2.0, 90), (3, 2.5, 90), (2, 4.0, 120), (3, 3.0, 90), (2, 5.0, 120), (1, 8.0, 0)],
    "m": [(1, 8.0, 0), (2, 6.0, 180), (1, 12.0, 0), (2, 8.0, 180), (1, 16.0, 0)],
}
TEMPO = [(1, 5.0, 0), (1, 6.0, 0), (1, 8.0, 0), (1, 10.0, 0), (1, 12.0, 0), (1, 14.0, 0)]

# The fewest reps a rung may be cut to before the rung below is used instead.
MIN_REPS = {"threshold": 1, "intervals": 3, "hills": 6, "race_pace": 1, "tempo": 1}
HILL_CAP_S = 15 * 60
# The weekly share and floor of each family's work: (share of the week, floor).
CAPS = {
    "threshold": (0.10, 20.0),  # minutes at T
    "intervals": (0.08, 12.0),  # minutes at I, never above 10 km
    "race_pace": {"5k": (0.08, 4.0), "10k": (0.10, 5.0), "hm": (0.20, 6.0), "m": (0.20, 8.0)},  # km
    "tempo": (0.20, 5.0),  # km
}
TAPER_FACTOR = 0.6
WARMUP_KM, COOLDOWN_KM = 2.0, 1.5

# Which session type a family is recorded as (plan matching and the hard-day rules read it).
RACE_PACE_TYPE = {"5k": "intervals", "10k": "threshold", "hm": "tempo", "m": "tempo"}
# The heart-rate band of race-pace work (physio.HR_FRACTIONS key).
RACE_PACE_HR = {"5k": "I", "10k": "T", "hm": "T", "m": "M"}

# The quality rotation: per distance and phase, slot A (the one quality day of a
# 3-4 day week) and slot B (the second one, 5+ days and enough volume). Each
# week takes the next family of its slot, so a one-quality week still sees
# every kind of work the phase calls for.
ROTATION = {
    "5k": {"base": (["hills", "threshold"], ["threshold"]),
           "build": (["intervals", "threshold"], ["threshold", "hills"]),
           "peak": (["intervals", "race_pace"], ["threshold"])},
    "10k": {"base": (["hills", "threshold"], ["threshold"]),
            "build": (["threshold", "intervals"], ["intervals", "threshold"]),
            "peak": (["race_pace", "intervals"], ["threshold"])},
    "hm": {"base": (["hills", "threshold"], ["threshold"]),
           "build": (["threshold", "threshold", "intervals"], ["intervals"]),
           "peak": (["race_pace", "threshold"], ["threshold"])},
    "m": {"base": (["hills", "tempo"], ["threshold"]),
          "build": (["threshold", "tempo"], ["tempo"]),
          "peak": (["race_pace", "threshold"], ["threshold"])},
}

STRIDES = (6, 20, 60)  # reps, seconds fast, seconds easy

# Race week (Bosquet et al. 2007, Mujika: keep the intensity, cut the volume): one
# short race-pace session 4-6 days out, so the legs keep the rhythm. (reps, km, rest s)
SHARPENER = {"5k": (4, 0.4, 90), "10k": (4, 0.8, 90), "hm": (3, 1.0, 90), "m": (2, 2.0, 120)}
SHARPEN_DAYS = (4, 6)


def family_type(family: str, distance: str) -> str:
    return RACE_PACE_TYPE[distance] if family == "race_pace" else {"hills": "intervals"}.get(family, family)


def rotation(distance: str, phase: str, slot: int) -> list[str]:
    if phase in ("taper", "race"):
        return ["race_pace"]
    slots = ROTATION[distance][phase if phase in ("base", "build", "peak") else "peak"]
    return slots[min(slot, len(slots) - 1)]


def ladder(family: str, distance: str) -> list[tuple]:
    return {"threshold": THRESHOLD, "intervals": INTERVALS, "hills": HILLS, "tempo": TEMPO}.get(family) \
        or RACE_PACE[distance]


def _mid(band: tuple[float, float] | None, default: float) -> float:
    return (band[0] + band[1]) / 2 if band else default


def _rep_km(minutes: float, pace: float) -> float:
    km = minutes / pace
    step = 0.1 if km < 0.5 else 0.2
    return round(round(km / step) * step, 1)


def cap(family: str, distance: str, weekly_km: float, paces: dict[str, tuple[float, float]]) -> float:
    """The most work one session of ``family`` may hold this week (minutes or km, as the ladder counts)."""
    if family == "hills":
        return HILL_CAP_S
    share, floor = CAPS["race_pace"][distance] if family == "race_pace" else CAPS[family]
    if family == "threshold":
        return max(floor, share * weekly_km * _mid(paces.get("T"), 5.0))
    if family == "intervals":
        return max(floor, min(share * weekly_km, 10.0) * _mid(paces.get("I"), 4.5))
    return max(floor, share * weekly_km)


def fit(family: str, distance: str, level: int, limit: float) -> tuple[int, int, tuple]:
    """The rung for ``level`` cut to ``limit``: (rung index used, reps, rung)."""
    rungs = ladder(family, distance)
    level = max(0, min(level, len(rungs) - 1))
    for index in range(level, -1, -1):
        rung = rungs[index]
        reps = min(rung[0], math.floor(limit / rung[1] + 1e-9))
        if reps >= min(MIN_REPS[family], rung[0]):
            return index, reps, rung
    rung = rungs[0]
    return 0, max(1, math.floor(limit / rung[1] + 1e-9)), rung


def quality(family: str, level: int, weekly_km: float, distance: str, paces: dict[str, tuple[float, float]],
            race_pace: float | None, factor: float = 1.0) -> dict[str, Any]:
    """One quality session: ``type``, ``text`` code, ``steps`` and its pace band.

    ``factor`` < 1 shortens the session (taper) below the family's floor.
    """
    easy = paces.get("E")
    limit = cap(family, distance, weekly_km, paces) * factor
    used, reps, rung = fit(family, distance, level, limit)
    warmup, cooldown = _step("warmup", km=WARMUP_KM, pace=easy), _step("cooldown", km=COOLDOWN_KM, pace=easy)
    spec: dict[str, Any] = {"key": family, "level": used, "reps": int(reps)}
    if family == "hills":
        uphill = rung[1]
        spec.update(s=int(uphill))
        steps = [warmup, _repeat(reps, _step("run", s=uphill), _step("recovery", s=2 * uphill)), cooldown]
        return {"type": "intervals", "text": spec, "steps": steps, "band": None, "intensity": "I"}
    if family in ("threshold", "intervals"):
        intensity = "T" if family == "threshold" else "I"
        band = paces.get(intensity)
        rep = _rep_km(rung[1], _mid(band, 5.0))
        rest = rung[2]
    else:
        intensity = "M" if family == "tempo" else RACE_PACE_HR[distance]
        band = paces.get("M") if family == "tempo" else \
            ((race_pace * 0.99, race_pace * 1.01) if race_pace else paces.get("M"))
        rep, rest = rung[1], rung[2]
        spec["distance"] = distance
    spec.update(rep=float(rep), rest=int(rest))
    work = [_step("run", km=rep, pace=band)]
    if reps == 1:
        main = work
    else:
        main = [_repeat(reps, *work, _step("recovery", s=rest))]
    return {"type": family_type(family, distance), "text": spec, "steps": [warmup, *main, cooldown],
            "band": band, "intensity": intensity}


def sharpener(distance: str, paces: dict[str, tuple[float, float]], race_pace: float | None) -> dict[str, Any]:
    """The race week's one quality session: a few short reps at race pace."""
    reps, rep, rest = SHARPENER[distance]
    band = (race_pace * 0.99, race_pace * 1.01) if race_pace else paces.get("T")
    easy = paces.get("E")
    steps = [_step("warmup", km=WARMUP_KM, pace=easy),
             _repeat(reps, _step("run", km=rep, pace=band), _step("recovery", s=rest)),
             _step("cooldown", km=COOLDOWN_KM, pace=easy)]
    spec = {"key": "race_pace", "sharpen": True, "reps": reps, "rep": rep, "rest": rest, "distance": distance}
    return {"type": family_type("race_pace", distance), "text": spec, "steps": steps, "band": band,
            "intensity": RACE_PACE_HR[distance]}


def strides(paces: dict[str, tuple[float, float]], reps: int | None = None) -> dict[str, Any]:
    default, fast, easy = STRIDES
    reps = reps or default
    return _repeat(reps, _step("run", s=fast, pace=paces.get("R")), _step("recovery", s=easy))


# --------------------------------------------------------------------------
# strength

STAGES = ("adapt", "strength", "maintain", "light")
ADAPT_SESSIONS = 6  # sessions of moderate loads before heavy work
DURATION_MIN = {"adapt": 35, "strength": 45, "maintain": 30, "light": 25}
PER_WEEK = {"base": 2, "build": 2, "peak": 1, "taper": 1, "race": 0}
# No strength this many days before a race (heavy legs for 2-3 days after).
BEFORE_RACE_DAYS = {"A": 8, "B": 4, "C": 4}


def strength_stage(phase: str, done: int, recovery: bool) -> str:
    if phase == "taper" or recovery:
        return "light"
    if done < ADAPT_SESSIONS:
        return "adapt"
    return "maintain" if phase == "peak" else "strength"


def strength(stage: str, number: int) -> dict[str, Any]:
    return {"type": "strength", "text": {"key": "strength", "stage": stage, "n": int(number)},
            "duration_min": DURATION_MIN[stage]}


# --------------------------------------------------------------------------
# steps (the same shape as plan._step / plan._repeat; kept here so the
# library has no import cycle with plan.py)


def _step(kind: str, *, km: float | None = None, s: float | None = None,
          pace: tuple[float, float] | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"kind": kind}
    if km is not None:
        step["km"] = round(float(km), 2)
    if s is not None:
        step["s"] = int(round(s))
    if pace:
        step["pace"] = [round(float(pace[0]), 3), round(float(pace[1]), 3)]
    return step


def _repeat(reps: int, *steps: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "repeat", "reps": int(reps), "steps": list(steps)}
