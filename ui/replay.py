"""An activity on its map: a static component, like the globe and the hero chart.

One map does everything (``ui/components/replay/index.html``): the track wears
the colour of a measure, pointing at it reads that moment (distance, time, pace,
heart rate, elevation, climb, cadence), it pans and zooms like any map, and the
play button runs a dot along it on a sped-up clock. Python only sends the track
as parallel arrays -- one clock, one value per sample -- and the words.

The map used to be two things under one switch (a Plotly figure to look at, this
player to play); the switch is gone, and a track without a clock is still drawn
here, only without the play button (``route``).

Playing back in Plotly frames was tried and dropped: every frame carries the
whole trail, so a quick replay of a long run is megabytes, and the colour of the
trail, the live numbers and a speed in whole multiples do not fit it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import streamlit.components.v1 as components

from core import i18n
from ui import theme as tz

COMPONENT = Path(__file__).resolve().parent / "components" / "replay"
_component = components.declare_component("garmin_replay", path=str(COMPONENT))
_charts = components.declare_component("garmin_replaycharts", path=str(COMPONENT.parent / "replaycharts"))

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


def _along(data: pd.DataFrame) -> pd.Series | None:
    """Kilometres from the start: the watch's own distance, else measured along the GPS line."""
    if "distance_km" in data.columns:
        values = pd.to_numeric(data["distance_km"], errors="coerce")
        if values.notna().sum() > 5:
            return values
    lat = np.radians(pd.to_numeric(data["lat"], errors="coerce"))
    lon = np.radians(pd.to_numeric(data["lon"], errors="coerce"))
    if lat.notna().sum() < 5:
        return None
    lat, lon = lat.ffill().bfill(), lon.ffill().bfill()
    a = np.sin(lat.diff() / 2) ** 2 + np.cos(lat) * np.cos(lat.shift()) * np.sin(lon.diff() / 2) ** 2
    return (2 * 6371.0 * np.arcsin(np.sqrt(a.fillna(0)))).cumsum()


def payload(track: pd.DataFrame | None) -> dict[str, Any] | None:
    """The track as parallel arrays for the browser, or None when there is nothing to play.

    A replay needs a GPS line, a distance and a clock to play it by. The clock
    only runs forward (a GPS hiccup that says otherwise is dropped), so the
    browser can look a moment up by bisecting ``t``.
    """
    return _arrays(track, timed=True)


def route(track: pd.DataFrame | None) -> dict[str, Any] | None:
    """What the map draws: ``payload``, or the same arrays without a clock.

    A track nobody timed is still a line to look at and point at. Its "clock"
    is then the distance in metres and ``playable`` is False, so the browser
    hides the play button and the time.
    """
    return _arrays(track, timed=True) or _arrays(track, timed=False)


def _arrays(track: pd.DataFrame | None, *, timed: bool) -> dict[str, Any] | None:
    if track is None or track.empty or not {"lat", "lon"} <= set(track.columns):
        return None
    if timed and "distance_km" not in track.columns:
        return None
    data = track.sort_values("seq") if "seq" in track.columns else track
    along = _along(data)
    if along is None:
        return None
    clock = _clock(data) if timed else along * 1000.0
    if clock is None:
        return None
    frame = pd.DataFrame({
        "t": clock.values,
        "km": along.values,
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
        "playable": timed,
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
        "pace": tr(pl="Tempo", en="Pace"), "hr": tr(pl="Tętno", en="Heart rate"),
        "elevation": tr(pl="Wysokość", en="Elevation"), "climb": tr(pl="Podejście", en="Climb"),
        "cadence": tr(pl="Kadencja", en="Cadence"),
        "m_pace": tr(pl="tempo", en="pace"), "m_hr": tr(pl="tętno", en="heart rate"),
        "m_ele": tr(pl="wysokość", en="elevation"),
        "zoom_in": tr(pl="Przybliż", en="Zoom in"), "zoom_out": tr(pl="Oddal", en="Zoom out"),
        "fit": tr(pl="Cała trasa", en="Whole route"), "full": tr(pl="Pełny ekran", en="Full screen"),
        "rest_mouse": tr(pl="Najedź na trasę albo wykres, żeby odczytać to miejsce · ▶ odtwarza aktywność",
                         en="Point at the route or a chart to read that spot · ▶ plays the activity"),
        "rest_touch": tr(pl="Dotknij trasy, żeby odczytać to miejsce · ▶ odtwarza aktywność",
                         en="Tap the route to read that spot · ▶ plays the activity"),
        "rest_mouse_still": tr(pl="Najedź na trasę, żeby odczytać to miejsce", en="Point at the route to read that spot"),
        "rest_touch_still": tr(pl="Dotknij trasy, żeby odczytać to miejsce", en="Tap the route to read that spot"),
        "wheel": tr(pl="Ctrl + kółko przybliża mapę", en="Ctrl + scroll zooms the map"),
        "wheel_mac": tr(pl="⌘ + przewijanie przybliża mapę", en="⌘ + scroll zooms the map"),
        "two_fingers": tr(pl="Mapę przesuwają dwa palce", en="Two fingers move the map"),
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


def show(track: pd.DataFrame, *, key: str, channel: int | str, map_height: int = 340) -> bool:
    """Draw the map. False when there is no line to draw, so the caller can say so.

    ``channel`` names the clock the charts beside it (``charts``) follow: the activity's id.
    """
    data = route(track)
    if data is None:
        return False
    _component(data=data, text=_text(), theme=_theme(), speeds=list(SPEEDS), map_height=int(map_height),
               channel=str(channel), key=key, default=None)
    return True


def charts(track: pd.DataFrame, *, key: str, channel: int | str, height: int = 360) -> bool:
    """Pace, heart rate and elevation on the player's clock, one playhead through the three.

    A press or a drag scrubs the player (they talk over a BroadcastChannel in the browser, so
    nothing here reruns Streamlit). False when there is no clock to play by.
    """
    data = payload(track)
    if data is None:
        return False
    # Only what the charts draw: the route stays out of this iframe.
    data = {name: data[name] for name in ("t", "km", "hr", "ele", "pace")}
    _charts(data=data, text=_text(), theme=_theme(), height=int(height), channel=str(channel), key=key, default=None)
    return True
