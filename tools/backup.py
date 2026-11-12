"""Encrypted backups of ``data/``: the server can make them, only the owner can open them.

    # once, on the owner's own machine (the Mac): a key pair
    .venv/bin/python tools/backup.py keygen ~/.config/garmin-dashboard/backup.key
    #   -> prints the public key (gdpub1...), which is all the server ever gets

    # on the server (cron / systemd timer), e.g. nightly:
    .venv/bin/python tools/backup.py create --to gdpub1... --out /var/backups/garmin
    #   -> /var/backups/garmin/garmin-20261107-0300.gdbk; older than backup_days (privacy.json, 30) deleted

    # on the owner's machine:
    rsync -a --delete server:/var/backups/garmin/ ~/garmin-backup/      # encrypted files only
    .venv/bin/python tools/backup.py list    ~/garmin-backup/garmin-....gdbk --identity ~/.config/garmin-dashboard/backup.key
    .venv/bin/python tools/backup.py restore ~/garmin-backup/garmin-....gdbk --identity ... --into ./restored

Why public-key: a backup lies somewhere else (a laptop, a disk, a cloud folder)
for weeks. Sealed to a key the server does not have, a stolen server cannot
read old backups and a stolen backup is noise. Rotation is what makes deletion
real: a deleted person (RODO art. 17) is gone from every backup after
``backup_days`` (the policy promises it, core/privacy.py).

The archive is ``data/`` as tar.gz plus the token key (core/secretbox.py, under
``_keys/``) -- a restore without it would leave every Garmin person to connect
again. Format ``GDBK1``: X25519 ephemeral key, HKDF-SHA256, AES-256-GCM in 1 MiB
chunks with a counter nonce and a "last chunk" flag (a cut file does not open).
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import os
import struct
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: E402

MAGIC = b"GDBK1\n"
PUB_PREFIX = "gdpub1"
PRIV_PREFIX = "gdkey1"
CHUNK = 1 << 20
INFO = b"garmin-dashboard backup v1"
NAME = "garmin-{:%Y%m%d-%H%M}.gdbk"
SKIP = {"cache", "terrain", "fetch.lock", "streamlit.log"}  # public rasters/cache are rebuilt after a restore


# ------------------------------------------------------------------ keys


def _raw_public(key: X25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def keygen(path: Path) -> str:
    """A new identity at ``path`` (0600); returns the public key to give the server."""
    if path.exists():
        raise SystemExit(f"{path} już istnieje — nie nadpisuję klucza, bez niego stare kopie są nie do otwarcia")
    private = X25519PrivateKey.generate()
    raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    public = PUB_PREFIX + base64.urlsafe_b64encode(_raw_public(private.public_key())).decode()
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(f"# klucz do kopii zapasowych garmin-dashboard; publiczny: {public}\n")
        out.write(PRIV_PREFIX + base64.urlsafe_b64encode(raw).decode() + "\n")
    return public


def _public(value: str) -> X25519PublicKey:
    text = value.strip()
    if not text.startswith(PUB_PREFIX) and Path(text).expanduser().is_file():
        text = Path(text).expanduser().read_text(encoding="utf-8").strip()
    if not text.startswith(PUB_PREFIX):
        raise SystemExit("--to: oczekiwano klucza publicznego gdpub1… (albo pliku z nim)")
    return X25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(text[len(PUB_PREFIX):]))


def _private(path: Path) -> X25519PrivateKey:
    for line in path.expanduser().read_text(encoding="utf-8").splitlines():
        if line.startswith(PRIV_PREFIX):
            return X25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(line[len(PRIV_PREFIX):]))
    raise SystemExit(f"{path}: brak klucza {PRIV_PREFIX}…")


def _derive(shared: bytes, ephemeral: bytes, recipient: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=ephemeral + recipient, info=INFO).derive(shared)


# ------------------------------------------------------------------ the stream


def _nonce(counter: int) -> bytes:
    return b"\0\0\0\0" + struct.pack(">Q", counter)


class _Sealer(io.RawIOBase):
    """A write-only stream: whatever tar writes leaves as sealed chunks."""

    def __init__(self, out, recipient: X25519PublicKey):
        super().__init__()
        ephemeral = X25519PrivateKey.generate()
        ephemeral_raw = _raw_public(ephemeral.public_key())
        self._aead = AESGCM(_derive(ephemeral.exchange(recipient), ephemeral_raw, _raw_public(recipient)))
        self._out = out
        self._buffer = bytearray()
        self._counter = 0
        out.write(MAGIC + ephemeral_raw)

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self._buffer += data
        while len(self._buffer) > CHUNK:  # keep at least one byte back: the last chunk is flagged on close
            self._emit(bytes(self._buffer[:CHUNK]), last=False)
            del self._buffer[:CHUNK]
        return len(data)

    def _emit(self, chunk: bytes, last: bool) -> None:
        sealed = self._aead.encrypt(_nonce(self._counter), chunk, b"last" if last else b"more")
        self._out.write(struct.pack(">I", len(sealed)) + sealed)
        self._counter += 1

    def close(self) -> None:
        if not self.closed:
            self._emit(bytes(self._buffer), last=True)
            self._buffer.clear()
        super().close()


def _unseal(source, identity: X25519PrivateKey):
    """Yield the plain chunks; raises on a wrong key, a changed byte or a cut file."""
    if source.read(len(MAGIC)) != MAGIC:
        raise SystemExit("to nie jest kopia GDBK1")
    ephemeral_raw = source.read(32)
    shared = identity.exchange(X25519PublicKey.from_public_bytes(ephemeral_raw))
    aead = AESGCM(_derive(shared, ephemeral_raw, _raw_public(identity.public_key())))
    counter = 0
    while True:
        head = source.read(4)
        if len(head) < 4:
            raise SystemExit("kopia jest ucięta (brak ostatniego bloku)")
        sealed = source.read(struct.unpack(">I", head)[0])
        try:
            plain = aead.decrypt(_nonce(counter), sealed, b"more")
            last = False
        except Exception:  # noqa: BLE001 - try the closing flag before giving up
            try:
                plain = aead.decrypt(_nonce(counter), sealed, b"last")
                last = True
            except Exception as exc:  # noqa: BLE001
                raise SystemExit("nie da się otworzyć: inny klucz albo uszkodzony plik") from exc
        yield plain
        counter += 1
        if last:
            return


class _Opened(io.RawIOBase):
    def __init__(self, chunks):
        super().__init__()
        self._chunks = chunks
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        size = min(len(target), len(self._buffer))
        target[:size] = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return size


# ------------------------------------------------------------------ commands


def _skip(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    if any(part in SKIP for part in parts) or info.name.endswith(".part"):
        return None
    return info


def create(data: Path, recipient: X25519PublicKey, out_dir: Path, now: dt.datetime | None = None) -> Path:
    from core import secretbox

    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = out_dir / NAME.format(now or dt.datetime.now())
    tmp = target.with_suffix(".part")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as raw:
        sealer = _Sealer(raw, recipient)
        with tarfile.open(fileobj=sealer, mode="w|gz") as tar:
            tar.add(data, arcname="data", filter=_skip)
            key = secretbox.key_path()
            if key.exists():
                tar.add(key, arcname="_keys/data.key")
        sealer.close()
    tmp.replace(target)
    return target


def prune(out_dir: Path, keep_days: int, today: dt.date | None = None) -> list[Path]:
    edge = (today or dt.date.today()) - dt.timedelta(days=keep_days)
    removed = []
    for path in sorted(out_dir.glob("garmin-*.gdbk")):
        try:
            made = dt.datetime.strptime(path.stem, "garmin-%Y%m%d-%H%M").date()
        except ValueError:
            continue
        if made < edge:
            path.unlink()
            removed.append(path)
    return removed


def _open_tar(path: Path, identity: Path):
    source = path.open("rb")
    try:
        stream = io.BufferedReader(_Opened(_unseal(source, _private(identity))), CHUNK)
        return source, tarfile.open(fileobj=stream, mode="r|gz")
    except BaseException:  # a wrong key or a cut file ends in SystemExit: close before it travels up
        source.close()
        raise


def members(path: Path, identity: Path) -> list[str]:
    source, tar = _open_tar(path, identity)
    with source, tar:
        return [info.name for info in tar]


def restore(path: Path, identity: Path, into: Path) -> None:
    if into.exists() and any(into.iterdir()):
        raise SystemExit(f"{into} nie jest pusty — odtwarzam tylko do pustego katalogu")
    into.mkdir(parents=True, exist_ok=True, mode=0o700)
    source, tar = _open_tar(path, identity)
    with source, tar:
        tar.extractall(into, filter="data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/backup.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("keygen", help="para kluczy u właściciela (prywatny zostaje u niego)")
    gen.add_argument("path", type=Path)
    make = sub.add_parser("create", help="zaszyfrowana kopia data/ + rotacja")
    make.add_argument("--to", required=True, help="klucz publiczny gdpub1… albo plik z nim")
    make.add_argument("--out", type=Path, required=True)
    make.add_argument("--data", type=Path, default=ROOT / "data")
    make.add_argument("--keep-days", type=int, help="domyślnie backup_days z data/privacy.json (30)")
    show = sub.add_parser("list")
    show.add_argument("file", type=Path)
    show.add_argument("--identity", type=Path, required=True)
    back = sub.add_parser("restore")
    back.add_argument("file", type=Path)
    back.add_argument("--identity", type=Path, required=True)
    back.add_argument("--into", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "keygen":
        public = keygen(args.path.expanduser())
        print(f"Klucz prywatny: {args.path} (nie kopiuj go na serwer; trzymaj też w menedżerze haseł)")
        print(f"Klucz publiczny dla serwera:\n{public}")
    elif args.command == "create":
        from core import privacy

        keep = args.keep_days if args.keep_days is not None else int(privacy.settings()["backup_days"])
        target = create(args.data, _public(args.to), args.out)
        removed = prune(args.out, keep)
        print(f"{target} ({target.stat().st_size / 1e6:.1f} MB); usunięte starsze niż {keep} dni: {len(removed)}")
    elif args.command == "list":
        print("\n".join(members(args.file, args.identity)))
    else:
        restore(args.file, args.identity, args.into)
        print(f"Odtworzono do {args.into}: data/ i _keys/data.key (→ GARMIN_KEY_FILE)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
