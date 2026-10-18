"""Shared paths and the metric registry for the Garmin dashboard pipeline."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
TABLES = DATA / "tables"
STATE_FILE = DATA / "state.json"
INSIGHTS = ROOT / "insights"
# Nights recorded on someone else's wrist: {"YYYY-MM-DD": "reason"}. Typed in
# by hand (etl/exclude.py), so like data/coach/ it cannot be rebuilt from raw/.
EXCLUDED_NIGHTS = DATA / "excluded_nights.json"
# Override with GARMIN_TOKENSTORE when the home directory is not where the
# tokens live - a systemd unit running as a service user, for instance.
TOKENSTORE = os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect")

# Garmin backfills data for a few days after the fact (manual sleep edits,
# late device syncs), so recent days are always re-fetched instead of trusted.
RECHECK_DAYS = 4

# Seconds between API calls. Garmin throttles aggressively; staying polite
# keeps the account out of temporary blocks during a long backfill.
THROTTLE = 0.7

# The oldest date worth fetching: first recorded activity minus a margin.
DEFAULT_BACKFILL_START = dt.date(2023, 6, 1)

# One call per metric per day. Each entry maps a directory under data/raw/
# to a Garmin client method taking a single ``YYYY-MM-DD`` argument.
DAILY_METRICS: dict[str, str] = {
    "summary": "get_user_summary",
    "sleep": "get_sleep_data",
    "hrv": "get_hrv_data",
    "readiness": "get_training_readiness",
    "training_status": "get_training_status",
    "weight": "get_daily_weigh_ins",
    # Full-day 3-minute series for stress and Body Battery. The only metric
    # fetched for its intraday arrays rather than its daily aggregate.
    "stress": "get_all_day_stress",
}

# Fetched per calendar month instead of per day: these endpoints answer with a
# whole date range in one call.
MONTHLY_METRICS: dict[str, str] = {
    "activities": "get_activities_by_date",
    "race": "get_race_predictions",
}

# Per-activity detail payloads (GPS track plus aligned sensor streams). Sizes
# are capped server-side by these limits: enough shape for a map and an
# elevation profile without storing every second of every run.
DETAIL_MAX_CHART = 400
DETAIL_MAX_POLY = 800

# Route points kept per activity after downsampling at load time.
ROUTE_POINTS = 400

# Extra positional arguments appended after (start, end) for range endpoints.
MONTHLY_EXTRA_ARGS: dict[str, tuple[str, ...]] = {
    "race": ("daily",),
}


def day_path(metric: str, date: dt.date) -> Path:
    return RAW / metric / f"{date.isoformat()}.json"


def month_path(metric: str, year: int, month: int) -> Path:
    return RAW / metric / f"{year:04d}-{month:02d}.json"
