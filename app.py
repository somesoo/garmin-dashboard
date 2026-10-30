"""Local Garmin dashboard -- streamlit run app.py

Router only: every page lives in ``views/``, every chart is built through
``theme.py`` and every page is laid out on the bento grid of ``bento.py``:
a header, four KPI tiles, then a mosaic of fixed-height tiles. All chrome
(navigation, the single global time filter, warehouse status) sits in the rail,
so the canvas never has to reserve space for controls.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

import i18n  # noqa: E402
import routing  # noqa: E402
import shell  # noqa: E402
import theme  # noqa: E402
from views import (  # noqa: E402
    activities,
    atlas,
    form,
    notebook,
    physio,
    recovery,
    reference,
    routes,
    run_forecast,
    run_load,
    run_overview,
    run_plan,
    run_races,
    run_segments,
    run_session,
    sleep,
    sport,
    sport_disciplines,
    stats,
    today,
    trends,
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
    return st.Page(render, title=i18n.page(url_path), icon=f":material/{icon}:", url_path=url_path, **kwargs)


PAGES = {
    i18n.group("overview"): [
        _page(today.render, "dzis", "today", default=True),
        _page(atlas.render, "atlas", "public"),
        # No menu entry: opened from the Dziennik, the Atlas globe and a run's "Mapa trasy".
        _page(routes.render, "trasy", "route", visibility="hidden"),
        _page(activities.render, "aktywnosci", "list_alt"),
    ],
    i18n.group("running"): [
        _page(run_overview.render, "bieganie", "directions_run"),
        _page(run_forecast.render, "prognoza", "timer"),
        _page(run_plan.render, "plan", "calendar_month"),
        _page(run_races.render, "zawody", "flag"),
        _page(run_session.render, "bieg", "insights"),
        _page(run_segments.render, "segmenty", "conversion_path"),
        _page(run_load.render, "obciazenie-biegowe", "stacked_bar_chart"),
    ],
    i18n.group("sport"): [
        _page(sport.render, "sport", "sports_gymnastics"),
        _page(sport_disciplines.render, "dyscypliny", "interests"),
    ],
    i18n.group("body"): [
        _page(recovery.render, "regeneracja", "monitor_heart"),
        _page(sleep.render, "sen", "bedtime"),
        _page(trends.render, "trendy", "trending_up"),
    ],
    i18n.group("training"): [
        _page(form.render, "forma", "bolt"),
        _page(physio.render, "fizjologia", "speed"),
    ],
    i18n.group("analysis"): [
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
shell.language_picker()

page.run()
