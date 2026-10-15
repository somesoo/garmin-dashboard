"""The hero globe: a static custom component, so the spin costs the server nothing.

This is the one figure in the app that is not built in ``theme.py``, and the
reason is motion. A rotating plotly globe has to be redrawn by Python on a
timer -- ``st.fragment(run_every=...)`` means a rerun, a figure rebuild and a
websocket round trip for every single frame, which is a terrible way to buy
9 degrees of rotation. Here the browser owns the animation: it fetches the
world outline once (a static file next to the component, then served from its
own cache), receives the places once per warehouse build, and rotates them in a
requestAnimationFrame loop. The server is involved again only when the viewer
clicks a place.

The chart system's rules still hold: colours come from ``theme.tokens`` so the
globe matches every other figure in both themes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import theme as tz

ROOT = Path(__file__).resolve().parent
_component = components.declare_component("garmin_globe", path=str(ROOT / "globe_component"))

def _theme() -> dict[str, Any]:
    t = tz.tokens()
    dark = tz.mode() == "dark"
    return {
        "ocean": "#0a111b" if dark else "#cfe0f1",
        "oceanLight": "#16263a" if dark else "#e8f1fa",
        "land": "#272c34" if dark else "#e6e3d8",
        "coast": "#4b525e" if dark else "#b3b0a4",
        "border": "#3c424c" if dark else "#c6c3b7",
        "graticule": "rgba(120,140,160,0.18)" if dark else "rgba(120,140,160,0.22)",
        "surface": t["surface"],
        "ink": t["ink"],
        "card": t["surface"],
        "edge": t["axis"],
        "glow": t["series"][0],
        "ramp": t["sequential"],
    }


@st.cache_data(show_spinner=False)
def starts(_frame: pd.DataFrame, build: str) -> list[dict[str, Any]]:
    """Every activity with GPS, as the start point the component plots.

    One row per activity rather than per place: the grouping is the browser's
    job now, because it depends on the zoom. Keyed on the warehouse build id,
    so this runs again when new activities are fetched and never on an ordinary
    rerun.
    """
    if _frame is None or _frame.empty or "start_lat" not in _frame.columns:
        return []
    frame = _frame.dropna(subset=["start_lat", "start_lon"]).copy()
    if frame.empty:
        return []
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    frame = frame.sort_values("start_local")
    payload = []
    for row in frame.itertuples():
        payload.append(
            {
                "id": int(row.activity_id),
                "lat": round(float(row.start_lat), 5),
                "lon": round(float(row.start_lon), 5),
                "name": str(getattr(row, "name", "") or "Trening"),
                "place": str(getattr(row, "location", "") or "—"),
                "sport": str(getattr(row, "sport", "") or ""),
                "km": round(float(getattr(row, "distance_km", 0) or 0), 1),
                "min": round(float(getattr(row, "duration_min", 0) or 0)),
                "date": row.start_local.strftime("%d.%m.%Y"),
                "ts": int(row.start_local.timestamp()),
            }
        )
    return payload


def show(
    starts: list[dict[str, Any]],
    *,
    spin: bool,
    target: tuple[float, float, float],
    frame: str,
    height: int = 620,
    speed: float = 9.0,
    key: str = "globe",
) -> dict[str, Any] | None:
    """Render the globe; return the click payload when a place was clicked.

    ``frame`` is the token that makes the globe fly somewhere: it changes only
    when the viewer picks another frame, so an ordinary rerun never yanks the
    sphere out of the angle it is at. The returned payload is either a single
    activity (a link) or a group of them (a question).
    """
    return _component(
        activities=starts,
        theme=_theme(),
        spin=bool(spin),
        speed=speed,
        target={"lon": float(target[0]), "lat": float(target[1]), "zoom": float(target[2])},
        frame=frame,
        height=height,
        key=key,
        default=None,
    )


def home(starts: list[dict[str, Any]], zoom: float = 1.6) -> tuple[float, float, float]:
    """The densest corner of the data, zoomed enough to tell its places apart.

    The tilt stops short of the data's own latitude on purpose: looking
    straight down at 52 N flattens the sphere into a polar cap. The zoom stops
    short too -- past ~2x the horizon leaves the canvas and the globe stops
    reading as a globe, which is what the wheel is for.
    """
    if not starts:
        return (0.0, 20.0, 1.0)
    cell = 1.0
    counts: dict[tuple[int, int], int] = {}
    for start in starts:
        key = (round(start["lat"] / cell), round(start["lon"] / cell))
        counts[key] = counts.get(key, 0) + 1
    lat_key, lon_key = max(counts, key=counts.get)
    lat = lat_key * cell
    return (lon_key * cell, max(-55.0, min(55.0, lat * 0.88)), zoom)


def world(starts: list[dict[str, Any]]) -> tuple[float, float, float]:
    """The whole globe, centred so no trip hides behind the sphere."""
    if not starts:
        return (0.0, 20.0, 1.0)
    lons = [s["lon"] for s in starts]
    lats = [s["lat"] for s in starts]
    centre_lat = (min(lats) + max(lats)) / 2
    return ((min(lons) + max(lons)) / 2, max(-55.0, min(55.0, centre_lat * 0.72)), 1.0)
