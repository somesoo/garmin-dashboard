"""How much of the dashboard a person sees: basic, standard or expert.

A ranking of every page and tile (2026-11-07) found the app crowded: next to
what a runner reads every morning stand models (Banister, critical speed),
statistics (lagged correlations, change points) and tools (SQL) that only a
curious owner opens. The level hides the latter from people who did not ask for
them; it never deletes anything.

* A **page** above the level leaves the navigation -- the drawer, the top line,
  the loop and the "Dalej" strip (``routing.listed``) -- but stays registered,
  so a link or an address still opens it.
* A **tile** above the level is not drawn and not computed: the view asks
  ``shows(...)`` before calling the tile's function (a ``with`` block cannot
  skip its body), and a half-row pair goes through ``bento.pair`` so the
  remaining tile takes the row.

The choice lives in the person's ``ui.json`` next to the language. Nobody who
had no choice saved loses anything: the default is ``expert``; a person added
with ``tenant add`` starts at ``basic``.
"""

from __future__ import annotations

import json

from core import i18n

LEVELS = ("basic", "standard", "expert")
KEY = "level"
DEFAULT = "expert"
NEW_PERSON = "basic"

# Pages above "basic" (url paths); every other page is for everyone.
PAGES = {
    "obciazenie-biegowe": "standard",
    "segmenty": "expert",
    "fizjologia": "expert",
    "statystyka": "expert",
    "insights": "expert",
    "sql": "expert",
}


def labels() -> dict[str, str]:
    """Display names (built per call: a module constant would freeze the first language)."""
    tr = i18n.tr
    return {"basic": tr(pl="Podstawowy", en="Basic"), "standard": tr(pl="Średni", en="Standard"),
            "expert": tr(pl="Ekspert", en="Expert")}


def descriptions() -> dict[str, str]:
    tr = i18n.tr
    return {
        "basic": tr(pl="Dzień, plan, biegi, sen i regeneracja — to, z czego korzystasz na co dzień.",
                    en="The day, the plan, runs, sleep and recovery — what you use every day."),
        "standard": tr(pl="Do tego obciążenie biegowe, porównania i rozkłady: więcej wykresów na każdej stronie.",
                       en="Plus running load, comparisons and distributions: more charts on every page."),
        "expert": tr(pl="Wszystko: modele (Banister, prędkość krytyczna), statystyka, segmenty, insighty i SQL.",
                     en="Everything: models (Banister, critical speed), statistics, segments, insights and SQL."),
    }


def saved() -> str:
    try:
        value = json.loads(i18n.settings_path().read_text(encoding="utf-8")).get(KEY)
    except (OSError, ValueError, AttributeError, LookupError):
        return DEFAULT
    return value if value in LEVELS else DEFAULT


def remember(value: str | None, path=None) -> None:
    """Save the choice in ``ui.json`` (``path``: a person's file outside a session, for ``tenant add``)."""
    if value not in LEVELS:
        return
    try:
        path = path or i18n.settings_path()
    except LookupError:
        return  # nobody signed in: the session keeps the choice
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current[KEY] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        pass  # the session still has it; only the next tab falls back


def current() -> str:
    """The level of the current render: the session's choice, else the saved one."""
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx(suppress_warning=True) is not None:
            value = st.session_state.get(KEY)
            if value in LEVELS:
                return value
    except Exception:  # noqa: BLE001 -- no Streamlit, no session: use the file
        pass
    return saved()


def shows(needed: str) -> bool:
    """True when the current level reaches ``needed`` ("basic" is always shown)."""
    return LEVELS.index(current()) >= LEVELS.index(needed)


def lists(url_path: str) -> bool:
    """True when the page belongs in the navigation at the current level."""
    return shows(PAGES.get(url_path, "basic"))
