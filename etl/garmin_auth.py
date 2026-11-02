"""Connecting a person's Garmin account from the browser (the account page), like etl/login.py.

The password is used for one login and dropped; what stays is the token file in
the person's own ``garmin/`` directory (tenant.User.tokenstore, mode 700). With
two-step verification the half-done login waits in the browser session for the
code -- never on disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOKEN_FILE = "garmin_tokens.json"


@dataclass
class Pending:
    """A login waiting for the two-step code (kept in the browser session only)."""

    api: Any
    state: Any


def connected(tokenstore: str) -> bool:
    return (Path(tokenstore).expanduser() / TOKEN_FILE).exists()


def _save(api: Any, tokenstore: str) -> str | None:
    folder = Path(tokenstore).expanduser()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    api.client.dump(str(folder))
    for path in folder.iterdir():
        if path.is_file():
            os.chmod(path, 0o600)
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
    folder = Path(tokenstore).expanduser()
    for name in (TOKEN_FILE, "oauth1_token.json", "oauth2_token.json"):
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
