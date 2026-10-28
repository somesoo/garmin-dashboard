"""Shared shell for the dashboard pages: data access, chrome, small helpers.

Each page is a module under ``views/`` that calls into here for its tables and
the shared chrome (rail, time range, styles); the page layout itself is the
bento grid in ``bento.py``. Keeping the chrome in the rail is what lets the
canvas be all tiles: nothing has to reserve space for navigation or filters.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

import config
import db
import glossary
import i18n
import routing
import sync

# Plain ground, cards on top: black in dark mode, a flat neutral in light.
# Each mode: canvas, sidebar, widget, edge, inner highlight, resting shadow,
# raised shadow.
_SURFACES = {
    "light": ("#f2f3f5", "#f7f8fa", "#ffffff", "rgba(15,23,42,0.08)",
              "inset 0 1px 0 rgba(255,255,255,0.9)",
              "0 1px 2px rgba(15,23,42,0.05), 0 8px 24px -12px rgba(15,23,42,0.14)",
              "0 2px 4px rgba(15,23,42,0.06), 0 16px 32px -14px rgba(15,23,42,0.22)"),
    # Solid graphite cards on the black ground. No gradients, ever (CLAUDE.md).
    "dark": ("#000000", "#0a0a0b", "#1a1c20",
             "rgba(255,255,255,0.11)",
             "inset 0 1px 0 rgba(255,255,255,0.10)",
             "0 1px 2px rgba(0,0,0,0.6), 0 10px 26px -14px rgba(0,0,0,0.9)",
             "0 2px 4px rgba(0,0,0,0.6), 0 18px 36px -14px rgba(0,0,0,0.95)"),
}

_STYLE = """
<style>
  /* ---- canvas ------------------------------------------------------------- */
  [data-testid="stApp"] {background: @CANVAS@;}
  [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stBottom"] > div {background: transparent;}
  [data-testid="stHeader"] {background: transparent;}
  [data-testid="stSidebar"] {background: @SIDEBAR@ !important; border-right: 1px solid @LINE@;}
  [data-testid="stSidebar"] > div {background: transparent;}
  .block-container {padding-top: 1.6rem; padding-bottom: 4rem; max-width: 1560px;}

  /* ---- widgets (bento.py): wgt_ = chart tile, kpi_ = number, pnl_ = form */
  [class*="st-key-wgt_"], [class*="st-key-kpi_"], [class*="st-key-pnl_"] {
      background: @WIDGET@; border: 1px solid @LINE@ !important; border-radius: 10px;
      box-shadow: @HIGHLIGHT@, @SHADOW@; padding: 1rem 1.25rem 0.9rem 1.25rem;
      transition: transform .25s cubic-bezier(.2,.75,.25,1), box-shadow .25s ease;
      animation: wgt-rise .55s cubic-bezier(.2,.75,.25,1) both;
      animation-delay: calc(var(--row-delay, 0ms) + var(--col-delay, 0ms));}
  [class*="st-key-wgt_"]:hover, [class*="st-key-kpi_"]:hover {transform: translateY(-3px);
      box-shadow: @HIGHLIGHT@, @RAISED@;}
  /* Numbers need less air than charts. */
  [class*="st-key-kpi_"] {padding: 0.85rem 1.15rem 0.8rem 1.15rem;}

  /* Rows line up without fixed heights: columns of a widget row stretch to the
     tallest, and widgets grow to fill their column -- nothing is clipped and
     nothing scrolls inside. Forms (pnl_) keep their own height. */
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-wgt_"]),
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-kpi_"]) {
      align-items: stretch !important;}
  [data-testid="stColumn"]:has([class*="st-key-wgt_"]) > [data-testid="stVerticalBlock"],
  [data-testid="stColumn"]:has([class*="st-key-kpi_"]) > [data-testid="stVerticalBlock"] {height: 100%;}
  [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
      > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-wgt_"], > [class*="st-key-kpi_"]) {
      flex: 1 0 auto; display: flex; flex-direction: column;}
  /* Grow, never shrink: shrinking below the content is exactly the clipping
     this layout exists to avoid. */
  [class*="st-key-wgt_"], [class*="st-key-kpi_"] {flex: 1 0 auto;}

  /* ---- widget chrome ------------------------------------------------------ */
  [class*="st-key-wgthd_"] {min-height: 30px; flex-wrap: nowrap;}
  [class*="st-key-wgthd_"] [data-testid="stElementContainer"]:first-child {flex: 1 1 auto; min-width: 0;}
  [class*="st-key-wgthd_"] [data-testid="stMarkdownContainer"] > div,
  [class*="st-key-wgthd_"] [data-testid="stMarkdown"] {margin: 0 !important;}
  [class*="st-key-wgthd_"] button {padding: 0 0.25rem; min-height: 28px; opacity: .38; transition: opacity .2s;}
  [class*="st-key-wgt_"]:hover [class*="st-key-wgthd_"] button,
  [class*="st-key-pnl_"]:hover [class*="st-key-wgthd_"] button,
  [class*="st-key-wgthd_"] button:focus-visible {opacity: 1;}
  @media (hover: none) {[class*="st-key-wgthd_"] button {opacity: .8;}}
  .tile-title {font-size: 0.86rem; font-weight: 640; letter-spacing: -0.003em; line-height: 1.3;}
  .tile-caption {font-size: 0.78rem; opacity: 0.72; line-height: 1.4;}
  /* Pull the status line up to its title by moving the whole element box, not
     the text inside it: a negative margin on the text sticks out of its own
     container and past the widget's edge. */
  [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] .tile-caption) {margin-top: -0.65rem;}
  /* Streamlit gives every markdown block margin-bottom: -1rem (it expects a
     trailing <p>); with a bare <div> that collapses the block to ~1 px and the
     text spills out of the widget. Widget text gets its real height back. */
  [data-testid="stMarkdownContainer"]:has(> .tile-caption),
  [data-testid="stMarkdownContainer"]:has(> .tile-list),
  [data-testid="stMarkdownContainer"]:has(> .tile-title) {margin-bottom: 0 !important;}
  [class*="st-key-kpi_"] [data-testid="stMetricValue"] {font-size: 1.6rem;
      animation: wgt-num .6s cubic-bezier(.2,.75,.25,1) both;
      animation-delay: calc(var(--row-delay, 0ms) + var(--col-delay, 0ms) + 120ms);}
  [class*="st-key-wgt_"] [data-testid="stMetricValue"] {font-size: 1.3rem;}
  [class*="st-key-wgt_"] [data-testid="stPlotlyChart"] {margin-top: -0.35rem;}
  [class*="st-key-wgt_"] .maplibregl-map, [class*="st-key-wgt_"] .mapboxgl-map {border-radius: 8px; overflow: hidden;}
  .tile-list {margin: 0 !important; padding-left: 1.1rem !important;}
  .tile-list li {font-size: 0.82rem !important; line-height: 1.45 !important; margin-bottom: 0.2rem !important;}

  /* ---- motion --------------------------------------------------------------
     Widgets rise in row by row, column by column; charts wipe in left to right
     (the direction time runs), numbers settle last. Only on first paint of a
     page: Streamlit keeps the DOM across reruns, so a rerun does not replay. */
  @keyframes wgt-rise {from {opacity: 0; transform: translateY(12px) scale(.985);} to {opacity: 1; transform: none;}}
  @keyframes wgt-num {from {opacity: 0; transform: translateY(6px);} to {opacity: 1; transform: none;}}
  @keyframes wgt-wipe {from {clip-path: inset(0 100% 0 0);} to {clip-path: inset(0 0 0 0);}}
  /* Plotly draws later than the widget appears (its library loads after the
     page), so the wipe starts when the traces arrive, not on the row stagger. */
  [class*="st-key-wgt_"] .js-plotly-plot .cartesianlayer .overplot {
      animation: wgt-wipe .9s cubic-bezier(.45,.05,.25,1) .05s both;}
