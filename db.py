"""Query layer: an in-memory DuckDB with views over the parquet tables.

Nothing holds a lock on the data, so the ETL can rewrite tables while the
dashboard is open -- which is the whole point of keeping the warehouse as
parquet files instead of a single database file.
"""

from __future__ import annotations

import json
from typing import Any

import duckdb
import pandas as pd

import config

# Base tables from the ETL plus everything analytics.py materialises. Views
# are created for whatever parquet files actually exist, so a partially built
# warehouse still answers queries for the tables it has.
BASE_TABLES = (
    "daily",
    "activities",
    "sleep_stages",
    "night_series",
    "intraday",
    "routes",
    "route_summary",
    "activity_segments",
    "run_laps",
)
DERIVED_TABLES = (
    "pmc",
    "load_weekly",
    "critical_speed",
    "riegel",
    "efficiency",
    "correlations",
    "acf",
    "changepoints",
    "weekday_effects",
    "circadian",
    "sleep_regularity",
    "night_profile",
    "intensity_distribution",
    "quadrants",
    "run_sessions",
    "run_splits",
    "run_efforts",
    "run_forecast",
)
TABLE_NAMES = BASE_TABLES + DERIVED_TABLES


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for name in TABLE_NAMES:
        path = config.TABLES / f"{name}.parquet"
        if path.exists():
            # The path is inlined rather than bound: a view definition cannot
            # carry a prepared parameter, and queries against it would fail.
            literal = str(path).replace("'", "''")
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS "
                f"SELECT * FROM read_parquet('{literal}')"
            )
    return con


def query(sql: str) -> pd.DataFrame:
    """Run read-only SQL against the warehouse and return a DataFrame."""
    con = connect()
    try:
        return con.execute(sql).fetch_df()
    finally:
        con.close()


def table(name: str) -> pd.DataFrame:
    path = config.TABLES / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def state() -> dict[str, Any]:
    if not config.STATE_FILE.exists():
        return {}
    try:
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def schema() -> dict[str, list[str]]:
    """Column listing per table -- used by the docs and the insight command."""
    out: dict[str, list[str]] = {}
    for name in TABLE_NAMES:
        df = table(name)
        if not df.empty:
            out[name] = list(df.columns)
    return out


if __name__ == "__main__":
    for name, columns in schema().items():
        print(f"\n{name} ({len(columns)} kolumn):")
        print("  " + ", ".join(columns))
    print("\nstate:", json.dumps(state(), indent=2))
