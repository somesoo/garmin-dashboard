"""The columns every source fills -- or leaves empty -- in the base tables.

Analytics, the running module and the pages were written against Garmin's
tables. A source that has no readiness or Body Battery (Apple Health) still has
to hand them a ``daily`` with those columns, all empty, rather than a table they
fail on. ``conform`` adds what is missing and keeps whatever extra a source has
(``hrv_sdnn``, ``sleep_in_bed_only``).

Garmin-only meanings stay Garmin-only: ``hrv_last_night`` is RMSSD and is never
filled from Apple's SDNN; ``training_load`` is Garmin's EPOC-based load or
Banister's TRIMP, which ``load_source`` names per row.
"""

from __future__ import annotations

import pandas as pd

DAILY = (
    "day", "source", "steps", "step_goal", "distance_m", "calories", "active_calories", "bmr_calories",
    "floors_up", "intensity_moderate", "intensity_vigorous", "intensity_goal",
    "rhr", "rhr_7d", "hr_min", "hr_max",
    "stress_avg", "stress_max", "stress_qualifier",
    "bb_high", "bb_low", "bb_wake", "bb_charged", "bb_drained", "spo2_avg", "respiration_waking",
    "sedentary_s", "active_s", "sleeping_s",
    "sleep_score", "sleep_qualifier", "sleep_h", "sleep_deep_h", "sleep_light_h", "sleep_rem_h",
    "sleep_awake_h", "sleep_nap_h", "sleep_awake_count", "sleep_restless", "sleep_stress", "sleep_respiration",
    "sleep_start", "sleep_end", "sleep_feedback", "sleep_insight",
    "overnight_hrv", "sleep_rhr", "hrv_last_night", "hrv_weekly", "hrv_high_5min", "hrv_status",
    "hrv_baseline_low", "hrv_baseline_high", "hrv_kind", "hrv_norm", "hrv_sdnn", "wrist_temp_c", "exercise_min",
    "readiness", "readiness_level", "readiness_feedback", "acute_load", "acwr_percent", "recovery_time_h",
    "f_sleep", "f_hrv", "f_recovery", "f_sleep_history", "f_stress_history",
    "vo2max", "fitness_age", "training_status", "training_status_code", "training_status_feedback",
    "load_acute", "load_chronic", "load_ratio", "load_ratio_status", "load_optimal_low", "load_optimal_high",
    "load_4w_low_aerobic", "load_4w_high_aerobic", "load_4w_anaerobic", "load_balance_feedback",
    "weight_kg", "body_fat_pct", "body_water_pct", "muscle_mass_kg",
)
# Text columns: empty as None (object), numbers as NaN (float).
DAILY_TEXT = {"source", "hrv_kind", "hrv_norm", "stress_qualifier", "sleep_qualifier", "sleep_feedback", "sleep_insight", "hrv_status",
              "readiness_level", "readiness_feedback", "training_status", "training_status_code",
              "training_status_feedback", "load_ratio_status", "load_balance_feedback"}

ACTIVITIES = (
    "activity_id", "start_local", "name", "sport", "distance_km", "duration_min", "moving_min", "pace_min_km",
    "speed_kmh", "avg_hr", "max_hr", "calories", "elevation_gain_m", "training_load", "load_source",
    "te_aerobic", "te_anaerobic", "avg_power", "norm_power", "cadence", "stride_m",
    "hr_z1_s", "hr_z2_s", "hr_z3_s", "hr_z4_s", "hr_z5_s", "location",
    "start_lat", "start_lon", "end_lat", "end_lon", "best_1k_s", "best_mile_s", "best_5k_s",
    "gap_speed", "max_speed", "vo2max_activity", "lap_count", "temperature_max", "moderate_minutes",
    "workout_id", "event_type", "source", "day", "iso_week",
)
ACTIVITIES_TEXT = {"name", "sport", "load_source", "location", "event_type", "source", "iso_week"}


def conform(df: pd.DataFrame, columns: tuple[str, ...], text: set[str]) -> pd.DataFrame:
    """``df`` with every column of the schema (missing ones empty), schema order first."""
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            if column in text:
                out[column] = pd.Series([None] * len(out), index=out.index, dtype=object)
            else:
                out[column] = pd.Series(float("nan"), index=out.index, dtype=float)
    extra = [c for c in out.columns if c not in columns]
    return out[[*columns, *extra]]


def daily(df: pd.DataFrame) -> pd.DataFrame:
    return conform(df, DAILY, DAILY_TEXT)


def activities(df: pd.DataFrame) -> pd.DataFrame:
    return conform(df, ACTIVITIES, ACTIVITIES_TEXT)
