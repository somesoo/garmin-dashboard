"""Recovery: HRV, resting heart rate, readiness and the quadrants they form."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import shell
import theme as tz


def _status(value: float | None, low: float | None, high: float | None) -> str:
    if value is None or low is None or high is None or pd.isna(value) or pd.isna(low) or pd.isna(high):
        return ""
    if value < low:
        return "poniżej normy"
    if value > high:
        return "powyżej normy"
    return "w normie"


def _headline(title: str, value: float | None, unit: str, low=None, high=None) -> None:
    """Section name with today's number and where it sits against the norm."""
    parts = []
    if value is not None and not pd.isna(value):
        parts.append(f"**{value:.0f}{' ' + unit if unit else ''}**")
    status = _status(value, low, high)
    if status:
        parts.append(f"{status} ({low:.0f}–{high:.0f})")
    st.markdown(f"### {title}")
    if parts:
        st.caption(" · ".join(parts))


def render() -> None:
    frame = shell.daily().sort_values("day")
    # The resting-HR norm is the person's own 60-day 10th-90th percentile,
    # computed over the full history so the window edge does not shrink it.
    rolling = frame["rhr"].rolling(60, min_periods=20)
    frame["rhr_norm_low"] = rolling.quantile(0.10)
    frame["rhr_norm_high"] = rolling.quantile(0.90)
    for column in ("stress_avg", "sleep_stress"):
        if f"{column}_roll7" not in frame.columns:
            frame[f"{column}_roll7"] = frame[column].rolling(7, min_periods=3).mean()
    view = shell.clip(frame)
    row = shell.latest_day()
    week = shell.week_before(frame)

    st.title("Regeneracja")
    st.caption(
        "HRV i tętno spoczynkowe mają sens wyłącznie względem własnej bazy — "
        "wartości bezwzględne różnią się międzyosobniczo o rzędy wielkości. "
        "Zmiany pod liczbami: względem średniej z poprzednich 7 dni."
    )
    shell.metrics(
        row,
        week,
        [
            ("readiness", "Readiness", ""),
            ("hrv_last_night", "HRV noc", "ms"),
            ("rhr", "RHR", "bpm", "inverse"),
            ("sleep_score", "Sen", ""),
            ("bb_high", "Body Battery max", ""),
        ],
    )
    feedback = row.get("readiness_feedback") if row is not None else None
    if isinstance(feedback, str) and feedback:
        st.caption(f"Komentarz Garmina: {feedback.replace('_', ' ').lower()}")

    shell.lead(
        "HRV, tętno spoczynkowe i readiness",
        "Kropki to pojedyncze dni, linia to średnia 7-dniowa — to ona niesie sygnał. "
        "Szary pas to Twoja norma: dla HRV zakres wyznaczony przez Garmina, dla "
        "tętna 10.–90. percentyl z ostatnich 60 dni.",
    )
    tz.key([("dot", "dzień"), ("line", "średnia 7 d"), ("band", "norma")])
    latest = frame.iloc[-1]

    _headline("HRV w nocy", latest.get("hrv_last_night"), "ms",
              latest.get("hrv_baseline_low"), latest.get("hrv_baseline_high"))
    tz.show(tz.trend(view, "day", {"HRV": ("hrv_last_night", "hrv_last_night_roll7")},
                     band=("hrv_baseline_low", "hrv_baseline_high"), unit="ms"),
            key="trend_hrv")

    _headline("Tętno spoczynkowe", latest.get("rhr"), "bpm",
              latest.get("rhr_norm_low"), latest.get("rhr_norm_high"))
    tz.show(tz.trend(view, "day", {"RHR": ("rhr", "rhr_roll7")},
                     band=("rhr_norm_low", "rhr_norm_high"), unit="bpm"),
            key="trend_rhr")

    _headline("Training readiness", latest.get("readiness"), "")
    tz.show(
        tz.trend(view, "day", {"readiness": ("readiness", "readiness_roll7")}),
        table=view[["day", "hrv_last_night", "rhr", "readiness", "sleep_h"]].tail(40),
        key="trend_readiness",
    )

    shell.lead(
        "Kwadranty regeneracji",
        "HRV i tętno spoczynkowe jako odchylenie od własnej bazy 60-dniowej. "
        "Szare punkty to historia, niebieska ścieżka — ostatni tydzień, dzień po "
        "dniu. Prawy-dolny róg (HRV wyżej, RHR niżej) to dzień zregenerowany; "
        "lewy-górny to jedyny układ, który konsekwentnie oznacza przeciążenie — "
        "samo niskie HRV to zwykle szum.",
    )
    quadrants = shell.clip(shell.table("quadrants"))
    if quadrants.empty:
        shell.missing("quadrants", "Potrzeba ~40 dni z HRV i RHR.")
    else:
        figure = tz.trail(
            quadrants,
            "hrv_z",
            "rhr_z",
            corners={"tl": "obciążony", "tr": "pobudzony", "bl": "stłumiony", "br": "zregenerowany"},
            x_title="HRV względem bazy (σ)",
            y_title="RHR względem bazy (σ)",
            height=460,
        )
        shares = (
            quadrants["quadrant"].value_counts(normalize=True).mul(100).round(1)
            .rename_axis("kwadrant").reset_index(name="udział %")
        )
        tz.show(figure, table=shares, note=f"n = {len(quadrants)} dni w tym zakresie")

    shell.lead(
        "Body Battery",
        "Każdy słupek to jeden dzień: od najniższego do najwyższego poziomu. "
        "Wysoki szczyt to dobra noc, niski dół to wymagający dzień — długi słupek "
        "oznacza oba naraz. Ostatni dzień jest wyróżniony.",
    )
    tz.show(tz.range_bars(view, "day", "bb_low", "bb_high"),
            table=view[["day", "bb_low", "bb_high", "bb_charged", "bb_drained"]].tail(40),
            key="bb_range")

    shell.lead("Stres", "Średnia dobowa i średnia podczas snu, każda ze swoją średnią 7-dniową.")
    tz.show(
        tz.trend(
            view,
            "day",
            {"dzień": ("stress_avg", "stress_avg_roll7"), "sen": ("sleep_stress", "sleep_stress_roll7")},
            height=240,
        ),
        key="trend_stress",
    )
