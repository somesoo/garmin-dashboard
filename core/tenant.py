"""Whose data: one directory per person, chosen per request.

Layout::

    data/users.json        the registry: who exists and how they are recognised
    data/server.secret     random key behind every per-person file name the browser sees
    data/users/<id>/       everything one person owns -- raw/, tables/, coach/, state.json,
                           excluded_nights.json, sport.json, ui.json, fetch.*, garmin/ (tokens)

Without ``data/users.json`` the app is single-user exactly as before: one person,
``me``, whose directory is ``data/`` itself. Nothing moves until someone is added.

Registry::

    {"users": {
       "x": {"name": "X", "source": "garmin", "identities": ["x@example.com"],
             "local": true, "insights": true, "root": "."},
       "y": {"name": "Y", "source": "apple", "identities": ["y@example.com"]}}}

- ``source``: where the data comes from (``garmin`` / ``apple``); only Garmin
  people get the pull button and the timer.
- ``identities``: e-mails / logins the sign-in layer (``auth.py``) may present.
- ``local``: a browser on this machine with no other identity is this person.
- ``insights``: the notes in ``insights/`` are prose about one person's numbers,
  so only the person they were written about sees them.
- ``admin``: sees the admin page (views/admin.py: people, server, pulls). Set
  with ``python -m core.tenant admin <id>``; the single-user layout's one person is admin.
- ``root``: directory relative to ``data/``; ``"."`` is the old single-user layout,
  left in place until ``python -m core.tenant migrate <id>``.
- ``tokenstore``: Garmin token directory; default ``data/users/<id>/garmin``
  (for ``root: "."``: ``GARMIN_TOKENSTORE`` or ``~/.garminconnect`` as before).

Who is "current" (``current()``), first match wins:

1. ``with tenant.use(id):`` -- explicit (the pull timer, tests);
2. inside a Streamlit run: the person ``auth.gate`` put in the session -- never
   the environment, so a variable left on the server cannot open anyone's data;
3. outside Streamlit: ``GARMIN_USER`` (CLIs, the detached ``etl/run.py``);
4. the only person in the registry.

More than one person and none of the above is an error, not a default: a page
that cannot tell whose data to read must not read anyone's.

    python -m core.tenant                         list people
    python -m core.tenant init x --name X         start a registry from today's data/ (root ".")
    python -m core.tenant add y --name Y --source apple --identity y@example.com
    python -m core.tenant migrate x               move a root "." person into data/users/x/
    python -m core.tenant remove y --yes          delete a person and everything they own
"""

from __future__ import annotations

import argparse
import contextlib
import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from core import config

REGISTRY = config.DATA / "users.json"
SECRET = config.DATA / "server.secret"
USERS = config.DATA / "users"
LEGACY_ID = "me"
SESSION_KEY = "tenant_user"
SOURCES = ("garmin", "apple")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
# What belongs to one person in the old layout -- moved by ``migrate``.
OWNED = ("raw", "tables", "coach", "state.json", "excluded_nights.json", "sport.json", "ui.json",
         "fetch.json", "fetch.log", "zones.json", "consent.json", "seen.json")

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant", default=None)


class NoUser(LookupError):
    """More than one person is registered and nothing says whose request this is."""


@dataclass(frozen=True)
class User:
    id: str
    name: str
    source: str
    root: Path
    identities: tuple[str, ...] = ()
    local: bool = False
    insights: bool = False
    legacy: bool = False
    admin: bool = False
    tokenstore_override: str | None = field(default=None, repr=False)

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def tables(self) -> Path:
        return self.root / "tables"

    @property
    def coach(self) -> Path:
        return self.root / "coach"

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"

    @property
    def excluded_nights(self) -> Path:
        # Nights recorded on someone else's wrist: typed in by hand (etl/exclude.py),
        # so like coach/ it cannot be rebuilt from raw/.
        return self.root / "excluded_nights.json"

    @property
    def ui_settings(self) -> Path:
        return self.root / "ui.json"

    @property
    def sport_settings(self) -> Path:
        return self.root / "sport.json"

    @property
    def zone_settings(self) -> Path:
        # Heart-rate anchors typed in from a test (hrzones.py); like coach/, not rebuildable from raw/.
        return self.root / "zones.json"

    @property
    def consent_file(self) -> Path:
        # The consent this person gave (core/privacy.py): which policy version, when, in which language.
        return self.root / "consent.json"

    @property
    def seen_file(self) -> Path:
        # The last day this person used the app -- the inactivity rule of core/privacy.py reads it.
        return self.root / "seen.json"

    @property
    def fetch_lock(self) -> Path:
        return self.root / "fetch.lock"

    @property
    def fetch_record(self) -> Path:
        return self.root / "fetch.json"

    @property
    def fetch_log(self) -> Path:
        return self.root / "fetch.log"

    @property
    def tokenstore(self) -> str:
        if self.tokenstore_override:
            return self.tokenstore_override
        if self.legacy:
            return os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect")
        return str(self.root / "garmin")

    def file_key(self, purpose: str) -> str:
        """An unguessable, stable name part for files the browser fetches by URL.

        The globe's track file is served statically; with the person's id or a
        timestamp in its name anyone could ask for someone else's routes.
        """
        digest = hmac.new(_secret(), f"{purpose}:{self.id}".encode(), hashlib.sha256).hexdigest()
        return digest[:20]


