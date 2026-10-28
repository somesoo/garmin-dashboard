"""Running overview: volume, regularity, pace by session type, records, recent runs."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import shell
import theme as tz
from running import coach, sessions, units
from views import run_common as rc

WINDOWS = {"7 dni": 7, "30 dni": 30, "90 dni": 90}


def render() -> None:
    frame = rc.guard()
    if frame is None:
        st.title(i18n.page("bieganie"))
        return
    end = frame["day"].max()
    bento.header(
        i18n.page("bieganie"),
        f"{len(frame)} biegów od {frame['day'].min():%d.%m.%Y}; spacery i nagrania < 1 km albo wolniejsze niż "
        f"12 min/km pominięte. Ostatni bieg: {end:%d.%m.%Y} ({(pd.Timestamp(dt.date.today()) - end).days} dni temu).",
    )
    _volume_strip(frame, end)

    left, right = bento.row(2, 2)
    with left:
        _weekly(frame)
    with right:
        _observations(frame)
        _forecast_strip()

    left, right = bento.row(2, 2)
    with left:
        _pace_by_kind(frame)
        _records()
    with right, bento.tile("Ostatnie treningi", rows=2, key="recent_runs", terms=["run_kind", "training_load"],
                           caption="Kliknij wiersz, żeby otworzyć szczegóły treningu."):
        recent = frame.sort_values("start_local").tail(bento.table_rows(2))
        rc.pickable_runs(recent, key="overview_runs", height=bento.table_height(len(recent)), hint=False)


def _volume_strip(frame: pd.DataFrame, end: pd.Timestamp) -> None:
    choice = st.segmented_control("Okres", list(WINDOWS), default="30 dni", key="overview_window",
                                  label_visibility="collapsed",
                                  help="Zmiany pod liczbami: względem poprzedniego okresu tej samej długości.")
    days = WINDOWS[choice or "30 dni"]
    now = sessions.window_summary(frame, end, days)
    before = sessions.window_summary(frame, end - pd.Timedelta(days=days), days)

    def delta(field: str, unit: str = "", decimals: int = 1) -> str | None:
        a, b = now.get(field), before.get(field)
        if a is None or b is None:
            return None
        return f"{a - b:+.{decimals}f}{unit}"

    pace_delta = None
    if now["pace"] and before["pace"]:
        seconds = (now["pace"] - before["pace"]) * 60
        pace_delta = ("-" if seconds < 0 else "+") + units.fmt_time(abs(seconds))
    longest = frame[frame["activity_id"] == now["longest_id"]].iloc[0] if now["longest_id"] else None
    columns = bento.row(1, 1, 1, 1)
    bento.stat(columns[0], "Kilometry", f"{now['km']:.0f} km", key="run_km", delta=delta("km", " km", 0),
               note=f"śr. {now['avg_km'] or 0:.1f} km na bieg")
    bento.stat(columns[1], "Biegi", f"{now['runs']}", key="run_count", delta=delta("runs", "", 0),
               note=f"{now['hours']:.1f} h łącznie")
    bento.stat(columns[2], "Tempo średnie", units.fmt_pace(now["pace"]), key="run_pace", delta=pace_delta,
               delta_color="inverse", note="czas łączny / dystans łączny")
    bento.stat(columns[3], "Najdłuższy bieg",
               f"{longest['distance_km']:.1f} km" if longest is not None else "—", key="run_longest",
               note=f"{longest['start_local']:%d.%m} · {units.fmt_pace(longest['pace_min_km'])}"
               if longest is not None else None)


def _observations(frame: pd.DataFrame) -> None:
    notes = coach.observations(frame, rc.history(), dt.date.today())
    with bento.tile("Co mówią dane", key="observations",
                    caption="Zdania liczone z liczb na tej stronie.") as t:
        if not notes:
            st.caption("Za mało biegów na wnioski.")
            return
        bento.bullets(notes[:4])


def _forecast_strip() -> None:
    result = rc.current_forecast()
    with bento.tile("Prognoza wyników", key="forecast", terms=["realistic", "interval80", "confidence"],
                    caption="Realistycznie przy obecnym przygotowaniu; pod spodem przedział 80%.") as t:
        with t.header:
            if st.button("", icon=":material/arrow_forward:", type="tertiary", key="overview_to_forecast",
                         help="Strona Prognoza"):
                routing.goto("prognoza")
        rc.forecast_tiles(result, compact=True)


def _weekly(frame: pd.DataFrame) -> None:
    weeks = shell.clip(sessions.weekly(frame), "week")
    with bento.tile(
        "Kilometry tygodniowo", rows=2, key="weekly_km", terms=["quality_sessions"],
        caption="Ile biegasz i ile z tego to mocne kilometry.",
        how="Niebieskie: biegi spokojne, regeneracyjne i długie; pomarańczowe: tempo, próg, interwały i starty. "
            "Tydzień bez słupka to tydzień bez biegania.",
    ) as t:
        if weeks.empty:
            st.caption("Brak biegów w wybranym zakresie.")
            return
        colors = tz.intensity_colors()
        t.chart(
            tz.stacked(weeks, "week", ["easy_km", "hard_km"], {"easy_km": "spokojnie", "hard_km": "mocno"},
                       y_title="km", colors={"easy_km": colors["easy"], "hard_km": colors["hard"]}, area=False),
            table=weeks[["iso_week", "km", "runs", "hard", "long_km", "easy_km_pct", "hours"]]
            .sort_values("iso_week", ascending=False)
            .rename(columns={"iso_week": "tydzień", "runs": "biegi", "hard": "mocne", "long_km": "najdłuższy",
                             "easy_km_pct": "% spokojnie", "hours": "h"}),
            key="overview_weekly",
        )


def _pace_by_kind(frame: pd.DataFrame) -> None:
    view = shell.clip(frame)
    with bento.tile(
        "Tempo według typu treningu", key="pace_kind", terms=["run_kind"],
        caption="Spokojne powinny być wyraźnie wolniejsze od tempa i progu.",
        how="Tempo grupy to czas łączny przez dystans łączny. Typ jest nadany regułami (struktura workoutu, "
            "tętno względem HRmax, tempo względem VDOT); powód etykiety na stronie Trening.",
    ):
        if view.empty:
            st.caption("Brak biegów w wybranym zakresie.")
            return
        grouped = view.groupby("kind").agg(km=("distance_km", "sum"), minutes=("duration_min", "sum"),
                                           n=("activity_id", "count"))
        grouped["pace"] = grouped["minutes"] / grouped["km"]
        grouped = grouped.reindex([k for k in rc.KIND_ORDER if k in grouped.index])
        columns = st.columns(max(len(grouped), 4))
        for column, (kind, row) in zip(columns, grouped.iterrows()):
            column.metric(rc.kind_label(kind), units.fmt_pace(row["pace"], False),
                          help=f"{rc.kind_label(kind)}: {int(row['n'])} biegów, {row['km']:.0f} km")


def _records() -> None:
    table = sessions.records(rc.efforts())
    missing = [sessions.EFFORT_LABELS[k] for k in ("5k", "10k", "hm", "m")
               if table.empty or k not in set(table["effort"])]
    with bento.tile(
        "Rekordy życiowe", key="records",
        caption=("brak: " + ", ".join(missing) + " — żaden bieg nie był tak długi") if missing else
        "Z biegu o tej długości albo z odcinka dłuższego biegu.",
        how="Najszybszy czas na dystansie w całej historii. Odcinek treningowy nie jest wynikiem z zawodów; "
            "źródło jest w podpowiedzi przy liczbie.",
    ):
        if table.empty:
            st.caption("Brak biegów o długości 5 km lub dłuższych.")
            return
        columns = st.columns(4)
        for column, row in zip(columns, table.itertuples(index=False)):
            column.metric(sessions.EFFORT_LABELS[row.effort], units.fmt_time(row.seconds),
                          help=f"{pd.Timestamp(row.day):%d.%m.%Y} · {row.source}; {units.fmt_pace(row.pace_min_km)}")
