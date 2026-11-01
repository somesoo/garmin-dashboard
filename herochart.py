"""The hero chart of a page: a static component, like the globe and the Dzień page.

Every page (``story.py``) leads with one main chart and the facts that explain it
on both sides, each tied to its point by a leader line, with thin strips from the
neighbouring stages of the loop under it on the same time axis and one cursor
through all of them. Plotly cannot draw that: an annotation's text can sit in the
margin only at a pixel offset from its point, and the server does not know the
pixel width. The browser does, so it draws (``herochart_component/chart.js``)
and Python sends a spec -- panels, series as ``[epoch ms, value]`` pairs, facts.

The chart system's rules still hold: colours are ``theme.tokens``, no gradients,
no titles inside the chart (the page headline says what it shows), one value axis
per panel (two quantities are two panels on the shared time axis).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import i18n
import routing
import theme as tz

COMPONENT = Path(__file__).resolve().parent / "herochart_component"
_component = components.declare_component("garmin_herochart", path=str(COMPONENT))


def ms(value: Any) -> int:
    """A day as epoch milliseconds (what the browser's Date takes)."""
    return int(pd.Timestamp(value).value // 1_000_000)


def points(frame: pd.DataFrame, x: str, y: str, decimals: int = 2) -> list[list[Any]]:
    """``[[epoch ms, value or None], ...]`` from two columns, in time order."""
    if frame is None or frame.empty or y not in frame.columns:
        return []
    rows = frame[[x, y]].sort_values(x)
    out = []
    for day, value in rows.itertuples(index=False):
        number = None if value is None or (isinstance(value, float) and math.isnan(value)) else round(float(value), decimals)
        out.append([ms(day), number])
    return out


def span(values: Iterable[float], *, pad: float = 0.08, floor: float | None = None) -> list[float]:
    """A value axis around the data, with a little air (``floor`` pins the bottom, e.g. 0 for km)."""
    numbers = [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not numbers:
        return [0.0, 1.0]
    low, high = min(numbers), max(numbers)
    air = (high - low) * pad or 1.0
    return [floor if floor is not None else round(low - air, 2), round(high + air, 2)]


def _theme() -> dict[str, Any]:
    t = tz.tokens()
    return {
        "page": "#000000", "ink": t["ink"], "ink2": t["ink_secondary"], "muted": t["muted"], "faint": "#5f6570",
        "edge": "#4a4f59", "grid": "#1f2126", "accent": t["sequential"][5], "raise": "#2c3038",
        "series": t["series"][0], "warm": t["series"][1], "band": "#1d2a3d", "bandText": "#6d7f99",
        "gap": "#121316", "gapText": "#4a4f59",
    }


def colors() -> dict[str, str]:
    """The few colours a page spec needs by name."""
    t = tz.tokens()
    return {"series": t["series"][0], "warm": t["series"][1], "light": t["sequential"][5], "pale": t["sequential"][4],
            "critical": t["status"]["critical"], "warning": t["status"]["warning"]}


def _text() -> dict[str, Any]:
    tr = i18n.tr
    return {"lang": i18n.lang(), "months": i18n.months(), "link": tr(pl="Połączenie", en="Link"),
            "open": tr(pl="Otwórz", en="Open")}


def show(spec: dict[str, Any], *, key: str, token: str, reserve: int = 250) -> None:
    """Draw the hero; a click on a fact's link opens its page.

    ``token`` changes when the data does (build, range, language), so the chart
    wipes in again then and not on an ordinary rerun. ``reserve`` is the room
    the page still needs below the chart, so that the whole page fits a screen.
    """
    clicked = _component(spec=spec, theme=_theme(), text=_text(), token=token, reserve=reserve, key=key, default=None)
    seen = f"{key}_clicks_seen"
    if clicked and int(clicked.get("clicks", 0)) > st.session_state.get(seen, 0):
        st.session_state[seen] = int(clicked["clicks"])
        go = clicked.get("go") or {}
        if go.get("switch") and go.get("view"):
            routing.goto_view(go["page"], go["switch"], go["view"])
        elif go.get("page"):
            routing.goto(go["page"])