# ----------------------------------------------------------------- registry


def _read_registry() -> dict | None:
    try:
        payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        # A broken registry must not silently fall back to "single user":
        # that would hand data/ to whoever opens the page.
        raise RuntimeError(f"{REGISTRY} nie da się odczytać: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("users"), dict):
        raise RuntimeError(f"{REGISTRY}: oczekiwano {{\"users\": {{...}}}}")
    return payload


def _user(user_id: str, entry: dict) -> User:
    if not ID_PATTERN.match(user_id):
        raise RuntimeError(f"{REGISTRY}: niedozwolony identyfikator {user_id!r}")
    source = entry.get("source", "garmin")
    if source not in SOURCES:
        raise RuntimeError(f"{REGISTRY}: {user_id}: nieznane źródło {source!r}")
    root_value = entry.get("root")
    legacy = root_value == "."
    if root_value is None:
        root = USERS / user_id
    else:
        root = (config.DATA / root_value).resolve()
        if root != config.DATA.resolve() and config.DATA.resolve() not in root.parents:
            raise RuntimeError(f"{REGISTRY}: {user_id}: katalog poza data/")
    return User(
        id=user_id,
        name=str(entry.get("name") or user_id),
        source=source,
        root=root,
        identities=tuple(str(i).strip().lower() for i in entry.get("identities", ()) if str(i).strip()),
        local=bool(entry.get("local", False)),
        insights=bool(entry.get("insights", legacy)),
        legacy=legacy,
        admin=bool(entry.get("admin", False)),
        tokenstore_override=entry.get("tokenstore"),
    )


def registered() -> bool:
    """Is there a registry at all? Without one the app is single-user."""
    return REGISTRY.exists()


def users() -> dict[str, User]:
    payload = _read_registry()
    if payload is None:
        return {LEGACY_ID: User(id=LEGACY_ID, name=LEGACY_ID, source="garmin", root=config.DATA,
                                local=True, insights=True, legacy=True, admin=True)}
    return {user_id: _user(user_id, entry) for user_id, entry in payload["users"].items()}


def get(user_id: str) -> User:
    found = users().get(user_id)
    if found is None:
        raise NoUser(f"nie ma osoby {user_id!r} w {REGISTRY}")
    return found


def by_identity(value: str | None) -> User | None:
    """The person an e-mail / login belongs to, or None."""
    wanted = (value or "").strip().lower()
    if not wanted:
        return None
    matches = [user for user in users().values() if wanted in user.identities]
    return matches[0] if len(matches) == 1 else None


def local_user() -> User | None:
    """The person a browser on this machine is, when exactly one is marked ``local``."""
    marked = [user for user in users().values() if user.local]
    return marked[0] if len(marked) == 1 else None


# ------------------------------------------------------------ who is current


def _streamlit_session() -> tuple[bool, str | None]:
    """(inside a Streamlit run?, the person in its session)."""
    if "streamlit" not in sys.modules:
        return False, None
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:  # pragma: no cover - private API moved
        return False, None
    ctx = get_script_run_ctx(suppress_warning=True)
    if ctx is None:
        return False, None
    import streamlit as st

    return True, st.session_state.get(SESSION_KEY)


def current() -> User:
    explicit = _current.get()
    if explicit:
        return get(explicit)
    in_streamlit, chosen = _streamlit_session()
    if chosen:
        return get(chosen)
    if not in_streamlit:
        named = os.getenv("GARMIN_USER", "").strip()
        if named:
            return get(named)
    everyone = users()
    if len(everyone) == 1:
        return next(iter(everyone.values()))
    raise NoUser("kilka osób w rejestrze, a żądanie nie mówi, czyje dane czytać "
                 "(GARMIN_USER=<id> dla CLI)")


@contextlib.contextmanager
def use(user_id: str) -> Iterator[User]:
    """Run a block as ``user_id`` (the pull timer, scripts, tests)."""
    user = get(user_id)
    token = _current.set(user.id)
    try:
        yield user
    finally:
        _current.reset(token)


def _secret() -> bytes:
    try:
        return SECRET.read_bytes()
    except FileNotFoundError:
        pass
    SECRET.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_bytes(32)
    try:
        fd = os.open(SECRET, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:  # another process won the race
        return SECRET.read_bytes()
    with os.fdopen(fd, "wb") as out:
        out.write(value)
    return value


# ---------------------------------------------------------------- the CLI


def _write_registry(payload: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(f".json.{os.getpid()}.part")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(REGISTRY)


def _entry(args: argparse.Namespace) -> dict:
    entry: dict = {"name": args.name or args.id, "source": args.source}
    if args.identity:
        entry["identities"] = args.identity
    if args.local:
        entry["local"] = True
    return entry


def init(args: argparse.Namespace) -> int:
    if registered():
        print(f"{REGISTRY} już istnieje")
        return 1
    entry = {**_entry(args), "root": ".", "insights": True}
    _user(args.id, entry)  # validate before writing
    _write_registry({"users": {args.id: entry}})
    print(f"Rejestr założony: {args.id} czyta dotychczasowe data/ (przenosi: python -m core.tenant migrate {args.id})")
    return 0


def add(args: argparse.Namespace) -> int:
    payload = _read_registry()
    if payload is None:
        print("Najpierw `python -m core.tenant init <id>` dla osoby, której dane są dziś w data/")
        return 1
    if args.id in payload["users"]:
        print(f"{args.id} już jest w rejestrze")
        return 1
    entry = _entry(args)
    user = _user(args.id, entry)
    payload["users"][args.id] = entry
    _write_registry(payload)
    user.root.mkdir(parents=True, exist_ok=True)
    from core import level
    level.remember(level.NEW_PERSON, user.ui_settings)  # a newcomer starts with the everyday pages
    print(f"Dodano {args.id} ({user.source}) -> {user.root}")
    return 0


def migrate(args: argparse.Namespace) -> int:
    payload = _read_registry()
    if payload is None or args.id not in payload["users"]:
        print(f"{args.id} nie ma w rejestrze")
        return 1
    entry = payload["users"][args.id]
    if entry.get("root") != ".":
        print(f"{args.id} ma już własny katalog")
        return 0
    if (config.DATA / "fetch.lock").exists():
        print("Trwa pobieranie (data/fetch.lock) — spróbuj po jego końcu")
        return 1
    target = USERS / args.id
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in OWNED:
        source = config.DATA / name
        if not source.exists():
            continue
        if (target / name).exists():
            print(f"{target / name} już istnieje — przerwane, nic więcej nie przeniesiono")
            return 1
        shutil.move(str(source), str(target / name))
        moved.append(name)
    entry.pop("root")
    # The tokens stay where etl/login.py put them; only their location is written down.
    entry.setdefault("tokenstore", os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect"))
    _write_registry(payload)
    print(f"Przeniesiono do {target}: {', '.join(moved) or 'nic'}")
    return 0


EDITABLE = ("name", "source")


def update(user_id: str, **fields: str) -> User:
    """Change what a person may change about themselves (account page): name, source.

    Without a registry (the single-user layout) one is created first, so the
    person's choice has somewhere to live; their data stays where it is.
    """
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise ValueError(f"nie do zmiany: {', '.join(sorted(unknown))}")
    if "source" in fields and fields["source"] not in SOURCES:
        raise ValueError(f"źródło: {', '.join(SOURCES)}")
    if "name" in fields:
        fields["name"] = " ".join(str(fields["name"]).split())[:60]
        if not fields["name"]:
            raise ValueError("pusta nazwa")
    payload = _read_registry()
    if payload is None:
        payload = {"users": {LEGACY_ID: {"name": LEGACY_ID, "source": "garmin", "root": ".", "insights": True,
                                         "local": True}}}
    if user_id not in payload["users"]:
        raise NoUser(f"nie ma osoby {user_id!r}")
    entry = {**payload["users"][user_id], **fields}
    _user(user_id, entry)  # validate before writing
    payload["users"][user_id] = entry
    _write_registry(payload)
    return get(user_id)


def archive(person: User) -> bytes:
    """Everything the person owns, as one zip (the right to a copy of one's data)."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for path in sorted(person.root.rglob("*")) if person.root.is_dir() else []:
            relative = path.relative_to(person.root)
            # Never hand out secrets: token hashes, Garmin login tokens, caches.
            if not path.is_file() or relative.parts[0] in ("garmin", "cache") or relative.name == "tokens.json":
                continue
            if person.legacy and relative.parts[0] not in OWNED:
                continue  # the old layout's data/ also holds other people and the server's files
            out.write(path, str(relative))
        # Who opened this person's data and when (core/audit.py) is theirs to see too (RODO art. 15).
        from core import audit

        lines = audit.events(person.id, limit=1_000_000)
        if lines:
            out.writestr("access_log.jsonl", "".join(json.dumps(item, ensure_ascii=False) + "\n"
                                                     for item in reversed(lines)))
    return buffer.getvalue()


def erase(person: User) -> list[str]:
    """Delete everything the person owns; the registry entry stays (they can sign in to an empty page).
    Returns what was removed."""
    if person.legacy:
        raise RuntimeError("stary układ (root \".\"): najpierw `python -m core.tenant migrate`, potem usuwanie")
    if not person.root.is_dir():
        return []
    removed = sorted(p.name for p in person.root.iterdir())
    shutil.rmtree(person.root)
    person.root.mkdir(parents=True, exist_ok=True)
    return removed


def admin(args: argparse.Namespace) -> int:
    """Give (or with ``--off`` take away) the admin page. Only from the server's shell, never from the app."""
    payload = _read_registry()
    if payload is None or args.id not in payload["users"]:
        print(f"{args.id} nie ma w rejestrze")
        return 1
    entry = dict(payload["users"][args.id])
    if args.off:
        entry.pop("admin", None)
    else:
        entry["admin"] = True
    payload["users"][args.id] = entry
    _write_registry(payload)
    print(f"{args.id}: admin {'wyłączony' if args.off else 'włączony'}")
    return 0


def remove(args: argparse.Namespace) -> int:
    payload = _read_registry()
    if payload is None or args.id not in payload["users"]:
        print(f"{args.id} nie ma w rejestrze")
        return 1
    person = _user(args.id, payload["users"][args.id])
    if not args.yes:
        print(f"Usunie {person.root} i wpis {args.id} z rejestru. Powtórz z --yes.")
        return 1
    if person.legacy:
        print("stary układ (root \".\"): najpierw `python -m core.tenant migrate`")
        return 1
    shutil.rmtree(person.root, ignore_errors=True)
    del payload["users"][args.id]
    _write_registry(payload)
    print(f"Usunięto {args.id}")
    return 0


def show(_: argparse.Namespace) -> int:
    for user in users().values():
        flags = [flag for flag, on in (("local", user.local), ("insights", user.insights), ("legacy", user.legacy),
                                       ("admin", user.admin)) if on]
        print(f"{user.id:12} {user.source:7} {user.root}  {', '.join(user.identities)}  {' '.join(flags)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.tenant", description="Osoby i ich katalogi danych")
    sub = parser.add_subparsers(dest="command")
    for name in ("init", "add"):
        cmd = sub.add_parser(name)
        cmd.add_argument("id")
        cmd.add_argument("--name")
        cmd.add_argument("--source", choices=SOURCES, default="garmin")
        cmd.add_argument("--identity", action="append", help="e-mail/login z warstwy logowania (można kilka)")
        cmd.add_argument("--local", action="store_true", help="przeglądarka na tym komputerze = ta osoba")
    sub.add_parser("migrate").add_argument("id")
    drop = sub.add_parser("remove")
    drop.add_argument("id")
    drop.add_argument("--yes", action="store_true")
    sub.add_parser("list")
    boss = sub.add_parser("admin", help="dostęp do strony Admin (osoby, serwer, synchronizacje)")
    boss.add_argument("id")
    boss.add_argument("--off", action="store_true", help="odbierz dostęp")
    args = parser.parse_args(argv)
    handler = {"init": init, "add": add, "migrate": migrate, "remove": remove, "admin": admin}.get(args.command, show)
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
