"""What to do next: every discipline scored for today, with the reasons as codes.

Hard filters first -- a discipline out of season (central Poland), needing
something the viewer said is out of reach (for one never tried: only a trip), or impossible at today's ceiling (a squash match on a
recovery day) is not ranked, it is listed in ``skipped`` with the reason.

Then points, all visible in ``reasons``:

* ``variety``  -- days since it was last done, up to 28 (+0..20); never done +12.
* ``dominant`` -- its share of the last 28 days' minutes (-30 x share).
* ``gap``      -- how much of what it trains the last 28 days lacked (+0..25).
* ``tired``    -- the fatigue of the systems it loads (-35 x sum of fatigue x weight);
                  ``quiet`` when no single system carries it (not worth a sentence).
* ``fresh``    -- its main system is rested while another one is tired (+5).
* ``waste``    -- a moderate or hard day spent below its ceiling (-5 per level).
* ``before``   -- a hard run or a long run planned for tomorrow: leg-heavy
                  disciplines lose 10 and stop at ``moderate``.
* ``familiar`` -- done at least three times (+5): you know you like it.

A small jitter fixed by date and discipline (+-3) keeps two near-equal options
from always appearing in the same order -- curiosity is the point of the page.

Intensity is ``min(readiness level, the discipline's ceiling)``; minutes are the
person's median session (two years, >= 3 sessions) or the catalog's, scaled
by intensity.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Iterable

import pandas as pd

from sport import catalog, variety

LEVEL_SCALE = {"recover": 0.5, "easy": 0.75, "moderate": 1.0, "hard": 1.0}
NOVELTY = 12.0
MODERATE = catalog.LEVELS.index("moderate")
ADDON_GAP = 0.5
TIRED_MIN = 0.25  # fatigue x weight of the worst system: below it a trace, not a reason
LEG_HEAVY = 0.7  # impact + legs: a ride counts, a swim or the gym does not
FAMILIAR = 5.0


def _jitter(day: dt.date, key: str) -> float:
    digest = hashlib.sha1(f"{day.isoformat()}:{key}".encode()).digest()
    return (digest[0] / 255 - 0.5) * 6


def _minutes(discipline: catalog.Discipline, median: float | None, level: str) -> int:
    # A record of short sessions (a swim watch stopped after the warm-up) is not a session length.
    base = median if median and median >= discipline.minutes / 2 else discipline.minutes
    return int(max(15, round(base * LEVEL_SCALE[level] / 5) * 5))


def rank(readiness: dict[str, Any], frame: pd.DataFrame, today: dt.date, *,
         available: Iterable[str] = catalog.CONDITIONS, before_key: bool = False,
         now: pd.Timestamp | None = None) -> dict[str, Any]:
    """``{"ranked": [...], "skipped": [...], "profile": DataFrame}`` for today."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp(dt.datetime.combine(today, dt.time(12)))
    available = set(available)
    ceiling = catalog.LEVELS.index(readiness.get("level") or "moderate")
    fatigue = readiness.get("systems") or {}
    done = variety.last_done(frame, now).set_index("discipline") if not frame.empty else pd.DataFrame()
    profile = variety.profile(frame, now)
    gaps = dict(zip(profile["quality"], profile["gap"]))
    recent = variety.window(frame, now, 28)
    total_28 = float(recent["minutes"].sum())

    ranked, skipped = [], []
    for key, d in catalog.DISCIPLINES.items():
        if not d.in_season(today.month):
            skipped.append({"discipline": key, "reason": "season"})
            continue
        # Something never tried means finding the venue anyway (a wall, a court in town);
        # only a trip -- water, wind, snow, mountains -- stays a hard condition for it.
        tried = key in done.index
        missing = [n for n in d.needs if n not in available and (tried or n in catalog.TRAVEL)]
        if missing:
            skipped.append({"discipline": key, "reason": "needs", "needs": missing})
            continue
        levels = d.level_range()
        if ceiling < levels.start:
            skipped.append({"discipline": key, "reason": "too_hard", "lowest": d.levels[0]})
            continue
        level = min(ceiling, levels.stop - 1)
        reasons: list[dict[str, Any]] = []

        history = done.loc[key] if key in done.index else None
        if history is None:
            reasons.append({"code": "never", "points": NOVELTY})
        else:
            days = int(history["days_ago"])
            reasons.append({"code": "variety", "points": round(min(days, 28) / 28 * 20, 1), "days": days})
            if history["sessions"] >= 3:
                reasons.append({"code": "familiar", "points": FAMILIAR, "sessions": int(history["sessions"])})
            share = float(history["minutes_28"]) / total_28 if total_28 else 0.0
            if share > 0.05:
                reasons.append({"code": "dominant", "points": round(-30 * share, 1), "share": round(share, 2)})

        trains = sum(d.trains.values()) or 1.0
        fill = sum(gaps.get(q, 0.0) * w for q, w in d.trains.items()) / trains
        top_gap = max(d.trains, key=lambda q: gaps.get(q, 0.0) * d.trains[q]) if d.trains else None
        if fill > 0.05 and top_gap and gaps.get(top_gap, 0) > 0:
            reasons.append({"code": "gap", "points": round(25 * fill, 1), "quality": top_gap})

        clash = sum(fatigue.get(s, 0.0) * w for s, w in d.load.items())
        loud = False
        if clash > 0.05:
            worst = max(d.load, key=lambda s: fatigue.get(s, 0.0) * d.load[s])
            # The points always count; the sentence only when the tired system really carries it
            # (a climber's legs at 85% fatigue x 0.2 weight is a trace, not "loads what is tired").
            loud = fatigue.get(worst, 0.0) * d.load[worst] >= TIRED_MIN
            reasons.append({"code": "tired", "points": round(-35 * clash, 1), "system": worst,
                            "fatigue": fatigue.get(worst, 0.0), "quiet": not loud})
        if not loud and d.load and max(fatigue.values(), default=0) > 0.3:
            rested = [s for s in catalog.SYSTEMS if d.load.get(s, 0) >= 0.5 and fatigue.get(s, 0.0) < 0.3]
            if rested:
                reasons.append({"code": "fresh", "points": 5.0, "system": rested[0]})

        if before_key and d.load.get("impact", 0) + d.load.get("legs", 0) >= LEG_HEAVY:
            level = min(level, catalog.LEVELS.index("moderate"))
            reasons.append({"code": "before", "points": -10.0})
        if ceiling >= MODERATE and level < ceiling:
            reasons.append({"code": "waste", "points": -5.0 * (ceiling - level)})

        score = 50 + sum(r["points"] for r in reasons) + _jitter(today, key)
        median = history["median_min"] if history is not None and pd.notna(history["median_min"]) else None
        level_code = catalog.LEVELS[level]
        ranked.append({
            "discipline": key,
            "family": d.family,
            "score": round(score, 1),
            "level": level_code,
            "minutes": _minutes(d, median, level_code),
            "new": history is None,
            "reasons": sorted(reasons, key=lambda r: -abs(r["points"])),
        })
    ranked.sort(key=lambda r: -r["score"])
    return {"ranked": ranked, "skipped": skipped, "profile": profile}


