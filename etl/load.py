"""Turn raw JSON payloads into flat parquet tables the dashboard queries.

Mapping is explicit rather than schema-inferred: Garmin payloads change shape
between devices and firmware versions, and an explicit map fails loudly on one
column instead of silently reshaping the whole table. The build is idempotent --
every table is rewritten from raw on each run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

import config  # noqa: E402


def read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def dig(obj: Any, *keys: str) -> Any:
    """Walk nested dicts, tolerating missing levels and null payloads."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def first_value(mapping: Any) -> dict[str, Any]:
    """Garmin keys some sub-objects by device id; take the single entry."""
    if isinstance(mapping, dict):
        for value in mapping.values():
            if isinstance(value, dict):
                return value
    return {}


def raw_days(metric: str) -> list[tuple[dt.date, Any]]:
    folder = config.RAW / metric
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            day = dt.date.fromisoformat(path.stem)
        except ValueError:
            continue
        out.append((day, read(path)))
    return out


def excluded_nights() -> dict[dt.date, str]:
    """Nights the owner did not sleep in the watch, keyed by Garmin's sleep day.

    Garmin files a night under the morning it ends, so excluding ``2026-10-17``
    drops the night of 16th -> 17th. Raw files stay untouched; the mask is
    applied on every build, so removing an entry restores the night.
    """
    payload = read(config.EXCLUDED_NIGHTS)
    out = {}
    for key, reason in (payload if isinstance(payload, dict) else {}).items():
        try:
            out[dt.date.fromisoformat(key)] = str(reason or "")
        except ValueError:
            continue
    return out


# Daily columns that describe the night (or are computed by Garmin from it):
# sleep itself, overnight HRV and SpO2, resting HR, wake-up Body Battery and
# the readiness score built on top of them. Daytime activity stays.
NIGHT_PREFIXES = ("sleep_", "hrv_", "readiness", "f_")
NIGHT_COLUMNS = (
    "overnight_hrv", "rhr", "spo2_avg", "sleeping_s", "bb_wake", "bb_charged",
)


def mask_nights(df: pd.DataFrame, nights: dict[dt.date, str]) -> pd.DataFrame:
    """Blank night-derived columns on excluded days, before rolling baselines."""
    df["night_excluded"] = df["day"].dt.date.isin(nights)
    if not nights:
        return df
    columns = [
        c for c in df.columns
        if c.startswith(NIGHT_PREFIXES) or c in NIGHT_COLUMNS
    ]
    df.loc[df["night_excluded"], columns] = None
    return df


def _hours(seconds: Any) -> float | None:
    if isinstance(seconds, (int, float)) and seconds:
        return round(seconds / 3600, 2)
    return None


def _hours_from_minutes(minutes: Any) -> float | None:
    if isinstance(minutes, (int, float)) and minutes:
        return round(minutes / 60, 1)
    return None


def status_label(phrase: Any) -> str | None:
    """"PRODUCTIVE_6" -> "Productive"; the trailing number is a message variant."""
    if not isinstance(phrase, str) or not phrase:
        return None
    head = phrase.rsplit("_", 1)[0] if phrase.rsplit("_", 1)[-1].isdigit() else phrase
    return head.replace("_", " ").title()


def _kg(grams: Any) -> float | None:
    if isinstance(grams, (int, float)) and grams:
        return round(grams / 1000, 2)
    return None


