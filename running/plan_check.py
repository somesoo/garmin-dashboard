"""The plan generator checked against the runner's own history.

At past anchor days the generator builds a plan toward a race 12 weeks
later, from the data up to that day only, and two things are measured:

* **rules** -- whether the plan breaks one of its own rules (a run over 1.1x
  the longest of 30 days, two hard days in a row, strength the day before a
  hard day, quality within 3 days or a long run within 6 days of the race).
  Every count should be zero; a non-zero one is a bug, not a statistic.
* **realism** -- the first four weeks' planned kilometres against what the
  runner then really ran. Much more planned than run means the plan starts
  above what this runner sustains.

``python -m running.plan_check`` prints the summary for the warehouse.
"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Any

import pandas as pd

import i18n
from running import forecast, plan as planning

RULES = ("spike", "hard_adjacent", "strength_before_hard", "quality_near_race", "long_near_race")


def violations(plan: dict[str, Any], runs: pd.DataFrame, start: dt.date) -> dict[str, int]:
    """Rule breaks of one generated plan from ``start`` on."""
    sessions = [s for s in plan.get("sessions", []) if s["date"] >= start.isoformat()]
    out = {rule: 0 for rule in RULES}
    out["spike"] = len(planning.spikes({"sessions": sessions}, runs, start))
    hard = sorted({dt.date.fromisoformat(s["date"]) for s in sessions if s["type"] in planning.HARD_TYPES})
    out["hard_adjacent"] = sum(1 for a, b in zip(hard, hard[1:]) if (b - a).days == 1)
    hard_days = {d.isoformat() for d in hard}
    out["strength_before_hard"] = sum(
        1 for s in sessions if s["type"] == "strength"
        and (dt.date.fromisoformat(s["date"]) + dt.timedelta(days=1)).isoformat() in hard_days)
    for race in (s for s in sessions if s["type"] == "race"):
        day = dt.date.fromisoformat(race["date"])
        for s in sessions:
            gap = (day - dt.date.fromisoformat(s["date"])).days
            if 0 < gap <= planning.QUALITY_GAP_DAYS and s["type"] in planning.QUALITY_TYPES:
                out["quality_near_race"] += 1
            if 0 < gap <= planning.LONG_GAP_DAYS and s["type"] == "long":
                out["long_near_race"] += 1
    return out


def realism(plan: dict[str, Any], runs: pd.DataFrame, start: dt.date, weeks: int = 4) -> dict[str, Any]:
    """Planned against really run in the plan's first ``weeks`` weeks."""
    end = start + dt.timedelta(days=7 * weeks)
    planned = sum(s.get("distance_km") or 0 for s in plan.get("sessions", [])
                  if start.isoformat() <= s["date"] < end.isoformat() and s["type"] in planning.RUN_TYPES)
    window = runs[(runs["day"] >= pd.Timestamp(start)) & (runs["day"] < pd.Timestamp(end))]
    actual = float(window["distance_km"].sum())
    longest_plan = max((s.get("distance_km") or 0 for s in plan.get("sessions", [])
                        if start.isoformat() <= s["date"] < end.isoformat() and s["type"] == "long"), default=0.0)
    return {"planned_km": round(planned, 1), "actual_km": round(actual, 1),
            "ratio": round(actual / planned, 2) if planned else None,
            "long_planned_km": round(longest_plan, 1),
            "long_actual_km": round(float(window["distance_km"].max()), 1) if not window.empty else 0.0}


def backtest(runs: pd.DataFrame, efforts: pd.DataFrame, daily: pd.DataFrame, *, hr_max: float | None = None,
             every_days: int = 28, race_weeks: int = 12, distance: str = "hm", since_days: int = 730,
             run_days: list[int] | None = None, history_days: int = 56, follow_days: int = 28) -> pd.DataFrame:
    """One row per anchor: rule breaks and realism of the plan made that day.

    Anchors need ``history_days`` of data before them and ``follow_days`` after
    (what was really run is the realism check)."""
    if runs is None or runs.empty:
        return pd.DataFrame()
    last = runs["day"].max()
    first = max(runs["day"].min() + pd.Timedelta(days=history_days), last - pd.Timedelta(days=since_days))
    rows = []
    for anchor in pd.date_range(first, last - pd.Timedelta(days=follow_days), freq=f"{every_days}D"):
        before = runs[runs["day"] <= anchor]
        if len(before[before["day"] > anchor - pd.Timedelta(days=28)]) < 3:
            continue  # not training then: nothing to plan from
        result = forecast.forecast(before, efforts[pd.to_datetime(efforts["day"]) <= anchor], daily, anchor,
                                   hr_max=hr_max)
        if result.get("status") != "ok":
            continue
        start = (anchor + pd.Timedelta(days=1)).date()
        goal = {"race_id": None, "name": None, "distance": distance,
                "date": (start + dt.timedelta(weeks=race_weeks)).isoformat(), "goal_s": None, "priority": "A"}
        settings = planning.PlanSettings(run_days=run_days or [1, 3, 6], long_day=6, start=start)
        try:
            plan = planning.generate_goals(settings, [goal], before, result, anchor=anchor)
        except ValueError:
            continue
        rows.append({"anchor": anchor.date(), "vdot": round(float(result["vdot"]), 1),
                     **violations(plan, before, start), **realism(plan, runs, start)})
    return pd.DataFrame(rows)


def summary(table: pd.DataFrame) -> dict[str, Any]:
    if table is None or table.empty:
        return {"plans": 0}
    ratios = table["ratio"].dropna()
    return {
        "plans": int(len(table)),
        "broken": {rule: int(table[rule].sum()) for rule in RULES},
        "ratio_median": round(float(ratios.median()), 2) if len(ratios) else None,
        "over_planned": int((ratios < 0.7).sum()),
        "under_planned": int((ratios > 1.3).sum()),
    }


def main(argv: list[str] | None = None) -> int:
    tr = i18n.tr
    parser = argparse.ArgumentParser(description=tr(pl="Generator planu sprawdzony na Twojej historii",
                                                    en="The plan generator checked on your history"))
    parser.add_argument("--lang", choices=list(i18n.LANGS))
    args = parser.parse_args(argv)
    if args.lang:
        i18n.force(args.lang)
    from running.coach import load_warehouse

    runs, efforts, daily = load_warehouse()
    hr_max = float(runs["hr_max_used"].dropna().iloc[0]) if "hr_max_used" in runs and runs["hr_max_used"].notna().any() \
        else None
    table = backtest(runs, efforts, daily, hr_max=hr_max)
    print(table.to_string(index=False) if not table.empty else tr(pl="Za mało historii.", en="Not enough history."))
    print(summary(table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
