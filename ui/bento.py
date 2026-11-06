"""Bento grid: every page is a mosaic of floating widgets on one 4-column grid.

A widget spans 1-4 columns (``row(2, 1, 1)``) and 1-3 grid rows
(``tile(..., rows=2)``). Widgets have **no fixed height**: a fixed box either
clips its content or scrolls inside it, and both read as broken. Instead the
grid is aligned in CSS (``shell.page_style``): every column of a row stretches
to the tallest one, and the widgets inside a column grow to fill it, so a
2-row widget next to two 1-row widgets ends level with them without anything
being cut. ``rows`` sets the size of the chart inside -- ``chart_height`` is
chosen so that one 2-row chart plus its chrome equals two 1-row widgets.

A widget owns its chrome: the title, a one-line status under it, and icons in
the header -- "?" (glossary terms + how to read the chart) and the data table
twin. Tables inside a widget show as many rows as fit and never scroll; the
full table sits behind the header icon.

Rules that keep the grid honest (see AGENTS.md, "Strony i układ"; docs/interfejs.md):

* KPIs: ``kpis(...)`` -- always four widgets in a row.
* A time axis gets at least two columns; a 1-column widget holds a number,
  a short list, a ``theme.spark`` or a chart without a time axis.
* Charts are drawn at ``chart_height(rows)``; builders' own heights are
  overridden, so the grid, not the builder, sets the rhythm.
"""

from __future__ import annotations

import html
from contextlib import contextmanager
from typing import Any, Iterator

import pandas as pd
import streamlit as st

from ui import glossary
from core import i18n
from ui import routing
from ui import tables
from ui import theme as tz

CHART = 150      # px of a chart in a 1-row widget
CHROME = 82      # px of a widget's header, status line and padding
GAP = 16         # px between widgets (Streamlit's "small" gap)
ROW_PX = 35      # px of one st.dataframe row (and its header)


def chart_height(rows: int) -> int:
    """A 2-row chart = two 1-row widgets stacked, minus its own chrome."""
    return rows * CHART + (rows - 1) * (CHROME + GAP)


def table_rows(rows: int) -> int:
    """How many table rows fit where a chart of ``rows`` would be."""
    return max(3, chart_height(rows) // ROW_PX - 1)


def table_height(count: int) -> int:
    """st.dataframe height that shows ``count`` rows with no inner scroll."""
    return (count + 1) * ROW_PX + 3


def row(*spans: int) -> list[Any]:
    """Columns of one grid row; spans are in quarters of the canvas (sum 4)."""
    if sum(spans) != 4:
        raise ValueError(i18n.tr(pl=f"rząd siatki musi sumować się do 4 kolumn, jest {spans}",
                                 en=f"a grid row must add up to 4 columns, got {spans}"))
    return st.columns(list(spans), gap="small")


def pair(left: Any, right: Any) -> None:
    """Two tiles side by side -- or the one that exists across the whole row.

    ``left``/``right`` draw a tile, or are None when the person's source has no
    such data (Body Battery for an Apple Watch): an empty tile is noise, and an
    empty half-row is a hole, so the other tile takes the row.
    """
    present = [draw for draw in (left, right) if draw is not None]
    if len(present) == 2:
        a, b = row(2, 2)
        with a:
            left()
        with b:
            right()
    elif present:
        present[0]()


class Tile:
    def __init__(self, rows: int, header: Any, key: str) -> None:
        self.rows = rows
        # Controls that steer only this widget (a night picker, a metric switch)
        # go here, next to the title, so they do not push the chart down:
        #     with t.header: st.selectbox(..., label_visibility="collapsed", width=150)
        self.header = header
        self.key = key

    def chart(self, fig: Any, *, table: pd.DataFrame | None = None, empty: str | None = None,
              key: str | None = None, height: int | None = None) -> None:
        """The widget's figure at the grid's height (or ``height``), table twin in the header."""
        if fig is None:
            st.caption(empty or i18n.tr(pl="Brak danych w tym zakresie.", en="No data in this range."))
            return
        fig.update_layout(height=height or chart_height(self.rows))
        st.plotly_chart(fig, width="stretch", key=key or f"{self.key}_chart", config={"displayModeBar": False})
        self.data(table)

    def table(self, frame: pd.DataFrame, *, full: pd.DataFrame | None = None, **kwargs: Any) -> None:
        """A table as the widget's content: the first rows that fit, no inner
        scroll; when there are more, the whole table is behind the header icon."""
        frame = tz.readable_paces(frame)
        shown = frame.head(table_rows(self.rows))
        tables.show(shown, column_config=kwargs.get("column_config"))
        rest = full if full is not None else frame
        if len(rest) > len(shown):
            note = i18n.tr(pl=f"pierwsze {len(shown)} z {len(rest)} — całość pod ikoną tabeli",
                           en=f"first {len(shown)} of {len(rest)} — all of it behind the table icon")
            st.markdown(f"<div class='tile-caption'>{note}</div>", unsafe_allow_html=True)
            self.data(rest)

    def data(self, table: pd.DataFrame | None) -> None:
        if table is None or table.empty:
            return
        with self.header:
            with st.popover("", icon=":material/table_view:", type="tertiary",
                            help=i18n.tr(pl="Dane", en="Data")):
                tables.show(table)


@contextmanager
def tile(title: str, *, rows: int = 1, caption: str | None = None, terms: tuple | list = (),
         how: str | None = None, key: str) -> Iterator[Tile]:
    """One widget. Use inside a column from ``row``::

        left, right = bento.row(2, 2)
        with left, bento.tile("HRV w nocy", rows=2, terms=["hrv"], key="hrv") as t:
            t.chart(fig, table=...)
    """
    with st.container(border=True, key=f"wgt_{key}"):
        header = _header(title, terms, how, key)
        if caption:
            st.markdown(f"<div class='tile-caption'>{caption}</div>", unsafe_allow_html=True)
        yield Tile(rows, header, key)


@contextmanager
def panel(title: str, *, caption: str | None = None, terms: tuple | list = (), how: str | None = None,
          key: str) -> Iterator[Any]:
    """A widget for forms, editors and prose. Same chrome; it is not stretched
    to its neighbours, so a form does not get a tall empty tail."""
    with st.container(border=True, key=f"pnl_{key}"):
        header = _header(title, terms, how, key)
        if caption:
            st.markdown(f"<div class='tile-caption'>{caption}</div>", unsafe_allow_html=True)
        yield header


def _header(title: str, terms: tuple | list, how: str | None, key: str) -> Any:
    header = st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"wgthd_{key}")
    with header:
        st.markdown(f"<div class='tile-title'>{title}</div>", unsafe_allow_html=True, width="stretch")
        _help(terms, how)
    return header


