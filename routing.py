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

import streamlit as st

_PAGES: dict[str, Any] = {}


def register(pages: dict[str, list[Any]]) -> None:
    """Called by the router with the same structure it hands to st.navigation."""
    _PAGES.clear()
    for group in pages.values():
        for page_object in group:
            _PAGES[str(page_object.url_path)] = page_object


def page(url_path: str) -> Any | None:
    return _PAGES.get(url_path)


def goto(url_path: str, **state: Any) -> None:
    """Switch to a page, leaving values behind for it in the session state."""
    target = page(url_path)
    if target is None:
        st.warning(f"Nie znam strony „{url_path}”.")
        return
    for key, value in state.items():
        st.session_state[key] = value
    st.switch_page(target)


def open_activity(activity_id: int) -> None:
    """Open one activity on the route explorer."""
    goto("trasy", routes_activity_request=int(activity_id))


def open_run(activity_id: int) -> None:
    """Open one run on the running session page."""
    goto("bieg", run_activity_request=int(activity_id))
