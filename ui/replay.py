"""An activity played back on its map: a static component, like the globe and the hero chart.

The browser animates (``ui/components/replay/index.html``): a dot runs the route
on a sped-up clock, the trail behind it takes the colour of the chosen measure,
and the numbers beside the map (distance, time, pace, heart rate, elevation,
climb, cadence) are those of the moment on screen. Python only sends the track
as parallel arrays -- one clock, one value per sample -- and the words.

Playing back in Plotly frames was tried and dropped: every frame carries the
whole trail, so a quick replay of a long run is megabytes, and the colour of the
trail, the live numbers and a speed in whole multiples do not fit it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit.components.v1 as components

from core import i18n
from ui import theme as tz

COMPONENT = Path(__file__).resolve().parent / "components" / "replay"
_component = components.declare_component("garmin_replay", path=str(COMPONENT))

# Seconds of the activity per second of the film. The first is the default.
SPEEDS = (10, 30, 60, 120, 300)


def _clock(track: pd.DataFrame) -> pd.Series | None:
    """Seconds from the start, one per sample (timer time, else the sample timestamps)."""
    for column, scale in (("duration_s", 1.0), ("timestamp_ms", 1000.0)):
        if column in track.columns:
            values = pd.to_numeric(track[column], errors="coerce")
            if values.notna().sum() > 5:
                return (values - values.min()) / scale
    return None


def _series(frame: pd.DataFrame, column: str, decimals: int) -> list[float] | None:
    """One sample-aligned stream with its gaps filled, or None when the watch never recorded it."""
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    if not values.notna().any():
        return None
    return values.ffill().bfill().round(decimals).tolist()


def payload(track: pd.DataFrame | None) -> dict[str, Any] | None:
    """The track as parallel arrays for the browser, or None when there is nothing to play.

    A replay needs a GPS line, a distance and a clock to play it by. The clock
    only runs forward (a GPS hiccup that says otherwise is dropped), so the
    browser can look a moment up by bisecting ``t``.
    """
    if track is None or track.empty or not {"lat", "lon", "distance_km"} <= set(track.columns):
        return None
    data = track.sort_values("seq") if "seq" in track.columns else track
    clock = _clock(data)
    if clock is None:
        return None
    frame = pd.DataFrame({
        "t": clock.values,
        "km": pd.to_numeric(data["distance_km"], errors="coerce").values,
        "lat": pd.to_numeric(data["lat"], errors="coerce").values,
        "lon": pd.to_numeric(data["lon"], errors="coerce").values,
    }, index=data.index)
    for column in ("hr", "elevation_m", "pace_min_km", "cadence"):
        if column in data.columns:
            frame[column] = pd.to_numeric(data[column], errors="coerce").values
    frame = frame.dropna(subset=["t", "km", "lat", "lon"])
    frame = frame[(frame["t"].diff().fillna(1) > 0) & (frame["km"].diff().fillna(0) >= 0)]
    if len(frame) < 5 or float(frame["t"].iloc[-1] - frame["t"].iloc[0]) < 30:
        return None
    frame = frame.assign(t=frame["t"] - frame["t"].iloc[0])
    cadence = _series(frame, "cadence", 0)
    if cadence and pd.Series(cadence).median() < 120:
        # directRunCadence counts one foot; people talk in steps of both feet per minute.
        cadence = [v * 2 for v in cadence]
    return {
        "t": frame["t"].round(1).tolist(),
        "km": frame["km"].round(3).tolist(),
        "lat": frame["lat"].round(5).tolist(),
        "lon": frame["lon"].round(5).tolist(),
        "hr": _series(frame, "hr", 0),
        "ele": _series(frame, "elevation_m", 1),
        "pace": _series(frame, "pace_min_km", 2),
        "cad": cadence,
    }


def ready(track: pd.DataFrame | None) -> bool:
    return payload(track) is not None


def _text() -> dict[str, str]:
    tr = i18n.tr
    return {
        "play": tr(pl="Odtwórz", en="Play"), "pause": tr(pl="Pauza", en="Pause"),
        "again": tr(pl="Jeszcze raz", en="Again"),
        "speed": tr(pl="Prędkość", en="Speed"),
        "speed_hint": tr(pl="s biegu na 1 s filmu", en="s of the activity per 1 s of film"),
        "distance": tr(pl="Dystans", en="Distance"), "time": tr(pl="Czas", en="Time"),
        "pace": tr(pl="Tempo (30 s)", en="Pace (30 s)"), "hr": tr(pl="Tętno", en="Heart rate"),
        "elevation": tr(pl="Wysokość", en="Elevation"), "climb": tr(pl="Podejście", en="Climb"),
        "cadence": tr(pl="Kadencja", en="Cadence"),
        "m_pace": tr(pl="tempo", en="pace"), "m_hr": tr(pl="tętno", en="heart rate"),
        "m_ele": tr(pl="wysokość", en="elevation"),
        "colour": tr(pl="Kolor śladu", en="Track colour"),
        "seek": tr(pl="Przewiń", en="Seek"),
        "faster": tr(pl="szybciej", en="faster"),
    }


def _theme() -> dict[str, Any]:
    t = tz.tokens()
    dark = tz.mode() == "dark"
    ramp = list(t["sequential"][2:]) if dark else list(t["sequential"])
    return {"dark": dark, "ink": t["ink"], "ink2": t["ink_secondary"], "muted": t["muted"], "grid": t["grid"],
            "axis": t["axis"], "surface": "#000000" if dark else t["surface"], "series": t["series"][0],
            "ramp": ramp, "accent": t["sequential"][4] if dark else t["sequential"][3]}


def show(track: pd.DataFrame, *, key: str, map_height: int = 340) -> bool:
    """Draw the player. False when the track cannot be played (no clock), so the caller can say so."""
    data = payload(track)
    if data is None:
        return False
    _component(data=data, text=_text(), theme=_theme(), speeds=list(SPEEDS), map_height=int(map_height),
               key=key, default=None)
    return True
