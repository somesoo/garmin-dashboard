"""Slow-moving numbers: VO2max, weight, sleep length, steps, week by week."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import glossary
import i18n
import shell
import theme as tz


def render() -> None:
    daily = shell.daily()
    view = shell.clip(daily)
    bento.header(i18n.page("trendy"), "Metryki, które zmieniają się w skali miesięcy — dzień do dnia nic tu nie znaczy.")
    bento.kpis(shell.latest_day(), shell.week_before(daily), [
        ("vo2max", "VO2max", ""),
        ("sleep_h", "Sen", "h"),
        ("steps", "Kroki", ""),
        ("weight_kg", "Masa ciała", "kg", "off"),
    ])

    left, right = bento.row(2, 2)
    with left, bento.tile("VO2max", key="trend_vo2", terms=["vo2max"],
                          caption="Średnia 28-dniowa — zmienia się w skali tygodni.", how=glossary.TREND_HOW) as t:
        t.chart(tz.trend(view, "day", {"VO2max": ("vo2max", "vo2max_roll28")}, decimals=1,
                         smooth_label="średnia 28 d"), table=view[["day", "vo2max", "vo2max_roll28"]].tail(40))
    with right, bento.tile("Długość snu", key="trend_sleep", how=glossary.TREND_HOW,
                           caption=_mean_line(view, "sleep_h", "h", 1)) as t:
        t.chart(tz.trend(view, "day", {"sen": ("sleep_h", "sleep_h_roll7")}, unit="h", decimals=1),
                table=view[["day", "sleep_h", "sleep_h_roll7"]].tail(40))

    left, right = bento.row(2, 2)
    with left, bento.tile("Kroki", key="trend_steps", how=glossary.TREND_HOW,
                          caption=_mean_line(view, "steps", "", 0)) as t:
        t.chart(tz.trend(view, "day", {"kroki": ("steps", "steps_roll7")}),
                table=view[["day", "steps", "steps_roll7"]].tail(40))
    weights = int(pd.to_numeric(view.get("weight_kg"), errors="coerce").notna().sum())
    with right, bento.tile("Masa ciała", key="trend_weight", how=glossary.TREND_HOW,
                           caption=f"{weights} pomiarów w zakresie") as t:
        if weights >= 3:
            t.chart(tz.trend(view, "day", {"waga": ("weight_kg", "weight_kg_roll7")}, unit="kg", decimals=1),
                    table=view[["day", "weight_kg"]].dropna().tail(40))
        else:
            st.caption("Za mało pomiarów na wykres — waga trafia do Garmina tylko z wagi Bluetooth.")

    weekly = (
        view.groupby("iso_week")
        .agg(kroki=("steps", "mean"), sen_h=("sleep_h", "mean"), hrv=("hrv_last_night", "mean"),
             rhr=("rhr", "mean"), readiness=("readiness", "mean"), stres=("stress_avg", "mean"))
        .round(1).reset_index().sort_values("iso_week", ascending=False)
    )
    with bento.panel("Tydzień po tygodniu", key="weekly", caption="Średnie tygodniowe, najnowszy tydzień na górze."):
        st.dataframe(
            weekly, width="stretch", hide_index=True, height=360,
            column_config={
                "iso_week": st.column_config.TextColumn("tydzień"),
                "kroki": st.column_config.NumberColumn("kroki", format="%.0f"),
                "sen_h": st.column_config.NumberColumn("sen (h)", format="%.1f"),
                "hrv": st.column_config.NumberColumn("HRV", format="%.0f"),
                "rhr": st.column_config.NumberColumn("RHR", format="%.0f"),
                "readiness": st.column_config.NumberColumn("readiness", format="%.0f"),
                "stres": st.column_config.NumberColumn("stres", format="%.0f"),
            },
        )


def _mean_line(view: pd.DataFrame, column: str, unit: str, decimals: int) -> str | None:
    values = pd.to_numeric(view.get(column), errors="coerce").dropna()
    if values.empty:
        return None
    number = f"{values.mean():,.{decimals}f}".replace(",", "\u2009")
    return f"średnio <b>{number}{' ' + unit if unit else ''}</b> w zakresie"