@DELAYS@
  @media (prefers-reduced-motion: reduce) {
      [class*="st-key-wgt_"], [class*="st-key-kpi_"], [class*="st-key-pnl_"],
      [class*="st-key-kpi_"] [data-testid="stMetricValue"],
      [class*="st-key-wgt_"] .js-plotly-plot .cartesianlayer .overplot {animation: none !important; transition: none;}
      [class*="st-key-wgt_"]:hover, [class*="st-key-kpi_"]:hover {transform: none;}}

  /* ---- type and the rest ---------------------------------------------------- */
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
  /* The globe bleeds past the grid -- it is the one element that should feel
     bigger than the page. Flat ground behind it: no halo, no gradient. */
  .st-key-globe_stage {margin: 0 -3.5rem;}
  .st-key-globe_stage [data-testid="stPlotlyChart"] {margin: 0;}
  hr {margin: 2.2rem 0 0 0; opacity: 0.25;}
</style>
"""


def _delays() -> str:
    # Stagger as CSS variables: the page row sets --row-delay, the column inside
    # it adds --col-delay, and every widget below inherits both.
    rows = "\n".join(
        f'  [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > :nth-child({n})'
        f" {{--row-delay: {min(n, 12) * 55}ms;}}"
        for n in range(1, 25)
    )
    columns = "\n".join(
        f'  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child({n}) {{--col-delay: {n * 70}ms;}}'
        for n in range(1, 5)
    )
    return rows + "\n" + columns


def page_style(mode: str = "light") -> str:
    """The app's CSS for the theme the browser renders (``theme.mode()``)."""
    canvas, sidebar, widget, line, highlight, shadow, raised = _SURFACES.get(mode, _SURFACES["light"])
    tokens = {"@CANVAS@": canvas, "@SIDEBAR@": sidebar, "@WIDGET@": widget, "@LINE@": line,
              "@HIGHLIGHT@": highlight, "@SHADOW@": shadow, "@RAISED@": raised, "@DELAYS@": _delays()}
    style = _STYLE
    for token, value in tokens.items():
        style = style.replace(token, value)
    return style


