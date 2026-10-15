"""Slow-moving numbers: VO2max, weight, sleep length, steps, week by week."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import shell
import theme as tz


def render() -> None:
    view = shell.clip(shell.daily())
    st.title("Trendy")
    st.caption(
        "Metryki, które zmieniają się w skali miesięcy. Każda z własną średnią "
        "kroczącą, bo dzień do dnia nic tu nie znaczy."
    )

    tz.key([("dot", "dzień"), ("line", "średnia krocząca")])

    shell.lead("VO2max", "Średnia 28-dniowa — VO2max zmienia się w skali tygodni, nie dni.")
    tz.show(tz.trend(view, "day", {"VO2max": ("vo2max", "vo2max_roll28")},
                     decimals=1, smooth_label="średnia 28 d"), key="trend_vo2")

    weights = pd.to_numeric(view.get("weight_kg"), errors="coerce").notna().sum()
    if weights >= 3:
        shell.lead("Masa ciała")
        tz.show(tz.trend(view, "day", {"waga": ("weight_kg", "weight_kg_roll7")},
                         unit="kg", decimals=1), key="trend_weight")
    else:
        st.caption(f"Masa ciała: {weights} pomiar(y) w tym zakresie — za mało na wykres.")

    shell.lead("Długość snu")
    tz.show(tz.trend(view, "day", {"sen": ("sleep_h", "sleep_h_roll7")}, unit="h", decimals=1),
            key="trend_sleep")

    shell.lead("Kroki")
    tz.show(tz.trend(view, "day", {"kroki": ("steps", "steps_roll7")}), key="trend_steps")

    shell.lead("Tydzień po tygodniu")
    weekly = (
        view.groupby("iso_week")
        .agg(
            kroki=("steps", "mean"),
            sen_h=("sleep_h", "mean"),
            hrv=("hrv_last_night", "mean"),
            rhr=("rhr", "mean"),
            readiness=("readiness", "mean"),
            stres=("stress_avg", "mean"),
        )
        .round(1)
        .reset_index()
        .sort_values("iso_week", ascending=False)
    )
    st.dataframe(
        weekly, width="stretch", hide_index=True, height=400,
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
