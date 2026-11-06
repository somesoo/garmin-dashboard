"""Page registry, so one view can send the viewer to another.

``app.py`` builds the pages from functions, not from files, so there is no path
string ``st.switch_page`` could take; a view also cannot import ``app`` (it is
``__main__``). The router registers the page objects here on every run, and a
view navigates by ``url_path``. Going through the registry keeps the session
state alive -- a plain link to ``/trasy`` reloads the browser and resets the
global time range.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from core import i18n

_PAGES: dict[str, Any] = {}
_NAMES: dict[int, str] = {}


def named(page_object: Any, url_path: str) -> Any:
    """Remember the page's own url_path: Streamlit reports ``""`` for the
    default page, so without this "dzis" could not be found by name."""
    _NAMES[id(page_object)] = url_path
    return page_object


def name(page_object: Any) -> str:
    """The url_path a page was created with (also for the default page)."""
    return _NAMES.get(id(page_object), str(page_object.url_path))


def register(pages: dict[str, list[Any]]) -> None:
    """Called by the router with the same structure it hands to st.navigation."""
    _PAGES.clear()
    for group in pages.values():
        for page_object in group:
            _PAGES[name(page_object)] = page_object


def page(url_path: str) -> Any | None:
    return _PAGES.get(url_path)


def goto(url_path: str, **state: Any) -> None:
    """Switch to a page, leaving values behind for it in the session state."""
    target = page(url_path)
    if target is None:
        st.warning(i18n.tr(pl=f"Nie znam strony „{url_path}”.", en=f"Unknown page “{url_path}”."))
        return
    for key, value in state.items():
        st.session_state[key] = value
    st.switch_page(target)


def open_activity(activity_id: int) -> None:
    """Open one activity: a run on its own page (the map is there), anything else on the route explorer."""
    from ui import shell

    runs = shell.table("run_sessions")
    if not runs.empty and (pd.to_numeric(runs["activity_id"], errors="coerce") == int(activity_id)).any():
        open_run(activity_id)
        return
    goto("trasy", routes_activity_request=int(activity_id))


def open_run(activity_id: int) -> None:
    """Open one run on the running session page."""
    goto("bieg", run_activity_request=int(activity_id))


def goto_view(url_path: str, switch: str, view: str) -> None:
    """Open one view of a page that holds two (``bento.switch``, views/hubs.py)."""
    goto(url_path, **{f"{switch}_request": view})
