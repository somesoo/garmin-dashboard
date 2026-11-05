"""Recovery: HRV, resting heart rate, readiness and the quadrants they form;
steps, body weight and the weekly table at the bottom (they move over months)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import bento
from ui import glossary
from core import i18n
from ui import shell
from analysis import facts
from ui import herochart as hc
from ui import story
from ui import theme as tz
from views import run_common as rc, trends


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


def _frame() -> pd.DataFrame:
    frame = shell.daily().sort_values("day")
    # The resting-HR norm is the person's own 60-day 10th-90th percentile,
    # computed over the full history so the window edge does not shrink it.
    rolling = frame["rhr"].rolling(60, min_periods=20)
    frame["rhr_norm_low"] = rolling.quantile(0.10)
    frame["rhr_norm_high"] = rolling.quantile(0.90)
    for column in ("stress_avg", "sleep_stress"):
        if f"{column}_roll7" not in frame.columns:
            frame[f"{column}_roll7"] = frame[column].rolling(7, min_periods=3).mean()
    return frame


def render() -> None:
    """The HRV hero: nights, the 7-night mean and Garmin's normal, hard sessions marked under it;
    the week's kilometres (stimulus) and sleep (the other response) on the same time axis."""
    tr = i18n.tr
    frame = _frame()
    view = shell.clip(frame)
    runs = rc.runs()
    told = facts.recovery(frame, runs, shell.cutoff())
    words = facts.hrv_norm_words(frame)
    story.frame_page(
        "regeneracja", headline=told["headline"],
        sub=tr(pl=f"{words['measure']}, średnia z 7 nocy i {words['short']}. Pomarańczowe kreski na dole to poranki "
                  "po mocnym treningu. Pod spodem — bodziec (kilometry) i druga odpowiedź (sen) na tej samej osi czasu.",
               en=f"{words['measure']}, the 7-night mean and {words['short']}. Orange ticks at the bottom are mornings "
                  "after a hard session. Below — the stimulus (kilometres) and the other response (sleep) on the same "
                  "time axis."),
        hero=lambda: _hero(view, runs, told),
        more=tr(pl="tętno spoczynkowe, readiness, kwadranty, Body Battery, stres, kroki, waga, tydzień po tygodniu",
                en="resting heart rate, readiness, quadrants, Body Battery, stress, steps, weight, week by week"),
        more_render=lambda: _details(frame),
    )


def _hero(view: pd.DataFrame, runs: pd.DataFrame, told: dict) -> None:
    tr = i18n.tr
    if view.empty or view["hrv_last_night"].notna().sum() < 5:
        shell.missing("HRV", tr(pl="Za mało nocy z HRV w wybranym zakresie.", en="Too few nights with HRV in this range."))
        return
    c = hc.colors()
    start, end = view["day"].min(), view["day"].max() + pd.Timedelta(days=1)
    hrv = hc.points(view, "day", "hrv_last_night", 0)
    band = [[hc.ms(r.day), float(r.hrv_baseline_low), float(r.hrv_baseline_high)]
            for r in view.dropna(subset=["hrv_baseline_low", "hrv_baseline_high"]).itertuples()]
    hard = facts.hard_days(runs)
    ticks = [[hc.ms(pd.Timestamp(d) + pd.Timedelta(days=1)), c["warm"]] for d in sorted(hard)
             if start <= pd.Timestamp(d) + pd.Timedelta(days=1) < end]
    last = view.dropna(subset=["hrv_last_night"]).iloc[-1]
    weeks = facts.weekly_km(runs)
    weeks = weeks[(weeks["week"] >= start - pd.Timedelta(days=6)) & (weeks["week"] < end)]
    whys = facts.recovery_whys(view, weeks)
    values = [v for _, v in hrv if v is not None] + [b for row in band for b in row[1:]]
    top = float(weeks["km"].max()) if not weeks.empty else 10.0
    panels = [
        {"kind": "trend", "points": hrv, "smooth": hc.points(view, "day", "hrv_last_night_roll7", 1), "band": band,
         "band_label": tr(pl="norma", en="normal"), "ticks": ticks, "y": hc.span(values), "unit": "ms",
         "name": "HRV", "smooth_name": tr(pl="średnia 7 nocy", en="7-night mean"), "end": f"{last['hrv_last_night']:.0f} ms"},
        {"kind": "bars", "strip": True,
         "bars": [[hc.ms(r.week), [round(r.easy_km, 1), round(r.hard_km, 1)]] for r in weeks.itertuples()],
         "colors": [c["series"], c["warm"]], "names": [tr(pl="spokojne km", en="easy km"), tr(pl="mocne km", en="hard km")],
         "period": tr(pl="tydzień od", en="week of"), "y": [0, max(10.0, top * 1.1)],
         "label": {"group": tr(pl="Bodziec · Obciążenie", en="Stimulus · Load"), "head": tr(pl="km tygodniowo", en="km per week"),
                   "note": tr(pl="pomarańczowe — treningi jakościowe", en="orange — quality sessions")},
         "why": whys.get("load", "")},
        {"kind": "trend", "strip": True, "points": hc.points(view, "day", "sleep_h", 2),
         "smooth": hc.points(view, "day", "sleep_h_roll7", 2), "y": [4, 10], "unit": "h", "decimals": 1, "tick_unit": " h",
         "name": tr(pl="sen", en="sleep"), "end": "•", "end_color": c["warm"],
         "label": {"group": tr(pl="Odpowiedź · Sen", en="Response · Sleep"), "head": tr(pl="godziny snu", en="hours of sleep"),
                   "note": tr(pl="średnia 7 nocy", en="7-night mean")},
         "why": whys.get("sleep", "")},
    ]
    satellites = [{**s, "anchor": {"t": hc.ms(s["anchor"][0]), "v": float(s["anchor"][1])} if s["anchor"] else None}
                  for s in told["satellites"]]
    spec = {"x": [hc.ms(start), hc.ms(end)], "panels": panels, "satellites": satellites}
    hc.show(spec, key="hero_regeneracja", token=story.token("regeneracja"))