# Activity tables: the warehouse field, its header in the interface language,
# and its format. Raw floats ("130.3395") and seconds on the start time are
# noise in a log you scan by eye.
def activity_labels() -> dict[str, str]:
    """Field -> table header; rename a frame with it, then pass activity_columns()."""
    tr = i18n.tr
    return {
        "start_local": tr(pl="kiedy", en="when"),
        "sport": "sport",
        "name": tr(pl="nazwa", en="name"),
        "location": tr(pl="miejsce", en="place"),
        "distance_km": "km",
        "duration_min": "min",
        "pace_min_km": tr(pl="tempo /km", en="pace /km"),
        "avg_hr": tr(pl="tętno", en="HR"),
        "max_hr": tr(pl="tętno max", en="max HR"),
        "training_load": "load",
        "te_aerobic": tr(pl="TE tlenowy", en="aerobic TE"),
        "te_anaerobic": tr(pl="TE beztlenowy", en="anaerobic TE"),
        "best_1k_s": tr(pl="najlepszy 1 km", en="best 1 km"),
        "best_5k_s": tr(pl="najlepszy 5 km", en="best 5 km"),
        "calories": "kcal",
        "elevation_gain_m": tr(pl="przewyższenie", en="elevation gain"),
    }


def activity_columns() -> dict[str, Any]:
    number = st.column_config.NumberColumn
    formats = {"distance_km": "%.1f", "duration_min": "%.0f", "avg_hr": "%.0f", "max_hr": "%.0f",
               "training_load": "%.0f", "te_aerobic": "%.1f", "te_anaerobic": "%.1f", "calories": "%.0f",
               "elevation_gain_m": "%.0f m"}
    labels = activity_labels()
    return {labels[field]: number(labels[field], format=fmt) for field, fmt in formats.items()}


# The value kept in the session is the key, not the label: switching the
# language must not reset the range.
WINDOWS = {"30d": 30, "90d": 90, "365d": 365, "all": None}


def _window_label(key: str) -> str:
    return {
        "30d": i18n.tr(pl="30 dni", en="30 days"),
        "90d": i18n.tr(pl="90 dni", en="90 days"),
        "365d": i18n.tr(pl="rok", en="year"),
        "all": i18n.tr(pl="wszystko", en="all"),
    }[key]


