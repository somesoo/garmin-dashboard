"""A local launch lives only as long as a browser tab is open on it.

``Dashboard.command`` / ``Dashboard.cmd`` set ``GARMIN_IDLE_EXIT_MIN``; once
no tab has been connected for that many minutes the server stops itself, so
nothing keeps running on the laptop after the page is closed. The next
double-click on the launcher starts it again.

Without the variable this does nothing -- the server deployment (systemd with
``Restart=always``) is meant to stay up.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

_log = logging.getLogger(__name__)
_started = False


def idle_exit() -> None:
    """Start the watchdog once per process (serve.py, before the server is up)."""
    global _started
    minutes = os.environ.get("GARMIN_IDLE_EXIT_MIN", "").strip()
    if _started or not minutes:
        return
    _started = True
    limit = float(minutes) * 60
    threading.Thread(target=_watch, args=(limit,), daemon=True, name="idle-exit").start()


def _active_sessions() -> int | None:
    # Private API: Streamlit has no public "who is connected". If it moves,
    # the watchdog stands down instead of stopping a server someone is using.
    try:
        from streamlit.runtime import Runtime

        if not Runtime.exists():
            return 0  # still starting: counts as idle, the clock is already running
        return Runtime.instance()._session_mgr.num_active_sessions()
    except Exception:  # noqa: BLE001
        return None


def _watch(limit: float) -> None:
    poll = max(1.0, min(10.0, limit / 3))
    idle_since = time.monotonic()
    while True:
        time.sleep(poll)
        active = _active_sessions()
        if active is None:
            _log.warning("idle-exit: brak licznika sesji Streamlit, serwer zostaje włączony")
            return
        now = time.monotonic()
        if active:
            idle_since = now
        elif now - idle_since >= limit:
            _log.info("idle-exit: brak otwartych kart od %.0f min, zamykam serwer", limit / 60)
            # Streamlit's own SIGTERM handler shuts the server down cleanly.
            os.kill(os.getpid(), signal.SIGTERM)
            return
