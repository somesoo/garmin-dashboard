"""One-shot update: fetch what is missing since the last run, rebuild tables.

This is what the Dashboard.command / Dashboard.cmd shortcuts call before opening the browser.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl import fetch  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        args = ["--days", "14"]
    return fetch.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
