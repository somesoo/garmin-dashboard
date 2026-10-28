"""Recovery: HRV, resting heart rate, readiness and the quadrants they form."""

from __future__ import annotations

import pandas as pd

import bento
import glossary
import i18n
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

    # Captions read the last scored night, not today's empty row before the watch synced.
    latest = frame[frame["day"] == row["day"]].iloc[-1] if row is not None else frame.iloc[-1]
    feedback = row.get("readiness_feedback") if row is not None else None

    bento.header(
        i18n.page("regeneracja"),
        "HRV i tętno spoczynkowe mają sens wyłącznie względem własnej bazy. Zmiany pod liczbami: względem "
        "średniej z poprzednich 7 dni.",
    )
    bento.kpis(row, week, [
        ("readiness", "Readiness", ""),
        ("hrv_last_night", "HRV noc", "ms"),
        ("rhr", "RHR", "bpm", "inverse"),
        ("sleep_score", "Sen", ""),
    ])

    left, right = bento.row(2, 2)
    with left, bento.tile("HRV w nocy", rows=2, key="hrv", terms=["hrv", "deviation"],
                          caption=_status_line(latest.get("hrv_last_night"), "ms",
                                               latest.get("hrv_baseline_low"), latest.get("hrv_baseline_high")),
                          how=glossary.TREND_HOW + " Norma to zakres „zrównoważony” Garmina.") as t:
        t.chart(tz.trend(view, "day", {"HRV": ("hrv_last_night", "hrv_last_night_roll7")},
                         band=("hrv_baseline_low", "hrv_baseline_high"), unit="ms"),
                table=view[["day", "hrv_last_night", "hrv_baseline_low", "hrv_baseline_high"]].tail(40))
    with right:
        with bento.tile("Tętno spoczynkowe", key="rhr", terms=["rhr"],
                        caption=_status_line(latest.get("rhr"), "bpm",
                                             latest.get("rhr_norm_low"), latest.get("rhr_norm_high")),
                        how=glossary.TREND_HOW + " Norma to 10.–90. percentyl z 60 dni.") as t:
            t.chart(tz.trend(view, "day", {"RHR": ("rhr", "rhr_roll7")},
                             band=("rhr_norm_low", "rhr_norm_high"), unit="bpm"),
                    table=view[["day", "rhr", "rhr_norm_low", "rhr_norm_high"]].tail(40))
        readiness_caption = _status_line(latest.get("readiness"), "")
        if isinstance(feedback, str) and feedback:
            readiness_caption = " · ".join(filter(None, [readiness_caption,
                                                         f"Garmin: {feedback.replace('_', ' ').lower()}"]))
        with bento.tile("Training readiness", key="readiness", terms=["readiness"], caption=readiness_caption,
                        how=glossary.TREND_HOW) as t:
            t.chart(tz.trend(view, "day", {"readiness": ("readiness", "readiness_roll7")}),
                    table=view[["day", "hrv_last_night", "rhr", "readiness", "sleep_h"]].tail(40))

    left, right = bento.row(2, 2)
    quadrants = shell.clip(shell.table("quadrants"))
    with left, bento.tile(
        "Kwadranty regeneracji", rows=2, key="quadrants", terms=["quadrants", "deviation"],
        caption="Lewy-górny róg (HRV nisko, RHR wysoko) to jedyny układ, który oznacza przeciążenie.",
        how="Szare punkty to historia, niebieska ścieżka — ostatni tydzień, dzień po dniu. Prawy-dolny róg "
            "(HRV wyżej, RHR niżej) to dzień zregenerowany.",
    ) as t:
        if quadrants.empty:
            shell.missing("quadrants", "Potrzeba ~40 dni z HRV i RHR.")
        else:
            shares = (
                quadrants["quadrant"].value_counts(normalize=True).mul(100).round(1)
                .rename_axis("kwadrant").reset_index(name="udział %")
            )
            t.chart(tz.trail(quadrants, "hrv_z", "rhr_z",
                             corners={"tl": "obciążony", "tr": "pobudzony", "bl": "stłumiony", "br": "zregenerowany"},
                             x_title="HRV względem bazy (σ)", y_title="RHR względem bazy (σ)"),
                    table=shares)
    with right:
        with bento.tile("Body Battery", key="bb", terms=["body_battery"],
                        caption=_range_line(latest.get("bb_low"), latest.get("bb_high")),
                        how="Słupek to jeden dzień: od najniższego do najwyższego poziomu. Wysoki szczyt to dobra "
                            "noc, niski dół to wymagający dzień.") as t:
            t.chart(tz.range_bars(view, "day", "bb_low", "bb_high"),
                    table=view[["day", "bb_low", "bb_high", "bb_charged", "bb_drained"]].tail(40))
        with bento.tile("Stres — dzień i sen", key="stress", terms=["stress"],
                        caption="Nocny powinien być niski, inaczej sen nie regeneruje.", how=glossary.TREND_HOW) as t:
            t.chart(tz.trend(view, "day", {"dzień": ("stress_avg", "stress_avg_roll7"),
                                           "sen": ("sleep_stress", "sleep_stress_roll7")}),
                    table=view[["day", "stress_avg", "sleep_stress"]].tail(40))


def _status_line(value: float | None, unit: str, low=None, high=None) -> str | None:
    """Today's number and where it sits against the norm, for a tile caption."""
    if value is None or pd.isna(value):
        return None
    text = f"<b>{value:.0f}{' ' + unit if unit else ''}</b>"
    status = _status(value, low, high)
    return f"{text} · {status} ({low:.0f}–{high:.0f})" if status else text


def _range_line(low: float | None, high: float | None) -> str | None:
    if low is None or high is None or pd.isna(low) or pd.isna(high):
        return None
    return f"ostatni dzień <b>{low:.0f}–{high:.0f}</b>"
