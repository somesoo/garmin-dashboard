"""Builds the materialised running tables; called from ``analytics.main``.

Two passes, because classification and fitness need each other: a first
classification by heart rate and workout structure feeds the effort table and
a first fitness history; that history gives every run the runner's own paces
for its date, and the second classification judges tempo and threshold
against them.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from running import forecast, physio, sessions


def context(activities: pd.DataFrame, daily: pd.DataFrame) -> dict[str, Any]:
    runs = sessions.select_runs(activities)
    hr_max = physio.robust_hr_max(runs["max_hr"]) if not runs.empty else None
    daily = daily.copy() if daily is not None else pd.DataFrame()
    if not daily.empty:
        daily["day"] = pd.to_datetime(daily["day"])
    return {"runs": runs, "hr_max": hr_max, "daily": daily}


def build(
    activities: pd.DataFrame,
    daily: pd.DataFrame,
    routes: pd.DataFrame,
    segments: pd.DataFrame,
    manual: dict[int, str] | None = None,
) -> dict[str, pd.DataFrame]:
    ctx = context(activities, daily)
    runs, hr_max, daily = ctx["runs"], ctx["hr_max"], ctx["daily"]
    if runs.empty:
        return {"run_sessions": pd.DataFrame(), "run_splits": pd.DataFrame(),
                "run_efforts": pd.DataFrame(), "run_forecast": pd.DataFrame()}

    first = sessions.classify(runs, segments, routes, hr_max, manual=manual)
    efforts = forecast.effort_quality(sessions.efforts(first, routes, segments), first, hr_max)
    rough = forecast.history(first, efforts, daily, hr_max=hr_max, step_days=7)
    vdot_by_day = (
        rough.drop_duplicates("day").set_index("day")["vdot"].sort_index() if not rough.empty else None
    )

    final = sessions.classify(runs, segments, routes, hr_max, vdot_by_day=vdot_by_day, manual=manual)
    efforts = forecast.effort_quality(efforts.drop(columns=["hr_frac", "minutes", "near_max"]), final, hr_max)
    history = forecast.history(final, efforts, daily, hr_max=hr_max, step_days=7)
    final["hr_max_used"] = hr_max

    splits = []
    if routes is not None and not routes.empty:
        ids = set(final["activity_id"])
        for activity_id, track in routes.groupby("activity_id"):
            if int(activity_id) not in ids:
                continue
            table = sessions.km_splits(track)
            if not table.empty:
                splits.append(table.assign(activity_id=int(activity_id)))
    return {
        "run_sessions": final,
        "run_splits": pd.concat(splits, ignore_index=True) if splits else pd.DataFrame(),
        "run_efforts": efforts,
        "run_forecast": history,
    }


def rebuild() -> dict[str, int]:
    """Recompute only the running tables from the warehouse (after a race is linked)."""
    import db
    from etl.load import write_table

    from running import store

    tables = build(db.table("activities"), db.table("daily"), db.table("routes"),
                   db.table("activity_segments"), manual=store.manual_kinds())
    for name, table in tables.items():
        if table is not None and not table.empty:
            write_table(table, name)
    return {name: int(len(table)) for name, table in tables.items()}
