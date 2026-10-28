"""Mark nights recorded on someone else's wrist, then rebuild the tables.

    python -m etl.exclude                          list excluded nights
    python -m etl.exclude 2026-10-17 2026-10-18    exclude (day = morning the night ends)
    python -m etl.exclude 2026-10-17 --reason "zegarek u kogoś innego"
    python -m etl.exclude --remove 2026-10-17      restore a night

Raw files are never touched: the mask lives in data/excluded_nights.json and
etl/load.py applies it on every build, so every derived table follows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import i18n  # noqa: E402
from etl import load  # noqa: E402


def save(nights: dict[dt.date, str]) -> None:
    payload = {str(day): reason for day, reason in sorted(nights.items())}
    config.EXCLUDED_NIGHTS.parent.mkdir(parents=True, exist_ok=True)
    config.EXCLUDED_NIGHTS.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    tr = i18n.tr
    p = argparse.ArgumentParser(description=tr(pl="Wyklucz noce spoza Twojego nadgarstka",
                                               en="Exclude nights recorded off your wrist"))
    p.add_argument("days", nargs="*", type=dt.date.fromisoformat, metavar="YYYY-MM-DD")
    p.add_argument("--remove", action="store_true", help=tr(pl="przywróć podane noce", en="restore these nights"))
    p.add_argument("--reason", default=tr(pl="zegarek u kogoś innego", en="the watch on someone else"))
    p.add_argument("--no-rebuild", action="store_true", help=tr(pl="tylko zapisz listę", en="only save the list"))
    args = p.parse_args(argv)

    nights = load.excluded_nights()
    if args.days:
        for day in args.days:
            if args.remove:
                nights.pop(day, None)
            else:
                nights[day] = args.reason
        save(nights)

    for day, reason in sorted(nights.items()):
        night = f"{day - dt.timedelta(days=1):%d.%m} → {day:%d.%m}"
        print(tr(pl=f"{day}  (noc {night})  {reason}", en=f"{day}  (night {night})  {reason}"))
    if not nights:
        print(tr(pl="brak wykluczonych nocy", en="no excluded nights"))

    if args.days and not args.no_rebuild:
        from etl import fetch

        fetch.rebuild()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
