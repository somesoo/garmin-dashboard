"""Training-plan generator, plan-vs-actual matching and re-planning.

Principles the generator follows (and the page states):

* **Start from what was actually run.** The first week is anchored on the mean
  of the last four weeks, not on the volume the goal "needs".
* **Volume grows by absolute steps toward a distance-specific peak** (at
  most ``MAX_STEP_KM`` a week), so no week jumps because a percentage
  compounds.
* **No single run is more than 10% longer than the longest run of the 30
  days before it**, real or planned (Garmin-RUNSAFE: Frandsen et al., BJSM
  2025 -- single-session spikes over 10% raised overuse injury risk, the
  week-to-week ratio did not). This replaced the 1.3x acute:chronic cap;
  ACWR stays a number to look at, not a rule.
* **Every third or fourth week is lighter** (every third when the recent
  record is irregular, i.e. tolerance is unproven), and the taper scales with
  the distance (1 / 1 / 2 / 3 weeks).
* **Hard days never touch.** Long run on the chosen day; quality sessions on
  the days furthest from it and from each other. When the available days make
  that impossible, the plan schedules fewer quality sessions, not adjacent
  ones.
* **Quality progresses** (``running/library.py``): each family is a ladder
  (cruise intervals lengthen into a tempo run, race-pace work extends),
  capped by the week's volume; one quality day a week rotates through the
  phase's families, a lighter week repeats the rung below.
* **Strength twice a week** in base and build, once in the peak and taper,
  on the quality day after the run or an easy day -- never the day before a
  hard one, none in the last week before an A race.
* **Paces come from current fitness** (VDOT now), not from the goal. The
  goal pace appears only in race-specific segments, and only when the goal is
  within reach of the forecast. Re-planning recalculates paces from the latest
  data, which is how the plan follows real progress.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

import i18n
from running import library, physio, store, text, units, workouts
from running.sessions import HARD_KINDS

PEAK_KM = {"5k": 32.0, "10k": 42.0, "hm": 50.0, "m": 65.0}
LONG_TARGET_KM = {"5k": 10.0, "10k": 14.0, "hm": 19.0, "m": 32.0}
# Weeks of reduced volume *including* the race week: a marathon gets two
# taper weeks plus race week, a 5 / 10 km only a lighter race week.
TAPER_WEEKS = {"5k": 1, "10k": 1, "hm": 2, "m": 3}
MAX_STEP_KM = 6.0
LONG_STEP_KM = {"5k": 1.0, "10k": 1.5, "hm": 1.5, "m": 2.0}
HARD_TYPES = ("tempo", "threshold", "intervals", "race", "long")
QUALITY_TYPES = ("tempo", "threshold", "intervals")
RUN_TYPES = ("recovery", "easy", "long", "tempo", "threshold", "intervals", "race")
# Garmin-RUNSAFE: a run longer than 1.1x the longest of the last 30 days is a spike.
SPIKE = 1.10
SPIKE_DAYS = 30
SPIKE_FLOOR_KM = 3.0
# Two A races closer than this share one build: the plan asks which one is the goal.
A_RACE_GAP_WEEKS = 8
# The week ahead follows the body's response (``response``): HRV against its own
# 60-day baseline with the smallest worthwhile change of 0.5 SD (Plews et al.
# 2013; HRV-guided training: Kiviniemi 2007, Javaloyes 2019), resting HR up
# >= 3 bpm (beyond its day-to-day noise, Buchheit 2014), and how much of the
# last two weeks was run.
HRV_SWC = 0.5
HRV_BASE_DAYS = 60
RHR_RISE_BPM = 3.0
DONE_SHARE = 0.7


@dataclass
class PlanRequest:
    distance: str
    race_date: dt.date
    goal_s: float | None = None
    run_days: list[int] = field(default_factory=lambda: [1, 3, 5, 6])  # Mon=0
    long_day: int = 6
    start: dt.date | None = None
    max_weekly_km: float | None = None
    race_id: str | None = None
    name: str | None = None
    priority: str = "A"

    def validate(self) -> list[str]:
        tr = i18n.tr
        errors = []
        if self.distance not in units.RACES:
            errors.append(tr(pl="Nieznany dystans.", en="Unknown distance."))
        days = sorted(set(self.run_days))
        if not 2 <= len(days) <= 7:
            errors.append(tr(pl="Wybierz od 2 do 7 dni biegowych w tygodniu.", en="Pick 2 to 7 running days a week."))
        if any(d < 0 or d > 6 for d in days):
            errors.append(tr(pl="Dni tygodnia to 0–6.", en="Weekdays are 0–6."))
        start = self.start or dt.date.today()
        if self.race_date <= start:
            errors.append(tr(pl="Data zawodów musi być w przyszłości.", en="The race date must be in the future."))
        if self.goal_s is not None and self.goal_s <= 0:
            errors.append(tr(pl="Cel czasowy musi być dodatni.", en="The time goal must be positive."))
        return errors


@dataclass
class PlanSettings:
    """What holds for the whole plan, whatever the goals."""

    run_days: list[int] = field(default_factory=lambda: [1, 3, 5, 6])  # Mon=0
    long_day: int = 6
    start: dt.date | None = None
    max_weekly_km: float | None = None
    strength: bool = True


# --------------------------------------------------------------------------
# baseline from the data


def baseline(runs: pd.DataFrame, anchor: pd.Timestamp, vdot: float | None) -> dict[str, Any]:
    """What the runner has actually been doing, measured at ``anchor``."""
    weeks = []
    for index in range(8):
        end = anchor - pd.Timedelta(days=7 * index)
        mask = (runs["day"] <= end) & (runs["day"] > end - pd.Timedelta(days=7)) if not runs.empty else []
        frame = runs[mask] if len(runs) else runs
        weeks.append(
            {
                "km": float(frame["distance_km"].sum()) if len(frame) else 0.0,
                "runs": int(len(frame)),
                "hard": int(frame["kind"].isin(HARD_KINDS).sum()) if len(frame) and "kind" in frame else 0,
            }
        )
    recent = runs[(runs["day"] <= anchor) & (runs["day"] > anchor - pd.Timedelta(days=42))] if len(runs) else runs
    last4 = weeks[:4]
    return {
        "anchor": str(pd.Timestamp(anchor).date()),
        "weekly_km_4w": round(sum(w["km"] for w in last4) / 4, 1),
        "weekly_km_8w": round(sum(w["km"] for w in weeks) / 8, 1),
        "weekly_km_last": round(weeks[0]["km"], 1),
        "max_week_km_8w": round(max(w["km"] for w in weeks), 1),
        "runs_per_week_4w": round(sum(w["runs"] for w in last4) / 4, 1),
        "hard_per_week_4w": round(sum(w["hard"] for w in last4) / 4, 1),
        "long_km_6w": round(float(recent["distance_km"].max()), 1) if len(recent) else 0.0,
        "consistency_8w": round(sum(w["runs"] >= 2 for w in weeks) / 8, 2),
        "vdot": None if vdot is None else round(float(vdot), 1),
        "history_km": [round(w["km"], 1) for w in reversed(weeks)],
    }


# --------------------------------------------------------------------------
# week skeleton


def _weeks(request: PlanRequest, start: dt.date, offset: int = 0) -> list[dict[str, Any]]:
    """Monday-based weeks from the start week to the race week, with phases
    (numbered from ``offset + 1``: a block after an earlier race)."""
    first_monday = start - dt.timedelta(days=start.weekday())
    race_monday = request.race_date - dt.timedelta(days=request.race_date.weekday())
    count = (race_monday - first_monday).days // 7 + 1
    full = TAPER_WEEKS[request.distance] if request.priority == "A" else 1
    taper = min(full, max(0, count - 1))
    out = []
    for index in range(count):
        from_end = count - 1 - index
        if from_end == 0:
            phase = "race"
        elif from_end < taper:
            phase = "taper"
        else:
            build_total = count - 1 - taper
            position = index / max(1, build_total)
            phase = "base" if build_total >= 8 and position < 0.34 else ("peak" if position >= 0.67 else "build")
        out.append({"week": offset + index + 1, "monday": first_monday + dt.timedelta(days=7 * index), "phase": phase})
    return out


def response(daily: pd.DataFrame | None, today: dt.date, done: dict[str, Any] | None = None) -> dict[str, Any]:
    """How the body is taking the training, for the week ahead.

    ``grow`` -- as planned; ``hold`` -- one signal: no step up this week;
    ``lighter`` -- two or more: this week becomes the lighter one. ``done`` is
    ``compliance`` of the last two weeks (None for a new plan).
    """
    signals: list[dict[str, Any]] = []
    if daily is not None and not daily.empty and "hrv_last_night" in daily:
        frame = daily[["day", *(c for c in ("hrv_last_night", "rhr") if c in daily)]].copy()
        frame["day"] = pd.to_datetime(frame["day"])
        end = pd.Timestamp(today)
        recent = frame[(frame["day"] > end - pd.Timedelta(days=7)) & (frame["day"] <= end)]
        base = frame[(frame["day"] > end - pd.Timedelta(days=7 + HRV_BASE_DAYS))
                     & (frame["day"] <= end - pd.Timedelta(days=7))]
        hrv_now = np.log(recent["hrv_last_night"].dropna().clip(lower=1))
        hrv_base = np.log(base["hrv_last_night"].dropna().clip(lower=1))
        if len(hrv_now) >= 4 and len(hrv_base) >= 20:
            floor = hrv_base.mean() - HRV_SWC * hrv_base.std()
            if hrv_now.mean() < floor:
                signals.append({"key": "hrv_low", "now": round(float(np.exp(hrv_now.mean())), 1),
                                "base": round(float(np.exp(hrv_base.mean())), 1),
                                "floor": round(float(np.exp(floor)), 1)})
        if "rhr" in frame:
            rhr_now, rhr_base = recent["rhr"].dropna(), base["rhr"].dropna()
            if len(rhr_now) >= 4 and len(rhr_base) >= 20 and rhr_now.mean() - rhr_base.mean() >= RHR_RISE_BPM:
                signals.append({"key": "rhr_up", "now": round(float(rhr_now.mean()), 1),
                                "base": round(float(rhr_base.mean()), 1)})
    if done and done.get("due", 0) >= 3 and done.get("km_ratio") is not None and done["km_ratio"] < DONE_SHARE:
        signals.append({"key": "not_run", "ratio": done["km_ratio"], "actual": done["actual_km"],
                        "planned": done["planned_km"]})
    decision = "lighter" if len(signals) >= 2 else "hold" if signals else "grow"
    return {"decision": decision, "signals": signals, "day": today.isoformat()}


def _volumes(weeks: list[dict[str, Any]], base: dict[str, Any], request: PlanRequest,
             adapt: dict[str, Any] | None = None) -> None:
    """Fill ``volume_km`` / ``long_km`` / ``recovery`` per week, in place.

    ``adapt`` (``response``) changes the first build week: ``hold`` keeps the
    next week at the starting volume, ``lighter`` makes the first week the
    lighter one and restarts the 3-4 week cycle after it.
    """
    decision = (adapt or {}).get("decision", "grow")
    days = len(set(request.run_days))
    start_km = max(base["weekly_km_4w"], 0.8 * base["weekly_km_8w"], 3.0 * days)
    peak_cap = PEAK_KM[request.distance] * (0.8 if days <= 3 else 1.0)
    if request.max_weekly_km:
        peak_cap = min(peak_cap, float(request.max_weekly_km))
    peak = max(start_km, peak_cap)
    cycle = 3 if base["consistency_8w"] < 0.5 else 4

    build = [w for w in weeks if w["phase"] in ("base", "build", "peak")]
    steps = max(1, sum(1 for i, _ in enumerate(build) if (i + 1) % cycle != 0))
    step = min(MAX_STEP_KM, max(0.0, (peak - start_km) / steps))

    long_now = max(base["long_km_6w"], 5.0)
    long_target = LONG_TARGET_KM[request.distance]
    long_share = 0.5 if days <= 3 else 0.42 if request.distance != "m" else 0.5
    last_build = start_km
    last_long = long_now
    shift = 1 if decision == "lighter" else 0
    for index, week in enumerate(weeks):
        if week["phase"] in ("base", "build", "peak"):
            position = build.index(week)
            recovery = (position - shift + 1) % cycle == 0 and position != len(build) - 1 and position >= shift
            if position == 0 and decision == "lighter" and not base.get("after_race"):
                volume, long_km = 0.75 * start_km, 0.75 * long_now
                recovery = True
                week["adapt"] = decision
            elif position == 1 and decision == "hold":
                # One signal against: the step up waits a week.
                volume, long_km = last_build, last_long
                week["adapt"] = decision
            elif position == 0 and base.get("after_race"):
                # The week after a goal race: recover before building again.
                volume, long_km = 0.7 * start_km, 0.7 * long_now
                recovery = True
            elif recovery:
                volume = 0.75 * last_build
                long_km = 0.75 * last_long
            else:
                volume = min(last_build + step if position else start_km, peak)
                long_km = min(last_long + (LONG_STEP_KM[request.distance] if position else 0), long_target)
                last_build = volume
                last_long = long_km
            week["recovery"] = recovery
        elif week["phase"] == "taper":
            to_race = len(weeks) - 1 - index
            factor = {1: 0.7, 2: 0.82, 3: 0.9}.get(to_race, 0.85)
            volume, long_km = last_build * factor, last_long * (factor - 0.1)
            week["recovery"] = False
        else:  # race week: volume before the race, the race itself is extra
            volume, long_km = last_build * (0.45 if request.priority == "A" else 0.6), 0.0
            week["recovery"] = False
        long_km = min(long_km, volume * long_share) if long_km else 0.0
        week["volume_km"] = round(volume, 1)
        week["long_km"] = round(long_km, 1)


# --------------------------------------------------------------------------
# days and sessions


def _circular_gap(a: int, b: int) -> int:
    diff = abs(a - b) % 7
    return min(diff, 7 - diff)


def place_hard_days(run_days: list[int], long_day: int, count: int) -> list[int]:
    """Quality days as far as possible from the long run and each other.

    Requires at least one non-hard day between hard days (gap >= 2, counted
    across the week boundary too). Returns fewer days than asked rather than
    break that rule.
    """
    hard = [long_day]
    chosen: list[int] = []
    candidates = [d for d in sorted(set(run_days)) if d != long_day]
    for _ in range(count):
        scored = [(min(_circular_gap(c, h) for h in hard), -c, c) for c in candidates if c not in chosen]
        scored = [s for s in scored if s[0] >= 2]
        if not scored:
            break
        best = max(scored)[2]
        chosen.append(best)
        hard.append(best)
    return sorted(chosen)


def _step(kind: str, *, km: float | None = None, s: float | None = None,
          pace: tuple[float, float] | None = None) -> dict[str, Any]:
    """One workout step: a distance or a time, optionally a pace band (min/km)."""
    return library._step(kind, km=km, s=s, pace=pace)


def _repeat(reps: int, *steps: dict[str, Any]) -> dict[str, Any]:
    return library._repeat(reps, *steps)


def steps_km(steps: list[dict[str, Any]], easy_pace: float = 6.5) -> float:
    """Distance a step list covers; timed steps are converted at ``easy_pace``."""
    total = 0.0
    for step in steps or []:
        if step["kind"] == "repeat":
            total += step["reps"] * steps_km(step["steps"], easy_pace)
        elif "km" in step:
            total += step["km"]
        elif "s" in step:
            pace = sum(step["pace"]) / 2 if step.get("pace") else easy_pace
            total += step["s"] / 60 / pace
    return round(total, 2)


def steps_minutes(steps: list[dict[str, Any]], easy_pace: float = 6.5) -> float:
    """Time a step list takes; distance steps at the middle of their band (or ``easy_pace``)."""
    total = 0.0
    for step in steps or []:
        if step["kind"] == "repeat":
            total += step["reps"] * steps_minutes(step["steps"], easy_pace)
        elif "s" in step:
            total += step["s"] / 60
        elif "km" in step:
            total += step["km"] * (sum(step["pace"]) / 2 if step.get("pace") else easy_pace)
    return total


def _hr_target(zones: dict[str, Any] | None, name: str) -> list[int] | None:
    """The watch target of an easy run: its heart-rate zone, when the zones come
    from a measured threshold heart rate (``physio.hr_zones``)."""
    band = (zones or {}).get(name)
    return [int(band[0]), int(band[1])] if band and (zones or {}).get("basis") == "lthr" else None


def _target(step: dict[str, Any], hr: list[int] | None) -> dict[str, Any]:
    """Easy running is steered by heart rate, not pace: pace from a short test
    runs ahead of aerobic fitness, so on easy days the watch watches the pulse."""
    if hr:
        step.pop("pace", None)
        step["hr"] = list(hr)
    return step


def _easy_steps(km: float, band: tuple[float, float] | None, paces: dict[str, tuple[float, float]],
                strides: bool, hr: list[int] | None = None) -> list[dict[str, Any]]:
    """An easy run; with ``strides`` the last part is 6x20 s fast, inside the same distance."""
    if not strides:
        return [_target(_step("run", km=km, pace=band), hr)]
    block = library.strides(paces, 4 if km < 5 else None)  # a short run keeps most of its distance easy
    extra = steps_km([block], sum(band) / 2 if band else 6.5)
    return [_target(_step("run", km=max(1.0, km - extra), pace=band), hr), block]


def _session(
    kind: str,
    date: dt.date,
    week: dict[str, Any],
    km: float,
    paces: dict[str, tuple[float, float]],
    zones: dict[str, Any],
    distance: str,
    race_pace: float | None,
    workout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One session: type, distance, pace and HR band, workout steps, and the
    ``text`` code its title, main set and purpose are written from (text.py).

    Quality sessions come from ``workout`` (``library.quality``); without it
    the family's first rung is used. ``strength`` takes ``workout`` from
    ``library.strength``.
    """
    easy = paces.get("E")
    easy_mid = sum(easy) / 2 if easy else 6.5
    hr_easy = physio.zone_text(zones, "E")
    session: dict[str, Any] = {
        "id": store.new_id("s"),
        "date": date.isoformat(),
        "week": week["week"],
        "phase": week["phase"],
        "type": kind,
        "status": "planned",
        "actual_activity_id": None,
        "note": "",
    }
    km = round(max(0.0, km), 1)
    if kind in ("easy", "recovery"):
        band = (easy[0], easy[1]) if kind == "easy" else (easy[1], easy[1] * 1.06) if easy else None
        strides = kind == "easy" and week["phase"] in ("base", "build", "peak") and km >= 3 \
            and not week.get("recovery")
        session.update(
            text={"key": kind, **({"strides": strides} if kind == "easy" else {})},
            distance_km=km,
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=hr_easy if kind == "easy" else physio.zone_text(zones, "recovery"),
            steps=_easy_steps(km, band, paces, strides, _hr_target(zones, "E" if kind == "easy" else "recovery")),
        )
    elif kind == "long":
        spec: dict[str, Any] = {"key": "long"}
        target = _hr_target(zones, "E")
        steps = [_target(_step("run", km=km, pace=easy), target)]
        if race_pace and week["phase"] == "peak" and distance in ("hm", "m"):
            part = min(round(km * (0.35 if distance == "m" else 0.3)), 14 if distance == "m" else 8)
            steps = [_target(_step("run", km=km - part, pace=easy), target),
                     _step("run", km=part, pace=(race_pace * 0.99, race_pace * 1.01))]
            spec.update(part=float(part), race_pace=round(sum(steps[-1]["pace"]) / 2, 3))
        session.update(
            text=spec,
            distance_km=km,
            pace_lo=easy[0] if easy else None,
            pace_hi=easy[1] if easy else None,
            hr=hr_easy,
            steps=steps,
        )
    elif kind in QUALITY_TYPES:
        workout = workout or library.quality(kind, 0, week["volume_km"], distance, paces, race_pace)
        band = workout["band"]
        session.update(
            type=workout["type"],
            text=workout["text"],
            distance_km=round(steps_km(workout["steps"], easy_mid), 1),
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=physio.zone_text(zones, workout["intensity"]),
            steps=workout["steps"],
        )
    elif kind == "strength":
        workout = workout or library.strength("adapt", 1)
        session.update(type="strength", text=workout["text"], distance_km=0.0, pace_lo=None, pace_hi=None,
                       hr=None, steps=[], duration_min=workout["duration_min"])
    elif kind == "race":
        session.update(
            text={"key": "race", "distance": distance},
            distance_km=units.RACES[distance],
            pace_lo=race_pace * 0.99 if race_pace else None,
            pace_hi=race_pace * 1.01 if race_pace else None,
            hr="—",
            steps=[_step("warmup", s=600 if distance in ("5k", "10k") else 420),
                   _step("run", km=units.RACES[distance],
                         pace=(race_pace * 0.99, race_pace * 1.01) if race_pace else None)],
        )
    if kind != "strength":
        session["duration_min"] = round(steps_minutes(session["steps"], easy_mid)) if session.get("distance_km") \
            else None
    session.update(text.session_text(session))
    return session


