"""Shared shell for the dashboard pages: data access, chrome, small helpers.

Each page is a module under ``views/`` that calls into here for its tables and
for the handful of layout primitives the whole app uses. Keeping the chrome in
one place is what lets the pages stay a single column of full-width charts:
nothing has to reserve space for navigation or filters.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

import config
import db

PAGE_STYLE = """
<style>
  /* One column, generous measure, no card chrome. The page is a document:
     a lead paragraph, then the chart it describes, full width. */
  .block-container {padding-top: 1.6rem; padding-bottom: 5rem; max-width: 1180px;}
  h1 {font-size: 1.55rem !important; font-weight: 650; letter-spacing: -0.015em;
      margin-bottom: 0.1rem !important;}
  h2 {font-size: 1.05rem !important; font-weight: 620; letter-spacing: -0.005em;
      margin: 2.4rem 0 0.15rem 0 !important;}
  h3 {font-size: 0.9rem !important; font-weight: 600; margin: 1.1rem 0 0 0 !important;}
  [data-testid="stMetricValue"] {font-size: 1.45rem; font-weight: 600;}
  [data-testid="stMetricLabel"] {opacity: 0.68; font-size: 0.78rem;}
  [data-testid="stCaptionContainer"] {max-width: 72ch; line-height: 1.55; opacity: 0.85;}
  [data-testid="stSidebarNav"] {padding-top: 0.5rem;}
  div[data-testid="stExpander"] details summary p {font-size: 0.8rem; opacity: 0.65;}
  div[data-testid="stExpander"] {border: none; border-top: 1px solid rgba(128,128,128,0.18);
      border-radius: 0;}
  /* The globe bleeds past the text measure -- it is the one element that should
     feel bigger than the document -- and a sphere floating on a flat page needs
     something behind it, so the stage carries its own soft halo. */
  .st-key-globe_stage {margin: 0 -3.5rem;
      background: radial-gradient(circle at 50% 47%,
          rgba(42,120,214,0.20) 0%, rgba(42,120,214,0.07) 36%,
          rgba(42,120,214,0.00) 61%);}
  .st-key-globe_stage [data-testid="stPlotlyChart"] {margin: 0;}
  hr {margin: 2.2rem 0 0 0; opacity: 0.25;}
</style>
"""

WINDOWS = {"30 dni": 30, "90 dni": 90, "rok": 365, "wszystko": None}


@st.cache_data(show_spinner=False)
def _table(name: str, _build: str) -> pd.DataFrame:
    return db.table(name)


@st.cache_data(show_spinner=False)
def _sql(sql: str, _build: str) -> pd.DataFrame:
    return db.query(sql)


@st.cache_data(show_spinner=False)
def _models(_build: str) -> dict:
    path = config.TABLES / "models.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def build_id() -> str:
    return db.state().get("built_at", "none")


def table(name: str) -> pd.DataFrame:
    """A warehouse table, cached until the ETL rebuilds it."""
    return _table(name, build_id())


def query(sql: str) -> pd.DataFrame:
    return _sql(sql, build_id())


def models() -> dict:
    return _models(build_id())


def state() -> dict[str, Any]:
    return db.state()


def daily() -> pd.DataFrame:
    frame = table("daily")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


def window_days() -> int | None:
    """The active time window, chosen once in the sidebar for every page."""
    return WINDOWS.get(st.session_state.get("range_choice", "90 dni"))


def cutoff() -> pd.Timestamp | None:
    span = window_days()
    if span is None:
        return None
    frame = daily()
    if frame.empty:
        return None
    return frame["day"].max() - pd.Timedelta(days=span)


def clip(frame: pd.DataFrame, column: str = "day") -> pd.DataFrame:
    """Restrict a table to the active window."""
    edge = cutoff()
    if frame.empty or edge is None or column not in frame.columns:
        return frame
    out = frame.copy()
    out[column] = pd.to_datetime(out[column])
    return out[out[column] >= edge]


def range_picker() -> None:
    """The one global filter, rendered once in the sidebar."""
    st.sidebar.radio(
        "Zakres",
        list(WINDOWS),
        index=1,
        key="range_choice",
        horizontal=True,
    )


def footer() -> None:
    """Warehouse status, kept out of the canvas."""
    info = state()
    st.sidebar.divider()
    st.sidebar.caption(
        f"**{info.get('days', 0)}** dni · **{info.get('activities', 0)}** aktywności · "
        f"**{info.get('routes', 0)}** tras\n\n"
        f"{info.get('first_day')} → {info.get('last_day')}\n\n"
        f"zbudowano: {info.get('built_at', '—')}"
    )
    if st.sidebar.button("Odśwież dane", width="stretch"):
        st.cache_data.clear()
        st.rerun()


def lead(title: str, note: str | None = None) -> None:
    """Section heading plus the sentence that says how to read what follows."""
    st.markdown(f"## {title}")
    if note:
        st.caption(note)


def sub(title: str, note: str | None = None) -> None:
    st.markdown(f"### {title}")
    if note:
        st.caption(note)


def metrics(row: pd.Series | None, previous: pd.Series | None, specs: list[tuple[str, str, str]]) -> None:
    columns = st.columns(len(specs))
    for column, (field, label, unit) in zip(columns, specs):
        value = row.get(field) if row is not None else None
        if value is None or pd.isna(value):
            column.metric(label, "—")
            continue
        delta = None
        before = previous.get(field) if previous is not None else None
        if before is not None and not pd.isna(before):
            diff = float(value) - float(before)
            delta = f"{diff:+.1f}".rstrip("0").rstrip(".") + (f" {unit}" if unit else "")
        shown = f"{float(value):.1f}".rstrip("0").rstrip(".")
        column.metric(label, f"{shown}{(' ' + unit) if unit else ''}", delta)


def missing(name: str, hint: str = "") -> None:
    st.caption(f"Tabela `{name}` jest pusta. {hint}".strip())


def clock(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def latest_day() -> pd.Series | None:
    frame = daily()
    if frame.empty:
        return None
    scored = frame.dropna(subset=["readiness", "sleep_score"], how="all")
    return (scored if not scored.empty else frame).iloc[-1]


def days_since(row: pd.Series | None) -> int | None:
    if row is None:
        return None
    return (dt.date.today() - row["day"].date()).days


def has_data() -> bool:
    return not daily().empty


def no_data_screen() -> None:
    st.title("Garmin Dashboard")
    st.warning(
        "Brak danych. Uruchom `Dashboard.command` (macOS), `Dashboard.cmd` (Windows) albo "
        "`.venv/bin/python etl/run.py` (Linux)."
    )
    st.stop()


ROOT = Path(__file__).resolve().parent
