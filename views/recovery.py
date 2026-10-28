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
        return i18n.tr(pl="poniżej normy", en="below normal")
    if value > high:
        return i18n.tr(pl="powyżej normy", en="above normal")
    return i18n.tr(pl="w normie", en="within normal")


def quadrant_labels() -> dict[str, str]:
    """Display names of the codes analytics.recovery_quadrants stores."""
    tr = i18n.tr
    return {"zregenerowany": tr(pl="zregenerowany", en="recovered"), "obciazony": tr(pl="obciążony", en="strained"),
            "pobudzony": tr(pl="pobudzony", en="aroused"), "stlumiony": tr(pl="stłumiony", en="suppressed")}


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

    tr = i18n.tr
    bento.header(
        i18n.page("regeneracja"),
        tr(pl="HRV i tętno spoczynkowe mają sens wyłącznie względem własnej bazy. Zmiany pod liczbami: względem "
              "średniej z poprzednich 7 dni.",
           en="HRV and resting heart rate only make sense against your own baseline. Changes under the numbers: "
              "against the average of the previous 7 days."),
    )
    bento.kpis(row, week, [
        ("readiness", "Readiness", ""),
        ("hrv_last_night", tr(pl="HRV noc", en="Night HRV"), "ms"),
        ("rhr", "RHR", "bpm", "inverse"),
        ("sleep_score", tr(pl="Sen", en="Sleep"), ""),
    ])

    left, right = bento.row(2, 2)
    with left, bento.tile(tr(pl="HRV w nocy", en="Overnight HRV"), rows=2, key="hrv", terms=["hrv", "deviation"],
                          caption=_status_line(latest.get("hrv_last_night"), "ms",
                                               latest.get("hrv_baseline_low"), latest.get("hrv_baseline_high")),
                          how=glossary.trend_how() + tr(pl=" Norma to zakres „zrównoważony” Garmina.",
                                                       en=" The normal is Garmin's “balanced” range.")) as t:
        t.chart(tz.trend(view, "day", {"HRV": ("hrv_last_night", "hrv_last_night_roll7")},
                         band=("hrv_baseline_low", "hrv_baseline_high"), unit="ms"),
                table=view[["day", "hrv_last_night", "hrv_baseline_low", "hrv_baseline_high"]].tail(40))
    with right:
        with bento.tile(tr(pl="Tętno spoczynkowe", en="Resting heart rate"), key="rhr", terms=["rhr"],
                        caption=_status_line(latest.get("rhr"), "bpm",
                                             latest.get("rhr_norm_low"), latest.get("rhr_norm_high")),
                        how=glossary.trend_how() + tr(pl=" Norma to 10.–90. percentyl z 60 dni.",
                                                     en=" The normal is the 10th–90th percentile of 60 days.")) as t:
            t.chart(tz.trend(view, "day", {"RHR": ("rhr", "rhr_roll7")},
                             band=("rhr_norm_low", "rhr_norm_high"), unit="bpm"),
                    table=view[["day", "rhr", "rhr_norm_low", "rhr_norm_high"]].tail(40))
        readiness_caption = _status_line(latest.get("readiness"), "")
        if isinstance(feedback, str) and feedback:
            readiness_caption = " · ".join(filter(None, [readiness_caption,
                                                         f"Garmin: {feedback.replace('_', ' ').lower()}"]))
        with bento.tile("Training readiness", key="readiness", terms=["readiness"], caption=readiness_caption,
                        how=glossary.trend_how()) as t:
            t.chart(tz.trend(view, "day", {"readiness": ("readiness", "readiness_roll7")}),
                    table=view[["day", "hrv_last_night", "rhr", "readiness", "sleep_h"]].tail(40))

    left, right = bento.row(2, 2)
    quadrants = shell.clip(shell.table("quadrants"))
    with left, bento.tile(
        tr(pl="Kwadranty regeneracji", en="Recovery quadrants"), rows=2, key="quadrants",
        terms=["quadrants", "deviation"],
        caption=tr(pl="Lewy-górny róg (HRV nisko, RHR wysoko) to jedyny układ, który oznacza przeciążenie.",
                   en="The top-left corner (HRV low, RHR high) is the only pattern that means overload."),
        how=tr(pl="Szare punkty to historia, niebieska ścieżka — ostatni tydzień, dzień po dniu. Prawy-dolny róg "
                  "(HRV wyżej, RHR niżej) to dzień zregenerowany.",
               en="Grey points are history, the blue path — the last week, day by day. The bottom-right corner "
                  "(HRV higher, RHR lower) is a recovered day."),
    ) as t:
        if quadrants.empty:
            shell.missing("quadrants", tr(pl="Potrzeba ~40 dni z HRV i RHR.", en="Needs ~40 days with HRV and RHR."))
        else:
            names = quadrant_labels()
            shares = (
                quadrants["quadrant"].map(names).value_counts(normalize=True).mul(100).round(1)
                .rename_axis(tr(pl="kwadrant", en="quadrant")).reset_index(name=tr(pl="udział %", en="share %"))
            )
            t.chart(tz.trail(quadrants, "hrv_z", "rhr_z",
                             corners={"tl": names["obciazony"], "tr": names["pobudzony"], "bl": names["stlumiony"],
                                      "br": names["zregenerowany"]},
                             x_title=tr(pl="HRV względem bazy (σ)", en="HRV vs baseline (σ)"),
                             y_title=tr(pl="RHR względem bazy (σ)", en="RHR vs baseline (σ)")),
                    table=shares)
    with right:
        with bento.tile("Body Battery", key="bb", terms=["body_battery"],
                        caption=_range_line(latest.get("bb_low"), latest.get("bb_high")),
                        how=tr(pl="Słupek to jeden dzień: od najniższego do najwyższego poziomu. Wysoki szczyt to "
                                  "dobra noc, niski dół to wymagający dzień.",
                               en="A bar is one day: from the lowest to the highest level. A high peak is a good "
                                  "night, a low trough a demanding day.")) as t:
            t.chart(tz.range_bars(view, "day", "bb_low", "bb_high"),
                    table=view[["day", "bb_low", "bb_high", "bb_charged", "bb_drained"]].tail(40))
        with bento.tile(tr(pl="Stres — dzień i sen", en="Stress — day and sleep"), key="stress", terms=["stress"],
                        caption=tr(pl="Nocny powinien być niski, inaczej sen nie regeneruje.",
                                   en="The night one should be low, otherwise sleep does not restore."),
                        how=glossary.trend_how()) as t:
            t.chart(tz.trend(view, "day", {tr(pl="dzień", en="day"): ("stress_avg", "stress_avg_roll7"),
                                           tr(pl="sen", en="sleep"): ("sleep_stress", "sleep_stress_roll7")}),
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
    return i18n.tr(pl=f"ostatni dzień <b>{low:.0f}–{high:.0f}</b>", en=f"last day <b>{low:.0f}–{high:.0f}</b>")
