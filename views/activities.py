"""Activity log: the table, plus the two scatters that read it back."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import shell
import theme as tz

COLUMNS = {
    "start_local": "kiedy",
    "sport": "sport",
    "name": "nazwa",
    "location": "miejsce",
    "distance_km": "km",
    "duration_min": "min",
    "pace_min_km": "min/km",
    "avg_hr": "tętno",
    "max_hr": "tętno max",
    "training_load": "load",
    "te_aerobic": "TE tlenowy",
    "te_anaerobic": "TE beztlenowy",
    "best_1k_s": "najlepszy 1 km (s)",
    "best_5k_s": "najlepszy 5 km (s)",
    "calories": "kcal",
    "elevation_gain_m": "przewyższenie",
}


def render() -> None:
    activities = shell.clip(shell.table("activities"))
    st.title("Aktywności")
    if activities.empty:
        st.caption("Brak aktywności w tym zakresie.")
        return

    columns = st.columns(4)
    columns[0].metric("Treningi", int(activities["activity_id"].count()))
    columns[1].metric("Dystans", f"{activities['distance_km'].sum():.0f} km")
    columns[2].metric("Czas", f"{activities['duration_min'].sum() / 60:.0f} h")
    columns[3].metric("Load", f"{activities['training_load'].sum():.0f}")

    sports = sorted(activities["sport"].dropna().unique())
    picked = st.multiselect("Sport", sports, default=sports, key="activities_sport")
    shown = activities[activities["sport"].isin(picked)] if picked else activities

    frame = shown.sort_values("start_local", ascending=False)
    frame = frame[[c for c in COLUMNS if c in frame.columns]].copy()
    frame["start_local"] = pd.to_datetime(frame["start_local"]).dt.strftime("%d.%m.%Y %H:%M")
    if "pace_min_km" in frame.columns:
        frame["pace_min_km"] = shell.pace_column(frame["pace_min_km"])
    for column in ("best_1k_s", "best_5k_s"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").map(
                lambda v: shell.clock(v) if pd.notna(v) else None
            )
    frame = frame.rename(columns=COLUMNS).rename(
        columns={"najlepszy 1 km (s)": "najlepszy 1 km", "najlepszy 5 km (s)": "najlepszy 5 km"}
    )
    st.dataframe(frame, width="stretch", hide_index=True, height=440,
                 column_config=shell.ACTIVITY_COLUMNS)

    runs = shown[shown["sport"].astype(str).str.contains("running", na=False)].copy()
    if runs.empty or not {"pace_min_km", "avg_hr"} <= set(runs.columns):
        return
    runs["start_local"] = pd.to_datetime(runs["start_local"])
    # Same rule as the efficiency table: under 1 km or slower than a walk is a
    # recording left running, and one 160 min/km point flattens the pace axis.
    runs = runs[
        (pd.to_numeric(runs["distance_km"], errors="coerce") >= 1.0)
        & (pd.to_numeric(runs["pace_min_km"], errors="coerce") <= 12.0)
    ]
    if runs.empty:
        return

    shell.lead(
        "Tempo w czasie",
        "Wyżej = szybciej. Rozmiar punktu to dystans, kolor — tętno średnie.",
    )
    tz.show(
        tz.scatter(
            runs, "start_local", "pace_min_km",
            color="avg_hr", color_kind="sequential", color_title="tętno",
            size="distance_km", hover=("name", "distance_km", "training_load"),
            x_title="", y_title="tempo /km", reverse_y=True, pace_y=True, height=380,
        )
    )

    shell.lead(
        "Tętno vs tempo",
        "Chmura punktów pokazuje koszt prędkości: im bardziej spłaszczona i przesunięta "
        "w lewo, tym taniej kupujesz tempo.",
    )
    tz.show(
        tz.scatter(
            runs, "avg_hr", "pace_min_km",
            size="distance_km", hover=("name", "distance_km"),
            x_title="tętno średnie (bpm)", y_title="tempo /km",
            reverse_y=True, pace_y=True, height=380,
        )
    )
