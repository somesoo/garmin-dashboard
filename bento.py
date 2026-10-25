"""Bento grid: every page is a mosaic of tiles on one 4-column, fixed-row grid.

Why a grid with fixed rows: tiles side by side only line up when their
heights come from the same scale. A tile spans 1-4 columns (``row(2, 1, 1)``)
and 1-4 grid rows (``tile(..., rows=2)``); its height is
``rows * ROW + (rows - 1) * GAP``, so a 2-row tile is exactly as tall as two
1-row tiles stacked next to it, and the mosaic closes without gaps.

A tile owns its chrome: the title, a one-line status under it, and two icons
in the header -- "?" (glossary terms + how to read the chart) and the data
table twin. Nothing about a chart is written above it on the canvas any more,
which is what made the old pages a long document with one chart per screen.

Rules that keep the grid honest (see CLAUDE.md, "Układ aplikacji"):

* KPIs: ``kpis(...)`` -- always four tiles in a row.
* A time axis gets at least two columns; a 1-column tile holds a number,
  a short list, a ``theme.spark`` or a chart without a time axis.
* Charts are drawn at ``chart_height(rows)``; builders' own heights are
  overridden, so no tile scrolls because a figure was drawn too tall.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import pandas as pd
import streamlit as st

import glossary
import routing

ROW = 196     # px per grid row: a 1-row tile still fits a readable trend (~120 px)
GAP = 16      # px between tiles, horizontal and vertical (Streamlit's "small" gap)
HEADER = 54   # px a tile spends on its header and padding
CAPTION = 22  # px for the status line under the title
KPI = 136     # px of a KPI tile: label, value, delta and a one-line note


def height(rows: int) -> int:
    return rows * ROW + (rows - 1) * GAP


def chart_height(rows: int, caption: bool = False) -> int:
    return height(rows) - HEADER - (CAPTION if caption else 0)


def row(*spans: int) -> list[Any]:
    """Columns of one grid row; spans are in quarters of the canvas (sum 4)."""
    if sum(spans) != 4:
        raise ValueError(f"rząd siatki musi sumować się do 4 kolumn, jest {spans}")
    return st.columns(list(spans), gap="small")


class Tile:
    def __init__(self, rows: int, caption: str | None, header: Any, key: str) -> None:
        self.rows = rows
        self.caption = caption
        # Controls that steer only this tile (a night picker, a metric switch)
        # go here, next to the title, so they do not eat the chart's height:
        #     with t.header: st.selectbox(..., label_visibility="collapsed", width=150)
        self.header = header
        self.key = key

    def chart(self, fig: Any, *, table: pd.DataFrame | None = None, empty: str = "Brak danych w tym zakresie.",
              key: str | None = None) -> None:
        """The tile's figure at the height the grid gives it, table twin in the header."""
        if fig is None:
            st.caption(empty)
            return
        fig.update_layout(height=chart_height(self.rows, caption=bool(self.caption)))
        st.plotly_chart(fig, width="stretch", key=key or f"{self.key}_chart", config={"displayModeBar": False})
        if table is not None and not table.empty:
            with self.header:
                with st.popover("", icon=":material/table_view:", type="tertiary", help="Dane wykresu"):
                    st.dataframe(table, width="stretch", hide_index=True, height=320)


@contextmanager
def tile(title: str, *, rows: int = 1, caption: str | None = None, terms: tuple | list = (),
         how: str | None = None, key: str) -> Iterator[Tile]:
    """One tile. Use inside a column from ``row``::

        left, right = bento.row(2, 2)
        with left, bento.tile("HRV w nocy", rows=2, terms=["hrv"], key="hrv") as t:
            t.chart(fig, table=...)
    """
    with st.container(height=height(rows), border=True, key=f"tile_{key}"):
        header = st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"tile_head_{key}")
        with header:
            st.markdown(f"<div class='tile-title'>{title}</div>", unsafe_allow_html=True, width="stretch")
            _help(terms, how)
        if caption:
            st.markdown(f"<div class='tile-caption'>{caption}</div>", unsafe_allow_html=True)
        yield Tile(rows, caption, header, key)


