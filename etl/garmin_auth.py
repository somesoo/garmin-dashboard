"""The person's Garmin tokens: connecting from the browser, sealed on disk, opened for a pull.

The password is used for one login and dropped; what stays is the token payload,
**sealed** (core/secretbox.py) as ``garmin_tokens.enc`` in the person's own
token directory (tenant.User.tokenstore, mode 700). A plain
``garmin_tokens.json`` left by an older version (or by ``garminconnect`` itself)
is sealed and removed the first time it is read. With two-step verification the
half-done login waits in the browser session for the code -- never on disk.

``connect`` is the only way the pipeline logs in: it opens the tokens in memory,
hands them to ``garminconnect`` as inline JSON, and puts every refresh back
sealed (a refresh rotates the token; losing it would mean a new password login).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import secretbox

TOKEN_FILE = "garmin_tokens.json"  # garminconnect's own, plain -- only ever read to be sealed
SEALED_FILE = "garmin_tokens.enc"


@dataclass
class Pending:
    """A login waiting for the two-step code (kept in the browser session only)."""

    api: Any
    state: Any


def _folder(tokenstore: str) -> Path:
    return Path(tokenstore).expanduser()


def connected(tokenstore: str) -> bool:
    folder = _folder(tokenstore)
    return (folder / SEALED_FILE).exists() or (folder / TOKEN_FILE).exists()


def store(tokenstore: str, payload: str) -> None:
    """Seal the token payload; the plain file, if any, goes."""
    folder = _folder(tokenstore)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    secretbox.write(folder / SEALED_FILE, payload.encode())
    (folder / TOKEN_FILE).unlink(missing_ok=True)


def load(tokenstore: str) -> str | None:
    """The token payload (JSON text), or None when this person never connected.

    Raises ``secretbox.Unreadable`` when the file was sealed with another key
    (``data/`` copied without ``GARMIN_KEY_FILE``)."""
    folder = _folder(tokenstore)
    sealed = folder / SEALED_FILE
    if sealed.exists():
        return secretbox.read(sealed).decode()
    plain = folder / TOKEN_FILE
    if plain.exists():
        payload = plain.read_text(encoding="utf-8")
        store(tokenstore, payload)
        return payload
    return None


def connect(tokenstore: str) -> Any:
    """A logged-in ``Garmin`` from the sealed tokens; refreshes are sealed back."""
    from garminconnect import Garmin, GarminConnectAuthenticationError

    try:
        payload = load(tokenstore)
    except secretbox.Unreadable as exc:
        raise GarminConnectAuthenticationError(
            "tokeny zaszyfrowane innym kluczem (GARMIN_KEY_FILE) — połącz Garmina ponownie") from exc
    if not payload:
        raise GarminConnectAuthenticationError("brak tokenów — połącz Garmina (Konto albo etl/login.py)")
    api = Garmin()
    api.login(payload)  # inline JSON: nothing plain touches the disk
    _persist_refreshes(api, tokenstore)
    store(tokenstore, api.client.dumps())  # login may have refreshed already
    return api


def _persist_refreshes(api: Any, tokenstore: str) -> None:
    """garminconnect writes a refreshed token with ``client.dump(path)``; route that through the seal."""
    client = api.client
    client.dump = lambda _path: store(tokenstore, client.dumps())
    client._tokenstore_path = tokenstore


def _save(api: Any, tokenstore: str) -> str | None:
    store(tokenstore, api.client.dumps())
    try:
        return api.get_full_name()
    except Exception:  # noqa: BLE001 - the name is a courtesy, the tokens are what matters
        return None


def start(email: str, password: str, tokenstore: str) -> tuple[str, Any]:
    """``("ok", full name)`` or ``("mfa", Pending)``; raises on a wrong password or a blocked login."""
    from garminconnect import Garmin

    api = Garmin(email=email.strip(), password=password, return_on_mfa=True)
    status, state = api.login()  # no tokenstore: a fresh login with these credentials
    if status == "needs_mfa":
        return "mfa", Pending(api, state)
    return "ok", _save(api, tokenstore)


def finish(pending: Pending, code: str, tokenstore: str) -> str | None:
    pending.api.resume_login(pending.state, code.strip())
    return _save(pending.api, tokenstore)


def disconnect(tokenstore: str) -> None:
    """Forget the Garmin tokens (the data already pulled stays)."""
    folder = _folder(tokenstore)
    for name in (SEALED_FILE, TOKEN_FILE, "oauth1_token.json", "oauth2_token.json"):
        (folder / name).unlink(missing_ok=True)


def describe(error: Exception) -> str:
    """A short, safe reason for the page -- never the request or the password."""
    text = str(error)
    for marker in ("401", "403", "Unauthorized", "credentials", "password"):
        if marker.lower() in text.lower():
            return "credentials"
    if "429" in text or "Too Many" in text:
        return "throttled"
    return "other"
