"""A coach looking at an athlete: the switch, its check on every run, and the bar that says whose data this is.

``start(athlete_id)`` puts the athlete in the session (``tenant.VIEW_KEY``);
from then on ``tenant.current()`` is the athlete and ``tenant.viewer()`` still
the coach -- every page reads the athlete's warehouse, plan and races without
knowing it is being watched, while the language, the level of detail and the
account stay the coach's own.

``gate()`` runs on every run right after the consent screen (app.py): the view
is dropped the moment the registry, the athlete's consent to the dashboard or
their consent to this coach says no (core/team.py) -- a withdrawal takes effect
on the coach's next click. The first look at an athlete in a browser session
goes to the access log (``coach_view``), which the athlete reads on their account.

What the coach does not get while looking (``core.team.NEVER`` and here): the
athlete's account, SQL, insights, the pull button, the admin page.
"""

from __future__ import annotations

import streamlit as st

from core import audit
from core import i18n
from core import team
from core import tenant
from ui import routing

SEEN_KEY = "coach_seen"


def _ip() -> str | None:
    try:
        return audit.client_ip(st.context.headers, st.context.ip_address)
    except Exception:  # noqa: BLE001
        return None


def viewing() -> tenant.User | None:
    """The athlete being looked at, or None (the viewer is looking at their own data)."""
    athlete_id = st.session_state.get(tenant.VIEW_KEY)
    if not athlete_id:
        return None
    return tenant.coached(tenant.viewer().id, athlete_id)


def scope() -> str | None:
    athlete = viewing()
    return team.scope(athlete) if athlete else None


def home() -> str:
    """The page a view opens on: the day, or the running overview when only training may be seen."""
    return "bieganie" if scope() == "training" else "dzien"


def gate() -> None:
    """Drop the view unless all of it still holds; log the first look of this session."""
    athlete_id = st.session_state.get(tenant.VIEW_KEY)
    if not athlete_id:
        return
    viewer = tenant.viewer()
    athlete = tenant.coached(viewer.id, athlete_id)
    if athlete is None or not team.allowed(viewer.id, athlete):
        st.session_state.pop(tenant.VIEW_KEY, None)
        return
    from ui import shell

    if not shell.has_data():
        # Nothing of theirs to show: their pages would open on the first-steps screen, which is the viewer's account.
        st.session_state.pop(tenant.VIEW_KEY, None)
        st.toast(i18n.tr(pl=f"{athlete.name}: jeszcze brak danych.", en=f"{athlete.name}: no data yet."))
        return
    seen = st.session_state.setdefault(SEEN_KEY, [])
    if athlete.id not in seen:
        audit.record("coach_view", athlete.id, by=viewer.id, scope=team.scope(athlete), ip=_ip())
        seen.append(athlete.id)


def pages(groups: dict[str, list]) -> dict[str, list]:
    """The menu while looking at an athlete: only what their consent's scope allows."""
    level = scope()
    if level is None:
        return groups
    kept = {}
    for title, entries in groups.items():
        allowed = [p for p in entries if team.page_allowed(routing.name(p), level)]
        if allowed:
            kept[title] = allowed
    return kept


def start(athlete_id: str, url_path: str | None = None, **state) -> None:
    """Look at an athlete (from the team page); ``url_path`` opens a page of theirs straight away."""
    viewer = tenant.viewer()
    athlete = tenant.coached(viewer.id, athlete_id)
    if athlete is None or not team.allowed(viewer.id, athlete):
        st.warning(i18n.tr(pl="Ta osoba nie dała zgody — jej dane są zamknięte.",
                           en="This person has not consented — their data is closed."))
        return
    st.session_state[tenant.VIEW_KEY] = athlete.id
    target = url_path if url_path and team.page_allowed(url_path, team.scope(athlete)) else \
        ("bieganie" if team.scope(athlete) == "training" else "dzien")
    if routing.page(target) is None:
        # This run's menu is the previous athlete's (a narrower scope): the next run builds the new one.
        for key, value in state.items():
            st.session_state[key] = value
        st.rerun()
    routing.goto(target, **state)


def stop() -> None:
    """Back to one's own data, on the team page."""
    st.session_state.pop(tenant.VIEW_KEY, None)
    routing.goto("zespol")


def bar() -> None:
    """One line over the page while looking: whose data, how far, switch to someone else, back."""
    athlete = viewing()
    if athlete is None:
        return
    tr = i18n.tr
    level = team.scope(athlete)
    how = tr(pl="tylko trening", en="training only") if level == "training" else tr(pl="wszystko", en="everything")
    with st.container(horizontal=True, key="coachbar", vertical_alignment="center", gap="small"):
        st.markdown(f"<span class='cb-who'>{tr(pl='Patrzysz na', en='Looking at')} <b>{athlete.name}</b></span>"
                    f"<span class='cb-how'>{how}</span>", unsafe_allow_html=True, width="content")
        st.space("stretch")
        viewer = tenant.viewer()
        others = [p for p in team.athletes(viewer) if p.id != athlete.id and team.allowed(viewer.id, p)]
        if others:
            with st.popover(tr(pl="Inna osoba", en="Someone else"), type="tertiary"):
                for other in others:
                    if st.button(other.name, key=f"cb_to_{other.id}", type="tertiary"):
                        start(other.id)
        if st.button(tr(pl="← Zespół", en="← Team"), key="cb_back", type="tertiary"):
            stop()
    st.html("""<style>
      .st-key-coachbar { border-bottom: 1px solid var(--cb-line, #333); padding: 0.25rem 0 0.4rem; margin-bottom: 0.4rem; }
      .st-key-coachbar .cb-who { font-size: 0.95rem; }
      .st-key-coachbar .cb-how { margin-left: 0.6rem; font-size: 0.8rem; opacity: 0.65; }
    </style>""")
