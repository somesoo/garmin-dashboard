"""One-shot update: fetch what is missing since the last run, rebuild tables.

Started by the sidebar button and the server's timer (sync.py), by the
systemd/pm2 schedule on the server, or by hand. It takes ``data/fetch.lock``
so two pulls never run at once, and records the attempt in ``data/fetch.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync  # noqa: E402
from etl import fetch  # noqa: E402


def _lock() -> bool:
    sync.LOCK.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(sync.LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if sync.running():
                return False
            sync.LOCK.unlink(missing_ok=True)  # left by a pull that died
            continue
        with os.fdopen(fd, "w") as out:
            out.write(str(os.getpid()))
        return True
    return False


def _record(**fields) -> None:
    record = {**sync.last(), **fields}
    sync.RECORD.write_text(json.dumps(record), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        args = ["--days", "14"]
    if not _lock():
        fetch.log("pobieranie juz trwa w innym procesie")
        return 0
    now = f"{dt.datetime.now():%Y-%m-%dT%H:%M:%S}"
    _record(started_at=now, finished_at=None, code=None)
    code = 1
    try:
        code = fetch.main(args)
        return code
    finally:
        _record(finished_at=f"{dt.datetime.now():%Y-%m-%dT%H:%M:%S}", code=code)
        sync.LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
