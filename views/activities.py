"""Activity log (on the History page, under the globe: every session, filtered
by category) and the two run scatters (on the running overview). No page of
its own any more."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import bento
from core import i18n
from ui import routing
from ui import tables
from ui import shell
from ui import theme as tz
from sport import catalog

COLUMNS = ["start_local", "sport", "name", "location", "distance_km", "duration_min", "pace_min_km", "avg_hr",
           "max_hr", "training_load", "te_aerobic", "te_anaerobic", "best_1k_s", "best_5k_s", "calories",
           "elevation_gain_m"]


def log() -> None:
    """The activity log: every session ever recorded, newest on top, filtered by
    category (``catalog.category_of``: running, cycling, swimming...). It ignores
    the global range on purpose -- the History page is where the whole record
    lives. A tap opens the route (or the run analysis for a run without GPS)."""
    tr = i18n.tr
    activities = shell.table("activities")
    with bento.panel(tr(pl="Wszystkie treningi", en="Every session"), key="activities_log",
                     caption=tr(pl="Cała historia, najnowsze na górze. Wybierz kategorie, żeby zawęzić; "
                                   "dotknij wiersza, żeby otworzyć trasę.",
                                en="The whole history, newest on top. Pick categories to narrow it; "
                                   "tap a row to open the route.")):
        if activities.empty:
            st.caption(tr(pl="Brak aktywności.", en="No activities."))
            return
        activities = activities.assign(category=activities["sport"].map(catalog.category_of))
        counts = activities["category"].value_counts()
        picked = st.pills(tr(pl="Kategoria", en="Category"), counts.index.tolist(), selection_mode="multi",
                          format_func=lambda key: f"{catalog.label(key)} · {counts.get(key, 0)}",
                          key="activities_category", label_visibility="collapsed")
        shown = activities[activities["category"].isin(picked)] if picked else activities
        hours = shown["duration_min"].sum() / 60
        noun = i18n.plural(len(shown), pl=("trening", "treningi", "treningów"), en=("session", "sessions"))
        st.caption(tr(pl=f"**{len(shown)}** {noun} · {shown['distance_km'].sum():,.0f} km · {hours:,.0f} h"
                         .replace(",", " "),
                      en=f"**{len(shown)}** {noun} · {shown['distance_km'].sum():,.0f} km · {hours:,.0f} h"))

        frame = shown.sort_values("start_local", ascending=False)
        ids = pd.to_numeric(frame["activity_id"], errors="coerce").tolist()
        frame["sport"] = frame["category"].map(lambda key: catalog.label(key) if key else None)
        frame = frame[[c for c in COLUMNS if c in frame.columns]].copy()
        frame["start_local"] = pd.to_datetime(frame["start_local"]).dt.strftime("%d.%m.%Y %H:%M")
        if "pace_min_km" in frame.columns:
            frame["pace_min_km"] = shell.pace_column(frame["pace_min_km"])
        for column in ("best_1k_s", "best_5k_s"):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce").map(
                    lambda v: shell.clock(v) if pd.notna(v) else None
                )
        frame = frame.rename(columns=shell.activity_labels())
        row = tables.pick(frame, key="activities_log_table", column_config=shell.activity_columns(),
                          max_height=520)
        if row is not None:
            _open(ids[row])


def _open(activity_id: float) -> None:
    """The route page for anything with a GPS track; a run without one (treadmill) opens its analysis."""
    if pd.isna(activity_id):
        return
    routes = shell.table("routes")
    tracked = not routes.empty and (pd.to_numeric(routes["activity_id"], errors="coerce") == activity_id).any()
    if tracked:
        routing.open_activity(int(activity_id))
        return
    runs = shell.table("run_sessions")
    if not runs.empty and (runs["activity_id"] == activity_id).any():
        routing.open_run(int(activity_id))
    else:
        st.toast(i18n.tr(pl="Ta aktywność nie ma śladu GPS.", en="This activity has no GPS track."))


def run_charts(shown: pd.DataFrame) -> None:
    """Pace over time and pace against heart rate, for the runs in ``shown``
    (a slice of ``activities``). Drawn on the running overview."""
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

    tr = i18n.tr
    pace = tr(pl="tempo /km", en="pace /km")
    left, right = bento.row(2, 2)
    with left, bento.tile(tr(pl="Tempo biegów w czasie", en="Run pace over time"), rows=2, key="pace_time",
                          caption=tr(pl="Czy biegasz szybciej niż kiedyś — i przy jakim tętnie.",
                                     en="Are you running faster than before — and at what heart rate."),
                          how=tr(pl="Wyżej = szybciej. Rozmiar punktu to dystans, kolor — tętno średnie.",
                                 en="Higher = faster. Point size is distance, colour — average heart rate.")) as t:
        t.chart(tz.scatter(runs, "start_local", "pace_min_km", color="avg_hr", color_kind="sequential",
                           color_title=tr(pl="tętno", en="HR"), size="distance_km",
                           hover=("name", "distance_km", "training_load"),
                           x_title="", y_title=pace, reverse_y=True, pace_y=True))
    with right, bento.tile(tr(pl="Tętno vs tempo", en="Heart rate vs pace"), rows=2, key="hr_pace", terms=["ef"],
                           caption=tr(pl="Ile tętna kosztuje cię prędkość.", en="How much heart rate speed costs you."),
                           how=tr(pl="Im bardziej chmura spłaszczona i przesunięta w lewo, tym taniej kupujesz tempo.",
                                  en="The flatter the cloud and the further left, the cheaper you buy pace.")) as t:
        t.chart(tz.scatter(runs, "avg_hr", "pace_min_km", size="distance_km", hover=("name", "distance_km"),
                           x_title=tr(pl="tętno średnie (bpm)", en="average HR (bpm)"), y_title=pace,
                           reverse_y=True, pace_y=True))