def _details(frame: pd.DataFrame) -> None:
    """The second plan of the page: everything the hero does not carry."""
    view = shell.clip(frame)
    row = shell.latest_day()
    week = shell.week_before(frame)
    latest = frame[frame["day"] == row["day"]].iloc[-1] if row is not None else frame.iloc[-1]
    feedback = row.get("readiness_feedback") if row is not None else None
    tr = i18n.tr
    # Garmin-only numbers (readiness, sleep score) give way to what the person's watch records.
    garmin = shell.has("readiness")
    bento.kpis(row, week, [
        ("readiness", "Readiness", "") if garmin else ("steps", tr(pl="Kroki", en="Steps"), ""),
        ("hrv_last_night", tr(pl="HRV noc", en="Night HRV"), "ms"),
        ("rhr", "RHR", "bpm", "inverse"),
        ("sleep_score", tr(pl="Sen", en="Sleep"), "") if shell.has("sleep_score")
        else ("sleep_h", tr(pl="Sen", en="Sleep"), "h"),
    ])

    def rhr_tile() -> None:
        with bento.tile(tr(pl="Tętno spoczynkowe", en="Resting heart rate"), key="rhr", terms=["rhr"],
                        caption=_status_line(latest.get("rhr"), "bpm",
                                             latest.get("rhr_norm_low"), latest.get("rhr_norm_high")),
                        how=glossary.trend_how() + tr(pl=" Norma to 10.–90. percentyl z 60 dni.",
                                                     en=" The normal is the 10th–90th percentile of 60 days.")) as t:
            t.chart(tz.trend(view, "day", {"RHR": ("rhr", "rhr_roll7")},
                             band=("rhr_norm_low", "rhr_norm_high"), unit="bpm"),
                    table=view[["day", "rhr", "rhr_norm_low", "rhr_norm_high"]].tail(40))

    def readiness_tile() -> None:
        readiness_caption = _status_line(latest.get("readiness"), "")
        if isinstance(feedback, str) and feedback:
            readiness_caption = " · ".join(filter(None, [readiness_caption,
                                                         f"Garmin: {feedback.replace('_', ' ').lower()}"]))
        with bento.tile("Training readiness", key="readiness", terms=["readiness"], caption=readiness_caption,
                        how=glossary.trend_how()) as t:
            t.chart(tz.trend(view, "day", {"readiness": ("readiness", "readiness_roll7")}),
                    table=view[["day", "hrv_last_night", "rhr", "readiness", "sleep_h"]].tail(40))

    # HRV is the hero above; the details start with what it does not show.
    bento.pair(rhr_tile if shell.has("rhr") else None, readiness_tile if garmin else None)

    quadrants = shell.clip(shell.table("quadrants"))
    if shell.has("bb_low", "bb_high", "stress_avg", "sleep_stress"):
        left, right = bento.row(2, 2)
    else:  # no Body Battery or stress (an Apple Watch): the quadrants take the row
        left = right = st.container()
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
        _battery_and_stress(view, latest)

    # Slow-moving numbers: they change over months, so they close the page.
    bento.pair((lambda: trends.steps(view)) if shell.has("steps") else None,
               (lambda: trends.weight(view)) if shell.has("weight_kg") else None)
    trends.weekly(view)


def _battery_and_stress(view: pd.DataFrame, latest: pd.Series) -> None:
    """Garmin's Body Battery and stress, each only when the person's source records it."""
    tr = i18n.tr
    if shell.has("bb_low", "bb_high"):
        with bento.tile("Body Battery", key="bb", terms=["body_battery"],
                        caption=_range_line(latest.get("bb_low"), latest.get("bb_high")),
                        how=tr(pl="Słupek to jeden dzień: od najniższego do najwyższego poziomu. Wysoki szczyt to "
                                  "dobra noc, niski dół to wymagający dzień.",
                               en="A bar is one day: from the lowest to the highest level. A high peak is a good "
                                  "night, a low trough a demanding day.")) as t:
            t.chart(tz.range_bars(view, "day", "bb_low", "bb_high"),
                    table=view[["day", "bb_low", "bb_high", "bb_charged", "bb_drained"]].tail(40))
    if shell.has("stress_avg", "sleep_stress"):
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
