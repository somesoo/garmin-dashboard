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

import routing  # noqa: E402
import shell  # noqa: E402
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
    run_session,
    sleep,
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
st.markdown(shell.PAGE_STYLE, unsafe_allow_html=True)

if not shell.has_data():
    shell.no_data_screen()

PAGES = {
    "Przegląd": [
        st.Page(today.render, title="Dziś", icon=":material/today:", url_path="dzis", default=True),
        st.Page(atlas.render, title="Atlas", icon=":material/public:", url_path="atlas"),
        st.Page(routes.render, title="Trasy", icon=":material/route:", url_path="trasy"),
        st.Page(activities.render, title="Aktywności", icon=":material/list_alt:", url_path="aktywnosci"),
    ],
    "Bieganie": [
        st.Page(run_overview.render, title="Bieganie", icon=":material/directions_run:", url_path="bieganie"),
        st.Page(run_forecast.render, title="Prognoza wyników", icon=":material/timer:", url_path="prognoza"),
        st.Page(run_plan.render, title="Plan treningowy", icon=":material/calendar_month:", url_path="plan"),
        st.Page(run_races.render, title="Zawody i cele", icon=":material/flag:", url_path="zawody"),
        st.Page(run_session.render, title="Trening", icon=":material/insights:", url_path="bieg"),
        st.Page(run_load.render, title="Obciążenie biegowe", icon=":material/stacked_bar_chart:",
                url_path="obciazenie-biegowe"),
    ],
    "Ciało": [
        st.Page(recovery.render, title="Regeneracja", icon=":material/monitor_heart:", url_path="regeneracja"),
        st.Page(sleep.render, title="Rytm i sen", icon=":material/bedtime:", url_path="sen"),
        st.Page(trends.render, title="Trendy", icon=":material/trending_up:", url_path="trendy"),
    ],
    "Trening": [
        st.Page(form.render, title="Forma", icon=":material/bolt:", url_path="forma"),
        st.Page(physio.render, title="Fizjologia", icon=":material/speed:", url_path="fizjologia"),
    ],
    "Analiza": [
        st.Page(stats.render, title="Statystyka", icon=":material/science:", url_path="statystyka"),
        st.Page(notebook.insights, title="Insights", icon=":material/lightbulb:", url_path="insights"),
        st.Page(notebook.sql, title="SQL", icon=":material/terminal:", url_path="sql"),
        st.Page(reference.render, title="Słownik", icon=":material/menu_book:", url_path="slownik"),
    ],
}

# Views navigate by url_path through this registry (see routing.py).
routing.register(PAGES)

page = st.navigation(PAGES, position="sidebar", expanded=True)

shell.range_picker()
shell.footer()

page.run()
