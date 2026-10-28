"""Training-plan generator, plan-vs-actual matching and re-planning.

Principles the generator follows (and the page states):

* **Start from what was actually run.** The first week is anchored on the mean
  of the last four weeks, not on the volume the goal "needs".
* **Volume grows by absolute steps toward a distance-specific peak**, and
  every week is also capped at 1.3x the mean of the four weeks before it,
  real or planned -- the acute:chronic guard (the upper edge of Gabbett's
  0.8-1.3 band). A runner coming off a break
  therefore climbs slower than one already near the peak, and no week
  jumps because a percentage compounds.
* **Every third or fourth week is lighter** (every third when the recent
  record is irregular, i.e. tolerance is unproven), and the taper scales with
  the distance (1 / 1 / 2 / 3 weeks).
* **Hard days never touch.** Long run on the chosen day; quality sessions on
  the days furthest from it and from each other. When the available days make
  that impossible, the plan schedules fewer quality sessions, not adjacent
  ones.
* **Paces come from current fitness** (VDOT now), not from the goal. The
  goal pace appears only in race-specific segments, and only when the goal is
  within reach of the forecast. Re-planning recalculates paces from the latest
  data, which is how the plan follows real progress.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

import i18n
from running import physio, store, text, units, workouts
from running.sessions import HARD_KINDS

PEAK_KM = {"5k": 32.0, "10k": 42.0, "hm": 50.0, "m": 65.0}
LONG_TARGET_KM = {"5k": 10.0, "10k": 14.0, "hm": 19.0, "m": 32.0}
# Weeks of reduced volume *including* the race week: a marathon gets two
# taper weeks plus race week, a 5 / 10 km only a lighter race week.
TAPER_WEEKS = {"5k": 1, "10k": 1, "hm": 2, "m": 3}
GUARD = 1.3
GUARD_WEEKS = 4
MAX_STEP_KM = 6.0
LONG_STEP_KM = {"5k": 1.0, "10k": 1.5, "hm": 1.5, "m": 2.0}
HARD_TYPES = ("tempo", "threshold", "intervals", "race", "long")


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


def _volumes(weeks: list[dict[str, Any]], base: dict[str, Any], request: PlanRequest) -> None:
    """Fill ``volume_km`` / ``long_km`` / ``recovery`` per week, in place."""
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

    history = list(base["history_km"][-GUARD_WEEKS:])
    long_now = max(base["long_km_6w"], 5.0)
    long_target = LONG_TARGET_KM[request.distance]
    long_share = 0.5 if days <= 3 else 0.42 if request.distance != "m" else 0.5
    last_build = start_km
    last_long = long_now
    for index, week in enumerate(weeks):
        chronic = history[-GUARD_WEEKS:]
        guard = GUARD * (sum(chronic) / len(chronic)) if chronic else start_km
        if week["phase"] in ("base", "build", "peak"):
            position = build.index(week)
            recovery = (position + 1) % cycle == 0 and position != len(build) - 1
            if position == 0 and base.get("after_race"):
                # The week after a goal race: recover before building again.
                volume, long_km = 0.7 * start_km, 0.7 * long_now
                recovery = True
            elif recovery:
                volume = 0.75 * last_build
                long_km = 0.75 * last_long
            else:
                volume = min(last_build + step if position else start_km, peak, max(guard, start_km))
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
        history.append(volume)


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


QUALITY_BY_PHASE = {
    "5k": {"base": ["tempo"], "build": ["intervals", "threshold"], "peak": ["intervals", "threshold"]},
    "10k": {"base": ["tempo"], "build": ["threshold", "intervals"], "peak": ["threshold", "intervals"]},
    "hm": {"base": ["tempo"], "build": ["threshold", "intervals"], "peak": ["threshold", "tempo"]},
    "m": {"base": ["tempo"], "build": ["threshold", "tempo"], "peak": ["tempo", "threshold"]},
}


def _step(kind: str, *, km: float | None = None, s: float | None = None,
          pace: tuple[float, float] | None = None) -> dict[str, Any]:
    """One workout step: a distance or a time, optionally a pace band (min/km)."""
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





def _session(
    kind: str,
    date: dt.date,
    week: dict[str, Any],
    km: float,
    paces: dict[str, tuple[float, float]],
    hr_max: float | None,
    distance: str,
    race_pace: float | None,
) -> dict[str, Any]:
    """One session: type, distance, pace and HR band, workout steps, and the
    ``text`` code its title, main set and purpose are written from (text.py)."""
    easy = paces.get("E")
    hr_easy = physio.hr_band(hr_max, *physio.HR_FRACTIONS["E"])
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
        session.update(
            text={"key": kind, **({"strides": week["phase"] in ("build", "peak")} if kind == "easy" else {})},
            distance_km=km,
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=hr_easy if kind == "easy" else physio.hr_band(hr_max, 0.6, 0.72),
            steps=[_step("run", km=km, pace=band)],
        )
    elif kind == "long":
        spec: dict[str, Any] = {"key": "long"}
        steps = [_step("run", km=km, pace=easy)]
        if race_pace and week["phase"] == "peak" and distance in ("hm", "m"):
            part = min(round(km * (0.35 if distance == "m" else 0.3)), 14 if distance == "m" else 8)
            steps = [_step("run", km=km - part, pace=easy),
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
    elif kind == "threshold":
        band = paces.get("T")
        # Daniels: threshold work up to ~10% of the week's volume per session.
        work = max(3.0, min(10.0, 0.12 * week["volume_km"]))
        rep = 2.0 if work >= 6 else 1.0 if work < 4 else 1.6
        reps = max(2, round(work / rep))
        work = reps * rep
        session.update(
            text={"key": "threshold", "reps": int(reps), "rep": float(rep)},
            distance_km=round(work + 3.5 + 0.2 * (reps - 1), 1),
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=physio.hr_band(hr_max, *physio.HR_FRACTIONS["T"]),
            steps=[_step("warmup", km=2.0, pace=easy),
                   _repeat(reps, _step("run", km=rep, pace=band), _step("recovery", s=60)),
                   _step("cooldown", km=1.5, pace=easy)],
        )
    elif kind == "intervals":
        band = paces.get("I")
        rep = {"5k": 0.8, "10k": 1.0, "hm": 1.0, "m": 1.0}[distance]
        # Daniels: interval work up to ~8% of the week's volume (and <= 8 km).
        reps = max(3, min(8, round(max(3.0, min(8.0, 0.08 * week["volume_km"])) / rep)))
        session.update(
            text={"key": "intervals", "reps": int(reps), "rep": float(rep)},
            distance_km=round(reps * rep * 1.5 + 3.5, 1),
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=physio.hr_band(hr_max, *physio.HR_FRACTIONS["I"]),
            steps=[_step("warmup", km=2.0, pace=easy),
                   _repeat(reps, _step("run", km=rep, pace=band),
                           _step("recovery", s=rep * (sum(band) / 2 if band else 5.0) * 60)),
                   _step("cooldown", km=1.5, pace=easy)],
        )
    elif kind == "tempo":
        band = paces.get("M") if distance in ("m", "hm") or week["phase"] == "base" else paces.get("T")
        if race_pace and week["phase"] == "peak" and distance in ("hm", "m"):
            band = (race_pace * 0.99, race_pace * 1.01)
        work = max(3.0, min(14.0 if distance == "m" else 8.0, 0.2 * week["volume_km"]))
        session.update(
            text={"key": "tempo", "work": round(float(work), 1), "distance": distance},
            distance_km=round(work + 3.5, 1),
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=physio.hr_band(hr_max, *physio.HR_FRACTIONS["M"]),
            steps=[_step("warmup", km=2.0, pace=easy), _step("run", km=round(work, 1), pace=band),
                   _step("cooldown", km=1.5, pace=easy)],
        )
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
    session["duration_min"] = (
        round(session["distance_km"] * ((session.get("pace_lo") or 6.5) + (session.get("pace_hi") or 6.5)) / 2)
        if session.get("distance_km")
        else None
    )
    session.update(text.session_text(session))
    return session


def generate(
    request: PlanRequest,
    runs: pd.DataFrame,
    result: dict[str, Any],
    *,
    anchor: pd.Timestamp | None = None,
    keep: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A plan toward one race (``generate_goals`` with a single goal)."""
    errors = request.validate()
    if errors:
        raise ValueError(" ".join(errors))
    settings = PlanSettings(run_days=list(request.run_days), long_day=request.long_day, start=request.start,
                            max_weekly_km=request.max_weekly_km)
    goal = {"race_id": request.race_id, "name": request.name, "distance": request.distance,
            "date": request.race_date.isoformat(), "goal_s": request.goal_s, "priority": request.priority}
    plan = generate_goals(settings, [goal], runs, result, anchor=anchor, keep=keep)
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
) -> dict[str, Any]:
    """Build one plan (store.validate_plan-compatible) through every goal ahead.

    Each race gets its own block: built from where the previous one ended,
    tapered by the race's priority (A: the distance's taper, B/C: a lighter
    race week only), and after an A race or a half / full marathon the next
    block opens with a recovery week. ``result`` is a ``forecast.forecast``
    output; ``keep`` holds sessions that already happened (kept unchanged).
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
    hr_max = result.get("hr_max")
    paces = physio.training_paces(vdot)
    base0 = baseline(runs, pd.Timestamp(anchor), vdot)
    warnings: list[dict[str, Any]] = []
    if base0["weekly_km_4w"] < 5:
        warnings.append({"key": "no_running"})
    kept_dates = {s["date"] for s in keep or []}
    done = already_run(runs, start)

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
                sessions.append({**_session("race", request.race_date, week, 0.0, paces, hr_max, request.distance,
                                            race_pace), "race_id": request.race_id})
            continue
        errors = request.validate()
        if errors:
            raise ValueError(" ".join(errors))
        block = _weeks(request, block_start, offset=len(weeks))
        if index == 0 and len(block) < 3:
            warnings.append({"key": "short"})
        _volumes(block, base, request)
        sessions.extend(_block_sessions(block, request, settings, base, paces, hr_max, race_pace, kept_dates,
                                        done if index == 0 else None, last_race))
        last_race = goal
        weeks.extend(block)
        base = _carried(base0, weeks, goal)
        race_monday = request.race_date - dt.timedelta(days=request.race_date.weekday())
        block_start = max(block_start, race_monday + dt.timedelta(days=7))

    sessions = sorted((keep or []) + sessions, key=lambda s: s["date"])
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
            "start": start.isoformat(),
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
        return 0
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
    hr_max: float | None,
    race_pace: float | None,
    kept_dates: set[str],
    done: dict[str, Any] | None = None,
    last_race: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Sessions of one block, in place of its weeks' volumes.

    ``done`` (``already_run``) is what was run before the start: this week's
    quality and long run count toward the week, and no quality session lands
    next to a hard day that really happened. Every change a rule makes to the
    pattern leaves a ``why`` code on the session (text.why writes it out).
    """
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
        types = QUALITY_BY_PHASE[request.distance].get(phase if phase in ("base", "build", "peak") else "peak")
        if phase == "taper":
            types = ["intervals" if request.distance in ("5k", "10k") else "threshold"]
        why: dict[str, list[dict[str, Any]]] = {}
        this_week = done is not None and done["monday"] == week["monday"]
        done_km, long_done = (done["km"], bool(done["long"])) if this_week else (0.0, False)
        pattern = place_hard_days(run_days, long_day, quality_wanted)
        quality_days = pattern
        if this_week and done["quality"]:
            quality_days = place_hard_days(run_days, long_day, max(0, quality_wanted - len(done["quality"])))
        hard_done = done["hard"] if done else []
        week_sessions: list[tuple[int, str]] = []
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
                kind = types[quality_days.index(day) % len(types)]
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
            session = _session(kind, date, week, km if kind == "long" else 6.0, paces, hr_max,
                               request.distance, race_pace)
            if kind == "race":
                session["race_id"] = request.race_id
            built.append(session)
        # A low-volume week cannot carry two quality sessions plus a long run:
        # drop quality (the later one first) rather than overshoot the volume.
        def fixed_km() -> float:
            return sum(s["distance_km"] for s in built if s["type"] not in ("easy", "race"))

        quality = [s for s in built if s["type"] in ("tempo", "threshold", "intervals")]
        easy_count = sum(1 for s in built if s["type"] == "easy")
        # One quality session stays when the record shows it is tolerated.
        keep_one = 1 if (base["hard_per_week_4w"] >= 0.75 or week["volume_km"] >= 15) else 0
        while len(quality) > keep_one and fixed_km() + 3.0 * easy_count > week["volume_km"] * 1.1:
            dropped = quality.pop()
            dropped.update(_session("easy", dt.date.fromisoformat(dropped["date"]), week, 3.0, paces,
                                    hr_max, request.distance, race_pace))
            easy_count += 1
        # Easy days absorb what is left of the weekly volume.
        fixed = fixed_km()
        easy = [s for s in built if s["type"] == "easy"]
        if easy:
            share = max(0.0, week["volume_km"] - fixed - done_km) / len(easy)
            cap = max(4.0, min(12.0, 0.8 * week["long_km"] if week["long_km"] else 10.0))
            share = min(max(share, 3.0), cap)
            # The day after a long run or hard session is the recovery run.
            hard_dates = {s["date"] for s in built if s["type"] in HARD_TYPES}
            for s in easy:
                previous = (dt.date.fromisoformat(s["date"]) - dt.timedelta(days=1)).isoformat()
                kind = "recovery" if previous in hard_dates and len(run_days) >= 4 else "easy"
                replacement = _session(kind, dt.date.fromisoformat(s["date"]), week,
                                       share * (0.75 if kind == "recovery" else 1.0), paces, hr_max,
                                       request.distance, race_pace)
                s.clear()
                s.update(replacement)
        for s in built:
            if s["date"] in why and any(w["key"] == "shakeout" for w in why[s["date"]]):
                s.update(_session("easy", dt.date.fromisoformat(s["date"]), {**week, "phase": "build"}, 3.0, paces,
                                  hr_max, request.distance, race_pace))
                s["phase"] = week["phase"]
            if s["type"] == "recovery" and s["date"] > request.race_date.isoformat():
                s.update(_session("recovery", dt.date.fromisoformat(s["date"]), week,
                                  min(s["distance_km"], 5.0), paces, hr_max, request.distance, race_pace))
            if s["date"] in why:
                s["why"] = why[s["date"]]
        week["planned_km"] = round(sum(s["distance_km"] or 0 for s in built), 1)  # the race counts too
        sessions.extend(built)
    return sessions


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
          laps: pd.DataFrame | None = None) -> pd.DataFrame:
    """Each planned session next to the run that fulfilled it (if any).

    A run matches a session on the same date first, then one day either side
    (a session moved by a day is still the same session). A stored status set
    by hand wins over the automatic one. With ``laps`` (table ``run_laps``),
    quality sessions are also compared rep by rep.
    """
    today = today or dt.date.today()
    by_activity = dict(tuple(laps.groupby("activity_id"))) if laps is not None and not laps.empty else {}
    rows = []
    used: set[int] = set()
    sessions = [s for s in plan.get("sessions", []) if s.get("type") != "rest"]
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
    return pd.DataFrame(rows)


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
    }


