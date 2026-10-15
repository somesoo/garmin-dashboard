"""Shared plumbing for the running pages (``views/run_*``).

Data comes through ``shell.table`` like everywhere else, so a warehouse
rebuild invalidates it. The forecast itself is cheap but depends on the races
and plans the runner entered, which live outside the warehouse -- their file
stamps are part of the cache key.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd
import streamlit as st

import shell
from running import coach, forecast, plan as planning, store, units

KIND_ORDER = ["recovery", "easy", "long", "tempo", "threshold", "intervals", "race"]
CONFIDENCE_ICON = {"wysoka": "●●●", "średnia": "●●○", "niska": "●○○"}


def runs() -> pd.DataFrame:
    frame = shell.table("run_sessions")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    return frame


def efforts() -> pd.DataFrame:
    frame = shell.table("run_efforts")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


def history() -> pd.DataFrame:
    frame = shell.table("run_forecast")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


def hr_max(frame: pd.DataFrame) -> float | None:
    if frame.empty or "hr_max_used" not in frame.columns or frame["hr_max_used"].isna().all():
        return None
    return float(frame["hr_max_used"].dropna().iloc[0])


def store_stamp() -> str:
    """Changes whenever a race or plan file is written."""
    parts = []
    for path in [store.RACES, *sorted(store.PLANS.glob("*.json"))] if store.PLANS.is_dir() else [store.RACES]:
        if path.exists():
            parts.append(f"{path.name}:{path.stat().st_mtime_ns}")
    return "|".join(parts)


def upcoming_weeks(today: dt.date) -> tuple[dict[str, float], dict[str, float]]:
    """Weeks to the nearest future race per distance, and the prep its plan reaches."""
    weeks: dict[str, float] = {}
    prep: dict[str, float] = {}
    for race in store.races():
        if race.get("date", "") < today.isoformat():
            continue
        distance = race["distance"]
        if distance in weeks:
            continue
        weeks[distance] = (dt.date.fromisoformat(race["date"]) - today).days / 7
        plans = store.plans_for(race["id"])
        if plans:
            prep[distance] = planning.reached_prep(plans[0], distance)
    return weeks, prep


@st.cache_data(show_spinner=False)
def _forecast(_build: str, _stamp: str, today: str) -> dict[str, Any]:
    frame = runs()
    weeks, prep = upcoming_weeks(dt.date.fromisoformat(today))
    return forecast.forecast(frame, efforts(), shell.daily(), hr_max=hr_max(frame),
                             weeks_to_race=weeks, plan_prep=prep)


def current_forecast() -> dict[str, Any]:
    frame = runs()
    if frame.empty:
        return {"status": "insufficient", "reason": "Brak tabeli biegów."}
    return _forecast(shell.build_id(), store_stamp(), dt.date.today().isoformat())


def guard() -> pd.DataFrame | None:
    """The running tables or a clear message; None means the page should stop."""
    frame = runs()
    if frame.empty:
        st.info(
            "Brak tabel biegowych. Uruchom `analytics.py` (albo `etl/run.py`, który robi to po "
            "pobraniu) — tabele `run_*` powstają z istniejących danych, bez odpytywania Garmina."
        )
        return None
    return frame


def fmt_time(seconds: Any) -> str:
    return units.fmt_time(seconds)


def kind_label(kind: Any) -> str:
    from running.sessions import KINDS

    return KINDS.get(str(kind), str(kind))


def runs_table(frame: pd.DataFrame) -> pd.DataFrame:
    """The compact run log used on several pages."""
    out = pd.DataFrame(
        {
            "kiedy": frame["start_local"].dt.strftime("%d.%m.%Y"),
            "typ": frame["kind"].map(kind_label),
            "km": frame["distance_km"].round(2),
            "czas": (frame["duration_min"] * 60).map(units.fmt_time),
            "tempo": frame["pace_min_km"].map(lambda v: units.fmt_pace(v, False)),
            "tętno": frame["avg_hr"],
            "load": frame["training_load"],
            "nazwa": frame["name"],
        }
    )
    return out


RUN_COLUMNS = {
    "km": st.column_config.NumberColumn("km", format="%.1f"),
    "tętno": st.column_config.NumberColumn("tętno", format="%.0f"),
    "load": st.column_config.NumberColumn("load", format="%.0f"),
}


def pickable_runs(frame: pd.DataFrame, key: str, height: int | None = None) -> None:
    """Run log where clicking a row opens the session page."""
    import routing

    shown = frame.sort_values("start_local", ascending=False).reset_index(drop=True)
    event = st.dataframe(
        runs_table(shown), hide_index=True, width="stretch", column_config=RUN_COLUMNS,
        on_select="rerun", selection_mode="single-row", key=key, height=height or "auto",
    )
    rows = getattr(getattr(event, "selection", None), "rows", None) or []
    if rows:
        routing.open_run(int(shown.iloc[rows[0]]["activity_id"]))
    st.caption("Kliknij wiersz, żeby otworzyć szczegóły treningu.")


def download_brief(prefix: str) -> None:
    """Brief for the assistant as Markdown and JSON downloads."""
    frame = runs()
    if frame.empty:
        return
    data = coach.brief(frame, efforts(), shell.daily())
    columns = st.columns(2)
    columns[0].download_button(
        "Brief (Markdown)", coach.markdown(data), file_name=f"brief-{dt.date.today()}.md",
        mime="text/markdown", key=f"{prefix}_brief_md", width="stretch",
    )
    columns[1].download_button(
        "Brief (JSON)", json.dumps(data, indent=2, ensure_ascii=False, default=str),
        file_name=f"brief-{dt.date.today()}.json", mime="application/json",
        key=f"{prefix}_brief_json", width="stretch",
    )
