"""Tables as typography, not as a spreadsheet grid.

``st.dataframe`` is a canvas grid: a box with cell borders, a checkbox column
for row selection, and on a phone a sideways scroll that cuts the last column
in half. Here a table is plain rows on the page ground -- a muted header, a
hairline between rows, numbers right-aligned in tabular figures -- and on a
phone the first column stays put while the rest slides (``page_style``).

* ``show(frame)``  -- a read-only table (tile content, data twin, panels).
* ``pick(frame, key=...)`` -- the same table where a tap on a row returns it
  (a component, so no checkbox column); the event fires once per tap.
* ``chooser(items, selected, key=...)`` -- a picker of one item from many
  (an activity): the chosen one as a layered card, a tap opens the list.
  No text field -- a phone never slides up its keyboard for it.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

COMPONENT = Path(__file__).resolve().parent / "components" / "pick"
_component = components.declare_component("garmin_pick", path=str(COMPONENT))

# A value that reads as a number: 12, -3, 4.5, 6:41, 1:02:33, 9.07–10.21, 15 s, +2 %, <1 s, —
_NUMERIC = re.compile(r"^[<>≈~+\-−]?\s?[\d.,:]+(\s?[–/-]\s?[+\-−]?[\d.,:]+)?\s?(km|m|s|%|bpm|min|h|/km)?\s?≈?$")


def _cell(value: Any, decimals: int | None = None) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "—"
    if isinstance(value, float):
        if decimals is not None:
            return f"{value:.{decimals}f}"
        return f"{value:.2f}".rstrip("0").rstrip(".") if value != int(value) else f"{value:.0f}"
    if isinstance(value, pd.Timestamp):
        return f"{value:%d.%m.%Y}"
    return str(value)


def _decimals(config: Any) -> int | None:
    fmt = ((config or {}).get("type_config") or {}).get("format") if isinstance(config, dict) else None
    match = re.match(r"%\.(\d)f", fmt or "")
    return int(match.group(1)) if match else None


def cells(frame: pd.DataFrame, column_config: dict | None = None) -> tuple[list[dict], list[list[str]]]:
    """Header descriptors and the body as strings, each column aligned once."""
    from ui import theme as tz

    frame = tz.readable_paces(frame)
    column_config = column_config or {}
    heads, columns = [], []
    for name in frame.columns:
        config = column_config.get(name)
        series = frame[name]
        text = [_cell(v, _decimals(config)) for v in series]
        filled = [v for v in text if v != "—"]
        numeric = pd.api.types.is_numeric_dtype(series) or (
            bool(filled) and sum(bool(_NUMERIC.match(v)) for v in filled) >= 0.8 * len(filled))
        help_text = config.get("help") if isinstance(config, dict) else None
        label = config.get("label") if isinstance(config, dict) else None
        heads.append({"name": str(label or name), "num": bool(numeric), "help": help_text or ""})
        columns.append(text)
    rows = [list(row) for row in zip(*columns)] if columns else []
    return heads, rows


def html_table(frame: pd.DataFrame, column_config: dict | None = None) -> str:
    heads, rows = cells(frame, column_config)
    esc = html.escape
    head = "".join(
        f"<th class='{'n' if h['num'] else ''}'" + (f" title='{esc(h['help'], quote=True)}'" if h["help"] else "")
        + f">{esc(h['name'])}</th>" for h in heads)
    body = "".join(
        "<tr>" + "".join(f"<td class='{'n' if h['num'] else ''}'>{esc(v)}</td>" for h, v in zip(heads, row))
        + "</tr>" for row in rows)
    return f"<div class='gt-wrap'><table class='gt'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def show(frame: pd.DataFrame, *, column_config: dict | None = None) -> None:
    """A read-only table: as many rows as given, never an inner scroll."""
    if frame is None or frame.empty:
        return
    st.html(html_table(frame.reset_index(drop=True), column_config))


def _fresh(value: Any, key: str) -> Any:
    """A component keeps its last value across reruns; act on each tap once."""
    if not isinstance(value, dict):
        return None
    seen = f"_{key}_seen"
    if st.session_state.get(seen) == value.get("n"):
        return None
    st.session_state[seen] = value.get("n")
    return value


def pick(frame: pd.DataFrame, *, key: str, column_config: dict | None = None,
         max_height: int | None = None, sticky: bool = False) -> int | None:
    """The table of ``show`` where tapping a row returns its position.

    By default each tap is returned once (a row that opens another page);
    ``sticky`` keeps the row selected until tapped again (a row that steers
    the map next to it).
    """
    if frame is None or frame.empty:
        return None
    heads, rows = cells(frame.reset_index(drop=True), column_config)
    held = f"_{key}_row"
    hit = _fresh(st.session_state.get(key), key)
    if sticky and hit is not None:
        st.session_state[held] = hit.get("row")
    selected = st.session_state.get(held) if sticky else None
    if selected is not None and selected >= len(rows):
        selected = st.session_state[held] = None
    _component(mode="table", heads=heads, rows=rows, max_height=max_height, selected=selected,
               key=key, default=None)
    if sticky:
        return selected
    return int(hit["row"]) if hit is not None and hit.get("row") is not None else None


def chooser(items: list[dict], selected: Any, *, key: str, state: str, compact: bool = False) -> Any:
    """One of many as a layered card; ``items`` = ``{id, kind, date, title, meta, group, short}``.

    ``compact`` shrinks the closed card to one line the height of the
    hamburger (``short``: the day and what the run was); the open list stays layered.

    The choice lives in ``st.session_state[state]`` (so another page can set it
    before the rerun); the return value is the current id.
    """
    if not items:
        return None
    ids = [item["id"] for item in items]
    if st.session_state.get(state) not in ids:
        st.session_state[state] = selected if selected in ids else ids[0]
    # The tap that caused this rerun is already in the widget state: read it
    # before drawing, or the card would be sent the old choice and jump back.
    hit = _fresh(st.session_state.get(key), key)
    if hit is not None and hit.get("id") in ids:
        st.session_state[state] = hit["id"]
    _component(mode="list", items=items, selected=st.session_state[state], compact=compact, key=key, default=None)
    return st.session_state[state]


def activity_items(frame: pd.DataFrame, kinds: pd.Series) -> list[dict]:
    """Items for ``chooser``, one per activity, newest first in ``frame``.

    Small print on top -- the type on the left, the day and hour on the right;
    the name below, larger; a line of numbers under it. Months head the list.
    """
    from core import i18n
    from running import units

    days = i18n.weekdays()
    items = []
    for (_, row), kind in zip(frame.iterrows(), kinds):
        when = pd.Timestamp(row["start_local"])
        meta = []
        if pd.notna(row.get("distance_km")):
            meta.append(f"{row['distance_km']:.2f} km")
        if pd.notna(row.get("duration_min")):
            meta.append(units.fmt_time(row["duration_min"] * 60))
        if pd.notna(row.get("pace_min_km")) and row.get("pace_min_km", 0) > 0:
            meta.append(f"{units.fmt_pace(row['pace_min_km'], False)} /km")
        if pd.notna(row.get("avg_hr")):
            meta.append(f"{row['avg_hr']:.0f} bpm")
        name = row.get("name")
        items.append({
            "id": int(row["activity_id"]),
            "kind": str(kind or ""),
            "date": f"{days[when.weekday()]} {when:%d.%m.%Y · %H:%M}",
            "title": str(name) if isinstance(name, str) and name.strip() else str(kind or ""),
            "meta": " · ".join(meta),
            "group": f"{i18n.month_name(when.month - 1)} {when.year}".capitalize(),
            # One line for the compact card: what it was and how far, the day before it.
            "day": f"{when:%d.%m}",
            "short": " · ".join(x for x in (str(kind or ""), f"{row['distance_km']:.1f} km"
                                            if pd.notna(row.get("distance_km")) else "") if x),
        })
    return items
