"""Running load: weekly volume, intensity balance, ramp and breaks."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import routing
import shell
import theme as tz
from running import sessions
from views import run_common as rc


def render() -> None:
    bento.header(
        "Obciążenie biegowe",
        "Wskaźniki pomagają zdecydować, czy dołożyć, czy odpuścić — nie diagnozują przetrenowania ani kontuzji. "
        "Ból, który zmienia sposób biegania, jest ważniejszy niż każdy wykres tutaj.",
    )
    frame = rc.guard()
    if frame is None:
        return
    weeks = shell.clip(sessions.weekly(frame), "week")
    if weeks.empty:
        st.caption("Brak biegów w wybranym zakresie.")
        return

    edge = shell.cutoff()
    info = sessions.gaps(frame, edge if edge is not None else frame["day"].min(), frame["day"].max())
    columns = bento.row(1, 1, 1, 1)
    bento.stat(columns[0], "Dni z biegiem", f"{info['run_days']}", key="run_days", note="w wybranym zakresie")
    bento.stat(columns[1], "Dni bez biegu", f"{info['rest_days']}", key="rest_days")
    bento.stat(columns[2], "Najdłuższa przerwa", f"{info['longest_break']} dni", key="longest_break")
    bento.stat(columns[3], "Od ostatniego biegu", f"{info['days_since_last']} dni", key="since_last")

    left, right = bento.row(2, 2)
    with left:
        _volume(weeks)
    with right:
        _ratio(frame)
        _intensity(weeks)

    left, right = bento.row(2, 2)
    with left:
        _recovery()
    with right:
        _breaks(frame, edge)


def _volume(weeks: pd.DataFrame) -> None:
    change = weeks["km"].pct_change().replace([float("inf")], pd.NA)
    jumps = weeks[(change > 0.3) & (weeks["km"] >= 15)]
    with bento.tile(
        "Kilometry i najdłuższy bieg", rows=2, key="load_volume",
        caption=("skoki > 30%: " + ", ".join(jumps["iso_week"].tail(4))) if not jumps.empty else
        "Długi bieg powinien rosnąć razem z objętością.",
        how="Dwa panele na wspólnej osi czasu: objętość tygodnia (linia: średnia 4 tyg.) i najdłuższy bieg. "
            "Skok samego długiego biegu przy płaskiej objętości to typowe ryzyko. Pojedynczy skok objętości po "
            "lżejszym tygodniu jest normalny; seria skoków — nie.",
    ) as t:
        view = weeks.assign(km_4w=weeks["km"].rolling(4, min_periods=2).mean().round(1))
        figure = tz.stacked_panels(
            view, "week",
            [
                {"title": "km / tydzień", "series": {"km": "km"}, "kind": "bar", "height": 1.3},
                {"title": "najdłuższy bieg (km)", "series": {"najdłuższy": "long_km"}, "kind": "bar", "height": 0.8},
            ],
            height=400,
        )
        if figure is not None:
            # The 4-week mean reads better as a line over the bars than as a second bar.
            line = view.dropna(subset=["km_4w"])
            figure.add_scatter(x=line["week"], y=line["km_4w"], mode="lines", name="średnia 4 tyg.",
                               line=dict(width=2.2, color=tz.tokens()["series"][1]), showlegend=False,
                               hovertemplate="%{y:.1f} km<extra>średnia 4 tyg.</extra>", row=1, col=1)
        t.chart(figure, table=view[["iso_week", "km", "km_4w", "long_km", "runs", "hours"]]
                .sort_values("iso_week", ascending=False))


def _intensity(weeks: pd.DataFrame) -> None:
    recent = weeks.tail(4)
    with bento.tile(
        "Balans: % kilometrów spokojnie", key="load_intensity", terms=["quality_sessions", "run_kind"],
        caption=f"pas 75–80% · mocnych sesji: <b>{recent['hard'].mean():.1f}</b>/tydz. (4 tyg.)",
        how="Udział spokojnych kilometrów w tygodniu. Strefy tętna (wszystkie sporty) są na stronie Fizjologia.",
    ) as t:
        figure = tz.timeseries(weeks, "week", {"% spokojnie": "easy_km_pct"}, markers=True, end_labels=True)
        if figure is not None:
            tz.band(figure, 75, 80)
        t.chart(figure, table=weeks[["iso_week", "hard", "easy_km_pct"]].sort_values("iso_week", ascending=False))


def _ratio(frame: pd.DataFrame) -> None:
    ratio = shell.clip(sessions.km_ratio(frame))
    with bento.tile(
        "Tempo przyrostu (km 7 d / 28 d)", key="load_ratio", terms=["run_ratio"],
        caption="Pas 0,8–1,3 to stopniowy przyrost.",
        how="Przy średniej z 28 dni poniżej 5 km/tydz. iloraz nie jest liczony — po przerwie każdy bieg dawałby "
            "„skok”. Obciążenie wszystkich sportów jest na stronie Forma.",
    ) as t:
        with t.header:
            if st.button("", icon=":material/arrow_forward:", type="tertiary", key="load_to_form",
                         help="Obciążenie wszystkich sportów (Forma)"):
                routing.goto("forma")
        figure = tz.timeseries(ratio, "day", {"iloraz": "ratio"}, y_title="iloraz", end_labels=True, decimals=2)
        if figure is not None:
            tz.band(figure, 0.8, 1.3)
            tz.threshold(figure, 1.5, label="1.5")
        t.chart(figure, table=ratio[["day", "acute_km", "chronic_km", "ratio"]].dropna().tail(30))


def _breaks(frame: pd.DataFrame, edge) -> None:
    days = pd.Series(sorted(frame["day"].unique()))
    gaps = days.diff().dt.days.dropna()
    breaks = pd.DataFrame({"od": days.shift(1), "do": days, "dni": days.diff().dt.days})
    breaks = breaks[(breaks["dni"] >= 10)]
    if edge is not None:
        breaks = breaks[breaks["do"] >= edge]
    with bento.tile(
        "Przerwy ≥ 10 dni", rows=2, key="breaks",
        caption=f"Typowy odstęp między biegami: {gaps.median():.0f} dni." if len(gaps) else None,
        how="Po przerwie ≥ 10 dni dobrze wrócić od ~70% wcześniejszej objętości.",
    ) as t:
        if breaks.empty:
            st.caption("Bez przerw ≥ 10 dni w tym zakresie.")
            return
        t.table(
            pd.DataFrame({
                "ostatni bieg przed": pd.to_datetime(breaks["od"]).dt.strftime("%d.%m.%Y"),
                "pierwszy po": pd.to_datetime(breaks["do"]).dt.strftime("%d.%m.%Y"),
                "dni przerwy": (breaks["dni"] - 1).astype(int),
            }).sort_values("pierwszy po", ascending=False),
        )


def _recovery() -> None:
    daily = shell.clip(shell.daily())
    columns = [c for c in ("readiness", "hrv_deviation", "sleep_h") if c in daily.columns]
    with bento.tile(
        "Regeneracja w tle", rows=2, key="load_recovery", terms=["readiness", "hrv", "deviation"],
        caption="Obciążenie czytane razem z odpowiedzią organizmu.",
        how="Gotowość Garmina i HRV względem własnej średniej 7 d. Pełna analiza: strona Regeneracja.",
    ) as t:
        if daily.empty or not columns or daily[columns].notna().sum().max() < 7:
            st.caption("Brak danych o regeneracji (gotowość, HRV, sen) w tym zakresie.")
            return
        t.chart(tz.stacked_panels(
            daily, "day",
            [
                {"title": "gotowość treningowa", "series": {"gotowość": "readiness"}, "kind": "line"},
                {"title": "HRV — odchylenie od średniej 7 d", "series": {"HRV Δ": "hrv_deviation"}, "kind": "bar"},
            ],
            height=360,
        ), table=daily[["day", "readiness", "hrv_deviation"]].tail(40))
