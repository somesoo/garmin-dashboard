"""Who opened whose data, and when: the access log (RODO art. 5(2), 32; docs/PRYWATNOSC.md).

One JSON line per event in ``data/audit/<YYYY-MM>.jsonl`` (0600). **Never a
health value** -- only who, when, which kind of access, from where:

    {"at": "2026-11-07T08:12:03", "event": "signin", "person": "y", "ip": "100.64.0.7"}

Events (``EVENTS``): a sign-in (once per browser session), a refused sign-in
(with the identity that was presented), the phone app reading (at most once an
hour per key), an iPhone push, an archive, an erase, a consent given or
withdrawn, a Garmin account connected or forgotten, an admin action on someone
else's data, a deletion for inactivity.

Months older than ``KEEP_DAYS`` are deleted on the next write: the log is for
spotting misuse and answering "who saw my data", not a history of people.
Each person sees their own lines on the account page; the admin page sees
everyone's (no health data is in them). Writing never breaks the request that
caused it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from core import config

DIR = config.DATA / "audit"
KEEP_DAYS = 92
EVENTS = ("signin", "refused", "api_read", "api_ingest", "archive", "erase", "consent", "withdraw",
          "garmin_connect", "garmin_disconnect", "admin", "inactive_erase", "policy")
# The phone app polls; one line an hour per key says the same as sixty.
API_EVERY_S = 3600

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_recent: dict[str, float] = {}


def _file(day: dt.date) -> Path:
    return DIR / f"{day:%Y-%m}.jsonl"


def record(event: str, person: str | None = None, **fields: Any) -> None:
    """Append one event. ``fields``: short strings only (ip, identity, key prefix, detail)."""
    if event not in EVENTS:
        raise ValueError(f"nieznane zdarzenie {event!r}")
    now = dt.datetime.now().replace(microsecond=0)
    line = {"at": now.isoformat(), "event": event}
    if person:
        line["person"] = person
    line.update({k: str(v)[:200] for k, v in fields.items() if v not in (None, "")})
    try:
        with _lock:
            DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = _file(now.date())
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as out:
                out.write(json.dumps(line, ensure_ascii=False) + "\n")
            prune(now.date())
    except OSError:
        _log.exception("audit: nie udało się zapisać zdarzenia %s", event)


def api_read(person: str, key_prefix: str, ip: str | None) -> None:
    """A read by the phone app, at most once per ``API_EVERY_S`` per key."""
    stamp = time.monotonic()
    with _lock:
        last = _recent.get(key_prefix)
        if last is not None and stamp - last < API_EVERY_S:
            return
        _recent[key_prefix] = stamp
    record("api_read", person, key=key_prefix, ip=ip)


def prune(today: dt.date | None = None) -> list[str]:
    """Delete months that ended more than ``KEEP_DAYS`` ago; their names."""
    today = today or dt.date.today()
    edge = today - dt.timedelta(days=KEEP_DAYS)
    removed = []
    for path in DIR.glob("*.jsonl") if DIR.is_dir() else []:
        try:
            month = dt.datetime.strptime(path.stem, "%Y-%m").date()
        except ValueError:
            continue
        month_end = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        if month_end < edge:
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


def events(person: str | None = None, limit: int = 200) -> list[dict]:
    """Newest first; ``person`` keeps that person's lines only."""
    found: list[dict] = []
    for path in sorted(DIR.glob("*.jsonl"), reverse=True) if DIR.is_dir() else []:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in reversed(lines):
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if person is None or item.get("person") == person:
                found.append(item)
                if len(found) >= limit:
                    return found
    return found


def client_ip(headers: Any, peer: str | None = None) -> str | None:
    """The visitor's address behind the proxy (first X-Forwarded-For hop), else the peer."""
    try:
        forwarded = headers.get("x-forwarded-for") or headers.get("x-real-ip")
    except Exception:  # noqa: BLE001
        forwarded = None
    if forwarded:
        return forwarded.split(",")[0].strip()
    return peer