@st.cache_data(show_spinner=False, max_entries=64)
def _table(name: str, build: str) -> pd.DataFrame:
    return db.table(name)


@st.cache_data(show_spinner=False, max_entries=64)
def _sql(sql: str, build: str) -> pd.DataFrame:
    return db.query(sql)


@st.cache_data(show_spinner=False)
def _models(build: str) -> dict:
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
    return WINDOWS.get(st.session_state.get("range_choice", "90d"), 90)


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
        i18n.tr(pl="Zakres", en="Range"),
        list(WINDOWS),
        index=1,
        key="range_choice",
        format_func=_window_label,
        horizontal=True,
    )


def language_picker() -> None:
    """Interface language, remembered for the next tab (i18n.py)."""
    st.sidebar.segmented_control(
        i18n.tr(pl="Język", en="Language"),
        list(i18n.LANGS),
        default=i18n.lang(),
        key=i18n.KEY,
        format_func=lambda code: code.upper(),
        on_change=lambda: i18n.remember(st.session_state.get(i18n.KEY)),
        label_visibility="collapsed",
    )


def footer() -> None:
    """Warehouse status, kept out of the canvas."""
    info = state()
    st.sidebar.divider()
    days, activities, routes = (int(info.get(k, 0) or 0) for k in ("days", "activities", "routes"))
    counts = " · ".join([
        f"**{days}** {i18n.plural(days, pl=('dzień', 'dni', 'dni'), en=('day', 'days'))}",
        f"**{activities}** "
        f"{i18n.plural(activities, pl=('aktywność', 'aktywności', 'aktywności'), en=('activity', 'activities'))}",
        f"**{routes}** {i18n.plural(routes, pl=('trasa', 'trasy', 'tras'), en=('route', 'routes'))}",
    ])
    st.sidebar.caption(
        f"{counts}\n\n"
        f"{info.get('first_day')} → {info.get('last_day')}\n\n"
        + i18n.tr(pl="zbudowano", en="built") + f": {info.get('built_at', '—')}"
    )
    busy = sync.running()
    with st.sidebar:
        # Polls the lock file: every few seconds while a pull runs (to reload
        # the page when it ends), once a minute otherwise (to notice the
        # timer starting one).
        st.fragment(run_every=3 if busy else 60)(_pull)(busy)


def _stamp(value: str | None) -> str:
    try:
        return f"{dt.datetime.fromisoformat(value):%d.%m %H:%M}"
    except (TypeError, ValueError):
        return "—"


def _pull(was_busy: bool) -> None:
    """The Garmin pull button and the state of the last pull (sync.py)."""
    busy = sync.running()
    if busy != was_busy:
        # Started by the timer, or just finished: the full run picks the new
        # build and swaps the polling rate.
        st.rerun()
    record = sync.last()
    if busy:
        st.button(i18n.tr(pl="Pobieranie z Garmina…", en="Pulling from Garmin…"), icon=":material/sync:",
                  width="stretch", disabled=True)
        started = _stamp(record.get("started_at"))
        st.caption(i18n.tr(pl=f"od {started} · strona odświeży się sama",
                           en=f"since {started} · the page reloads on its own"))
        return
    if st.button(i18n.tr(pl="Pobierz z Garmina", en="Pull from Garmin"), icon=":material/cloud_download:",
                 width="stretch"):
        sync.start()
        st.rerun()
    if record.get("code") == 2:
        st.caption(i18n.tr(pl=":orange[Token Garmina wygasł] — zaloguj się raz hasłem:",
                           en=":orange[The Garmin token has expired] — log in once with the password:")
                   + " `.venv/bin/python etl/login.py`")
    elif record and record.get("code") != 0:
        st.caption(i18n.tr(pl=":orange[Ostatnie pobranie nie powiodło się] — log w",
                           en=":orange[The last pull failed] — log in") + " `data/fetch.log`")
    hours = os.environ.get("GARMIN_AUTO_FETCH_H", "").strip()
    finished = _stamp(record.get("finished_at"))
    note = i18n.tr(pl=f"pobrano: {finished}", en=f"pulled: {finished}")
    upcoming = sync.next_due(float(hours)) if hours else None
    if upcoming is not None:
        note += i18n.tr(pl=f" · automatycznie co {hours} h (następne ~{upcoming:%H:%M})",
                        en=f" · automatically every {hours} h (next ~{upcoming:%H:%M})")
    st.caption(note)


