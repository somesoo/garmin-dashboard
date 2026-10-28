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

WINDOWS = {"7d": 7, "30d": 30, "90d": 90}


def render() -> None:
    frame = rc.guard()
    if frame is None:
        st.title(i18n.page("bieganie"))
        return
    end = frame["day"].max()
    count, first, ago = len(frame), frame["day"].min(), (pd.Timestamp(dt.date.today()) - end).days
    runs = i18n.plural(count, pl=("bieg", "biegi", "biegów"), en=("run", "runs"))
    bento.header(
        i18n.page("bieganie"),
        i18n.tr(pl=f"{count} {runs} od {first:%d.%m.%Y}; spacery i nagrania < 1 km albo wolniejsze niż 12 min/km "
                   f"pominięte. Ostatni bieg: {end:%d.%m.%Y} ({ago} dni temu).",
                en=f"{count} {runs} since {first:%d.%m.%Y}; walks and recordings < 1 km or slower than 12 min/km "
                   f"left out. Last run: {end:%d.%m.%Y} ({ago} days ago)."),
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
    with right, bento.tile(i18n.tr(pl="Ostatnie treningi", en="Recent sessions"), rows=2, key="recent_runs",
                           terms=["run_kind", "training_load"],
                           caption=i18n.tr(pl="Kliknij wiersz, żeby otworzyć szczegóły treningu.",
                                           en="Click a row to open the session details.")):
        recent = frame.sort_values("start_local").tail(bento.table_rows(2))
        rc.pickable_runs(recent, key="overview_runs", height=bento.table_height(len(recent)), hint=False)


def _volume_strip(frame: pd.DataFrame, end: pd.Timestamp) -> None:
    tr = i18n.tr
    choice = st.segmented_control(tr(pl="Okres", en="Period"), list(WINDOWS), default="30d", key="overview_window",
                                  format_func=lambda k: tr(pl=f"{WINDOWS[k]} dni", en=f"{WINDOWS[k]} days"),
                                  label_visibility="collapsed",
                                  help=tr(pl="Zmiany pod liczbami: względem poprzedniego okresu tej samej długości.",
                                          en="Changes under the numbers: against the previous period of the same "
                                             "length."))
    days = WINDOWS.get(choice or "30d", 30)
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
    average = now["avg_km"] or 0
    bento.stat(columns[0], tr(pl="Kilometry", en="Kilometres"), f"{now['km']:.0f} km", key="run_km",
               delta=delta("km", " km", 0),
               note=tr(pl=f"śr. {average:.1f} km na bieg", en=f"avg {average:.1f} km per run"))
    bento.stat(columns[1], tr(pl="Biegi", en="Runs"), f"{now['runs']}", key="run_count", delta=delta("runs", "", 0),
               note=tr(pl=f"{now['hours']:.1f} h łącznie", en=f"{now['hours']:.1f} h in total"))
    bento.stat(columns[2], tr(pl="Tempo średnie", en="Average pace"), units.fmt_pace(now["pace"]), key="run_pace",
               delta=pace_delta, delta_color="inverse",
               note=tr(pl="czas łączny / dystans łączny", en="total time / total distance"))
    bento.stat(columns[3], tr(pl="Najdłuższy bieg", en="Longest run"),
               f"{longest['distance_km']:.1f} km" if longest is not None else "—", key="run_longest",
               note=f"{longest['start_local']:%d.%m} · {units.fmt_pace(longest['pace_min_km'])}"
               if longest is not None else None)


def _observations(frame: pd.DataFrame) -> None:
    notes = coach.observations(frame, rc.history(), dt.date.today())
    with bento.tile(i18n.tr(pl="Co mówią dane", en="What the data says"), key="observations",
                    caption=i18n.tr(pl="Zdania liczone z liczb na tej stronie.",
                                    en="Sentences computed from the numbers on this page.")) as t:
        if not notes:
            st.caption(i18n.tr(pl="Za mało biegów na wnioski.", en="Too few runs for conclusions."))
            return
        bento.bullets(notes[:4])


def _forecast_strip() -> None:
    result = rc.current_forecast()
    with bento.tile(i18n.page("prognoza"), key="forecast", terms=["realistic", "interval80", "confidence"],
                    caption=i18n.tr(pl="Realistycznie przy obecnym przygotowaniu; pod spodem przedział 80%.",
                                    en="Realistic at your current preparation; the 80% range underneath.")) as t:
        with t.header:
            if st.button("", icon=":material/arrow_forward:", type="tertiary", key="overview_to_forecast",
                         help=i18n.page("prognoza")):
                routing.goto("prognoza")
        rc.forecast_tiles(result, compact=True)


def _weekly(frame: pd.DataFrame) -> None:
    tr = i18n.tr
    weeks = shell.clip(sessions.weekly(frame), "week")
    with bento.tile(
        tr(pl="Kilometry tygodniowo", en="Weekly kilometres"), rows=2, key="weekly_km", terms=["quality_sessions"],
        caption=tr(pl="Ile biegasz i ile z tego to mocne kilometry.",
                   en="How much you run and how much of it is hard kilometres."),
        how=tr(pl="Niebieskie: biegi spokojne, regeneracyjne i długie; pomarańczowe: tempo, próg, interwały i "
                  "starty. Tydzień bez słupka to tydzień bez biegania.",
               en="Blue: easy, recovery and long runs; orange: tempo, threshold, intervals and races. A week "
                  "without a bar is a week without running."),
    ) as t:
        if weeks.empty:
            st.caption(tr(pl="Brak biegów w wybranym zakresie.", en="No runs in the selected range."))
            return
        colors = tz.intensity_colors()
        t.chart(
            tz.stacked(weeks, "week", ["easy_km", "hard_km"],
                       {"easy_km": tr(pl="spokojnie", en="easy"), "hard_km": tr(pl="mocno", en="hard")},
                       y_title="km", colors={"easy_km": colors["easy"], "hard_km": colors["hard"]}, area=False),
            table=weeks[["iso_week", "km", "runs", "hard", "long_km", "easy_km_pct", "hours"]]
            .sort_values("iso_week", ascending=False)
            .rename(columns={"iso_week": tr(pl="tydzień", en="week"), "runs": tr(pl="biegi", en="runs"),
                             "hard": tr(pl="mocne", en="hard"), "long_km": tr(pl="najdłuższy", en="longest"),
                             "easy_km_pct": tr(pl="% spokojnie", en="% easy"), "hours": "h"}),
            key="overview_weekly",
        )


def _pace_by_kind(frame: pd.DataFrame) -> None:
    view = shell.clip(frame)
    tr = i18n.tr
    with bento.tile(
        tr(pl="Tempo według typu treningu", en="Pace by session type"), key="pace_kind", terms=["run_kind"],
        caption=tr(pl="Spokojne powinny być wyraźnie wolniejsze od tempa i progu.",
                   en="Easy runs should be clearly slower than tempo and threshold."),
        how=tr(pl="Tempo grupy to czas łączny przez dystans łączny. Typ jest nadany regułami (struktura workoutu, "
                  "tętno względem HRmax, tempo względem VDOT); powód etykiety na stronie Trening.",
               en="A group's pace is total time over total distance. The type is assigned by rules (workout "
                  "structure, heart rate against HRmax, pace against VDOT); the label's reason is on the "
                  "Workout page."),
    ):
        if view.empty:
            st.caption(tr(pl="Brak biegów w wybranym zakresie.", en="No runs in the selected range."))
            return
        grouped = view.groupby("kind").agg(km=("distance_km", "sum"), minutes=("duration_min", "sum"),
                                           n=("activity_id", "count"))
        grouped["pace"] = grouped["minutes"] / grouped["km"]
        grouped = grouped.reindex([k for k in rc.KIND_ORDER if k in grouped.index])
        columns = st.columns(max(len(grouped), 4))
        for column, (kind, row) in zip(columns, grouped.iterrows()):
            column.metric(rc.kind_label(kind), units.fmt_pace(row["pace"], False),
                          help=f"{rc.kind_label(kind)}: {int(row['n'])} "
                               f"{i18n.plural(row['n'], pl=('bieg', 'biegi', 'biegów'), en=('run', 'runs'))}, "
                               f"{row['km']:.0f} km")


def _records() -> None:
    table = sessions.records(rc.efforts())
    tr = i18n.tr
    missing = ", ".join(rc.effort_label(k) for k in ("5k", "10k", "hm", "m")
                        if table.empty or k not in set(table["effort"]))
    with bento.tile(
        tr(pl="Rekordy życiowe", en="Personal bests"), key="records",
        caption=tr(pl=f"brak: {missing} — żaden bieg nie był tak długi",
                   en=f"missing: {missing} — no run was that long") if missing else
        tr(pl="Z biegu o tej długości albo z odcinka dłuższego biegu.",
           en="From a run of that length or from a stretch of a longer run."),
        how=tr(pl="Najszybszy czas na dystansie w całej historii. Odcinek treningowy nie jest wynikiem z zawodów; "
                  "źródło jest w podpowiedzi przy liczbie.",
               en="The fastest time over the distance in all of history. A training stretch is not a race "
                  "result; the source is in the tooltip on the number."),
    ):
        if table.empty:
            st.caption(tr(pl="Brak biegów o długości 5 km lub dłuższych.", en="No runs of 5 km or longer."))
            return
        columns = st.columns(4)
        for column, row in zip(columns, table.itertuples(index=False)):
            column.metric(rc.effort_label(row.effort), units.fmt_time(row.seconds),
                          help=f"{pd.Timestamp(row.day):%d.%m.%Y} · {row.source}; {units.fmt_pace(row.pace_min_km)}")
