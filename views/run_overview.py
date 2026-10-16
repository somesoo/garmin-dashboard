"""Running overview: volume, regularity, pace by session type, records, recent runs."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import routing
import shell
import theme as tz
from running import coach, sessions, units
from views import run_common as rc

WINDOWS = {"7 dni": 7, "30 dni": 30, "90 dni": 90}


def render() -> None:
    st.title("Bieganie")
    frame = rc.guard()
    if frame is None:
        return
    end = frame["day"].max()
    st.caption(
        f"{len(frame)} biegów od {frame['day'].min():%d.%m.%Y}. Spacery i nagrania krótsze niż 1 km "
        "albo wolniejsze niż 12 min/km są pominięte. Ostatni bieg: "
        f"{end:%d.%m.%Y} ({(pd.Timestamp(dt.date.today()) - end).days} dni temu)."
    )

    notes = coach.observations(frame, rc.history(), dt.date.today())
    if notes:
        shell.lead("Co mówią dane", "Zdania generowane z liczb poniżej — każde da się sprawdzić na wykresie.")
        st.markdown("\n".join(f"- {note}" for note in notes))

    _volume_strip(frame, end)
    _forecast_strip()
    _weekly(frame)
    _pace_by_kind(frame)
    _records()

    shell.lead("Ostatnie treningi", "Typ treningu jest nadany regułami — szczegóły i powód etykiety po kliknięciu.",
               terms=["run_kind", "training_load"])
    rc.pickable_runs(frame.tail(15), key="overview_runs")


def _volume_strip(frame: pd.DataFrame, end: pd.Timestamp) -> None:
    shell.lead(
        "Objętość",
        "Zmiana: względem poprzedniego okresu tej samej długości. Tempo średnie to czas łączny przez "
        "dystans łączny — nie średnia z temp, w której 3-km trucht waży tyle co 20 km.",
    )
    choice = st.segmented_control("Okres", list(WINDOWS), default="30 dni", key="overview_window")
    days = WINDOWS[choice or "30 dni"]
    now = sessions.window_summary(frame, end, days)
    before = sessions.window_summary(frame, end - pd.Timedelta(days=days), days)

    def delta(field: str, unit: str = "", decimals: int = 1) -> str | None:
        a, b = now.get(field), before.get(field)
        if a is None or b is None:
            return None
        return f"{a - b:+.{decimals}f}{unit}"

    columns = st.columns(5)
    columns[0].metric("Kilometry", f"{now['km']:.0f} km", delta("km", " km", 0))
    columns[1].metric("Biegi", now["runs"], delta("runs", "", 0))
    columns[2].metric("Czas", f"{now['hours']:.1f} h", delta("hours", " h"))
    columns[3].metric("Śr. dystans", f"{now['avg_km'] or 0:.1f} km", delta("avg_km", " km"))
    pace_delta = None
    if now["pace"] and before["pace"]:
        seconds = (now["pace"] - before["pace"]) * 60
        pace_delta = ("-" if seconds < 0 else "+") + units.fmt_time(abs(seconds))
    columns[4].metric("Tempo średnie", units.fmt_pace(now["pace"]), pace_delta, delta_color="inverse")
    if now["longest_id"]:
        longest = frame[frame["activity_id"] == now["longest_id"]].iloc[0]
        st.caption(
            f"Najdłuższy bieg w okresie: **{longest['distance_km']:.1f} km** "
            f"({longest['start_local']:%d.%m}, {units.fmt_pace(longest['pace_min_km'])}). "
            "Tempo średnie zależy od tego, ile było mocnych sesji — postęp widać lepiej na stronie *Prognoza*."
        )


def _forecast_strip() -> None:
    result = rc.current_forecast()
    shell.lead(
        "Prognoza wyników",
        "Wynik realistyczny przy obecnym przygotowaniu; pod spodem przedział 80%. Metoda, dane wejściowe "
        "i założenia — na stronie Prognoza.",
        terms=["realistic", "interval80", "confidence"],
    )
    if result.get("status") != "ok":
        st.caption(result.get("reason", "Brak prognozy."))
        return
    columns = st.columns(4)
    for column, (key, item) in zip(columns, result["distances"].items()):
        column.metric(units.RACE_LABELS[key], units.fmt_time(item.realistic_s))
        column.caption(
            f"{units.fmt_time(item.low_s)}–{units.fmt_time(item.high_s)} · {units.fmt_pace(item.pace)}  \n"
            f"pewność {item.confidence} {rc.CONFIDENCE_ICON[item.confidence]}"
        )
    if st.button("Szczegóły prognozy →", key="overview_to_forecast"):
        routing.goto("prognoza")


def _weekly(frame: pd.DataFrame) -> None:
    weeks = sessions.weekly(frame)
    weeks = shell.clip(weeks, "week")
    shell.lead(
        "Kilometry tygodniowo",
        "Ile biegasz i ile z tego to mocne kilometry.",
        terms=["quality_sessions"],
        how="Niebieskie: biegi spokojne, regeneracyjne i długie; pomarańczowe: tempo, próg, interwały i starty. "
            "Tydzień bez słupka to tydzień bez biegania.",
    )
    if weeks.empty:
        st.caption("Brak biegów w wybranym zakresie.")
        return
    colors = tz.intensity_colors()
    tz.show(
        tz.stacked(
            weeks, "week", ["easy_km", "hard_km"], {"easy_km": "spokojnie", "hard_km": "mocno"},
            y_title="km", height=300, colors={"easy_km": colors["easy"], "hard_km": colors["hard"]},
            area=False,
        ),
        table=weeks[["iso_week", "km", "runs", "hard", "long_km", "easy_km_pct", "hours"]]
        .sort_values("iso_week", ascending=False)
        .rename(columns={"iso_week": "tydzień", "runs": "biegi", "hard": "mocne", "long_km": "najdłuższy",
                         "easy_km_pct": "% spokojnie", "hours": "h"}),
        key="overview_weekly",
    )


def _pace_by_kind(frame: pd.DataFrame) -> None:
    view = shell.clip(frame)
    shell.lead(
        "Tempo według typu treningu",
        "Spokojne biegi powinny być wyraźnie wolniejsze od tempa i progu — jeśli różnica jest mała, "
        "spokojne dni są za szybkie albo mocne za wolne.",
        terms=["run_kind"],
        how="Tempo grupy to czas łączny przez dystans łączny.",
    )
    if view.empty:
        st.caption("Brak biegów w wybranym zakresie.")
        return
    grouped = view.groupby("kind").agg(km=("distance_km", "sum"), minutes=("duration_min", "sum"),
                                       n=("activity_id", "count"))
    grouped["pace"] = grouped["minutes"] / grouped["km"]
    grouped = grouped.reindex([k for k in rc.KIND_ORDER if k in grouped.index])
    table = pd.DataFrame(
        {
            "typ": [rc.kind_label(k) for k in grouped.index],
            "biegów": grouped["n"].astype(int).values,
            "km": grouped["km"].round(1).values,
            "tempo": grouped["pace"].map(lambda v: units.fmt_pace(v, False)).values,
        }
    )
    columns = st.columns(len(table)) if len(table) <= 7 else st.columns(7)
    for column, row in zip(columns, table.itertuples(index=False)):
        column.metric(row.typ, row.tempo, help=f"{row.biegów} biegów, {row.km} km")
    st.caption("Typ treningu jest nadany regułami (struktura workoutu, tętno względem HRmax, tempo względem "
               "aktualnego VDOT). Pewność i powód etykiety: strona *Trening*.")


def _records() -> None:
    table = sessions.records(rc.efforts())
    shell.lead(
        "Rekordy życiowe",
        "Najszybszy czas na dystansie w całej historii — z biegu o tej długości albo z odcinka dłuższego "
        "biegu. Odcinek treningowy nie jest wynikiem z zawodów; źródło jest podane przy każdym.",
    )
    if table.empty:
        st.caption("Brak biegów o długości 5 km lub dłuższych.")
        return
    columns = st.columns(len(table))
    for column, row in zip(columns, table.itertuples(index=False)):
        column.metric(
            sessions.EFFORT_LABELS[row.effort], units.fmt_time(row.seconds),
            help=f"{row.source}; {units.fmt_pace(row.pace_min_km)}",
        )
        column.caption(f"{pd.Timestamp(row.day):%d.%m.%Y}  \n{row.source}")
    missing = [sessions.EFFORT_LABELS[k] for k in ("5k", "10k", "hm", "m") if k not in set(table["effort"])]
    if missing:
        st.caption("Brak rekordu: " + ", ".join(missing) + " — żaden bieg nie był tak długi.")
