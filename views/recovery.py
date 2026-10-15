"""Recovery: HRV, resting heart rate, readiness and the quadrants they form."""

from __future__ import annotations

import streamlit as st

import shell
import theme as tz


def render() -> None:
    frame = shell.daily()
    view = shell.clip(frame)
    row = shell.latest_day()

    st.title("Regeneracja")
    st.caption(
        "HRV i tętno spoczynkowe mają sens wyłącznie względem własnej bazy — "
        "wartości bezwzględne różnią się międzyosobniczo o rzędy wielkości."
    )
    shell.metrics(
        row,
        frame.iloc[-2] if len(frame) > 1 else None,
        [
            ("readiness", "Readiness", ""),
            ("hrv_last_night", "HRV noc", "ms"),
            ("rhr", "RHR", "bpm"),
            ("sleep_score", "Sen", ""),
            ("bb_high", "Body Battery max", ""),
        ],
    )
    feedback = row.get("readiness_feedback") if row is not None else None
    if isinstance(feedback, str) and feedback:
        st.caption(f"Komentarz Garmina: {feedback.replace('_', ' ').lower()}")

    shell.lead("HRV, tętno spoczynkowe i readiness")
    tz.show(
        tz.stacked_panels(
            view,
            "day",
            [
                {
                    "title": "HRV w nocy (ms)",
                    "series": {"HRV": "hrv_last_night", "średnia 7 d": "hrv_last_night_roll7"},
                    "kind": "line",
                },
                {
                    "title": "Tętno spoczynkowe (bpm)",
                    "series": {"RHR": "rhr", "średnia 7 d": "rhr_roll7"},
                    "kind": "line",
                },
                {
                    "title": "Training readiness",
                    "series": {"readiness": "readiness", "średnia 7 d": "readiness_roll7"},
                    "kind": "line",
                },
            ],
            height=520,
        ),
        table=view[["day", "hrv_last_night", "rhr", "readiness", "sleep_h"]].tail(40),
    )

    shell.lead(
        "Kwadranty regeneracji",
        "HRV i tętno spoczynkowe jako odchylenie od własnej bazy 60-dniowej. "
        "Prawy-dolny róg (HRV wyżej, RHR niżej) to dzień zregenerowany; lewy-górny "
        "to jedyny układ, który konsekwentnie oznacza przeciążenie — samo niskie HRV "
        "to zwykle szum.",
    )
    quadrants = shell.clip(shell.table("quadrants"))
    if quadrants.empty:
        shell.missing("quadrants", "Potrzeba ~40 dni z HRV i RHR.")
    else:
        figure = tz.scatter(
            quadrants,
            "hrv_z",
            "rhr_z",
            color="load_day",
            color_kind="sequential",
            color_title="load dnia",
            hover=("quadrant", "readiness", "sleep_h"),
            x_title="HRV (odchylenie standardowe od bazy)",
            y_title="RHR (odchylenie standardowe od bazy)",
            height=440,
        )
        if figure is not None:
            tz.zero_lines(figure)
        shares = (
            quadrants["quadrant"].value_counts(normalize=True).mul(100).round(1)
            .rename_axis("kwadrant").reset_index(name="udział %")
        )
        tz.show(figure, table=shares, note=f"n = {len(quadrants)} dni w tym zakresie")

    shell.lead(
        "Body Battery",
        "Maksimum dnia, minimum i stan po wstaniu. Rozjazd między maksimum a stanem "
        "porannym mówi o nocy więcej niż sama ocena snu.",
    )
    tz.show(
        tz.timeseries(
            view,
            "day",
            {"maksimum": "bb_high", "minimum": "bb_low", "po wstaniu": "bb_wake"},
        )
    )

    shell.lead("Stres", "Średnia dobowa i średnia podczas snu.")
    tz.show(tz.timeseries(view, "day", {"dzień": "stress_avg", "sen": "sleep_stress"}))
