"""Slow-moving numbers: VO2max, weight, sleep length, steps, week by week."""

from __future__ import annotations

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

    shell.lead("VO2max i masa ciała")
    tz.show(
        tz.stacked_panels(
            view,
            "day",
            [
                {
                    "title": "VO2max",
                    "series": {"VO2max": "vo2max", "średnia 28 d": "vo2max_roll28"},
                    "kind": "line",
                },
                {
                    "title": "Masa ciała (kg)",
                    "series": {"waga": "weight_kg", "średnia 7 d": "weight_kg_roll7"},
                    "kind": "line",
                },
            ],
            height=420,
        )
    )

    shell.lead("Sen i aktywność dzienna")
    tz.show(
        tz.stacked_panels(
            view,
            "day",
            [
                {
                    "title": "Długość snu (h)",
                    "series": {"sen": "sleep_h", "średnia 7 d": "sleep_h_roll7"},
                    "kind": "line",
                },
                {
                    "title": "Kroki",
                    "series": {"kroki": "steps", "średnia 7 d": "steps_roll7"},
                    "kind": "line",
                },
            ],
            height=420,
        )
    )

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
    st.dataframe(weekly, width="stretch", hide_index=True, height=400)