def build_daily() -> pd.DataFrame:
    """One row per calendar day, joined across every daily metric."""
    rows: dict[dt.date, dict[str, Any]] = {}

    def cell(day: dt.date, **values: Any) -> None:
        rows.setdefault(day, {"day": day}).update(values)

    for day, payload in raw_days("summary"):
        s = payload or {}
        cell(
            day,
            steps=s.get("totalSteps"),
            step_goal=s.get("dailyStepGoal"),
            distance_m=s.get("totalDistanceMeters"),
            calories=s.get("totalKilocalories"),
            active_calories=s.get("activeKilocalories"),
            bmr_calories=s.get("bmrKilocalories"),
            floors_up=s.get("floorsAscended"),
            intensity_moderate=s.get("moderateIntensityMinutes"),
            intensity_vigorous=s.get("vigorousIntensityMinutes"),
            intensity_goal=s.get("intensityMinutesGoal"),
            rhr=s.get("restingHeartRate"),
            rhr_7d=s.get("lastSevenDaysAvgRestingHeartRate"),
            hr_min=s.get("minHeartRate"),
            hr_max=s.get("maxHeartRate"),
            stress_avg=s.get("averageStressLevel"),
            stress_max=s.get("maxStressLevel"),
            stress_qualifier=s.get("stressQualifier"),
            bb_high=s.get("bodyBatteryHighestValue"),
            bb_low=s.get("bodyBatteryLowestValue"),
            bb_wake=s.get("bodyBatteryAtWakeTime"),
            bb_charged=s.get("bodyBatteryChargedValue"),
            bb_drained=s.get("bodyBatteryDrainedValue"),
            spo2_avg=s.get("averageSpo2"),
            respiration_waking=s.get("avgWakingRespirationValue"),
            sedentary_s=s.get("sedentarySeconds"),
            active_s=s.get("activeSeconds"),
            sleeping_s=s.get("sleepingSeconds"),
        )

    for day, payload in raw_days("sleep"):
        d = dig(payload, "dailySleepDTO") or {}
        scores = d.get("sleepScores") or {}
        cell(
            day,
            sleep_score=dig(scores, "overall", "value"),
            sleep_qualifier=dig(scores, "overall", "qualifierKey"),
            sleep_h=_hours(d.get("sleepTimeSeconds")),
            sleep_deep_h=_hours(d.get("deepSleepSeconds")),
            sleep_light_h=_hours(d.get("lightSleepSeconds")),
            sleep_rem_h=_hours(d.get("remSleepSeconds")),
            sleep_awake_h=_hours(d.get("awakeSleepSeconds")),
            sleep_nap_h=_hours(d.get("napTimeSeconds")),
            sleep_awake_count=d.get("awakeCount"),
            sleep_restless=dig(payload, "restlessMomentsCount"),
            sleep_stress=d.get("avgSleepStress"),
            sleep_respiration=d.get("averageRespirationValue"),
            sleep_start=d.get("sleepStartTimestampLocal"),
            sleep_end=d.get("sleepEndTimestampLocal"),
            sleep_feedback=d.get("sleepScoreFeedback"),
            sleep_insight=d.get("sleepScoreInsight"),
            overnight_hrv=dig(payload, "avgOvernightHrv"),
            sleep_rhr=dig(payload, "restingHeartRate"),
        )

    for day, payload in raw_days("hrv"):
        h = dig(payload, "hrvSummary") or {}
        cell(
            day,
            hrv_last_night=h.get("lastNightAvg"),
            hrv_weekly=h.get("weeklyAvg"),
            hrv_high_5min=h.get("lastNight5MinHigh"),
            hrv_status=h.get("status"),
            hrv_baseline_low=dig(h, "baseline", "balancedLow"),
            hrv_baseline_high=dig(h, "baseline", "balancedUpper"),
        )

    for day, payload in raw_days("readiness"):
        r = payload[0] if isinstance(payload, list) and payload else {}
        cell(
            day,
            readiness=r.get("score"),
            readiness_level=r.get("level"),
            readiness_feedback=r.get("feedbackShort"),
            acute_load=r.get("acuteLoad"),
            acwr_percent=r.get("acwrFactorPercent"),
            recovery_time_h=_hours_from_minutes(r.get("recoveryTime")),
            f_sleep=r.get("sleepScoreFactorPercent"),
            f_hrv=r.get("hrvFactorPercent"),
            f_recovery=r.get("recoveryTimeFactorPercent"),
            f_sleep_history=r.get("sleepHistoryFactorPercent"),
            f_stress_history=r.get("stressHistoryFactorPercent"),
        )

    for day, payload in raw_days("training_status"):
        vo2 = dig(payload, "mostRecentVO2Max", "generic") or {}
        latest = first_value(
            dig(payload, "mostRecentTrainingStatus", "latestTrainingStatusData")
        )
        acute = latest.get("acuteTrainingLoadDTO")
        acute = acute if isinstance(acute, dict) else {}
        balance = first_value(
            dig(
                payload,
                "mostRecentTrainingLoadBalance",
                "metricsTrainingLoadBalanceDTOMap",
            )
        )
        cell(
            day,
            vo2max=vo2.get("vo2MaxPreciseValue"),
            fitness_age=vo2.get("fitnessAge"),
            # The numeric trainingStatus is an opaque code; the feedback phrase
            # carries the label Garmin shows ("PRODUCTIVE_6" -> Productive).
            training_status=status_label(latest.get("trainingStatusFeedbackPhrase")),
            training_status_code=latest.get("trainingStatus"),
            training_status_feedback=latest.get("trainingStatusFeedbackPhrase"),
            load_acute=acute.get("dailyTrainingLoadAcute"),
            load_chronic=acute.get("dailyTrainingLoadChronic"),
            load_ratio=acute.get("dailyAcuteChronicWorkloadRatio"),
            load_ratio_status=acute.get("acwrStatus"),
            load_optimal_low=acute.get("minTrainingLoadChronic"),
            load_optimal_high=acute.get("maxTrainingLoadChronic"),
            load_4w_low_aerobic=balance.get("monthlyLoadAerobicLow"),
            load_4w_high_aerobic=balance.get("monthlyLoadAerobicHigh"),
            load_4w_anaerobic=balance.get("monthlyLoadAnaerobic"),
            load_balance_feedback=balance.get("trainingBalanceFeedbackPhrase"),
        )

    for day, payload in raw_days("weight"):
        entries = dig(payload, "dateWeightList") or []
        first = entries[0] if entries and isinstance(entries[0], dict) else {}
        cell(
            day,
            weight_kg=_kg(first.get("weight")),
            body_fat_pct=first.get("bodyFat"),
            body_water_pct=first.get("bodyWater"),
            muscle_mass_kg=_kg(first.get("muscleMass")),
        )

    if not rows:
        return pd.DataFrame(columns=["day"])

    df = pd.DataFrame(sorted(rows.values(), key=lambda row: row["day"]))
    df["day"] = pd.to_datetime(df["day"])

    races = race_predictions()
    if not races.empty:
        df = df.merge(races, on="day", how="left")

    return add_derived(mask_nights(df, excluded_nights()))


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling baselines and deviations -- the columns the trends read from."""
    df = df.sort_values("day").reset_index(drop=True)
    windows = (
        ("hrv_last_night", 7),
        ("rhr", 7),
        ("sleep_h", 7),
        ("sleep_score", 7),
        ("readiness", 7),
        ("steps", 7),
        ("weight_kg", 7),
        ("vo2max", 28),
    )
    for col, window in windows:
        if col in df.columns:
            df[f"{col}_roll{window}"] = (
                pd.to_numeric(df[col], errors="coerce")
                .rolling(window, min_periods=3)
                .mean()
                .round(2)
            )
    for col in ("hrv_last_night", "rhr"):
        baseline = f"{col}_roll7"
        if col in df.columns and baseline in df.columns:
            df[f"{col.replace('_last_night', '')}_deviation"] = (
                pd.to_numeric(df[col], errors="coerce") - df[baseline]
            ).round(1)
    df["weekday"] = df["day"].dt.day_name()
    df["iso_week"] = df["day"].dt.strftime("%G-W%V")
    df["month"] = df["day"].dt.strftime("%Y-%m")
    return df


def build_activities() -> pd.DataFrame:
    """One row per activity, deduplicated across overlapping month files."""
    folder = config.RAW / "activities"
    if not folder.is_dir():
        return pd.DataFrame(columns=["activity_id"])

    seen: dict[Any, dict[str, Any]] = {}
    for path in sorted(folder.glob("*.json")):
        for activity in read(path) or []:
            if isinstance(activity, dict) and activity.get("activityId"):
                seen[activity["activityId"]] = activity

    rows = []
    for a in seen.values():
        duration = a.get("duration") or 0
        distance = a.get("distance") or 0
        speed = a.get("averageSpeed") or 0
        moving = a.get("movingDuration") or 0
        rows.append(
            {
                "activity_id": a.get("activityId"),
                "start_local": a.get("startTimeLocal"),
                "name": a.get("activityName"),
                "sport": dig(a, "activityType", "typeKey"),
                "distance_km": round(distance / 1000, 3) if distance else None,
                "duration_min": round(duration / 60, 1) if duration else None,
                "moving_min": round(moving / 60, 1) if moving else None,
                "pace_min_km": round(1000 / speed / 60, 2) if speed else None,
                "speed_kmh": round(speed * 3.6, 2) if speed else None,
                "avg_hr": a.get("averageHR"),
                "max_hr": a.get("maxHR"),
                "calories": a.get("calories"),
                "elevation_gain_m": a.get("elevationGain"),
                "training_load": a.get("activityTrainingLoad"),
                "te_aerobic": a.get("aerobicTrainingEffect"),
                "te_anaerobic": a.get("anaerobicTrainingEffect"),
                "avg_power": a.get("avgPower"),
                "norm_power": a.get("normPower"),
                "cadence": a.get("averageRunningCadenceInStepsPerMinute"),
                "stride_m": a.get("avgStrideLength"),
                "hr_z1_s": a.get("hrTimeInZone_1"),
                "hr_z2_s": a.get("hrTimeInZone_2"),
                "hr_z3_s": a.get("hrTimeInZone_3"),
                "hr_z4_s": a.get("hrTimeInZone_4"),
                "hr_z5_s": a.get("hrTimeInZone_5"),
                "location": a.get("locationName"),
                # Start/end coordinates come with the activity summary, so the
                # world map works without the per-activity detail payloads.
                "start_lat": a.get("startLatitude"),
                "start_lon": a.get("startLongitude"),
                "end_lat": a.get("endLatitude"),
                "end_lon": a.get("endLongitude"),
                # Best splits inside the activity (seconds): what the
                # critical-speed and Riegel fits are built from.
                "best_1k_s": a.get("fastestSplit_1000"),
                "best_mile_s": a.get("fastestSplit_1609"),
                "best_5k_s": a.get("fastestSplit_5000"),
                "gap_speed": a.get("avgGradeAdjustedSpeed"),
                "max_speed": a.get("maxSpeed"),
                "vo2max_activity": a.get("vO2MaxValue"),
                "lap_count": a.get("lapCount"),
                "temperature_max": a.get("maxTemperature"),
                "moderate_minutes": a.get("moderateIntensityMinutes"),
                # Set when the run came from a structured watch workout; the
                # segments themselves are in the activity_segments table.
                "workout_id": a.get("workoutId"),
                "event_type": dig(a, "eventType", "typeKey"),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["activity_id"])

    df = pd.DataFrame(rows)
    df["start_local"] = pd.to_datetime(df["start_local"], errors="coerce")
    df["day"] = df["start_local"].dt.normalize()
    df["iso_week"] = df["start_local"].dt.strftime("%G-W%V")
    return df.sort_values("start_local", ascending=False).reset_index(drop=True)


def _parse_ts(value):
    """Garmin timestamps arrive as epoch millis or as ISO strings."""
    if isinstance(value, (int, float)) and value:
        return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).replace(tzinfo=None)
    if isinstance(value, str) and value:
        try:
            return dt.datetime.fromisoformat(value.replace("Z", ""))
        except ValueError:
            return None
    return None


def _offset(payload, gmt_key, local_key):
    """Local-time offset for one day, taken from a GMT/local timestamp pair.

    Using the day's own pair keeps DST changes and travel correct instead of
    assuming the machine's current timezone.
    """
    gmt = _parse_ts(payload.get(gmt_key))
    local = _parse_ts(payload.get(local_key))
    if gmt and local:
        return local - gmt
    return dt.timedelta(0)


SLEEP_STAGES = {0.0: "deep", 1.0: "light", 2.0: "rem", 3.0: "awake"}


def build_sleep_stages() -> pd.DataFrame:
    """Hypnogram segments: one row per sleep-stage block, in local time."""
    rows = []
    skip = excluded_nights()
    for day, payload in raw_days("sleep"):
        if not isinstance(payload, dict) or day in skip:
            continue
        dto = payload.get("dailySleepDTO") or {}
        shift = _offset(dto, "sleepStartTimestampGMT", "sleepStartTimestampLocal")
        for index, segment in enumerate(payload.get("sleepLevels") or []):
            start = _parse_ts(segment.get("startGMT"))
            end = _parse_ts(segment.get("endGMT"))
            if not start or not end:
                continue
            rows.append(
                {
                    "day": day,
                    "segment": index,
                    "stage": SLEEP_STAGES.get(segment.get("activityLevel"), "unknown"),
                    "start_local": start + shift,
                    "end_local": end + shift,
                    "minutes": round((end - start).total_seconds() / 60, 1),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["day", "stage"])
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    return df


NIGHT_SERIES = {
    "hr": "sleepHeartRate",
    "body_battery": "sleepBodyBattery",
    "stress": "sleepStress",
    "restless": "sleepRestlessMoments",
}


def build_night_series() -> pd.DataFrame:
    """Long-format overnight samples: heart rate, Body Battery, stress, HRV."""
    rows = []
    skip = excluded_nights()
    for day, payload in raw_days("sleep"):
        if not isinstance(payload, dict) or day in skip:
            continue
        dto = payload.get("dailySleepDTO") or {}
        shift = _offset(dto, "sleepStartTimestampGMT", "sleepStartTimestampLocal")
        for metric, key in NIGHT_SERIES.items():
            for sample in payload.get(key) or []:
                if not isinstance(sample, dict):
                    continue
                stamp = _parse_ts(sample.get("startGMT"))
                if stamp is None or sample.get("value") is None:
                    continue
                rows.append(
                    {
                        "day": day,
                        "metric": metric,
                        "t_local": stamp + shift,
                        "value": float(sample["value"]),
                    }
                )

    for day, payload in raw_days("hrv"):
        if not isinstance(payload, dict) or day in skip:
            continue
        for reading in payload.get("hrvReadings") or []:
            if not isinstance(reading, dict):
                continue
            stamp = _parse_ts(reading.get("readingTimeLocal"))
            if stamp is None or reading.get("hrvValue") is None:
                continue
            rows.append(
                {
                    "day": day,
                    "metric": "hrv",
                    "t_local": stamp,
                    "value": float(reading["hrvValue"]),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["day", "metric", "t_local", "value"])
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    df["minutes_from_midnight"] = df["t_local"].dt.hour * 60 + df["t_local"].dt.minute
    return df.sort_values(["day", "metric", "t_local"]).reset_index(drop=True)


def build_intraday() -> pd.DataFrame:
    """Full-day 3-minute stress and Body Battery samples, in local time."""
    rows = []
    for day, payload in raw_days("stress"):
        if not isinstance(payload, dict):
            continue
        shift = _offset(payload, "startTimestampGMT", "startTimestampLocal")
        stress = {
            int(entry[0]): entry[1]
            for entry in payload.get("stressValuesArray") or []
            if isinstance(entry, list) and len(entry) >= 2
        }
        battery = {
            int(entry[0]): entry[2]
            for entry in payload.get("bodyBatteryValuesArray") or []
            if isinstance(entry, list) and len(entry) >= 3
        }
        for stamp_ms in sorted(set(stress) | set(battery)):
            moment = _parse_ts(stamp_ms)
            if moment is None:
                continue
            local = moment + shift
            level = stress.get(stamp_ms)
            rows.append(
                {
                    "day": day,
                    "t_local": local,
                    "hour": local.hour + local.minute / 60,
                    # Garmin encodes "not measured" as a negative stress level.
                    "stress": level
                    if isinstance(level, (int, float)) and level >= 0
                    else None,
                    "body_battery": battery.get(stamp_ms),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["day", "t_local", "stress", "body_battery"])
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    return df


RACE_FIELDS = {
    "race_5k_s": "time5K",
    "race_10k_s": "time10K",
    "race_hm_s": "timeHalfMarathon",
    "race_marathon_s": "timeMarathon",
}


def race_predictions() -> pd.DataFrame:
    """Garmin's own race-time predictions, one row per day."""
    folder = config.RAW / "race"
    if not folder.is_dir():
        return pd.DataFrame(columns=["day"])
    rows = {}
    for path in sorted(folder.glob("*.json")):
        for entry in read(path) or []:
            if not isinstance(entry, dict):
                continue
            try:
                day = dt.date.fromisoformat(entry.get("calendarDate"))
            except (TypeError, ValueError):
                continue
            row = {"day": day}
            for column, key in RACE_FIELDS.items():
                row[column] = entry.get(key)
            rows[day] = row
    if not rows:
        return pd.DataFrame(columns=["day"])
    df = pd.DataFrame(sorted(rows.values(), key=lambda r: r["day"]))
    df["day"] = pd.to_datetime(df["day"])
    return df


