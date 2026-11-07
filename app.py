"""Local Garmin dashboard -- streamlit run app.py

Router only: every page lives in ``views/``, every chart is built through
``theme.py`` and every page is laid out on the bento grid of ``bento.py``:
a header, four KPI tiles, then a mosaic of fixed-height tiles. All chrome
(the everyday pages, the lab, the single global time filter, the Garmin pull)
sits in one line on top (``story.topbar``); the pages navigate through the loop
next to their headline. A phone gets all of it in one drawer instead
(``ui/drawer.py``). ``guide.py`` puts the
page's question above it and the "Dalej" links below it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from core import auth  # noqa: E402
from core import team  # noqa: E402
from ui import coaching  # noqa: E402
from ui import drawer  # noqa: E402
from ui import gesture  # noqa: E402
from ui import guide  # noqa: E402
from core import i18n  # noqa: E402
from ui import routing  # noqa: E402
from ui import shell  # noqa: E402
from ui import story  # noqa: E402
from ui import theme  # noqa: E402
from ui import webapp  # noqa: E402
from core import tenant  # noqa: E402
from views import (  # noqa: E402
    account,
    admin,
    atlas,
    consent,
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
from views import team as team_wall  # noqa: E402

st.set_page_config(
    page_title="Garmin Dashboard",
    page_icon="🏔️",
    layout="wide",
    # The drawer (ui/drawer.py) starts shut, on a phone and on a desktop.
    initial_sidebar_state="collapsed",
)
st.markdown(shell.page_style(theme.mode()), unsafe_allow_html=True)
# Installable from the home screen as a full-screen app, the sign-in screen included.
webapp.head()
# Charts wait for a double tap before they zoom; a list never brings up the keyboard.
gesture.install()

# Whose data this run reads -- before anything touches the warehouse (auth.py, tenant.py).
auth.gate()
# Explicit consent before anything of theirs is pulled or shown (core/privacy.py; not for the controller).
consent.gate()
# A coach looking at an athlete (ui/coaching.py): dropped here unless the athlete's consent still holds.
coaching.gate()

# No data yet (a friend's first visit, a fresh server): the account page is the
# whole app until a source is chosen and something has arrived.
ONBOARDING = not shell.has_data()


def _page(render, url_path: str, icon: str, **kwargs) -> st.Page:
    """A menu entry; its title is the page's title in the current language."""
    return routing.named(st.Page(render, title=i18n.page(url_path), icon=f":material/{icon}:", url_path=url_path,
                                 **kwargs), url_path)


# Grouped by the question a visitor brings, not by the kind of data. Pages
# that answer one question from two sides share an entry behind a switch
# (views/hubs.py); detail pages have no entry and are opened from lists.
PAGES = {
    i18n.group("everyday"): [
        # The start page: the day in facts around a run (analysis/hero.py, ui/components/hero/).
        _page(day.render, "dzien", "wb_sunny", default=coaching.home() == "dzien"),
        _page(today.render, "dzis", "today"),
        _page(hubs.sports, "sport", "sports_gymnastics"),
        _page(atlas.render, "atlas", "public"),
        # Who I am, where my data comes from, my phone and my keys (views/account.py).
        _page(account.render, "konto", "account_circle"),
        # Every activity but a run; also opened from the log, the globe and a run's "Mapa trasy".
        _page(routes.render, "trasy", "route"),
    ],
    i18n.group("running"): [
        _page(run_overview.render, "bieganie", "directions_run", default=coaching.home() == "bieganie"),
        _page(hubs.plan, "plan", "calendar_month"),
        _page(run_forecast.render, "prognoza", "timer"),
        _page(run_segments.render, "segmenty", "conversion_path"),
        _page(hubs.load, "obciazenie-biegowe", "stacked_bar_chart"),
        # One run in detail with the list of runs at its head; also opened from every list of runs.
        _page(run_session.render, "bieg", "insights"),
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
# The server's admin only (tenant.User.admin): people, processes, pulls (views/admin.py).
# Not registered for anyone else, so the address does not exist for them.
if tenant.viewer().admin:
    PAGES[i18n.group("lab")].append(_page(admin.render, "admin", "monitoring"))
# A coach's wall of sticky notes, one per athlete (views/team.py) -- only for someone who coaches.
if team.is_coach(tenant.viewer()):
    PAGES[i18n.group("everyday")].insert(1, _page(team_wall.render, "zespol", "groups"))
# Looking at an athlete: only what their consent's scope allows (core/team.py).
PAGES = coaching.pages(PAGES)

# Views navigate by url_path through this registry (see routing.py).
if ONBOARDING:
    PAGES = {i18n.group("everyday"): [_page(account.render, "konto", "account_circle", default=True)]}

routing.register(PAGES)

# Streamlit's own page list never shows: the top line carries the everyday pages,
# the lab, the range, the language and the pull; the drawer lists every page.
page = st.navigation(PAGES, position="hidden")

if ONBOARDING:
    story.topbar_minimal()
    page.run()
else:
    # Every page in one list behind the hamburger (drawer.py): on a phone the
    # only navigation, on a desktop one beside the top line.
    drawer.render(routing.name(page))
    story.topbar(routing.name(page))
    coaching.bar()
    guide.eyebrow(routing.name(page))
    page.run()
    guide.next_steps(routing.name(page))