def lead(title: str, note: str | None = None, *, terms: tuple | list = (), how: str | None = None) -> None:
    """Section heading plus the sentence that says why the section is there.

    ``terms`` are glossary keys and ``how`` says how to read the chart; both go
    into a "Co to jest?" popover, so the canvas carries one sentence and the
    explanation is one click away instead of a legend in prose.
    """
    st.markdown(f"## {title}")
    if note:
        st.caption(note)
    explain(terms, how)


def sub(title: str, note: str | None = None, *, terms: tuple | list = (), how: str | None = None) -> None:
    st.markdown(f"### {title}")
    if note:
        st.caption(note)
    explain(terms, how)


def explain(terms: tuple | list = (), how: str | None = None) -> None:
    """The help popover: what each number is, why it matters, how to read it."""
    if not terms and not how:
        return

    with st.popover(i18n.tr(pl="Co to jest?", en="What is this?"), icon=":material/help_outline:", type="tertiary"):
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


def metrics(row: pd.Series | None, previous: pd.Series | None, specs: list[tuple]) -> None:
    """A strip of tiles: ``(field, label, unit[, delta_color])``.

    ``delta_color`` is Streamlit's: "normal" when up is good, "inverse" when up
    is bad (resting HR, stress), "off" when the direction alone means nothing
    (fatigue, load ratios). Left to the default every rise turns green.
    """
    columns = st.columns(len(specs))
    for column, spec in zip(columns, specs):
        field, label, unit = spec[:3]
        delta_color = spec[3] if len(spec) > 3 else "normal"
        help_text = glossary.short(glossary.FIELDS[field]) if field in glossary.FIELDS else None
        value = row.get(field) if row is not None else None
        if value is None or pd.isna(value):
            column.metric(label, "—", help=help_text)
            continue
        delta = None
        before = previous.get(field) if previous is not None else None
        if before is not None and not pd.isna(before):
            diff = float(value) - float(before)
            delta = f"{diff:+.1f}".rstrip("0").rstrip(".") + (f" {unit}" if unit else "")
        shown = f"{float(value):.1f}".rstrip("0").rstrip(".")
        column.metric(label, f"{shown}{(' ' + unit) if unit else ''}", delta, delta_color=delta_color,
                      help=help_text)


def week_before(frame: pd.DataFrame) -> pd.Series | None:
    """Mean of the seven days before the latest one: the baseline the tiles
    compare against. Yesterday alone is too noisy a reference for HRV or sleep."""
    if len(frame) < 3:
        return None
    return frame.sort_values("day").iloc[-8:-1].mean(numeric_only=True)


def missing(name: str, hint: str = "") -> None:
    st.caption(i18n.tr(pl=f"Tabela `{name}` jest pusta. {hint}", en=f"Table `{name}` is empty. {hint}").strip())


def pace(minutes: float | None) -> str:
    """Tile text for a pace: ``5:43 /km``."""
    if minutes is None or pd.isna(minutes):
        return "—"
    seconds = int(round(float(minutes) * 60))
    return f"{seconds // 60}:{seconds % 60:02d} /km"


def pace_column(values: pd.Series) -> pd.Series:
    """A pace column for tables, as ``m:ss`` text."""
    return pd.to_numeric(values, errors="coerce").map(
        lambda v: pace(v).removesuffix(" /km") if pd.notna(v) else None
    )


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
    st.warning(i18n.tr(
        pl="Brak danych. Uruchom `Dashboard.command` (macOS), `Dashboard.cmd` (Windows) albo "
           "`.venv/bin/python etl/run.py` (Linux).",
        en="No data yet. Run `Dashboard.command` (macOS), `Dashboard.cmd` (Windows) or "
           "`.venv/bin/python etl/run.py` (Linux).",
    ))
    st.stop()


ROOT = Path(__file__).resolve().parent
