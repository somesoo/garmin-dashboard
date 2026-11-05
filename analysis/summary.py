"""What the phone shows, computed on the server: one JSON per person and language.

The PWA (``pwa/``, served by api.py) does not reimplement any number: the
headlines are the dashboard's own (``facts.py``: recovery, sleep, the running
year), the norms are the warehouse's, paces are already ``m:ss``. The phone
keeps the last summary and shows it offline.

Cached on disk per build and language (``cache/summary-<lang>-<etag>.json``);
building takes a fraction of a second, but a phone opening the app every
morning should not cost a rebuild of anything.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import threading
from typing import Any

import pandas as pd

from core import db
from analysis import facts
from core import i18n
from core import tenant
from running import units

# i18n.force is process-wide; API requests run in threads. One summary at a time.
_LOCK = threading.Lock()
SERIES_DAYS = 90
WEEKS = 26
ACTIVITIES = 25


def _clean(value: Any) -> Any:
    """JSON-safe: NaN/NaT -> None, numpy -> Python, timestamps -> ISO dates."""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return None if pd.isna(value) else value.isoformat()[:19]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _num(row: pd.Series, column: str, digits: int = 1) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _story(told: dict[str, Any], limit: int = 4) -> dict[str, Any]:
    return {"headline": told.get("headline"),
            "cards": [{"group": s.get("group"), "head": s.get("head"), "text": s.get("text")}
                      for s in told.get("satellites", [])[:limit]]}


def _today(daily: pd.DataFrame) -> dict[str, Any]:
    nights = daily.dropna(subset=["sleep_h"]) if "sleep_h" in daily.columns else daily.iloc[0:0]
    days = daily.dropna(subset=["steps"]) if "steps" in daily.columns else daily.iloc[0:0]
    hrv_rows = daily.dropna(subset=["hrv_last_night"])
    out: dict[str, Any] = {}
    if len(nights):
        night = nights.iloc[-1]
        out["sleep"] = {"day": night["day"], "hours": _num(night, "sleep_h", 2), "deep": _num(night, "sleep_deep_h", 2),
                        "rem": _num(night, "sleep_rem_h", 2), "week_mean": round(float(nights["sleep_h"].iloc[-8:-1].mean()), 2)
                        if len(nights) > 1 else None}
    if len(hrv_rows):
        row = hrv_rows.iloc[-1]
        week = hrv_rows["hrv_last_night"].iloc[-8:-1]
        out["hrv"] = {"day": row["day"], "value": _num(row, "hrv_last_night"), "kind": row.get("hrv_kind"),
                      "low": _num(row, "hrv_baseline_low"), "high": _num(row, "hrv_baseline_high"),
                      "week_mean": round(float(week.mean()), 1) if len(week) else None,
                      "norm": facts.hrv_norm_words(daily)["short"]}
    rhr_rows = daily.dropna(subset=["rhr"])
    if len(rhr_rows) >= 1:
        row = rhr_rows.iloc[-1]
        window = rhr_rows["rhr"].iloc[-60:]
        out["rhr"] = {"day": row["day"], "value": _num(row, "rhr", 0),
                      "low": round(float(window.quantile(0.10))) if len(window) >= 20 else None,
                      "high": round(float(window.quantile(0.90))) if len(window) >= 20 else None}
    if len(days):
        row = days.iloc[-1]
        out["steps"] = {"day": row["day"], "value": _num(row, "steps", 0),
                        "week_mean": round(float(days["steps"].iloc[-8:-1].mean())) if len(days) > 1 else None}
    for column in ("readiness", "bb_wake", "vo2max"):
        rows = daily.dropna(subset=[column]) if column in daily.columns else daily.iloc[0:0]
        if len(rows):
            out[column] = {"day": rows.iloc[-1]["day"], "value": _num(rows.iloc[-1], column)}
    return out


def _series(daily: pd.DataFrame) -> dict[str, list]:
    if daily.empty:
        return {}
    end = daily["day"].max()
    view = daily[daily["day"] > end - pd.Timedelta(days=SERIES_DAYS)]
    keep = ["day", "hrv_last_night", "hrv_last_night_roll7", "hrv_baseline_low", "hrv_baseline_high", "sleep_h",
            "sleep_h_roll7", "rhr", "steps"]
    return {column: [_clean(v) for v in view[column]] for column in keep if column in view.columns}


def _activities(acts: pd.DataFrame) -> list[dict[str, Any]]:
    if acts.empty:
        return []
    rows = []
    for a in acts.sort_values("start_local", ascending=False).head(ACTIVITIES).itertuples(index=False):
        pace = getattr(a, "pace_min_km", None)
        rows.append({"start": a.start_local, "sport": a.sport, "name": getattr(a, "name", None),
                     "km": round(float(a.distance_km), 2) if pd.notna(a.distance_km) else None,
                     "minutes": round(float(a.duration_min)) if pd.notna(a.duration_min) else None,
                     "pace": units.fmt_pace(pace, unit=False) if pace is not None and pd.notna(pace) else None,
                     "avg_hr": round(float(a.avg_hr)) if pd.notna(a.avg_hr) else None,
                     "load": round(float(a.training_load)) if pd.notna(getattr(a, "training_load", None)) else None})
    return rows


def build(person: tenant.User, lang: str) -> dict[str, Any]:
    with _LOCK, tenant.use(person.id):
        previous = i18n._forced
        i18n.force(lang)
        try:
            return _build(person, lang)
        finally:
            i18n.force(previous)


def _build(person: tenant.User, lang: str) -> dict[str, Any]:
    state = db.state()
    daily = db.table("daily")
    if daily.empty:
        return {"person": person.id, "name": person.name, "source": person.source, "built_at": state.get("built_at"),
                "lang": lang, "empty": True}
    daily = daily.sort_values("day").reset_index(drop=True)
    daily["day"] = pd.to_datetime(daily["day"])
    runs = db.table("run_sessions")
    if not runs.empty:
        runs["day"] = pd.to_datetime(runs["day"])
        runs["start_local"] = pd.to_datetime(runs["start_local"])
    since = daily["day"].max() - pd.Timedelta(days=SERIES_DAYS)
    stories: dict[str, Any] = {}
    for key, make in (
        ("recovery", lambda: facts.recovery(daily, runs, since)),
        ("sleep", lambda: facts.sleep(daily, db.table("circadian"), since, dt.date.today())),
        ("running", lambda: facts.running_year(runs, db.table("pmc"), daily["day"].max() - pd.Timedelta(days=365),
                                               daily["day"].max()) if not runs.empty else {}),
    ):
        try:
            stories[key] = _story(make())
        except Exception as exc:  # noqa: BLE001 - one story failing must not cost the phone the rest
            stories[key] = {"headline": None, "cards": [], "error": type(exc).__name__}
    weeks = facts.weekly_km(runs) if not runs.empty else pd.DataFrame()
    if not weeks.empty:
        weeks = weeks[weeks["week"] > weeks["week"].max() - pd.Timedelta(weeks=WEEKS)]
    return _clean({
        "person": person.id, "name": person.name, "source": person.source, "lang": lang,
        "built_at": state.get("built_at"), "last_day": daily["day"].max(),
        "today": _today(daily), "stories": stories, "series": _series(daily),
        "weeks": {"week": list(weeks["week"]) if not weeks.empty else [],
                  "km": [round(float(k), 1) for k in weeks["km"]] if not weeks.empty else []},
        "activities": _activities(db.table("activities")),
    })


def cached(person: tenant.User, lang: str) -> tuple[bytes, str]:
    """(JSON bytes, etag) -- rebuilt only when the warehouse is."""
    lang = lang if lang in i18n.LANGS else i18n.DEFAULT
    try:
        built = json.loads(person.state_file.read_text(encoding="utf-8")).get("built_at", "")
    except (OSError, ValueError):
        built = ""
    etag = hashlib.sha256(f"{person.id}|{built}|{lang}|{dt.date.today()}".encode()).hexdigest()[:24]
    folder = person.root / "cache"
    target = folder / f"summary-{lang}-{etag}.json"
    if target.exists():
        return target.read_bytes(), etag
    body = json.dumps(build(person, lang), ensure_ascii=False, separators=(",", ":")).encode()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(target)
    for old in folder.glob(f"summary-{lang}-*.json"):
        if old != target:
            old.unlink(missing_ok=True)
    return body, etag
