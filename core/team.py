"""A coach and the people they train: who may look at whom, how far, and the notes between them.

The relation has two halves, and both must hold on every run:

1. the registry names the coach -- ``"coach": "<id>"`` on the athlete, set from
   the server's shell (``python -m core.tenant coach <athlete> <coach>``);
2. the athlete agreed -- for a child, a parent or legal guardian in their name
   (RODO art. 8, art. 9(2)(a)) -- on the consent screen or the account page.
   ``coach.json`` in the athlete's directory says which coach, how far
   (``scope``), who agreed and under which policy version. Withdrawing deletes
   the file and the coach loses the view on their next click.

Consent to the coach is separate from consent to the dashboard and never a
condition of it: an athlete who says no to the coach keeps the dashboard.

Scopes (``SCOPES``):

- ``all`` -- what the athlete sees, except their account, the SQL notebook and
  the insights (``NEVER``);
- ``training`` -- running, the plan, races, routes, sport (``TRAINING_PAGES``):
  no sleep, HRV, stress or recovery pages, and the loop's recovery number hidden.
  Heart rate *during* a run is training data and stays.

What a coach does in an athlete's dashboard: looks, writes notes, changes the
plan (create, rebuild, adjust, edit one session -- ``running.plan.edit_session``,
which a rebuild then leaves alone). What never: pulls, the account page,
Garmin, deleting, the athlete's language or level (those are the viewer's own,
``i18n.settings_path``). The first look at an athlete in a browser session goes
to the access log (``coach_view``), which the athlete reads on their account page.

Notes live in the athlete's directory (``notes.json``): they are about the
athlete, so they leave with the athlete's archive and go with an erase.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any

from core import audit
from core import tenant

SCOPES = ("all", "training")
AGREED_BY = ("self", "guardian")
# Never for a coach, whatever the scope: the athlete's account (Garmin, keys,
# deleting), the admin page, free SQL and the prose written about one person.
NEVER = ("konto", "admin", "sql", "insights")
# The "training only" scope: pages that read no sleep, HRV, stress or recovery
# at all. Not "obciazenie-biegowe" (its hero draws HRV, its tiles readiness) nor
# "sport" (readiness is built from recovery) -- a page is in or out whole, a tile
# hidden here and there would leak through the next one. "zespol" is the coach's own.
TRAINING_PAGES = ("bieganie", "plan", "prognoza", "segmenty", "bieg", "trasy", "atlas", "slownik", "zespol")
NOTE_MAX = 1000


# ------------------------------------------------------------------ the relation


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.part")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def athletes(coach: tenant.User) -> list[tenant.User]:
    """Everyone the registry names ``coach`` for -- agreed or still waiting -- by name."""
    return sorted((p for p in tenant.users().values() if p.coach_id == coach.id), key=lambda p: p.name.lower())


def is_coach(person: tenant.User) -> bool:
    return any(p.coach_id == person.id for p in tenant.users().values())


def grant(athlete: tenant.User) -> dict | None:
    """The athlete's consent to their coach, as stored; None when there is none."""
    value = _read(athlete.coach_grant, None)
    return value if isinstance(value, dict) else None


def _policy_version() -> str:
    from core import privacy

    return privacy.POLICY_VERSION


def valid(athlete: tenant.User) -> dict | None:
    """The consent, when it names the coach the registry names and today's policy; else None."""
    given = grant(athlete)
    if not given or not athlete.coach_id or given.get("coach") != athlete.coach_id:
        return None
    if given.get("scope") not in SCOPES or given.get("version") != _policy_version():
        return None
    return given


def allowed(coach_id: str, athlete: tenant.User) -> bool:
    """May ``coach_id`` look at ``athlete`` now? Registry, the athlete's consent to the
    dashboard and their consent to this coach -- all three."""
    from core import privacy

    if athlete.coach_id != coach_id or athlete.id == coach_id:
        return False
    if privacy.required(athlete):
        return False
    return valid(athlete) is not None


