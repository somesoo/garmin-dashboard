"""Sealing small secrets at rest (Garmin tokens) with a key that does not live in ``data/``.

The Garmin token file is as good as the person's password (it refreshes itself
for months). On disk it is Fernet (AES-128-CBC + HMAC-SHA256) under one server
key. The key sits **outside** ``data/`` -- ``GARMIN_KEY_FILE`` or
``~/.config/garmin-dashboard/data.key`` (0600, created on first use) -- so a
copy of ``data/`` (``scp`` to a server, ``rsync`` to a laptop, a stray archive)
carries sealed tokens that open nowhere else. The encrypted backup
(``tools/backup.py``) takes the key along, sealed to the owner's backup key.

What this does not do: protect against someone who is root on the running
server. The server has to open the tokens to pull data; against that the
answer is the host (full-disk encryption, nobody else with a shell), see
docs/PRYWATNOSC.md.

Losing the key costs one thing: every Garmin person connects again (Konto ->
Garmin Connect). The health data itself is not sealed with it.
"""

from __future__ import annotations

import os
from pathlib import Path

KEY_ENV = "GARMIN_KEY_FILE"
DEFAULT_KEY = "~/.config/garmin-dashboard/data.key"


class Unreadable(ValueError):
    """Sealed with another key (data copied without it) or damaged."""


def key_path() -> Path:
    return Path(os.environ.get(KEY_ENV) or DEFAULT_KEY).expanduser()


def _key() -> bytes:
    from cryptography.fernet import Fernet

    path = key_path()
    try:
        return path.read_bytes().strip()
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = Fernet.generate_key()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:  # another process won the race
        return path.read_bytes().strip()
    with os.fdopen(fd, "wb") as out:
        out.write(value + b"\n")
    return value


def seal(data: bytes) -> bytes:
    from cryptography.fernet import Fernet

    return Fernet(_key()).encrypt(data)


def unseal(token: bytes) -> bytes:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return Fernet(_key()).decrypt(token)
    except (InvalidToken, ValueError) as exc:
        raise Unreadable(f"nie da się odczytać kluczem {key_path()}") from exc


def write(path: Path, data: bytes) -> None:
    """Seal ``data`` into ``path`` atomically, owner-only."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.part")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(seal(data))
    tmp.replace(path)


def read(path: Path) -> bytes:
    return unseal(path.read_bytes())
