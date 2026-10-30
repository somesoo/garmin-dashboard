"""What the record says about variety: when each discipline last happened,
which qualities the last weeks built, and how many sports effectively shared
the time.

``profile`` weighs each session's minutes by the catalog's ``trains`` and
compares the shares with ``TARGET`` -- a deliberately plain all-round mix for
someone whose base is endurance (not a prescription from a study: a reference
line that makes "four weeks of nothing but aerobic work" visible).

``diversity`` is the effective number of disciplines, exp(Shannon entropy) of
minutes: 1.0 = one sport only, 3.0 = time split as if evenly between three.
It does not care how many sports were touched once -- ten minutes of yoga next
to ten hours of running barely moves it, which is the point.
"""

from __future__ import annotations

import math

import pandas as pd

from sport import catalog

TARGET = {"aerobic": 0.45, "power": 0.15, "strength": 0.15, "skill": 0.15, "mobility": 0.10}


def window(frame: pd.DataFrame, end: pd.Timestamp, days: int) -> pd.DataFrame:
    return frame[(frame["start_local"] <= end) & (frame["start_local"] > end - pd.Timedelta(days=days))]


def profile(frame: pd.DataFrame, end: pd.Timestamp, days: int = 28) -> pd.DataFrame:
    """Share of each quality in the window against ``TARGET``; ``gap`` 0-1 = how much is missing."""
    part = window(frame, end, days)
    totals = {q: 0.0 for q in catalog.QUALITIES}
    for item in part.itertuples(index=False):
        if item.discipline not in catalog.DISCIPLINES:
            continue
        for quality, weight in catalog.get(item.discipline).trains.items():
            totals[quality] += float(item.minutes) * weight
    whole = sum(totals.values())
    rows = []
    for quality in catalog.QUALITIES:
        share = totals[quality] / whole if whole else 0.0
        target = TARGET[quality]
        rows.append({"quality": quality, "share": round(share, 3), "target": target,
                     "gap": round(max(0.0, target - share) / target, 2)})
    return pd.DataFrame(rows)


def last_done(frame: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    """Per discipline: last time, sessions all-time and in a year, minutes in 28 days."""
    if frame.empty:
        return pd.DataFrame(columns=["discipline", "last", "days_ago", "sessions", "sessions_365", "hours",
                                     "minutes_28", "median_min"])
    past = frame[frame["start_local"] <= end]
    rows = []
    for key, group in past.groupby("discipline"):
        recent = group[group["start_local"] > end - pd.Timedelta(days=730)]
        rows.append({
            "discipline": key,
            "last": group["day"].max(),
            "days_ago": int((end.normalize() - group["day"].max()).days),
            "sessions": len(group),
            "sessions_365": int((group["start_local"] > end - pd.Timedelta(days=365)).sum()),
            "hours": round(float(group["minutes"].sum()) / 60, 1),
            "minutes_28": float(window(group, end, 28)["minutes"].sum()),
            "median_min": float(recent["minutes"].median()) if len(recent) >= 3 else None,
        })
    return pd.DataFrame(rows).sort_values("days_ago").reset_index(drop=True)


def effective_number(minutes: pd.Series) -> float:
    total = float(minutes.sum())
    if total <= 0:
        return 0.0
    shares = [m / total for m in minutes if m > 0]
    return round(math.exp(-sum(p * math.log(p) for p in shares)), 2)


def diversity(frame: pd.DataFrame, end: pd.Timestamp, weeks: int = 52, days: int = 28) -> pd.DataFrame:
    """Effective number of disciplines over a rolling ``days`` window, once a week."""
    rows = []
    for offset in range(weeks - 1, -1, -1):
        edge = end - pd.Timedelta(weeks=offset)
        part = window(frame, edge, days)
        rows.append({"day": edge.normalize(), "diversity": effective_number(part.groupby("discipline")["minutes"].sum()),
                     "disciplines": int(part["discipline"].nunique()), "hours": round(part["minutes"].sum() / 60, 1)})
    return pd.DataFrame(rows)


def weekly_mix(frame: pd.DataFrame, end: pd.Timestamp, weeks: int, top: int = 2) -> tuple[pd.DataFrame, list[str]]:
    """Hours per week for the ``top`` disciplines of the period and the rest folded
    into ``other`` -- three series at most, as the palette allows."""
    start = (end - pd.Timedelta(weeks=weeks)).normalize()
    part = frame[(frame["start_local"] > start) & (frame["start_local"] <= end)].copy()
    if part.empty:
        return pd.DataFrame(), []
    leaders = part.groupby("discipline")["minutes"].sum().sort_values(ascending=False).head(top).index.tolist()
    part["series"] = part["discipline"].where(part["discipline"].isin(leaders), "other")
    part["week"] = part["day"] - pd.to_timedelta(part["day"].dt.weekday, unit="D")
    table = part.pivot_table(index="week", columns="series", values="minutes", aggfunc="sum", fill_value=0) / 60
    weeks_index = pd.date_range(start - pd.to_timedelta(start.weekday(), unit="D"), end.normalize(), freq="7D")
    table = table.reindex(weeks_index, fill_value=0).round(1)
    columns = [c for c in [*leaders, "other"] if c in table.columns]
    return table[columns].rename_axis("week").reset_index(), columns