def scope(athlete: tenant.User) -> str | None:
    given = valid(athlete)
    return given["scope"] if given else None


def give(athlete: tenant.User, scope_value: str, agreed_by: str = "self", guardian: str | None = None,
         ip: str | None = None) -> dict:
    """Record the athlete's (or their guardian's) consent to their coach."""
    if not athlete.coach_id:
        raise ValueError("ta osoba nie ma trenera")
    if scope_value not in SCOPES:
        raise ValueError(f"zakres: {', '.join(SCOPES)}")
    if agreed_by not in AGREED_BY:
        raise ValueError(f"kto: {', '.join(AGREED_BY)}")
    guardian = " ".join(str(guardian or "").split())[:80] or None
    if agreed_by == "guardian" and not guardian:
        raise ValueError("zgoda rodzica: brak imienia i nazwiska")
    record = {"coach": athlete.coach_id, "scope": scope_value, "by": agreed_by, "guardian": guardian,
              "at": dt.datetime.now().isoformat(timespec="seconds"), "version": _policy_version()}
    _write(athlete.coach_grant, record)
    audit.record("coach_grant", athlete.id, coach=athlete.coach_id, scope=scope_value, by=agreed_by, ip=ip)
    return record


def revoke(athlete: tenant.User, ip: str | None = None) -> None:
    if athlete.coach_grant.exists():
        athlete.coach_grant.unlink(missing_ok=True)
        audit.record("coach_revoke", athlete.id, coach=athlete.coach_id, ip=ip)


def page_allowed(url_path: str, scope_value: str | None) -> bool:
    """Is this page shown to a coach looking at an athlete with ``scope_value``?"""
    if url_path in NEVER or scope_value not in SCOPES:
        return False
    return scope_value == "all" or url_path in TRAINING_PAGES


# ------------------------------------------------------------------ notes


def notes(athlete: tenant.User) -> list[dict[str, Any]]:
    """Newest first."""
    found = _read(athlete.notes_file, [])
    if not isinstance(found, list):
        return []
    return sorted((n for n in found if isinstance(n, dict) and n.get("text")), key=lambda n: str(n.get("at")),
                  reverse=True)


def add_note(athlete: tenant.User, author: tenant.User, text: str, day: str | None = None,
             session: str | None = None) -> dict[str, Any]:
    """A note in the athlete's thread; only the athlete and their coach write there."""
    if author.id not in (athlete.id, athlete.coach_id):
        raise PermissionError("notatki pisze tylko osoba i jej trener")
    text = str(text or "").strip()[:NOTE_MAX]
    if not text:
        raise ValueError("pusta notatka")
    if day is not None:
        day = dt.date.fromisoformat(day).isoformat()
    note = {"id": uuid.uuid4().hex[:10], "at": dt.datetime.now().isoformat(timespec="seconds"), "by": author.id,
            "text": text, "read_by": [author.id]}
    if day:
        note["day"] = day
    if session:
        note["session"] = str(session)[:40]
    _write(athlete.notes_file, [note, *notes(athlete)])
    return note


def delete_note(athlete: tenant.User, note_id: str, author: tenant.User) -> bool:
    """Remove one's own note; True when something went."""
    kept = [n for n in notes(athlete) if not (n.get("id") == note_id and n.get("by") == author.id)]
    if len(kept) == len(notes(athlete)):
        return False
    _write(athlete.notes_file, kept)
    return True


def unread(athlete: tenant.User, reader_id: str) -> list[dict[str, Any]]:
    """Notes someone else wrote in this thread that ``reader_id`` has not seen yet."""
    return [n for n in notes(athlete) if n.get("by") != reader_id and reader_id not in (n.get("read_by") or [])]


def mark_read(athlete: tenant.User, reader_id: str) -> None:
    found = notes(athlete)
    changed = False
    for note in found:
        seen = list(note.get("read_by") or [])
        if reader_id not in seen:
            note["read_by"] = [*seen, reader_id]
            changed = True
    if changed:
        _write(athlete.notes_file, found)
