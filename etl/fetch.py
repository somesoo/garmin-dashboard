"""Pull raw Garmin Connect payloads to disk, one JSON file per metric per day.

The raw files are the source of truth: transformations can be rewritten and
replayed without touching the API again. A day already on disk is never
re-fetched, except inside the recheck window where Garmin still backfills.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

from garminconnect import (  # noqa: E402
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def connect() -> Garmin:
    api = Garmin()
    api.login(config.TOKENSTORE)
    return api


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def call(api: Garmin, method: str, *args: Any) -> Any:
    """Call one API method, absorbing the failures that are normal here.

    A day with no wearable data answers with 404 or an empty body; that is a
    fact about the day, not an error, and gets stored as null so the day is
    not retried forever. Rate limiting backs off and retries.
    """
    for attempt in range(4):
        try:
            return getattr(api, method)(*args)
        except GarminConnectTooManyRequestsError:
            wait = 60 * (attempt + 1)
            log(f"  rate limited on {method}{args}; waiting {wait}s")
            time.sleep(wait)
        except GarminConnectConnectionError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 404:
                return None
            if attempt == 3:
                raise
            log(f"  {method}{args} failed ({exc}); retry {attempt + 1}/3")
            time.sleep(5 * (attempt + 1))
    return None


def missing_days(start: dt.date, end: dt.date) -> list[tuple[str, str, dt.date]]:
    """List (metric, method, date) triples that still need fetching."""
    recheck_from = dt.date.today() - dt.timedelta(days=config.RECHECK_DAYS)
    work: list[tuple[str, str, dt.date]] = []
    day = start
    while day <= end:
        for metric, method in config.DAILY_METRICS.items():
            path = config.day_path(metric, day)
            if not path.exists() or day >= recheck_from:
                work.append((metric, method, day))
        day += dt.timedelta(days=1)
    return work


def months_between(start: dt.date, end: dt.date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    first = dt.date(year, month, 1)
    nxt = dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    return first, nxt - dt.timedelta(days=1)


def fetch_monthly(api: Garmin, start: dt.date, end: dt.date) -> int:
    """Fetch range endpoints month by month; the last two months always refresh."""
    today = dt.date.today()
    recent = (
        (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    )
    calls = 0
    for metric, method in config.MONTHLY_METRICS.items():
        extra = config.MONTHLY_EXTRA_ARGS.get(metric, ())
        for year, month in months_between(start, end):
            path = config.month_path(metric, year, month)
            if path.exists() and (year, month) < recent:
                continue
            first, last = month_bounds(year, month)
            payload = call(
                api, method, first.isoformat(), last.isoformat(), *extra
            )
            write_json(path, payload)
            calls += 1
            size = len(payload) if isinstance(payload, (list, dict)) else 0
            log(f"  {metric} {year}-{month:02d}: {size}")
            time.sleep(config.THROTTLE)
    return calls


def known_activity_ids() -> list[str]:
    """Activity ids from the raw monthly files, newest first."""
    folder = config.RAW / "activities"
    if not folder.is_dir():
        return []
    ids: dict[str, str] = {}
    for path in sorted(folder.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for activity in payload or []:
            if isinstance(activity, dict) and activity.get("activityId"):
                ids[str(activity["activityId"])] = str(
                    activity.get("startTimeLocal") or ""
                )
    return [key for key, _ in sorted(ids.items(), key=lambda kv: kv[1], reverse=True)]


def fetch_details(api: Garmin, limit: int | None = None) -> int:
    """Fetch GPS tracks and sensor streams for activities missing them.

    One call per activity and the payload never changes afterwards, so an
    activity already on disk is skipped forever.
    """
    folder = config.RAW / "details"
    folder.mkdir(parents=True, exist_ok=True)
    pending = [
        activity_id
        for activity_id in known_activity_ids()
        if not (folder / f"{activity_id}.json").exists()
    ]
    if limit:
        pending = pending[:limit]
    if not pending:
        return 0

    log(
        f"  szczegoly aktywnosci: {len(pending)} do pobrania "
        f"(~{len(pending) * config.THROTTLE / 60:.0f} min)"
    )
    done = 0
    for index, activity_id in enumerate(pending, start=1):
        payload = call(
            api,
            "get_activity_details",
            activity_id,
            config.DETAIL_MAX_CHART,
            config.DETAIL_MAX_POLY,
        )
        write_json(folder / f"{activity_id}.json", payload)
        done += 1
        if index % 25 == 0:
            log(f"    {index}/{len(pending)}")
        time.sleep(config.THROTTLE)
    return done


def run(start: dt.date, end: dt.date, load_every: int = 0, details: bool = True) -> None:
    work = missing_days(start, end)
    per_day = max(len(config.DAILY_METRICS), 1)
    log(
        f"zakres {start} .. {end}: {len(work)} wywolan dziennych "
        f"(~{len(work) * config.THROTTLE / 60:.0f} min) + aktywnosci"
    )
    api = connect()
    log(f"zalogowany jako {api.get_full_name()}")

    fetch_monthly(api, start, end)
    if details:
        fetch_details(api)

    done_days = 0
    last_day: dt.date | None = None
    for i, (metric, method, day) in enumerate(work, start=1):
        payload = call(api, method, day.isoformat())
        write_json(config.day_path(metric, day), payload)
        time.sleep(config.THROTTLE)
        if day != last_day:
            if last_day is not None:
                done_days += 1
            last_day = day
            if done_days and done_days % 30 == 0:
                log(f"  {day} ({i}/{len(work)} wywolan, {done_days} dni)")
            if load_every and done_days and done_days % load_every == 0:
                rebuild()
    rebuild()
    log(f"gotowe: {len(work)} wywolan, {len(work) // per_day} dni")


def rebuild() -> None:
    """Rebuild parquet tables and derived analytics from the raw files."""
    from etl import load

    load.main()
    # Analytics is a separate step so a modelling failure never costs the
    # fetched data: the base tables are already on disk by this point.
    try:
        import analytics

        analytics.main()
    except Exception as exc:  # noqa: BLE001 - logged, fetch continues
        log(f"  analityka pominieta: {type(exc).__name__}: {exc}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch raw Garmin data to data/raw/")
    p.add_argument(
        "--backfill",
        metavar="YYYY-MM-DD",
        nargs="?",
        const=config.DEFAULT_BACKFILL_START.isoformat(),
        help="fetch everything from this date (default: first recorded activity)",
    )
    p.add_argument(
        "--days",
        type=int,
        default=14,
        help="incremental mode: how many recent days to check (default 14)",
    )
    p.add_argument(
        "--no-details",
        action="store_true",
        help="skip per-activity GPS/stream payloads",
    )
    p.add_argument(
        "--load-every",
        type=int,
        default=30,
        help="rebuild tables every N days during a backfill (0 = only at the end)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    end = dt.date.today()
    if args.backfill:
        start = dt.date.fromisoformat(args.backfill)
        load_every = args.load_every
    else:
        start = end - dt.timedelta(days=args.days)
        load_every = 0
    try:
        run(start, end, load_every, details=not args.no_details)
    except GarminConnectAuthenticationError as exc:
        log(f"BLAD logowania: {exc}")
        log(f"Zaloguj sie raz haslem, zeby odswiezyc {config.TOKENSTORE}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