DETAIL_METRICS = {
    "directLatitude": "lat",
    "directLongitude": "lon",
    "directElevation": "elevation_m",
    "directHeartRate": "hr",
    "directSpeed": "speed_ms",
    "directGradeAdjustedSpeed": "gap_speed_ms",
    "sumDistance": "distance_km",
    # Timer time (auto-pause excluded): what the watch's own km splits use.
    "sumDuration": "duration_s",
    "directTimestamp": "timestamp_ms",
    "directRunCadence": "cadence",
    "directPower": "power",
    "directAirTemperature": "temperature",
}


def build_segments() -> pd.DataFrame:
    """Per-activity split summaries: workout phases and run/walk detection.

    ``splitSummaries`` aggregates the watch's own segmentation -- for a
    structured workout that is warm-up / active / recovery / cool-down
    (``INTERVAL_*``), for every run the run/walk/stand detection
    (``RWD_*``). Several reps of the same phase arrive as one row with
    ``splits`` > 1, so this is the rep count and total, not each rep.
    """
    folder = config.RAW / "activities"
    columns = ["activity_id", "split_type", "splits", "distance_m", "duration_s",
               "avg_speed_ms", "max_speed_ms", "ascent_m"]
    if not folder.is_dir():
        return pd.DataFrame(columns=columns)
    seen: dict[Any, list[dict[str, Any]]] = {}
    for path in sorted(folder.glob("*.json")):
        for activity in read(path) or []:
            if isinstance(activity, dict) and activity.get("activityId"):
                seen[activity["activityId"]] = activity.get("splitSummaries") or []
    rows = []
    for activity_id, splits in seen.items():
        for split in splits:
            if not isinstance(split, dict) or not split.get("splitType"):
                continue
            rows.append(
                {
                    "activity_id": activity_id,
                    "split_type": split.get("splitType"),
                    "splits": split.get("noOfSplits"),
                    "distance_m": split.get("distance"),
                    "duration_s": split.get("duration"),
                    "avg_speed_ms": split.get("averageSpeed"),
                    "max_speed_ms": split.get("maxSpeed"),
                    "ascent_m": split.get("totalAscent"),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def build_routes() -> tuple[pd.DataFrame, pd.DataFrame]:
    """GPS tracks with the sensor streams aligned to each point.

    Garmin returns the samples as a bare array plus a separate descriptor list
    giving each metric's position, so the mapping has to be rebuilt per
    activity -- the column order is not stable between activities.
    """
    folder = config.RAW / "details"
    if not folder.is_dir():
        return pd.DataFrame(columns=["activity_id"]), pd.DataFrame(columns=["activity_id"])

    tracks = []
    summaries = []
    for path in sorted(folder.glob("*.json")):
        payload = read(path)
        if not isinstance(payload, dict):
            continue
        samples = payload.get("activityDetailMetrics") or []
        descriptors = payload.get("metricDescriptors") or []
        if not samples or not descriptors:
            continue
        index_of = {
            DETAIL_METRICS[d["key"]]: d["metricsIndex"]
            for d in descriptors
            if isinstance(d, dict)
            and d.get("key") in DETAIL_METRICS
            and d.get("metricsIndex") is not None
        }
        if "lat" not in index_of or "lon" not in index_of:
            continue

        activity_id = payload.get("activityId") or int(path.stem)
        step = max(1, len(samples) // config.ROUTE_POINTS)
        rows = []
        for position in range(0, len(samples), step):
            values = (samples[position] or {}).get("metrics") or []
            point = {"activity_id": activity_id, "seq": position}
            for name, column in index_of.items():
                point[name] = values[column] if column < len(values) else None
            if point.get("lat") is None or point.get("lon") is None:
                continue
            rows.append(point)
        if len(rows) < 5:
            continue

        track = pd.DataFrame(rows)
        if "distance_km" in track.columns:
            track["distance_km"] = pd.to_numeric(track["distance_km"], errors="coerce") / 1000
        if "speed_ms" in track.columns:
            speed = pd.to_numeric(track["speed_ms"], errors="coerce")
            track["pace_min_km"] = (1000 / speed / 60).where(speed > 0.5).round(2)
        tracks.append(track)

        geo = payload.get("geoPolylineDTO") or {}
        summaries.append(
            {
                "activity_id": activity_id,
                "points": int(len(track)),
                "min_lat": geo.get("minLat"),
                "max_lat": geo.get("maxLat"),
                "min_lon": geo.get("minLon"),
                "max_lon": geo.get("maxLon"),
                "start_lat": dig(geo, "startPoint", "lat"),
                "start_lon": dig(geo, "startPoint", "lon"),
                "elevation_gain_m": _elevation_gain(track),
            }
        )

    if not tracks:
        return pd.DataFrame(columns=["activity_id"]), pd.DataFrame(columns=["activity_id"])
    return (
        pd.concat(tracks, ignore_index=True),
        pd.DataFrame(summaries),
    )


def _elevation_gain(track: pd.DataFrame) -> float | None:
    """Summed positive elevation change, smoothed to drop GPS jitter."""
    if "elevation_m" not in track.columns:
        return None
    series = pd.to_numeric(track["elevation_m"], errors="coerce").dropna()
    if len(series) < 5:
        return None
    smoothed = series.rolling(5, min_periods=1, center=True).mean()
    gain = smoothed.diff().clip(lower=0).sum()
    return round(float(gain), 1)


def write_table(df: pd.DataFrame, name: str) -> Path:
    """Publish a table only once the new file is complete.

    The dashboard reads these files while the ETL runs, so a half-written
    parquet must never be visible under the real name. On Windows the swap can
    briefly collide with a reader, hence the retries.
    """
    config.TABLES.mkdir(parents=True, exist_ok=True)
    target = config.TABLES / f"{name}.parquet"
    # The staging name carries the pid: a backfill rebuilding tables while
    # another process runs the loader would otherwise swap the same temp file
    # out from under it.
    tmp = config.TABLES / f"{name}.parquet.{os.getpid()}.part"
    df.to_parquet(tmp, index=False)
    for attempt in range(5):
        try:
            tmp.replace(target)
            return target
        except PermissionError:
            if attempt == 4:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.4)
    tmp.unlink(missing_ok=True)
    return target


def main() -> int:
    daily = build_daily()
    activities = build_activities()
    write_table(daily, "daily")
    write_table(activities, "activities")
    write_table(build_segments(), "activity_segments")

    # Intraday tables: hypnograms, overnight series, full-day 3-minute samples.
    stages = build_sleep_stages()
    nights = build_night_series()
    intraday = build_intraday()
    write_table(stages, "sleep_stages")
    write_table(nights, "night_series")
    write_table(intraday, "intraday")

    routes, route_summary = build_routes()
    write_table(routes, "routes")
    write_table(route_summary, "route_summary")
    state = {
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "days": int(len(daily)),
        "first_day": str(daily["day"].min().date()) if len(daily) else None,
        "last_day": str(daily["day"].max().date()) if len(daily) else None,
        "activities": int(len(activities)),
        "sleep_stage_rows": int(len(stages)),
        "night_series_rows": int(len(nights)),
        "intraday_rows": int(len(intraday)),
        "route_points": int(len(routes)),
        "routes": int(len(route_summary)),
        "excluded_nights": sorted(str(d) for d in excluded_nights()),
    }
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(
        f"tabele przebudowane: {state['days']} dni "
        f"({state['first_day']} .. {state['last_day']}), "
        f"{state['activities']} aktywnosci",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
