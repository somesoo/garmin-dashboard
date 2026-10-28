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

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import i18n
import theme as tz

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT / "globe_component"
# GPS tracks for the heat layer, written once per warehouse build next to the
# component so the browser fetches them as a static, cacheable file instead of
# receiving half a megabyte over the websocket on every rerun. Gitignored: these
# are the same GPS traces as data/, just in the component's reach.
CACHE = COMPONENT / "cache"
_component = components.declare_component("garmin_globe", path=str(COMPONENT))

def _theme() -> dict[str, Any]:
    t = tz.tokens()
    dark = tz.mode() == "dark"
    return {
        "ocean": "#0a111b" if dark else "#cfe0f1",
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
        # Pass-count classes, light to strong on whichever surface: the dark
        # ramp runs dark -> light, so a daily corridor glows on dark land and
        # reads as deep navy on light land.
        # Steps 1, 3-6: the faintest class one step lighter than its neighbour
        # so a one-off detour separates from a regular route.
        "heat": [t["sequential"][i] for i in (1, 3, 4, 5, 6)],
        "casing": "rgba(14,17,23,0.85)" if dark else "rgba(255,255,255,0.92)",
        # Basemap under the flat map: OpenStreetMap tiles, muted (light) or inverted (dark).
        "tiles": "dark" if dark else "light",
    }


@st.cache_data(show_spinner=False)
def tracks_url(_routes: pd.DataFrame, build: str) -> str | None:
    """Write every GPS track to the component's cache once per build; return its URL.

    Format: ``{activity_id: [lat0, lon0, dlat1, dlon1, ...]}`` in 1e-5 degree
    integers (~1 m), delta-encoded, consecutive duplicates dropped -- about a
    third of the size of plain coordinates.
    """
    if _routes is None or _routes.empty or "lat" not in _routes.columns:
        return None
    frame = _routes.dropna(subset=["lat", "lon"])
    order = ["activity_id"] + (["seq"] if "seq" in frame.columns else [])
    frame = frame.sort_values(order)
    tracks: dict[str, list[int]] = {}
    for activity, one in frame.groupby("activity_id", sort=False):
        lat = (one["lat"].to_numpy(float) * 1e5).round().astype("int64")
        lon = (one["lon"].to_numpy(float) * 1e5).round().astype("int64")
        flat: list[int] = []
        prev_lat = prev_lon = 0
        for index, (a, b) in enumerate(zip(lat, lon)):
            if index and a == prev_lat and b == prev_lon:
                continue
            flat.extend((int(a - prev_lat), int(b - prev_lon)))
            prev_lat, prev_lon = a, b
        if len(flat) >= 4:
            tracks[str(int(activity))] = flat
    if not tracks:
        return None
    CACHE.mkdir(exist_ok=True)
    name = "tracks-" + re.sub(r"[^0-9A-Za-z]", "", build) + ".json"
    for old in CACHE.glob("tracks-*.json"):
        if old.name != name:
            old.unlink(missing_ok=True)
    target = CACHE / name
    if not target.exists():
        target.write_text(json.dumps(tracks, separators=(",", ":")), encoding="utf-8")
    return f"./cache/{name}"


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
                # Cached per build, so no language here: the page fills a nameless one in.
                "name": str(getattr(row, "name", "") or ""),
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
    tracks: str | None = None,
    selected: list[int] | None = None,
    height: int = 620,
    speed: float = 9.0,
    key: str = "globe",
) -> dict[str, Any] | None:
    """Render the globe; return the click payload when a place was clicked.

    ``frame`` is the token that makes the globe fly somewhere: it changes only
    when the viewer picks another frame, so an ordinary rerun never yanks the
    sphere out of the angle it is at. The returned payload is either a single
    activity (a link) or a group of them (a question).

    ``tracks`` is the URL from :func:`tracks_url`; ``selected`` the activity ids
    the filters keep (``None`` = all). The browser recounts the heat layer for a
    new selection, so a filter change sends a list of ids, not the tracks.
    """
    return _component(
        activities=starts,
        tracks=tracks,
        selected=selected,
        theme=_theme(),
        text=_text(),
        spin=bool(spin),
        speed=speed,
        target={"lon": float(target[0]), "lat": float(target[1]), "zoom": float(target[2])},
        frame=frame,
        height=height,
        key=key,
        default=None,
    )


def _text() -> dict[str, Any]:
    """The component's words in the interface language (index.html keeps the
    Polish ones as defaults, so test.html works without Streamlit)."""
    tr = i18n.tr
    return {
        "zoomIn": tr(pl="Przybliż", en="Zoom in"),
        "zoomOut": tr(pl="Oddal", en="Zoom out"),
        "reset": tr(pl="Cały glob", en="The whole globe"),
        "whole": tr(pl="cały glob", en="whole globe"),
        "legend": tr(pl="ile razy przebiegnięte", en="times run"),
        "heatMax": tr(pl="16× i więcej", en="16× or more"),
        "session": tr(pl="Trening", en="Session"),
        "openOne": tr(pl="kliknij, aby otworzyć trasę", en="click to open the route"),
        "openMany": tr(pl="kliknij, aby wybrać · przybliż, aby rozdzielić", en="click to choose · zoom in to split"),
        "lang": i18n.lang(),
        # Activity noun: Polish 1 / 2-4 / 5+, English 1 / many (i18n.plural).
        "activities": i18n.pick({"pl": ["aktywność", "aktywności", "aktywności"], "en": ["activity", "activities"]}),
    }


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


def place(points: pd.DataFrame, *, fill: float = 0.75) -> tuple[float, float, float] | None:
    """Camera over one place: centre and a zoom that frames the bulk of its tracks.

    The sphere's radius is ~half the canvas at zoom 1, so a span of ``s``
    radians fills ``fill`` of it at zoom ~ 2*fill/s. Quantiles, not extremes:
    one long ride out of town would otherwise decide the frame.
    """
    if points is None or points.empty:
        return None
    lat = pd.to_numeric(points["lat"], errors="coerce").dropna()
    lon = pd.to_numeric(points["lon"], errors="coerce").dropna()
    if lat.empty:
        return None
    lat_lo, lat_hi = lat.quantile(0.04), lat.quantile(0.96)
    lon_lo, lon_hi = lon.quantile(0.04), lon.quantile(0.96)
    centre_lat = float((lat_lo + lat_hi) / 2)
    span = max(float(lat_hi - lat_lo), float(lon_hi - lon_lo) * math.cos(math.radians(centre_lat)), 0.01)
    zoom = 2 * fill / math.radians(span)
    return (float((lon_lo + lon_hi) / 2), centre_lat, max(2.0, min(3000.0, zoom)))