def _help(terms: tuple | list, how: str | None) -> None:
    if not terms and not how:
        return
    with st.popover("", icon=":material/help_outline:", type="tertiary", help="Co to jest?"):
        for index, key in enumerate(terms):
            if index:
                st.divider()
            st.markdown(glossary.markdown(key))
        if how:
            if terms:
                st.divider()
            st.markdown(f"**Jak czytać wykres** — {how}")
        target = routing.page("slownik")
        if target is not None:
            st.page_link(target, label="Wszystkie pojęcia — Słownik", icon=":material/menu_book:")


def bullets(items: list[str]) -> None:
    """A short list in tile type size (st.markdown lists are document-sized)."""
    import html

    rows = "".join(f"<li>{html.escape(item)}</li>" for item in items)
    st.markdown(f"<ul class='tile-list'>{rows}</ul>", unsafe_allow_html=True)


def header(title: str, note: str | None = None) -> None:
    """Page title and the one sentence that says what the page is for."""
    st.title(title)
    if note:
        st.caption(note)


def kpis(current: pd.Series | None, previous: pd.Series | None, specs: list[tuple]) -> None:
    """Four KPI tiles: ``(field, label, unit[, delta_color])`` like ``shell.metrics``.

    ``delta_color`` is Streamlit's: "normal" when up is good, "inverse" when up
    is bad (resting HR, stress), "off" when direction alone means nothing.
    """
    if len(specs) != 4:
        raise ValueError("pasek KPI ma zawsze 4 kafle")
    for column, spec in zip(row(1, 1, 1, 1), specs):
        field, label, unit = spec[:3]
        delta_color = spec[3] if len(spec) > 3 else "normal"
        help_text = glossary.short(glossary.FIELDS[field]) if field in glossary.FIELDS else None
        value = current.get(field) if current is not None else None
        with column, st.container(height=KPI, border=True, key=f"kpi_{field}"):
            if value is None or pd.isna(value):
                st.metric(label, "—", help=help_text)
                continue
            delta = None
            before = previous.get(field) if previous is not None else None
            if before is not None and not pd.isna(before):
                diff = float(value) - float(before)
                delta = f"{diff:+.1f}".rstrip("0").rstrip(".") + (f" {unit}" if unit else "")
            shown = f"{float(value):.1f}".rstrip("0").rstrip(".")
            st.metric(label, f"{shown}{(' ' + unit) if unit else ''}", delta, delta_color=delta_color,
                      help=help_text)


def stat(column: Any, label: str, value: str, note: str | None = None, *, key: str, help: str | None = None,
         delta: str | None = None, delta_color: str = "normal") -> None:
    """A KPI tile for a value that is not a daily column (forecast time, km in a week)."""
    with column, st.container(height=KPI, border=True, key=f"kpi_{key}"):
        st.metric(label, value, delta, delta_color=delta_color, help=help)
        if note:
            st.markdown(f"<div class='tile-caption'>{note}</div>", unsafe_allow_html=True)


def empty_stat(column: Any, key: str) -> None:
    """A blank KPI slot, so a row with three numbers still keeps four columns."""
    with column, st.container(height=KPI, border=False, key=f"kpi_{key}"):
        pass


@contextmanager
def panel(title: str, *, caption: str | None = None, terms: tuple | list = (), how: str | None = None,
          key: str) -> Iterator[Any]:
    """A full-width tile whose height follows its content: forms, editors,
    long tables and prose. Same chrome as ``tile``, no fixed height."""
    with st.container(border=True, key=f"tile_{key}"):
        header = st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"tile_head_{key}")
        with header:
            st.markdown(f"<div class='tile-title'>{title}</div>", unsafe_allow_html=True, width="stretch")
            _help(terms, how)
        if caption:
            st.markdown(f"<div class='tile-caption'>{caption}</div>", unsafe_allow_html=True)
        yield header