def picks(result: dict[str, Any], level: str, count: int = 3) -> dict[str, Any]:
    """``main``: the top ``count`` of what the person already does, at most one per
    family, so three cards are three different ideas -- a suggestion has to be
    something you could actually go and do tonight. ``new``: the best discipline
    never done that needs no trip (``catalog.TRAVEL``). ``addon``: on a moderate or hard day the mobility family is not
    a session but something to add -- offered when the last 28 days lacked it.
    """
    as_addon = catalog.LEVELS.index(level) >= MODERATE
    chosen, families = [], set()
    for item in result["ranked"]:
        if item["new"] or item["family"] in families or (as_addon and item["family"] == "mobility"):
            continue
        chosen.append(item)
        families.add(item["family"])
        if len(chosen) == count:
            break
    novel = next((r for r in result["ranked"] if r["new"]
                  and not set(catalog.get(r["discipline"]).needs) & set(catalog.TRAVEL)
                  and not (as_addon and r["family"] == "mobility")), None)
    addon = None
    profile = result["profile"]
    gap = float(profile.loc[profile["quality"] == "mobility", "gap"].iloc[0]) if not profile.empty else 0.0
    if as_addon and gap >= ADDON_GAP:
        addon = next((r for r in result["ranked"] if r["family"] == "mobility"), None)
        if addon is not None:
            # An add-on is not the day's session: "below today's ceiling" is no reason against it.
            addon = {**addon, "level": "easy", "minutes": 20,
                     "reasons": [r for r in addon["reasons"] if r["code"] != "waste"]}
    return {"main": chosen, "new": novel, "addon": addon}


KEY_TYPES = ("tempo", "threshold", "intervals", "race", "long")


def from_plan(plan: dict[str, Any] | None, today: dt.date) -> dict[str, Any]:
    """The running plan's say: today's sessions, and tomorrow's key run if there
    is one (``before_key`` for ``rank``) -- the legs should arrive at it fresh."""
    if not plan:
        return {"today": [], "tomorrow": None, "before_key": False}
    sessions = plan.get("sessions") or []

    def on(day: dt.date) -> list[dict]:
        return [s for s in sessions if s.get("date") == day.isoformat() and s.get("type") != "rest"]

    key = next((s for s in on(today + dt.timedelta(days=1)) if s.get("type") in KEY_TYPES), None)
    return {"today": on(today), "tomorrow": key, "before_key": key is not None}
