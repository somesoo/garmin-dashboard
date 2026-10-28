"""Fetching from Garmin Connect in the background, next to a running server.

The launchers no longer fetch before starting the site: the page opens at
once, and a pull runs either from the sidebar button or on its own once the
last one is ``GARMIN_AUTO_FETCH_H`` hours old (the launchers set 6). Every
pull is ``etl/run.py`` in its own process, so it survives the server's idle
exit and never blocks a rerun.

``etl/run.py`` owns the bookkeeping: ``data/fetch.lock`` (pid, created
exclusively -- two pulls never write the same raw files) and
``data/fetch.json`` (when the last pull started and finished, its exit code).
This module only reads them, starts the process and runs the timer.

Without the variable there is no timer (the systemd/pm2 deployment has its own
schedule); the button works everywhere.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "data" / "fetch.lock"
RECORD = ROOT / "data" / "fetch.json"
LOG = ROOT / "data" / "fetch.log"
# A pull that failed for a network reason is retried sooner than a good one is
# repeated; an expired token (code 2) waits the full interval -- only the
# password login fixes it.
RETRY_AFTER_H = 0.5

_log = logging.getLogger(__name__)
_started = False


def alive(pid: int, marker: str) -> bool:
    """Is ``pid`` still running a command containing ``marker``?"""
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # Guard against a recycled pid: it must still be the same program.
    command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    return marker in command


def running() -> bool:
    try:
        pid = int(LOCK.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return alive(pid, "run.py")


def last() -> dict:
    """``{"started_at", "finished_at", "code"}`` of the latest pull, or {}."""
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def next_due(hours: float) -> dt.datetime | None:
    """When the timer pulls next; None when there is no pull on record."""
    record = last()
    try:
        started = dt.datetime.fromisoformat(record["started_at"])
    except (KeyError, TypeError, ValueError):
        return None
    # No code: the process died before writing one (killed, crashed).
    wait = hours if record.get("code") in (0, 2) else RETRY_AFTER_H
    return started + dt.timedelta(hours=wait)


def due(hours: float, now: dt.datetime | None = None) -> bool:
    edge = next_due(hours)
    return edge is None or (now or dt.datetime.now()) >= edge


def start() -> bool:
    """Start ``etl/run.py`` detached; False when a pull is already running."""
    if running():
        return False
    LOG.parent.mkdir(parents=True, exist_ok=True)
    detach = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with LOG.open("w", encoding="utf-8") as out:
        subprocess.Popen(
            [sys.executable, str(ROOT / "etl" / "run.py")],
            cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **detach,
        )
    # The child takes the lock a moment later; wait so the page asking right
    # after the click already sees "running".
    for _ in range(20):
        if running():
            break
        time.sleep(0.1)
    return True


def auto() -> None:
    """Start the pull timer once per process (serve.py, before the server is up)."""
    global _started
    hours = os.environ.get("GARMIN_AUTO_FETCH_H", "").strip()
    if _started or not hours:
        return
    _started = True
    threading.Thread(target=_watch, args=(float(hours),), daemon=True, name="auto-fetch").start()


def _watch(hours: float) -> None:
    while True:
        try:
            if not running() and due(hours):
                _log.info("auto-fetch: ostatnie pobranie starsze niż %.0f h, startuję", hours)
                start()
        except Exception:  # noqa: BLE001 - the timer must outlive one bad check
            _log.exception("auto-fetch: sprawdzenie nie powiodło się")
        time.sleep(600)
