"""Local Garmin dashboard -- streamlit run app.py

Router only: every page lives in ``views/``, every chart is built through
``theme.py`` and every page is laid out on the bento grid of ``bento.py``:
a header, four KPI tiles, then a mosaic of fixed-height tiles. All chrome
(navigation, the single global time filter, warehouse status) sits in the rail,
so the canvas never has to reserve space for controls. ``guide.py`` puts the
page's question above it and the "Dalej" links below it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

import guide  # noqa: E402
import i18n  # noqa: E402
import routing  # noqa: E402
import shell  # noqa: E402
import theme  # noqa: E402
from views import (  # noqa: E402
    atlas,
    day,
    hubs,
    notebook,
    physio,
    recovery,
    reference,
    routes,
    run_forecast,
    run_overview,
    run_segments,
    run_session,
    sleep,
    stats,
    today,
)

st.set_page_config(
    page_title="Garmin Dashboard",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(shell.page_style(theme.mode()), unsafe_allow_html=True)

if not shell.has_data():
    shell.no_data_screen()


def _page(render, url_path: str, icon: str, **kwargs) -> st.Page:
    """A menu entry; its title is the page's title in the current language."""
    return routing.named(st.Page(render, title=i18n.page(url_path), icon=f":material/{icon}:", url_path=url_path,
                                 **kwargs), url_path)


# Grouped by the question a visitor brings, not by the kind of data. Pages
# that answer one question from two sides share an entry behind a switch
# (views/hubs.py); detail pages have no entry and are opened from lists.
PAGES = {
    i18n.group("everyday"): [
        # The start page: the day in facts around a run (hero.py, hero_component/).
        _page(day.render, "dzien", "wb_sunny", default=True),
        _page(today.render, "dzis", "today"),
        _page(hubs.sports, "sport", "sports_gymnastics"),
        _page(atlas.render, "atlas", "public"),
        # No menu entry: opened from the log, the globe and a run's "Mapa trasy".
        _page(routes.render, "trasy", "route", visibility="hidden"),
    ],
    i18n.group("running"): [
        _page(run_overview.render, "bieganie", "directions_run"),
        _page(hubs.plan, "plan", "calendar_month"),
        _page(run_forecast.render, "prognoza", "timer"),
        _page(run_segments.render, "segmenty", "conversion_path"),
        _page(hubs.load, "obciazenie-biegowe", "stacked_bar_chart"),
        # No menu entry: one run in detail, opened from every list of runs.
        _page(run_session.render, "bieg", "insights", visibility="hidden"),
    ],
    i18n.group("body"): [
        _page(recovery.render, "regeneracja", "monitor_heart"),
        _page(sleep.render, "sen", "bedtime"),
    ],
    i18n.group("lab"): [
        _page(physio.render, "fizjologia", "speed"),
        _page(stats.render, "statystyka", "science"),
        _page(notebook.insights, "insights", "lightbulb"),
        _page(notebook.sql, "sql", "terminal"),
        _page(reference.render, "slownik", "menu_book"),
    ],
}

# Views navigate by url_path through this registry (see routing.py).
routing.register(PAGES)

page = st.navigation(PAGES, position="sidebar", expanded=True)

shell.range_picker()
shell.footer()
guide.rail()
shell.language_picker()

guide.eyebrow(routing.name(page))
page.run()
guide.next_steps(routing.name(page))
