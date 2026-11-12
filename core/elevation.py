"""Two views of the same warehouse: recorded elevation or corrected terrain.

Selection is a viewer preference. It never rewrites the person's tables and
never changes the ETL's input. Missing corrections retain the recorded value.
"""
from __future__ import annotations

import json

import pandas as pd

from core import i18n

KEY = "elevation_mode"
MODES = ("terrain", "garmin")


def saved() -> str:
    try:
        value = json.loads(i18n.settings_path().read_text(encoding="utf-8")).get(KEY)
    except (OSError, ValueError, AttributeError, LookupError):
        return "terrain"
    return value if value in MODES else "terrain"


def current() -> str:
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx(suppress_warning=True) is not None:
            value = st.session_state.get(KEY)
            if value in MODES:
                return value
    except Exception:
        pass
    return saved()


def remember(value: str | None) -> None:
    if value not in MODES:
        return
    path = i18n.settings_path()
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    settings[KEY] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def labels() -> dict[str, str]:
    return {"terrain": i18n.tr(pl="Korekta terenowa", en="Terrain correction"),
            "garmin": i18n.tr(pl="Oryginał Garmin", en="Garmin original")}


def select(frame: pd.DataFrame, name: str, mode: str) -> pd.DataFrame:
    """Return an independent recorded view only where originals were saved."""
    if mode != "garmin" or frame.empty:
        return frame
    pairs = {"elevation_m": "elevation_original_m", "elevation_gain_m": "elevation_gain_original_m",
             "elev_gain_m": "elev_gain_original_m", "elev_loss_m": "elev_loss_original_m"}
    columns = [(active, original) for active, original in pairs.items() if original in frame]
    if not columns:
        return frame
    out = frame.copy()
    for active, original in columns:
        out[active] = out[original]
    if "elevation_source" in out:
        out["elevation_source"] = None
    if name == "routes":
        out = out.drop(columns=["elevation_gain_cum_m", "elevation_loss_cum_m"], errors="ignore")
    return out