def generate(
    request: PlanRequest,
    runs: pd.DataFrame,
    result: dict[str, Any],
    *,
    anchor: pd.Timestamp | None = None,
    keep: list[dict[str, Any]] | None = None,
    strength_history: int = 0,
) -> dict[str, Any]:
    """A plan toward one race (``generate_goals`` with a single goal)."""
    errors = request.validate()
    if errors:
        raise ValueError(" ".join(errors))
    settings = PlanSettings(run_days=list(request.run_days), long_day=request.long_day, start=request.start,
                            max_weekly_km=request.max_weekly_km)
    goal = {"race_id": request.race_id, "name": request.name, "distance": request.distance,
            "date": request.race_date.isoformat(), "goal_s": request.goal_s, "priority": request.priority}
    plan = generate_goals(settings, [goal], runs, result, anchor=anchor, keep=keep,
                          strength_history=strength_history)
    if request.name:
        plan["name"] = request.name
    return plan


def goal_of(race: dict[str, Any]) -> dict[str, Any]:
    """The part of a saved race the plan depends on."""
    return {"race_id": race.get("id"), "name": race.get("name"), "distance": race["distance"], "date": race["date"],
            "goal_s": race.get("goal_s"), "priority": race.get("priority", "A")}


def plan_goals(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The goals a plan was built for (a plan from before goals: its one race)."""
    if plan.get("goals"):
        return list(plan["goals"])
    request = plan.get("request", {})
    if not request.get("race_date"):
        return []
    return [{"race_id": plan.get("race_id") or request.get("race_id"), "name": request.get("name"),
             "distance": request.get("distance"), "date": request["race_date"], "goal_s": request.get("goal_s"),
             "priority": request.get("priority", "A")}]


def _signature(goals: list[dict[str, Any]], today: dt.date) -> list[tuple]:
    return sorted((g.get("race_id"), g["date"], g["distance"], g.get("goal_s"), g.get("priority", "A"))
                  for g in goals if g["date"] > today.isoformat())


def stale(plan: dict[str, Any], races: list[dict[str, Any]], today: dt.date | None = None) -> bool:
    """True when the races ahead are not the goals the plan was built for."""
    today = today or dt.date.today()
    return _signature(plan_goals(plan), today) != _signature([goal_of(r) for r in races], today)


def next_goal(plan: dict[str, Any] | None, today: dt.date | None = None) -> dict[str, Any] | None:
    """The plan's nearest goal from ``today`` on."""
    if plan is None:
        return None
    today = today or dt.date.today()
    ahead = [g for g in plan_goals(plan) if g["date"] >= today.isoformat()]
    return min(ahead, key=lambda g: g["date"]) if ahead else None


def covers(plan: dict[str, Any] | None, race: dict[str, Any]) -> bool:
    return plan is not None and any(g.get("race_id") == race.get("id") for g in plan_goals(plan))


def race_outlook(item: Any, race: dict[str, Any], plan: dict[str, Any] | None, base: dict[str, Any],
                 today: dt.date) -> Any:
    """The distance forecast with this race's target: after the plan when the
    plan covers the race, otherwise what continuing the current training gives."""
    from running import forecast

    weeks = (dt.date.fromisoformat(race["date"]) - today).days / 7
    if covers(plan, race):
        return forecast.target(item, weeks, reached_prep(plan, race["distance"], race["date"]))
    return forecast.steady(item, weeks, base.get("consistency_8w", 0.0))


def generate_goals(
    settings: PlanSettings,
    goals: list[dict[str, Any]],
    runs: pd.DataFrame,
    result: dict[str, Any],
    *,
    anchor: pd.Timestamp | None = None,
    keep: list[dict[str, Any]] | None = None,
    strength_history: int = 0,
    done_as_planned: dict[str, dict[str, Any]] | None = None,
    adapt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one plan (store.validate_plan-compatible) through every goal ahead.

    Each race gets its own block: built from where the previous one ended,
    tapered by the race's priority (A: the distance's taper, B/C: a lighter
    race week only), and after an A race or a half / full marathon the next
    block opens with a recovery week. ``result`` is a ``forecast.forecast``
    output; ``keep`` holds sessions that already happened (kept unchanged);
    ``strength_history`` is the number of strength sessions done recently
    (``strength_done``), which decides when heavy work starts;
    ``done_as_planned`` (``outcomes``) decides which past sessions move the
    ladders up; ``adapt`` (``response``) sets the first block's next week.
    """
    tr = i18n.tr
    if result.get("status") != "ok":
        raise ValueError(tr(pl="Brak prognozy formy — plan potrzebuje co najmniej jednego mierzalnego biegu. ",
                            en="No fitness forecast — the plan needs at least one measurable run. ")
                         + str(result.get("reason", "")))
    anchor = anchor if anchor is not None else (runs["day"].max() if not runs.empty else pd.Timestamp.today())
    start = settings.start or (dt.date.today() + dt.timedelta(days=1))
    goals = sorted((g for g in goals if g["date"] >= start.isoformat()), key=lambda g: g["date"])
    if not goals:
        raise ValueError(tr(pl="Brak startów przed nami — dodaj cel na stronie Zawody.",
                            en="No races ahead — add a goal on the Races page."))
    vdot = float(result["vdot"])
    lthr = result.get("lthr")
    zones = physio.hr_zones(result.get("hr_max"), (lthr or {}).get("bpm"))
    # T never faster than critical speed when clean efforts give one (physio.cap_threshold).
    paces = physio.cap_threshold(physio.training_paces(vdot), result.get("cs"))
    base0 = baseline(runs, pd.Timestamp(anchor), vdot)
    warnings: list[dict[str, Any]] = []
    if base0["weekly_km_4w"] < 5:
        warnings.append({"key": "no_running"})
    a_races = [g for g in goals if g.get("priority", "A") == "A"]
    for first, second in zip(a_races, a_races[1:]):
        gap = (dt.date.fromisoformat(second["date"]) - dt.date.fromisoformat(first["date"])).days / 7
        if gap < A_RACE_GAP_WEEKS:
            # Two peaks this close leave the second block a recovery week, one build week and a taper.
            warnings.append({"key": "close_a_races", "first": first.get("name") or first["date"],
                             "second": second.get("name") or second["date"], "weeks": round(gap, 1)})
    kept_dates = {s["date"] for s in keep or []}
    done = already_run(runs, start)
    progress = _progress(keep or [], strength_history, settings.strength, done_as_planned)
    progress["adapt"] = adapt

    weeks: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    base, block_start = base0, start
    last_race: dict[str, Any] | None = None
    for index, goal in enumerate(goals):
        request = PlanRequest(
            distance=goal["distance"], race_date=dt.date.fromisoformat(goal["date"]), goal_s=goal.get("goal_s"),
            run_days=list(settings.run_days), long_day=settings.long_day, start=block_start,
            max_weekly_km=settings.max_weekly_km, race_id=goal.get("race_id"), name=goal.get("name"),
            priority=goal.get("priority", "A"),
        )
        item = result["distances"].get(request.distance)
        race_pace = _race_pace(request, item, warnings, len(goals) > 1)
        if request.race_date < block_start:
            # Two races in one week: the later one goes into the week already built.
            week = next((w for w in weeks if w["monday"] <= request.race_date < w["monday"] + dt.timedelta(days=7)),
                        None)
            if week is not None and goal["date"] not in kept_dates:
                sessions.append({**_session("race", request.race_date, week, 0.0, paces, zones, request.distance,
                                            race_pace), "race_id": request.race_id})
            continue
        errors = request.validate()
        if errors:
            raise ValueError(" ".join(errors))
        block = _weeks(request, block_start, offset=len(weeks))
        if index == 0 and len(block) < 3:
            warnings.append({"key": "short"})
        _volumes(block, base, request, adapt if index == 0 else None)
        sessions.extend(_block_sessions(block, request, settings, base, paces, zones, race_pace, kept_dates,
                                        done if index == 0 else None, last_race, progress))
        last_race = goal
        weeks.extend(block)
        base = _carried(base0, weeks, goal)
        race_monday = request.race_date - dt.timedelta(days=request.race_date.weekday())
        block_start = max(block_start, race_monday + dt.timedelta(days=7))

    _cap_spikes(sessions, runs, start, paces, weeks)
    sessions = sorted((keep or []) + sessions, key=lambda s: (s["date"], s["type"] == "strength"))
    first, last = goals[0], goals[-1]
    item = result["distances"].get(first["distance"])
    names = [g.get("name") or f"{text.race_label(g['distance'])} — {g['date']}" for g in goals]
    return {
        "id": store.new_id("plan"),
        "name": " → ".join(names),
        "race_id": first.get("race_id") if len(goals) == 1 else None,
        "goals": goals,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "request": {
            "distance": last["distance"], "goal_s": last.get("goal_s"), "run_days": sorted(set(settings.run_days)),
            "long_day": settings.long_day, "max_weekly_km": settings.max_weekly_km, "race_id": last.get("race_id"),
            "name": last.get("name"), "priority": last.get("priority", "A"), "race_date": last["date"],
            "start": start.isoformat(), "strength": settings.strength,
        },
        "baseline": base0,
        "forecast": {
            "vdot": round(vdot, 1),
            "distance": first["distance"],
            "realistic_s": round(item.realistic_s) if item else None,
            "low_s": round(item.low_s) if item else None,
            "high_s": round(item.high_s) if item else None,
            "confidence": item.confidence if item else None,
        },
        "paces": {name: [round(a, 3), round(b, 3)] for name, (a, b) in paces.items()},
        "cs": result.get("cs"),
        "response": adapt,
        "zones": {"basis": zones.get("basis"), "lthr": lthr,
                  **{name: list(band) for name, band in zones.items() if name != "basis" and band}},
        "weeks": [
            {**{k: v for k, v in w.items() if k != "monday"}, "monday": w["monday"].isoformat()} for w in weeks
        ],
        "sessions": sessions,
        "warnings": warnings,
    }


def _race_pace(request: PlanRequest, item: Any, warnings: list[dict[str, Any]], named: bool) -> float | None:
    """Goal pace when the goal is within reach of the forecast, else the forecast pace."""
    if request.goal_s and item is not None:
        if request.goal_s >= item.low_s * 0.98:
            return units.pace_from(request.goal_s, units.RACES[request.distance])
        warnings.append({"key": "goal_too_fast", "goal_s": round(request.goal_s), "low_s": round(item.low_s),
                         **({"race": request.name} if named and request.name else {})})
    return units.pace_from(item.realistic_s, units.RACES[request.distance]) if item is not None else None


def _carried(base0: dict[str, Any], weeks: list[dict[str, Any]], goal: dict[str, Any]) -> dict[str, Any]:
    """The next block's starting point: where the plan stands after this race,
    assuming it was followed (a rebuild replaces it with what was actually run)."""
    built = [w["volume_km"] for w in weeks if w["phase"] in ("base", "build", "peak") and not w.get("recovery")]
    level = 0.9 * built[-1] if built else base0["weekly_km_4w"]
    return {
        **base0,
        "weekly_km_4w": round(level, 1),
        "weekly_km_8w": round(level, 1),
        "long_km_6w": max([w["long_km"] for w in weeks[-6:]] + [0.0]) or base0["long_km_6w"],
        "consistency_8w": max(base0["consistency_8w"], 0.5),
        "history_km": (list(base0["history_km"]) + [w["volume_km"] for w in weeks])[-8:],
        "after_race": goal.get("priority", "A") == "A" or goal["distance"] in ("hm", "m"),
    }


# A long run lands at least a week before a race, quality at least 4 days.
LONG_GAP_DAYS = 6
QUALITY_GAP_DAYS = 3
QUALITY_ROOM_KM = 35.0
SHAKEOUT_MIN_DAYS = 4


def easy_days_after(distance: str) -> int:
    """Daniels: one easy day per 3 km raced before the next quality session or long run."""
    return max(2, round(units.RACES[distance] / 3))


def quality_count(run_days: int, week: dict[str, Any]) -> int:
    """Quality sessions in a week, on top of the long run.

    The long run is a hard day too (Daniels counts it as one of the week's
    quality sessions). Two more need room around them: five running days and
    35+ km, otherwise the week is three hard days out of four and nothing easy
    to absorb them.
    """
    if week["phase"] == "race":
        return 1  # the sharpener 4-6 days out (library.SHARPENER); none when no running day fits
    if run_days <= 4 or week["volume_km"] < QUALITY_ROOM_KM or week.get("recovery") or week["phase"] == "taper":
        return 1
    return 2


def already_run(runs: pd.DataFrame, start: dt.date) -> dict[str, Any]:
    """What was run in the 7 days before ``start``: this week's km, quality and
    long run, and every hard day (the plan keeps its quality off their neighbours)."""
    monday = start - dt.timedelta(days=start.weekday())
    out: dict[str, Any] = {"monday": monday, "km": 0.0, "quality": [], "long": [], "hard": []}
    if runs is None or runs.empty or "kind" not in runs:
        return out
    recent = runs[(runs["day"] >= pd.Timestamp(start - dt.timedelta(days=7))) & (runs["day"] < pd.Timestamp(start))]

    def rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
        return [{"date": str(pd.Timestamp(r["day"]).date()), "name": str(r.get("name") or ""),
                 "kind": str(r["kind"]), "km": round(float(r["distance_km"]), 1)}
                for r in frame.sort_values("day").to_dict("records")]

    week = recent[recent["day"] >= pd.Timestamp(monday)]
    out["km"] = round(float(week["distance_km"].sum()), 1)
    out["quality"] = rows(week[week["kind"].isin(("tempo", "threshold", "intervals", "race"))])
    out["long"] = rows(week[week["kind"] == "long"])
    out["hard"] = rows(recent[recent["kind"].isin((*HARD_KINDS, "long"))])
    return out


def _block_sessions(
    weeks: list[dict[str, Any]],
    request: PlanRequest,
    settings: PlanSettings,
    base: dict[str, Any],
    paces: dict[str, tuple[float, float]],
    zones: dict[str, Any],
    race_pace: float | None,
    kept_dates: set[str],
    done: dict[str, Any] | None = None,
    last_race: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Sessions of one block, in place of its weeks' volumes.

    ``done`` (``already_run``) is what was run before the start: this week's
    quality and long run count toward the week, and no quality session lands
    next to a hard day that really happened. Every change a rule makes to the
    pattern leaves a ``why`` code on the session (text.why writes it out).
    ``progress`` (``_progress``) carries the ladder rungs and the strength
    count from block to block; it is updated in place.
    """
    progress = progress if progress is not None else _progress([], 0, True)
    turns: dict[tuple[str, int], int] = {}
    start = request.start or dt.date.today()
    # Long runs are capped by time on feet, not only by distance: past ~2.5 h
    # (2:45 for the marathon) the run costs more recovery than it builds.
    if "E" in paces:
        limit = (165 if request.distance == "m" else 150) / (sum(paces["E"]) / 2)
        for week in weeks:
            week["long_km"] = round(min(week["long_km"], limit), 1)

    run_days = sorted(set(settings.run_days))
    long_day = settings.long_day if settings.long_day in run_days else run_days[-1]
    sessions: list[dict[str, Any]] = []
    for week in weeks:
        week["race_id"] = request.race_id
        phase = week["phase"]
        quality_wanted = quality_count(len(run_days), week)
        why: dict[str, list[dict[str, Any]]] = {}
        this_week = done is not None and done["monday"] == week["monday"]
        done_km, long_done = (done["km"], bool(done["long"])) if this_week else (0.0, False)
        pattern = place_hard_days(run_days, long_day, quality_wanted)
        if phase == "race":
            low, high = library.SHARPEN_DAYS
            fits = [d for d in run_days if low <= (request.race_date - (week["monday"] + dt.timedelta(days=d))).days
                    <= high]
            # The latest day that still leaves 4 days: closest to the race, furthest from the last long run.
            pattern = [max(fits)] if fits else []
        quality_days = pattern
        if this_week and done["quality"]:
            quality_days = place_hard_days(run_days, long_day, max(0, quality_wanted - len(done["quality"])))
        hard_done = done["hard"] if done else []
        week_sessions: list[tuple[int, str]] = []
        families: dict[int, str] = {}
        for day in run_days:
            date = week["monday"] + dt.timedelta(days=day)
            days_to = (request.race_date - date).days
            if date < start or date.isoformat() in kept_dates:
                continue
            if date > request.race_date:
                # After a race in the same week: short recovery runs, not before 2 (A: 3) days.
                if -days_to >= 2:
                    week_sessions.append((day, "recovery"))
                    why.setdefault(date.isoformat(), []).append({"key": "post_race", "days": -days_to})
                continue
            if date == request.race_date:
                week_sessions.append((day, "race"))
                continue
            if days_to == 1:
                # The day before: a shakeout only when it is a usual running day of a
                # runner who runs often (a day off would break the rhythm); otherwise rest.
                if len(run_days) >= SHAKEOUT_MIN_DAYS:
                    week_sessions.append((day, "easy"))
                    why.setdefault(date.isoformat(), []).append({"key": "shakeout", "run_days": len(run_days)})
                continue
            kind = "easy"
            if day == long_day and week["long_km"] > 0:
                kind = "long"
            elif day in quality_days:
                slot = quality_days.index(day)
                cycle = library.rotation(request.distance, phase, slot)
                turn = turns.get((phase, slot), 0)
                families[day] = cycle[turn % len(cycle)]
                kind = library.family_type(families[day], request.distance)
            note = None
            if kind == "long" and long_done:
                kind, note = "easy", {"key": "week_long_done", **done["long"][0]}
            elif kind == "long" and days_to <= LONG_GAP_DAYS:
                kind, note = "easy", {"key": "pre_race_long", "days": days_to, "gap": LONG_GAP_DAYS + 1}
            elif kind not in ("easy", "long") and days_to <= QUALITY_GAP_DAYS:
                kind, note = "easy", {"key": "pre_race_quality", "days": days_to}
            elif kind != "easy" and last_race and 0 < (date - dt.date.fromisoformat(last_race["date"])).days \
                    <= easy_days_after(last_race["distance"]):
                kind, note = "easy", {"key": "post_race_easy",
                                      "days": (date - dt.date.fromisoformat(last_race["date"])).days,
                                      "easy_days": easy_days_after(last_race["distance"]),
                                      "distance": last_race["distance"]}
            elif kind not in ("easy", "long"):
                near = next((h for h in hard_done if abs((date - dt.date.fromisoformat(h["date"])).days) < 2), None)
                if near:
                    kind, note = "easy", {"key": "after_hard", **near}
            if note:
                why.setdefault(date.isoformat(), []).append(note)
            week_sessions.append((day, kind))
        if request.race_date >= week["monday"] and request.race_date < week["monday"] + dt.timedelta(days=7) \
                and request.race_date.weekday() not in run_days and request.race_date >= start:
            week_sessions.append((request.race_date.weekday(), "race"))
        if len(quality_days) < len(pattern):
            # The week's quality was already run: the first session left says so.
            first = next((day for day, kind in week_sessions if kind == "easy"), None)
            if first is not None:
                why.setdefault((week["monday"] + dt.timedelta(days=first)).isoformat(), []).insert(
                    0, {"key": "week_quality_done", **done["quality"][0]})

        built = []
        for day, kind in week_sessions:
            date = week["monday"] + dt.timedelta(days=day)
            km = week["long_km"] if kind == "long" else 0.0
            workout = None
            if kind in QUALITY_TYPES and phase == "race":
                workout = library.sharpener(request.distance, paces, race_pace)
            elif kind in QUALITY_TYPES and day in families:
                family = families[day]
                slot = quality_days.index(day)
                turns[(phase, slot)] = turns.get((phase, slot), 0) + 1
                count = progress["levels"].get(family, 0)
                # A lighter week repeats the rung below; the taper does the current one, shortened.
                level = max(0, count - 1) if week.get("recovery") else count
                workout = library.quality(family, level, week["volume_km"], request.distance, paces, race_pace,
                                          factor=library.TAPER_FACTOR if phase == "taper" else 1.0)
                note = progress.get("held", {}).pop(family, None)
                if note:
                    why.setdefault(date.isoformat(), []).append(note)
                if not week.get("recovery") and phase != "taper":
                    progress["levels"][family] = count + 1
            session = _session(kind, date, week, km if kind == "long" else 6.0, paces, zones,
                               request.distance, race_pace, workout)
            if kind == "race":
                session["race_id"] = request.race_id
            built.append(session)
        # A low-volume week cannot carry two quality sessions plus a long run:
        # drop quality (the later one first) rather than overshoot the volume.
        def fixed_km() -> float:
            return sum(s["distance_km"] for s in built if s["type"] not in ("easy", "race"))

        quality = [s for s in built if s["type"] in QUALITY_TYPES]
        easy_count = sum(1 for s in built if s["type"] == "easy")
        # One quality session stays when the record shows it is tolerated.
        keep_one = 1 if (base["hard_per_week_4w"] >= 0.75 or week["volume_km"] >= 15) else 0
        while len(quality) > keep_one and fixed_km() + 3.0 * easy_count > week["volume_km"] * 1.1:
            dropped = quality.pop()
            family = (dropped.get("text") or {}).get("key")
            if family in progress["levels"] and not week.get("recovery") and phase != "taper":
                progress["levels"][family] = max(0, progress["levels"][family] - 1)
            dropped.update(_session("easy", dt.date.fromisoformat(dropped["date"]), week, 3.0, paces,
                                    zones, request.distance, race_pace))
            easy_count += 1
        # Easy days absorb what is left of the weekly volume.
        fixed = fixed_km()
        easy = [s for s in built if s["type"] == "easy"]
        if easy:
            share = max(0.0, week["volume_km"] - fixed - done_km) / len(easy)
            cap = max(4.0, min(12.0, 0.8 * week["long_km"] if week["long_km"] else 10.0))
            if phase == "race":
                # Race week: short easy runs (a third of the race distance, 4-8 km) -- the taper
                # cuts kilometres; what the week "should" hold is not made up on the last days.
                cap = max(4.0, min(8.0, 0.35 * units.RACES[request.distance]))
            share = min(max(share, 3.0), cap)
            # The day after a long run or hard session is the recovery run.
            hard_dates = {s["date"] for s in built if s["type"] in HARD_TYPES}
            for s in easy:
                previous = (dt.date.fromisoformat(s["date"]) - dt.timedelta(days=1)).isoformat()
                kind = "recovery" if previous in hard_dates and len(run_days) >= 4 else "easy"
                replacement = _session(kind, dt.date.fromisoformat(s["date"]), week,
                                       share * (0.75 if kind == "recovery" else 1.0), paces, zones,
                                       request.distance, race_pace)
                s.clear()
                s.update(replacement)
        for s in built:
            if s["date"] in why and any(w["key"] == "shakeout" for w in why[s["date"]]):
                s.update(_session("easy", dt.date.fromisoformat(s["date"]), {**week, "phase": "build"}, 3.0, paces,
                                  zones, request.distance, race_pace))
                s["phase"] = week["phase"]
            if s["type"] == "recovery" and s["date"] > request.race_date.isoformat():
                s.update(_session("recovery", dt.date.fromisoformat(s["date"]), week,
                                  min(s["distance_km"], 5.0), paces, zones, request.distance, race_pace))
            if s["date"] in why:
                s["why"] = why[s["date"]]
        if week.get("adapt") and progress.get("adapt"):
            first_run = next((s for s in built if s["type"] in RUN_TYPES and s["type"] != "race"), None)
            if first_run is not None:
                first_run.setdefault("why", []).insert(0, {"key": "response", **progress["adapt"]})
        if settings.strength:
            built.extend(_strength_sessions(week, built, request, settings, start, kept_dates, hard_done,
                                            last_race, progress))
        week["planned_km"] = round(sum(s["distance_km"] or 0 for s in built), 1)  # the race counts too
        sessions.extend(built)
    return sessions


FAMILIES = ("threshold", "intervals", "hills", "race_pace", "tempo")


def _progress(keep: list[dict[str, Any]], strength_history: int, strength: bool,
              outcomes: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Where the ladders stand before the first new session.

    With ``outcomes`` (``outcomes``: what really happened to each past session)
    a family climbs only for sessions that were done as written; a missed,
    cut short, off-pace or too-hard one holds the rung, and the reason waits
    in ``held`` for the next session of that family. Without them (a first
    plan) every past session counts.
    """
    levels: dict[str, int] = {}
    held: dict[str, dict[str, Any]] = {}
    marked = 0
    for session in sorted(keep or [], key=lambda s: s["date"]):
        key = (session.get("text") or {}).get("key")
        outcome = (outcomes or {}).get(session.get("id"))
        if key in FAMILIES and session.get("phase") != "taper" and not (session.get("text") or {}).get("sharpen"):
            if outcomes is None or (outcome and outcome["advance"]):
                levels[key] = levels.get(key, 0) + 1
                held.pop(key, None)
            elif outcome:
                held[key] = {"key": "rung_hold", "family": key, "date": session["date"],
                             **{k: v for k, v in outcome.items() if k != "advance"}}
        elif session.get("type") == "strength":
            done = outcome["done"] if outcome else session.get("status") in ("done", "modified")
            marked += int(bool(done))
    # Garmin's record and the sessions ticked off overlap: the larger one counts.
    return {"levels": levels, "held": held, "strength": max(int(strength_history), marked), "enabled": strength}


# Rep execution: a rung counts when every rep was run and two thirds were on pace,
# and threshold reps stayed within the T heart-rate zone (+3 bpm for drift).
ON_PACE_SHARE = 2 / 3
HR_MARGIN = 3


def outcomes(plan: dict[str, Any], runs: pd.DataFrame, today: dt.date, laps: pd.DataFrame | None = None,
             activities: pd.DataFrame | None = None) -> dict[str, dict[str, Any]]:
    """What happened to each session before ``today``: ``advance`` for a quality
    session done as written (else ``reason``), ``done`` for strength."""
    past = {**plan, "sessions": [s for s in plan.get("sessions", []) if s["date"] < today.isoformat()]}
    if not past["sessions"]:
        return {}
    matched = match(past, runs, today=today, laps=laps, activities=activities)
    top = ((plan.get("zones") or {}).get("T") or [None, None])[1]
    out: dict[str, dict[str, Any]] = {}
    for row in matched.to_dict("records"):
        effective = row.get("effective")
        if row.get("type") == "strength":
            out[row["id"]] = {"done": effective in ("done", "modified")}
            continue
        if row.get("type") not in QUALITY_TYPES:
            continue
        result: dict[str, Any] = {"advance": True}
        planned, done = row.get("reps_planned"), row.get("reps_done")
        on_pace = row.get("reps_on_pace")
        if effective in ("missed", "skipped", "planned"):
            result = {"advance": False, "reason": "missed"}
        elif row.get("type_ok") is False:
            result = {"advance": False, "reason": "other_kind", "kind": row.get("actual_kind")}
        elif _number(planned) and _number(done) and done < planned:
            result = {"advance": False, "reason": "short", "done": int(done), "planned": int(planned)}
        elif _number(planned) and _number(on_pace) and on_pace < math.ceil(planned * ON_PACE_SHARE):
            result = {"advance": False, "reason": "off_pace", "on_pace": int(on_pace), "planned": int(planned)}
        elif top and row.get("type") == "threshold" and isinstance(row.get("rep_hr"), list) and row["rep_hr"] \
                and sum(row["rep_hr"]) / len(row["rep_hr"]) > top + HR_MARGIN:
            result = {"advance": False, "reason": "hr_high", "hr": round(sum(row["rep_hr"]) / len(row["rep_hr"])),
                      "top": int(top)}
        out[row["id"]] = result
    return out


def _last_weeks(plan: dict[str, Any], runs: pd.DataFrame, today: dt.date, days: int = 14) -> dict[str, Any]:
    """``compliance`` of the plan's last ``days`` before ``today``."""
    since = (today - dt.timedelta(days=days)).isoformat()
    recent = [s for s in plan.get("sessions", []) if since <= s["date"] < today.isoformat()]
    if not recent:
        return {"due": 0}
    return compliance(match({**plan, "sessions": recent}, runs, today=today))


def _number(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


STRENGTH_SPORTS = ("strength_training", "indoor_cardio", "hiit")
STRENGTH_HISTORY_DAYS = 120


def strength_done(activities: pd.DataFrame | None, before: dt.date | None = None) -> int:
    """Strength sessions recorded by the watch in the last ``STRENGTH_HISTORY_DAYS`` days."""
    if activities is None or activities.empty or "sport" not in activities:
        return 0
    before = before or dt.date.today()
    days = pd.to_datetime(activities["day"])
    mask = activities["sport"].isin(STRENGTH_SPORTS) & (days < pd.Timestamp(before)) \
        & (days >= pd.Timestamp(before - dt.timedelta(days=STRENGTH_HISTORY_DAYS)))
    return int(mask.sum())


def _strength_sessions(
    week: dict[str, Any],
    built: list[dict[str, Any]],
    request: PlanRequest,
    settings: PlanSettings,
    start: dt.date,
    kept_dates: set[str],
    hard_done: list[dict[str, Any]],
    last_race: dict[str, Any] | None,
    progress: dict[str, Any],
) -> list[dict[str, Any]]:
    """The week's strength sessions (``library.PER_WEEK`` by phase, one in a lighter week).

    First choice is the quality day, after the run (hard days hard, easy days
    easy); then an easy-run day, then a day off. Never the day before a hard
    day, never on the long run or race day, never within
    ``library.BEFORE_RACE_DAYS`` before the race or the easy days after the
    last one; two sessions at least two days apart.
    """
    wanted = library.PER_WEEK.get(week["phase"], 0)
    if week.get("recovery"):
        wanted = min(wanted, 1)
    if not wanted:
        return []
    hard = {s["date"] for s in built if s["type"] in HARD_TYPES} | {h["date"] for h in hard_done}
    kinds = {s["date"]: s["type"] for s in built}
    quiet = library.BEFORE_RACE_DAYS.get(request.priority, 4)
    last_date = dt.date.fromisoformat(last_race["date"]) if last_race else None
    after = easy_days_after(last_race["distance"]) if last_race else 0
    candidates = []
    for offset in range(7):
        date = week["monday"] + dt.timedelta(days=offset)
        iso = date.isoformat()
        if date < start or iso in kept_dates or date > request.race_date:
            continue
        if (request.race_date - date).days < quiet:
            continue
        if last_date and 0 <= (date - last_date).days <= after:
            continue
        if (date + dt.timedelta(days=1)).isoformat() in hard or kinds.get(iso) in ("long", "race"):
            continue
        kind = kinds.get(iso)
        score = 3 if kind in QUALITY_TYPES else 2 if kind in ("easy", "recovery") else 1
        candidates.append((score, -offset, date))
    chosen: list[dt.date] = []
    for _ in range(wanted):
        left = [c for c in candidates if all(abs((c[2] - d).days) >= 2 for d in chosen)]
        if not left:
            break
        chosen.append(max(left)[2])
    out = []
    for date in sorted(chosen):
        stage = library.strength_stage(week["phase"], progress["strength"], bool(week.get("recovery")))
        progress["strength"] += 1
        out.append(_session("strength", date, week, 0.0, {}, None, request.distance, None,
                            library.strength(stage, progress["strength"])))
    return out


def longest_before(history: list[tuple[dt.date, float]], date: dt.date, days: int = SPIKE_DAYS) -> float:
    """The longest run of the ``days`` before ``date`` (not counting that day)."""
    return max((km for day, km in history if date - dt.timedelta(days=days) <= day < date), default=0.0)


def spike_cap(history: list[tuple[dt.date, float]], date: dt.date) -> tuple[float, float]:
    """(longest run of the last 30 days, the longest a run on ``date`` may be)."""
    longest = longest_before(history, date)
    return longest, max(SPIKE * longest, SPIKE_FLOOR_KM)


def run_history(runs: pd.DataFrame | None, before: dt.date) -> list[tuple[dt.date, float]]:
    """(day, km) of the real runs in the 30 days before ``before``."""
    if runs is None or runs.empty:
        return []
    frame = runs[(runs["day"] < pd.Timestamp(before))
                 & (runs["day"] >= pd.Timestamp(before - dt.timedelta(days=SPIKE_DAYS)))]
    return [(pd.Timestamp(d).date(), float(km)) for d, km in zip(frame["day"], frame["distance_km"])]


def _shorten(session: dict[str, Any], cap: float, paces: dict[str, tuple[float, float]]) -> None:
    """Cut a run to ``cap`` km keeping its kind: an easy or long run loses easy
    kilometres, a quality session loses reps first and warm-up/cool-down last."""
    easy = paces.get("E")
    easy_mid = sum(easy) / 2 if easy else 6.5
    kind = session["type"]
    steps = [dict(step) for step in session.get("steps") or []]
    if kind in ("easy", "recovery"):
        band = (session["pace_lo"], session["pace_hi"]) if session.get("pace_lo") else None
        strides = bool((session.get("text") or {}).get("strides"))
        steps = _easy_steps(math.floor(cap * 10) / 10, band, paces, strides, steps[0].get("hr") if steps else None)
    elif kind == "long":
        excess = steps_km(steps, easy_mid) - cap
        steps[0]["km"] = round(max(1.0, steps[0]["km"] - excess), 1)
    else:
        repeat = next((step for step in steps if step["kind"] == "repeat"), None)
        while repeat and repeat["reps"] > 1 and steps_km(steps, easy_mid) > cap:
            repeat["reps"] -= 1
        for step in steps:
            if step["kind"] in ("warmup", "cooldown") and "km" in step and steps_km(steps, easy_mid) > cap:
                step["km"] = 1.0
        if repeat:
            session["text"] = {**session["text"], "reps": repeat["reps"]}
    session["steps"] = steps
    session["distance_km"] = round(steps_km(steps, easy_mid), 1)
    session["duration_min"] = round(steps_minutes(steps, easy_mid))
    session.update(text.session_text(session))


def _cap_spikes(sessions: list[dict[str, Any]], runs: pd.DataFrame, start: dt.date,
                paces: dict[str, tuple[float, float]], weeks: list[dict[str, Any]]) -> None:
    """Hold every planned run to ``SPIKE`` x the longest run of the 30 days
    before it, counting real runs before ``start`` and the plan from there on.
    A race is never cut -- it only counts toward what follows."""
    history = run_history(runs, start)
    by_week = {w["week"]: w for w in weeks}
    for session in sorted(sessions, key=lambda s: s["date"]):
        if session["type"] not in RUN_TYPES or not session.get("distance_km"):
            continue
        date = dt.date.fromisoformat(session["date"])
        longest, cap = spike_cap(history, date)
        if session["type"] != "race" and session["distance_km"] > cap + 0.05:
            before = session["distance_km"]
            _shorten(session, cap, paces)
            session.setdefault("why", []).append(
                {"key": "spike", "from_km": round(before, 1), "cap": round(cap, 1), "longest": round(longest, 1)})
            week = by_week.get(session.get("week"))
            if week is not None:
                week["planned_km"] = round(week.get("planned_km", 0) - (before - session["distance_km"]), 1)
                if session["type"] == "long":
                    week["long_km"] = session["distance_km"]
        history.append((date, float(session["distance_km"])))


def spikes(plan: dict[str, Any], runs: pd.DataFrame | None, today: dt.date | None = None) -> list[dict[str, Any]]:
    """Planned runs from ``today`` on that break the 1.1x rule (for a plan edited by hand)."""
    today = today or dt.date.today()
    history = run_history(runs, today)
    out = []
    for session in sorted(plan.get("sessions", []), key=lambda s: s["date"]):
        if session["date"] < today.isoformat() or session.get("type") not in RUN_TYPES \
                or not session.get("distance_km"):
            continue
        date = dt.date.fromisoformat(session["date"])
        longest, cap = spike_cap(history, date)
        if session["type"] != "race" and session["distance_km"] > cap + 0.05:
            out.append({"id": session["id"], "date": session["date"], "km": session["distance_km"],
                        "longest": round(longest, 1), "cap": round(cap, 1)})
        history.append((date, float(session["distance_km"])))
    return out


def reached_prep(plan: dict[str, Any], distance: str, race_date: str | None = None) -> float:
    """Preparation score the plan reaches at its peak (for the target forecast);
    with ``race_date`` only the 8 weeks before that race count."""
    from running.forecast import REQUIREMENTS

    need = REQUIREMENTS[distance]
    weeks = [w for w in plan.get("weeks", []) if w.get("phase") in ("build", "peak", "base")]
    if race_date:
        race = dt.date.fromisoformat(race_date)
        weeks = [w for w in weeks if race - dt.timedelta(weeks=8) <= dt.date.fromisoformat(w["monday"]) <= race]
    if not weeks:
        return 0.0
    peak_volume = max(w.get("planned_km", w.get("volume_km", 0)) for w in weeks)
    peak_long = max(w.get("long_km", 0) for w in weeks)
    return round(0.4 * min(1, peak_long / need["long_km"]) + 0.4 * min(1, peak_volume / need["weekly_km"]) + 0.2, 3)


# --------------------------------------------------------------------------
# plan vs actual


COMPATIBLE = {
    "easy": {"easy", "recovery", "long"},
    "recovery": {"recovery", "easy"},
    "long": {"long", "easy"},
    "tempo": {"tempo", "threshold"},
    "threshold": {"threshold", "tempo", "intervals"},
    "intervals": {"intervals", "threshold"},
    "race": {"race", "threshold", "tempo"},
}


PACE_TOLERANCE = 0.03  # a rep within 3% of the band counts as on pace: GPS noise on 1 km is ~1-2%


def rep_blocks(laps: pd.DataFrame) -> list[dict[str, Any]]:
    """Work reps of one structured run, from its laps (``workouts.reps``)."""
    table = workouts.reps(laps)
    return [{"km": row.km, "pace": row.pace, "hr": round(row.hr) if pd.notna(row.hr) else None}
            for row in table.itertuples()] if not table.empty else []


def planned_reps(steps: list[dict[str, Any]] | None) -> tuple[int, tuple[float, float] | None]:
    """How many work reps a session asks for, and their pace band."""
    for step in steps or []:
        if step["kind"] == "repeat":
            work = next((s for s in step["steps"] if s["kind"] == "run"), None)
            return step["reps"], tuple(work["pace"]) if work and work.get("pace") else None
    work = [s for s in steps or [] if s["kind"] == "run" and s.get("pace")]
    return (1, tuple(work[-1]["pace"])) if work else (0, None)


def match(plan: dict[str, Any], runs: pd.DataFrame, today: dt.date | None = None,
          laps: pd.DataFrame | None = None, activities: pd.DataFrame | None = None) -> pd.DataFrame:
    """Each planned session next to the run that fulfilled it (if any).

    A run matches a session on the same date first, then one day either side
    (a session moved by a day is still the same session). A stored status set
    by hand wins over the automatic one. With ``laps`` (table ``run_laps``),
    quality sessions are also compared rep by rep. Strength sessions match a
    watch strength activity (``activities``, ``STRENGTH_SPORTS``) the same way;
    without ``activities`` they only carry the status set by hand.
    """
    today = today or dt.date.today()
    by_activity = dict(tuple(laps.groupby("activity_id"))) if laps is not None and not laps.empty else {}
    rows = []
    used: set[int] = set()
    sessions = [s for s in plan.get("sessions", []) if s.get("type") not in ("rest", "strength")]
    strength = [s for s in plan.get("sessions", []) if s.get("type") == "strength"]
    by_day = {}
    if runs is not None and not runs.empty:
        for run in runs.itertuples(index=False):
            by_day.setdefault(run.day.date(), []).append(run)
    pending = []
    for session in sessions:
        date = dt.date.fromisoformat(session["date"])
        chosen = None
        if session.get("actual_activity_id"):
            for runs_on_day in by_day.values():
                for run in runs_on_day:
                    if int(run.activity_id) == int(session["actual_activity_id"]):
                        chosen = run
        if chosen is None:
            same = [r for r in by_day.get(date, []) if int(r.activity_id) not in used]
            if same:
                chosen = min(same, key=lambda r: abs(r.distance_km - (session.get("distance_km") or 0)))
        if chosen is not None:
            used.add(int(chosen.activity_id))
        pending.append((session, date, chosen))
    for session, date, chosen in pending:
        if chosen is None:
            for offset in (-1, 1):
                near = [r for r in by_day.get(date + dt.timedelta(days=offset), []) if int(r.activity_id) not in used]
                if near:
                    chosen = near[0]
                    used.add(int(chosen.activity_id))
                    break
        row = _compare(session, date, chosen, today)
        if chosen is not None and session.get("type") in ("tempo", "threshold", "intervals"):
            row.update(_compare_reps(session, by_activity.get(int(chosen.activity_id))))
        rows.append(row)
    rows.extend(_match_strength(strength, activities, today))
    return pd.DataFrame(rows).sort_values("date", kind="stable").reset_index(drop=True) if rows else pd.DataFrame()


def _match_strength(sessions: list[dict[str, Any]], activities: pd.DataFrame | None,
                    today: dt.date) -> list[dict[str, Any]]:
    days: dict[dt.date, list[int]] = {}
    if activities is not None and not activities.empty and "sport" in activities:
        frame = activities[activities["sport"].isin(STRENGTH_SPORTS)]
        for day, activity in zip(pd.to_datetime(frame["day"]), frame["activity_id"]):
            days.setdefault(day.date(), []).append(int(activity))
    used: set[int] = set()
    rows = []
    for session in sessions:
        date = dt.date.fromisoformat(session["date"])
        found = next((a for offset in (0, -1, 1) for a in days.get(date + dt.timedelta(days=offset), [])
                      if a not in used), None)
        row = _compare(session, date, None, today)
        if found is not None:
            used.add(found)
            row.update(activity_id=found, auto="done")
        elif activities is None:
            row["auto"] = None
        row["effective"] = row["status"] if row["status"] != "planned" else (row["auto"] or "planned")
        rows.append(row)
    return rows


def _compare_reps(session: dict[str, Any], laps: pd.DataFrame | None) -> dict[str, Any]:
    planned, band = planned_reps(session.get("steps"))
    blocks = rep_blocks(laps)
    if not planned or not blocks:
        return {}
    on_pace = None
    if band:
        low, high = band[0] * (1 - PACE_TOLERANCE), band[1] * (1 + PACE_TOLERANCE)
        on_pace = sum(1 for b in blocks if low <= b["pace"] <= high)
    return {
        "reps_planned": planned,
        "reps_done": len(blocks),
        "reps_on_pace": on_pace,
        "rep_paces": [round(b["pace"], 3) for b in blocks],
        "rep_hr": [b["hr"] for b in blocks if b["hr"] is not None],
    }


def _compare(session: dict[str, Any], date: dt.date, run: Any, today: dt.date) -> dict[str, Any]:
    planned_km = session.get("distance_km") or 0
    stored = session.get("status", "planned")
    out = {
        "id": session["id"],
        "date": date,
        "week": session.get("week"),
        "type": session.get("type"),
        "title": session.get("title"),
        "planned_km": planned_km,
        "pace_lo": session.get("pace_lo"),
        "pace_hi": session.get("pace_hi"),
        "activity_id": None,
        "actual_km": None,
        "actual_pace": None,
        "actual_kind": None,
        "distance_ratio": None,
        "type_ok": None,
        "status": stored,
        "auto": None,
        "note": session.get("note", ""),
    }
    if run is not None:
        ratio = (run.distance_km / planned_km) if planned_km else None
        kind = getattr(run, "kind", None)
        type_ok = kind in COMPATIBLE.get(session.get("type"), {kind})
        auto = "done" if type_ok and (ratio is None or 0.8 <= ratio <= 1.25) else "modified"
        out.update(
            activity_id=int(run.activity_id),
            actual_km=round(float(run.distance_km), 2),
            actual_pace=float(run.pace_min_km),
            actual_kind=kind,
            distance_ratio=None if ratio is None else round(ratio, 2),
            type_ok=bool(type_ok),
            auto=auto,
        )
    elif date < today:
        out["auto"] = "missed"
    out["effective"] = stored if stored != "planned" else (out["auto"] or "planned")
    return out


def compliance(matched: pd.DataFrame) -> dict[str, Any]:
    """Summary of the plan so far: done / modified / skipped and km ratio."""
    if matched is None or matched.empty:
        return {"due": 0}
    due = matched[matched["date"] < dt.date.today() + dt.timedelta(days=1)]
    strength = due[due["type"] == "strength"]
    due = due[due["type"] != "strength"]
    if due.empty:
        return {"due": 0}
    counts = due["effective"].value_counts()
    planned_km = float(due["planned_km"].sum())
    actual_km = float(due["actual_km"].fillna(0).sum())
    hard = due[due["type"].isin(("tempo", "threshold", "intervals"))]
    return {
        "due": int(len(due)),
        "done": int(counts.get("done", 0)),
        "modified": int(counts.get("modified", 0)),
        "skipped": int(counts.get("skipped", 0) + counts.get("missed", 0)),
        "planned_km": round(planned_km, 1),
        "actual_km": round(actual_km, 1),
        "km_ratio": round(actual_km / planned_km, 2) if planned_km else None,
        "quality_done": int(hard["effective"].isin(("done", "modified")).sum()),
        "quality_due": int(len(hard)),
        "strength_done": int(strength["effective"].isin(("done", "modified")).sum()),
        "strength_due": int(len(strength)),
    }


# --------------------------------------------------------------------------
# changing a plan


def replan(
    plan: dict[str, Any],
    runs: pd.DataFrame,
    result: dict[str, Any],
    today: dt.date | None = None,
    goals: list[dict[str, Any]] | None = None,
    strength_history: int = 0,
    laps: pd.DataFrame | None = None,
    activities: pd.DataFrame | None = None,
    daily: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Rebuild everything from ``today`` on with fresh data; the past stays as it was.

    The workout ladders continue from what was really done (``outcomes``:
    the watch laps, when given, check reps and pace); with ``daily`` the next
    week grows, holds or gets lighter by the body's response (``response``).

    ``goals`` replaces the plan's goals (the races saved now); without it the
    plan keeps the goals it has.
    """
    today = today or dt.date.today()
    request_data = dict(plan["request"])
    settings = PlanSettings(
        run_days=list(request_data.get("run_days") or [1, 3, 5, 6]),
        long_day=int(request_data.get("long_day", 6)),
        start=today,
        max_weekly_km=request_data.get("max_weekly_km"),
        strength=bool(request_data.get("strength", True)),
    )
    keep = [s for s in plan.get("sessions", []) if s["date"] < today.isoformat()]
    fresh = generate_goals(settings, plan_goals(plan) if goals is None else goals, runs, result, keep=keep,
                           strength_history=strength_history,
                           done_as_planned=outcomes(plan, runs, today, laps=laps, activities=activities),
                           adapt=response(daily, today - dt.timedelta(days=1), _last_weeks(plan, runs, today))
                           if daily is not None else None)
    fresh["id"] = plan["id"]
    if goals is None and plan.get("name"):
        fresh["name"] = plan["name"]
    fresh["created"] = plan.get("created", fresh["created"])
    fresh["request"]["start"] = plan["request"].get("start", fresh["request"]["start"])
    # What was pushed to Garmin outlives the session ids; the next push uses
    # it to remove workouts of sessions this rebuild replaced.
    if plan.get("garmin"):
        fresh["garmin"] = dict(plan["garmin"])
    fresh["history"] = list(plan.get("history", [])) + [
        {"at": dt.datetime.now().isoformat(timespec="seconds"), "action": "replan" if goals is None else "goals",
         "vdot": fresh["forecast"]["vdot"]}
    ]
    return fresh


# The reasons a plan can be adjusted for (labels: text.adjustment_label).
ADJUSTMENTS = ("fatigue", "sick", "busy")


def adjust(plan: dict[str, Any], reason: str, today: dt.date | None = None) -> dict[str, Any]:
    """Local change after a change in condition; the rest of the plan is untouched."""
    if reason not in ADJUSTMENTS:
        raise ValueError(i18n.tr(pl=f"Nieznany powód: {reason}", en=f"Unknown reason: {reason}"))
    today = today or dt.date.today()
    horizon = today + dt.timedelta(days=11 if reason == "sick" else 7)
    plan = dict(plan)
    paces = {k: tuple(v) for k, v in (plan.get("paces") or {}).items()}
    easy = paces.get("E")
    changed = []
    for session in plan.get("sessions", []):
        date = dt.date.fromisoformat(session["date"])
        if not today <= date < horizon or session.get("status") != "planned" or session["type"] == "race":
            continue
        if session["type"] == "strength":
            # Ill or worn out: no strength in the window; short on time: a shorter session.
            if reason == "busy":
                session["duration_min"] = round((session.get("duration_min") or 30) * 0.7)
            else:
                session.update(type="rest", text={"key": "sick" if reason == "sick" else "rest_strength"},
                               distance_km=0.0, duration_min=0, steps=[])
        elif reason == "sick" and date < today + dt.timedelta(days=4):
            session.update(type="rest", text={"key": "sick"}, distance_km=0.0, duration_min=0, steps=[])
        elif reason in ("sick", "fatigue"):
            factor = 0.8
            km = round((session.get("distance_km") or 0) * factor, 1)
            if session["type"] in ("tempo", "threshold", "intervals"):
                km = round(min(km, 6.0), 1)
            if session["type"] != "long":
                session.update(type="easy", text={"key": "adjusted"},
                               pace_lo=easy[0] if easy else None, pace_hi=easy[1] if easy else None)
            if session["type"] == "long" and session.get("steps"):
                session["steps"] = _scale_steps(session["steps"], factor)
            else:
                session["steps"] = [_step("run", km=km, pace=easy)]
            session["distance_km"] = km
        else:  # busy
            session["distance_km"] = round((session.get("distance_km") or 0) * 0.7, 1)
            if session.get("steps"):
                session["steps"] = _scale_steps(session["steps"], 0.7)
        session["adjusted"] = reason
        session.update(text.session_text(session))
        changed.append(session["id"])
    plan["history"] = list(plan.get("history", [])) + [
        {"at": dt.datetime.now().isoformat(timespec="seconds"), "action": reason, "sessions": len(changed)}
    ]
    return plan


def soften(plan: dict[str, Any], session_id: str, today: dt.date | None = None) -> dict[str, Any]:
    """One hard session becomes an easy run of at most its distance (6 km cap
    for quality): the morning's decision when recovery says no. A strength
    session on the same day is dropped with it."""
    today = today or dt.date.today()
    easy = tuple((plan.get("paces") or {}).get("E") or ()) or None
    session = _find(plan, session_id)
    if session["type"] not in HARD_TYPES or session["type"] == "race":
        raise ValueError(i18n.tr(pl="Ta sesja nie jest mocna — nie ma czego zmiękczać.",
                                 en="This session is not a hard one — there is nothing to soften."))
    if session["date"] < today.isoformat():
        raise ValueError(_past())
    km = session.get("distance_km") or 0
    if session["type"] != "long":
        km = min(km, 6.0)
    km = round(km * (0.8 if session["type"] == "long" else 1.0), 1)
    before = dict(session.get("text") or {"key": session["type"]})
    # Only the easy and long titles carry a distance ("Długie wybieganie 16 km").
    before_km = float(round(session.get("distance_km") or 0)) if before.get("key") in ("easy", "recovery", "long") \
        else None
    session.update(type="easy", text={"key": "softened", "before": before, "before_km": before_km},
                   distance_km=km, pace_lo=easy[0] if easy else None, pace_hi=easy[1] if easy else None,
                   steps=[_step("run", km=km, pace=easy)])
    session.update(text.session_text(session))
    # The strength session after it goes too: the same signals say no to both.
    for other in plan.get("sessions", []):
        if other["type"] == "strength" and other["date"] == session["date"] and other.get("status") == "planned":
            other.update(type="rest", text={"key": "rest_strength"}, duration_min=0, steps=[])
            other.update(text.session_text(other))
    _log(plan, "soften", session_id)
    return plan


def _past() -> str:
    return i18n.tr(pl="Sesja jest w przeszłości.", en="The session is in the past.")


def postpone(plan: dict[str, Any], session_id: str, today: dt.date | None = None) -> dict[str, Any]:
    """Move a session one day later, swapping with whatever sat there.

    Refuses when the move would put two hard days side by side -- the rule
    the generator keeps, kept here too. A strength session on the same day
    moves with the run (it belongs after it); a strength session moved on its
    own may not land the day before a hard day.
    """
    today = today or dt.date.today()
    session = _find(plan, session_id)
    date = dt.date.fromisoformat(session["date"])
    tr = i18n.tr
    if date < today:
        raise ValueError(_past())
    target = date + dt.timedelta(days=1)
    race_day = plan.get("request", {}).get("race_date")
    if race_day and target.isoformat() >= race_day and session["type"] != "race":
        raise ValueError(tr(pl="Przesunięcie wypadłoby na dzień startu albo po nim.",
                            en="The move would land on race day or after it."))
    strength = session["type"] == "strength"
    other = None if strength else next((s for s in plan.get("sessions", [])
                                        if s["date"] == target.isoformat() and s["type"] != "strength"), None)
    if other is not None and other["type"] == "race":
        raise ValueError(tr(pl="Następnego dnia jest start.", en="The race is the next day."))
    moved = {s["id"]: s["date"] for s in plan.get("sessions", [])}
    moved[session["id"]] = target.isoformat()
    if other is not None:
        moved[other["id"]] = date.isoformat()
    along = [] if strength else [s for s in plan.get("sessions", [])
                                 if s["type"] == "strength" and s["date"] == date.isoformat()]
    for item in along:
        moved[item["id"]] = target.isoformat()
    if strength and any(moved[s["id"]] == (target + dt.timedelta(days=1)).isoformat()
                        for s in plan.get("sessions", []) if s["type"] in HARD_TYPES):
        raise ValueError(tr(pl="Siłownia nie ląduje w przeddzień mocnego dnia.",
                            en="Strength never lands the day before a hard day."))
    hard = sorted(dt.date.fromisoformat(moved[s["id"]]) for s in plan.get("sessions", [])
                  if s["type"] in HARD_TYPES)
    if any((b - a).days == 1 for a, b in zip(hard, hard[1:])):
        raise ValueError(tr(pl="Po przesunięciu dwa mocne dni wypadłyby obok siebie — lepiej zamienić na spokojny.",
                            en="After the move two hard days would sit side by side — better swap it for an easy "
                               "run."))
    session["date"] = target.isoformat()
    if other is not None:
        other["date"] = date.isoformat()
    for item in along:
        item["date"] = target.isoformat()
    plan["sessions"] = sorted(plan["sessions"], key=lambda s: (s["date"], s["type"] == "strength"))
    _log(plan, "postpone", session_id)
    return plan


def _scale_steps(steps: list[dict[str, Any]], factor: float) -> list[dict[str, Any]]:
    """Shorter version of the same workout: the work shrinks, warm-up and
    cool-down stay (a shorter warm-up before quality is a false saving)."""
    out = []
    for step in steps:
        step = dict(step)
        if step["kind"] == "repeat":
            step["reps"] = max(1, round(step["reps"] * factor))
        elif step["kind"] == "run" and "km" in step:
            step["km"] = round(step["km"] * factor, 1)
        out.append(step)
    return out


def _find(plan: dict[str, Any], session_id: str) -> dict[str, Any]:
    for session in plan.get("sessions", []):
        if session["id"] == session_id:
            return session
    raise ValueError(i18n.tr(pl=f"Brak sesji {session_id}.", en=f"No session {session_id}."))


def _log(plan: dict[str, Any], action: str, session_id: str) -> None:
    plan["history"] = list(plan.get("history", [])) + [
        {"at": dt.datetime.now().isoformat(timespec="seconds"), "action": action, "session": session_id}
    ]


def set_status(plan: dict[str, Any], session_id: str, status: str, note: str | None = None,
               activity_id: int | None = None) -> dict[str, Any]:
    if status not in store.STATUSES:
        raise ValueError(i18n.tr(pl=f"Status spoza {store.STATUSES}", en=f"Status outside {store.STATUSES}"))
    for session in plan.get("sessions", []):
        if session["id"] == session_id:
            session["status"] = status
            if note is not None:
                session["note"] = note
            if activity_id is not None:
                session["actual_activity_id"] = int(activity_id)
    return plan


def week_table(plan: dict[str, Any]) -> pd.DataFrame:
    """Per plan week: phase, planned km, long run, quality count."""
    weeks = pd.DataFrame(plan.get("weeks", []))
    if weeks.empty:
        return weeks
    sessions = pd.DataFrame(plan.get("sessions", []))
    if not sessions.empty:
        quality = sessions[sessions["type"].isin(("tempo", "threshold", "intervals"))].groupby("week").size()
        weeks["quality"] = weeks["week"].map(quality).fillna(0).astype(int)
    weeks["phase_label"] = weeks["phase"].map(text.phase_label)
    return weeks
