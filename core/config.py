"""Shared paths and the metric registry for the Garmin dashboard pipeline."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Shared by everyone: the registry, the server record. What one person owns
# lives in their own directory (tenant.py) -- reach it through the functions
# below, which answer for whoever the current request belongs to.
DATA = ROOT / "data"
INSIGHTS = ROOT / "insights"


def _person():
    from core import tenant

    return tenant.current()


def raw() -> Path:
    return _person().raw


def tables() -> Path:
    return _person().tables


def state_file() -> Path:
    return _person().state_file


def excluded_nights() -> Path:
    """Nights recorded on someone else's wrist ({"YYYY-MM-DD": "reason"}), typed in by hand."""
    return _person().excluded_nights


def tokenstore() -> str:
    """Garmin tokens of the current person; ``GARMIN_TOKENSTORE`` still overrides the old layout's."""
    return _person().tokenstore

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
    return raw() / metric / f"{date.isoformat()}.json"


def month_path(metric: str, year: int, month: int) -> Path:
    return raw() / metric / f"{year:04d}-{month:02d}.json"