def _help(terms: tuple | list, how: str | None) -> None:
    if not terms and not how:
        return
    with st.popover("", icon=":material/help_outline:", type="tertiary",
                    help=i18n.tr(pl="Co to jest?", en="What is this?")):
        for index, key in enumerate(terms):
            if index:
                st.divider()
            st.markdown(glossary.markdown(key))
        if how:
            if terms:
                st.divider()
            st.markdown(f"**{i18n.tr(pl='Jak czytać wykres', en='How to read the chart')}** — {how}")
        target = routing.page("slownik")
        if target is not None:
            st.page_link(target, label=i18n.tr(pl="Wszystkie pojęcia — Słownik", en="All terms — Glossary"),
                         icon=":material/menu_book:")


def bullets(items: list[str]) -> None:
    """A short list in widget type size (st.markdown lists are document-sized)."""
    rows = "".join(f"<li>{html.escape(item)}</li>" for item in items)
    st.markdown(f"<ul class='tile-list'>{rows}</ul>", unsafe_allow_html=True)


def switch(key: str, options: dict[str, str]) -> str:
    """Views that share one menu entry (Plan | Zawody): a segmented control
    above the view's own header. Returns the chosen key, the first by default.

    Another page opens a given view through ``routing.goto(url, **{f"{key}_request": view})``:
    the widget key itself cannot be written once the widget exists in the run
    that asks for the switch, so the request waits under its own key.
    """
    wanted = st.session_state.pop(f"{key}_request", None)
    first = next(iter(options))
    if wanted in options:
        st.session_state[key] = wanted
    elif st.session_state.get(key) not in options:
        st.session_state[key] = first
    with st.container(key=f"viewswitch_{key}"):
        choice = st.segmented_control(i18n.tr(pl="Widok", en="View"), list(options), key=key,
                                      format_func=options.get, label_visibility="collapsed")
    return choice or first


# Set by story.head for the run: the page already has its headline, so a view's
# header below it is a section title, not a second page title.
HEADED = False


def header(title: str, note: str | None = None) -> None:
    """Page title and the one sentence that says what the page is for."""
    if HEADED:
        st.markdown(f"<div class='view-title'>{title}</div>", unsafe_allow_html=True)
    else:
        st.title(title)
    if note:
        st.caption(note)


def kpis(current: pd.Series | None, previous: pd.Series | None, specs: list[tuple]) -> None:
    """Four KPI widgets: ``(field, label, unit[, delta_color])``.

    ``delta_color`` is Streamlit's: "normal" when up is good, "inverse" when up
    is bad (resting HR, stress), "off" when direction alone means nothing.
    """
    if len(specs) != 4:
        raise ValueError(i18n.tr(pl="pasek KPI ma zawsze 4 kafle", en="a KPI strip always has 4 tiles"))
    for column, spec in zip(row(1, 1, 1, 1), specs):
        field, label, unit = spec[:3]
        delta_color = spec[3] if len(spec) > 3 else "normal"
        help_text = glossary.short(glossary.FIELDS[field]) if field in glossary.FIELDS else None
        value = current.get(field) if current is not None else None
        with column, st.container(border=True, key=f"kpi_{field}"):
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
    """A KPI widget for a value that is not a daily column (forecast time, km in a week)."""
    with column, st.container(border=True, key=f"kpi_{key}"):
        st.metric(label, value, delta, delta_color=delta_color, help=help)
        if note:
            st.markdown(f"<div class='tile-caption'>{note}</div>", unsafe_allow_html=True)


def empty_stat(column: Any, key: str) -> None:
    """A blank KPI slot, so a row with three numbers still keeps four columns."""
    with column, st.container(border=False, key=f"kpiempty_{key}"):
        pass
