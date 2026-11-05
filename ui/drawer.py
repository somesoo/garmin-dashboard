"""The whole app in one list: the drawer a phone navigates by.

On a wide screen the navigation is the top line (``story.topbar``) and the loop
beside the headline (``story.loop``); both fit the window. On a phone neither
does. The loop stacked under the headline is twelve words above the hero, the
page links and the lab menu wrap into two or three lines, and the "Dalej" strip
closes the page -- a screen of chrome above and below what one came for, on
every page.

So on a phone there is **one navigation, in a drawer**: the hamburger in the top
left corner opens Streamlit's sidebar with every page in it, and the top line
keeps nothing but the page's title.

Which visitor gets it is decided in Python (``shell.phone``), not by the
viewport -- the same lever the rest of the phone page uses, so ``?layout=phone``
shows the drawer on a desktop too and it can be reviewed without a phone in
hand. The sidebar and the hamburger are Streamlit's own chrome, which only CSS
can reach; ``shell.page_style`` therefore holds back the rules that reveal them
until this drawer is actually rendered.

The order of the list is the app's model, not the alphabet: the everyday pages,
the four stages of the loop with their number of the day (stimulus -> response
-> adaptation -> goal), the lab, the view and the account. Every page appears
**once** -- one that belongs to two groups (Sport, Fizjologia) stays in the
first.

Because the top line on a phone no longer carries them, the drawer is also where
the range, the language, the Garmin pull and signing out live. Each of those is
one widget on one key: exactly one of the two chromes is rendered per run, which
is what keeps them from colliding (two widgets on one key is a Streamlit
exception, and a copy with its own key drifts out of step with the state).
"""

from __future__ import annotations

import streamlit as st

from core import i18n
from core import tenant
from ui import routing
from ui import shell
from ui import story

# The everyday pages in menu order (app.py); the lab, minus what the loop holds.
EVERYDAY = ["dzien", "dzis", "sport", "atlas"]
LAB = ["statystyka", "insights", "sql", "slownik", "admin"]


def render(current: str) -> None:
    """The drawer, on a phone only: who is looking, every page, the view, the account."""
    if not shell.phone():
        return
    seen: set[str] = set()
    with st.sidebar, st.container(key="drawer"):
        _who()
        _section(i18n.group("everyday"), EVERYDAY, current, seen)
        _loop(current, seen)
        _section(i18n.group("lab"), LAB, current, seen)
        _tour()
        _view()
        _account(current, seen)
    _close_on_tap()


def _who() -> None:
    """The person and one line about the warehouse -- what the lab menu shows on a desktop."""
    person = tenant.current()
    name = person.name if tenant.registered() else i18n.page("konto")
    try:
        note = shell.status_lines()
    except Exception:  # noqa: BLE001 -- navigation must never break the page
        note = ""
    st.markdown(f"<div class='dw-who'>{name}</div><div class='dw-note'>{note}</div>", unsafe_allow_html=True)


def _section(title: str | None, pages: list[str], current: str, seen: set[str]) -> None:
    links = [url for url in pages if url not in seen and routing.page(url) is not None]
    if not links:
        return
    if title:
        _heading(title)
    for url in links:
        _link(url, current, seen)


def _loop(current: str, seen: set[str]) -> None:
    """The four stages of the loop, each with its number of the day and its pages (story.loop)."""
    here = story.stage_of(current)
    names = story.stage_names()
    try:
        values = story.loop_values()
    except Exception:  # noqa: BLE001 -- the stage's number is decoration, not a condition for navigating
        values = {}
    _heading(i18n.tr(pl="Pętla treningu", en="The training loop"))
    for index, (key, pages) in enumerate(story.STAGE_PAGES.items(), start=1):
        links = [url for url in pages if url not in seen and routing.page(url) is not None]
        if not links:
            continue
        _, title = names[key]
        lit = "on" if key == here else ""
        st.markdown(f"<div class='dw-s {lit}'><span class='dw-i'>{index}</span><span class='dw-n'>{title}</span>"
                    f"<span class='dw-v'>{values.get(key, '—')}</span></div>", unsafe_allow_html=True)
        for url in links:
            _link(url, current, seen)


def _view() -> None:
    """The settings the top line carries on a desktop: the range and the language."""
    _heading(i18n.tr(pl="Widok", en="View"))
    shell.range_picker()
    shell.language_picker()


def _account(current: str, seen: set[str]) -> None:
    """Where the data comes from, the pull, signing out."""
    from core import auth
    from core import sync

    _heading(i18n.tr(pl="Twoje dane", en="Your data"))
    _section(None, ["konto"], current, seen)
    if tenant.current().source == "garmin":
        st.fragment(run_every=3 if sync.running() else 60)(shell.pull_inline)(sync.running())
    if auth.can_sign_out():
        st.button(i18n.tr(pl="Wyloguj", en="Sign out"), on_click=st.logout, key="dw_sign_out", type="tertiary")


def _tour() -> None:
    """The way back to the first-visit tour; on a desktop it stands in the lab menu."""
    from ui import guide

    guide.rail()


def _heading(title: str) -> None:
    st.markdown(f"<div class='dw-h'>{title}</div>", unsafe_allow_html=True)


def _link(url: str, current: str, seen: set[str]) -> None:
    """A page as a word; the current one is not a link but a highlight."""
    seen.add(url)
    if url == current:
        st.markdown(f"<div class='dw-here'>{i18n.page(url)}</div>", unsafe_allow_html=True)
    else:
        st.page_link(routing.page(url), label=i18n.page(url))


# A link in the sidebar does not close it. Only Streamlit's own page menu
# collapses it on a tap, and that menu is what the list above replaces, so
# without this the drawer would stay open over the page one has just chosen.
# One delegated listener on the document, attached once -- the DOM survives
# reruns. The range and the language are left out of it on purpose: those are
# settings one may change twice in a row, and the drawer is where to stand
# while doing it.
_CLOSE = """<script>
(() => {
  let doc = document;
  try { if (window.frameElement && window.parent.document) doc = window.parent.document; } catch (e) {}
  if (doc.__gdDrawerClose) return;
  doc.__gdDrawerClose = true;
  const view = doc.defaultView || window;
  doc.addEventListener("click", (event) => {
    const panel = doc.querySelector('[data-testid="stSidebarUserContent"]');
    if (!panel || !(event.target instanceof view.Element) || !panel.contains(event.target)) return;
    const tapped = event.target.closest("a, button");
    if (!tapped || tapped.closest('[data-testid="stButtonGroup"]')) return;
    const shut = doc.querySelector('[data-testid="stSidebarCollapseButton"] button')
              || doc.querySelector('[data-testid="stSidebarCollapseButton"]');
    if (shut) view.setTimeout(() => shut.click(), 60);
  }, true);
})();
</script>"""


def _close_on_tap() -> None:
    # The same pattern as ui/webapp.py: in a recent Streamlit the script goes
    # into the page itself, in an older one into a same-origin component frame.
    try:
        st.html(_CLOSE, unsafe_allow_javascript=True)
    except TypeError:
        import streamlit.components.v1 as components

        components.html(_CLOSE, height=0)