# --------------------------------------------------------------------------
# changing a plan


def replan(
    plan: dict[str, Any],
    runs: pd.DataFrame,
    result: dict[str, Any],
    today: dt.date | None = None,
    goals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild everything from ``today`` on with fresh data; the past stays as it was.

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
    )
    keep = [s for s in plan.get("sessions", []) if s["date"] < today.isoformat()]
    fresh = generate_goals(settings, plan_goals(plan) if goals is None else goals, runs, result, keep=keep)
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
        if reason == "sick" and date < today + dt.timedelta(days=4):
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
    for quality): the morning's decision when recovery says no."""
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
    _log(plan, "soften", session_id)
    return plan


def _past() -> str:
    return i18n.tr(pl="Sesja jest w przeszłości.", en="The session is in the past.")


def postpone(plan: dict[str, Any], session_id: str, today: dt.date | None = None) -> dict[str, Any]:
    """Move a session one day later, swapping with whatever sat there.

    Refuses when the move would put two hard days side by side -- the rule
    the generator keeps, kept here too.
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
    other = next((s for s in plan.get("sessions", []) if s["date"] == target.isoformat()), None)
    if other is not None and other["type"] == "race":
        raise ValueError(tr(pl="Następnego dnia jest start.", en="The race is the next day."))
    moved = {s["id"]: s["date"] for s in plan.get("sessions", [])}
    moved[session["id"]] = target.isoformat()
    if other is not None:
        moved[other["id"]] = date.isoformat()
    hard = sorted(dt.date.fromisoformat(moved[s["id"]]) for s in plan.get("sessions", [])
                  if s["type"] in HARD_TYPES)
    if any((b - a).days == 1 for a, b in zip(hard, hard[1:])):
        raise ValueError(tr(pl="Po przesunięciu dwa mocne dni wypadłyby obok siebie — lepiej zamienić na spokojny.",
                            en="After the move two hard days would sit side by side — better swap it for an easy "
                               "run."))
    session["date"] = target.isoformat()
    if other is not None:
        other["date"] = date.isoformat()
    plan["sessions"] = sorted(plan["sessions"], key=lambda s: s["date"])
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
