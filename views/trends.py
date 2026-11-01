"""Slow-moving numbers as tiles for other pages (no page of their own any more):
sleep length on Sen; steps, body weight and the weekly table on Regeneracja;
VO2max next to Garmin's race predictions on Prognoza."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import glossary
import i18n
import shell
import theme as tz


def vo2max(view: pd.DataFrame, rows: int = 1) -> None:
    tr = i18n.tr
    with bento.tile("VO2max", rows=rows, key="trend_vo2", terms=["vo2max"],
                    caption=tr(pl="Szacunek Garmina, średnia 28-dniowa — zmienia się w skali tygodni.",
                               en="Garmin's estimate, 28-day average — it changes over weeks."),
                    how=glossary.trend_how()) as t:
        t.chart(tz.trend(view, "day", {"VO2max": ("vo2max", "vo2max_roll28")}, decimals=1,
                         smooth_label=tr(pl="średnia 28 d", en="28-day mean")),
                table=view[["day", "vo2max", "vo2max_roll28"]].tail(40))


def sleep_length(view: pd.DataFrame) -> None:
    tr = i18n.tr
    with bento.tile(tr(pl="Długość snu", en="Sleep duration"), key="trend_sleep", how=glossary.trend_how(),
                    caption=_mean_line(view, "sleep_h", "h", 1)) as t:
        t.chart(tz.trend(view, "day", {tr(pl="sen", en="sleep"): ("sleep_h", "sleep_h_roll7")}, unit="h", decimals=1),
                table=view[["day", "sleep_h", "sleep_h_roll7"]].tail(40))


def steps(view: pd.DataFrame) -> None:
    tr = i18n.tr
    with bento.tile(tr(pl="Kroki", en="Steps"), key="trend_steps", how=glossary.trend_how(),
                    caption=_mean_line(view, "steps", "", 0)) as t:
        t.chart(tz.trend(view, "day", {tr(pl="kroki", en="steps"): ("steps", "steps_roll7")}),
                table=view[["day", "steps", "steps_roll7"]].tail(40))


def weight(view: pd.DataFrame) -> None:
    tr = i18n.tr
    weights = int(pd.to_numeric(view.get("weight_kg"), errors="coerce").notna().sum())
    noun = i18n.plural(weights, pl=("pomiar", "pomiary", "pomiarów"), en=("measurement", "measurements"))
    with bento.tile(tr(pl="Masa ciała", en="Body weight"), key="trend_weight", how=glossary.trend_how(),
                    caption=tr(pl=f"{weights} {noun} w zakresie", en=f"{weights} {noun} in range")) as t:
        if weights >= 3:
            t.chart(tz.trend(view, "day", {tr(pl="waga", en="weight"): ("weight_kg", "weight_kg_roll7")}, unit="kg",
                             decimals=1),
                    table=view[["day", "weight_kg"]].dropna().tail(40))
        else:
            st.caption(tr(pl="Za mało pomiarów na wykres — waga trafia do Garmina tylko z wagi Bluetooth.",
                          en="Too few measurements for a chart — weight reaches Garmin only from a Bluetooth scale."))


def has_weight(view: pd.DataFrame) -> bool:
    return int(pd.to_numeric(view.get("weight_kg"), errors="coerce").notna().sum()) >= 3


def weekly(view: pd.DataFrame) -> None:
    tr = i18n.tr
    table = (
        view.groupby("iso_week")
        .agg(kroki=("steps", "mean"), sen_h=("sleep_h", "mean"), hrv=("hrv_last_night", "mean"),
             rhr=("rhr", "mean"), readiness=("readiness", "mean"), stres=("stress_avg", "mean"))
        .round(1).reset_index().sort_values("iso_week", ascending=False)
    )
    with bento.panel(tr(pl="Tydzień po tygodniu", en="Week by week"), key="weekly",
                     caption=tr(pl="Średnie tygodniowe, najnowszy tydzień na górze.",
                                en="Weekly averages, the latest week on top.")):
        st.dataframe(
            table, width="stretch", hide_index=True, height=360,
            column_config={
                "iso_week": st.column_config.TextColumn(tr(pl="tydzień", en="week")),
                "kroki": st.column_config.NumberColumn(tr(pl="kroki", en="steps"), format="%.0f"),
                "sen_h": st.column_config.NumberColumn(tr(pl="sen (h)", en="sleep (h)"), format="%.1f"),
                "hrv": st.column_config.NumberColumn("HRV", format="%.0f"),
                "rhr": st.column_config.NumberColumn("RHR", format="%.0f"),
                "readiness": st.column_config.NumberColumn("readiness", format="%.0f"),
                "stres": st.column_config.NumberColumn(tr(pl="stres", en="stress"), format="%.0f"),
            },
        )


def _mean_line(view: pd.DataFrame, column: str, unit: str, decimals: int) -> str | None:
    values = pd.to_numeric(view.get(column), errors="coerce").dropna()
    if values.empty:
        return None
    number = f"{values.mean():,.{decimals}f}".replace(",", "\u2009")
    value = f"<b>{number}{' ' + unit if unit else ''}</b>"
    return i18n.tr(pl=f"średnio {value} w zakresie", en=f"{value} on average in range")
