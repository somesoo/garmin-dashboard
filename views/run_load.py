"""Running load: weekly volume, intensity balance, ramp and breaks."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import routing
import shell
import theme as tz
from running import sessions
from views import run_common as rc


def render() -> None:
    st.title("Obciążenie biegowe")
    st.caption(
        "Wskaźniki obciążenia pomagają zdecydować, czy dołożyć, czy odpuścić — nie diagnozują przetrenowania "
        "ani kontuzji. Ból, który zmienia sposób biegania, jest ważniejszy niż każdy wykres na tej stronie."
    )
    frame = rc.guard()
    if frame is None:
        return
    weeks = shell.clip(sessions.weekly(frame), "week")
    if weeks.empty:
        st.caption("Brak biegów w wybranym zakresie.")
        return

    _volume(weeks)
    _intensity(weeks)
    _ratio(frame)
    _breaks(frame)
    _recovery()


def _volume(weeks: pd.DataFrame) -> None:
    shell.lead(
        "Kilometry i najdłuższy bieg",
        "Długie wybieganie powinno rosnąć razem z objętością — skok samego długiego biegu przy płaskiej "
        "objętości to typowe ryzyko.",
        how="Dwa panele na wspólnej osi czasu: objętość tygodnia i najdłuższy bieg w tygodniu.",
    )
    view = weeks.assign(km_4w=weeks["km"].rolling(4, min_periods=2).mean().round(1))
    figure = tz.stacked_panels(
        view, "week",
        [
            {"title": "km / tydzień (linia: średnia 4 tyg.)", "series": {"km": "km"}, "kind": "bar", "height": 1.3},
            {"title": "najdłuższy bieg (km)", "series": {"najdłuższy": "long_km"}, "kind": "bar", "height": 0.8},
        ],
        height=440,
    )
    if figure is not None:
        # The 4-week mean reads better as a line over the bars than as a second bar.
        line = view.dropna(subset=["km_4w"])
        figure.add_scatter(x=line["week"], y=line["km_4w"], mode="lines", name="średnia 4 tyg.",
                           line=dict(width=2.2, color=tz.tokens()["series"][1]), showlegend=False,
                           hovertemplate="%{y:.1f} km<extra>średnia 4 tyg.</extra>", row=1, col=1)
    tz.show(figure, table=view[["iso_week", "km", "km_4w", "long_km", "runs", "hours"]]
            .sort_values("iso_week", ascending=False), key="load_volume")
    change = weeks["km"].pct_change().replace([float("inf")], pd.NA)
    jumps = weeks[(change > 0.3) & (weeks["km"] >= 15)]
    if not jumps.empty:
        st.caption(
            f"Tygodnie z przyrostem > 30% wobec poprzedniego (przy ≥ 15 km): "
            + ", ".join(jumps["iso_week"].tail(6)) + ". Pojedynczy skok po lżejszym tygodniu jest normalny; "
            "seria skoków — nie."
        )


def _intensity(weeks: pd.DataFrame) -> None:
    shell.lead(
        "Mocne sesje i balans",
        "Czy proporcja mocnego i spokojnego biegania jest zdrowa.",
        terms=["quality_sessions", "run_kind"],
    )
    figure = tz.stacked_panels(
        weeks, "week",
        [
            {"title": "mocne sesje / tydzień", "series": {"mocne": "hard"}, "kind": "bar", "height": 0.8},
            {"title": "% kilometrów spokojnie", "series": {"% spokojnie": "easy_km_pct"}, "kind": "line"},
        ],
        height=360,
    )
    if figure is not None:
        tz.band(figure, 75, 80, row=2)
    tz.show(figure, key="load_intensity")
    st.caption("Strefy tętna tydzień po tygodniu (wszystkie sporty) są na stronie *Fizjologia* → "
               "„Rozkład intensywności”.")


def _ratio(frame: pd.DataFrame) -> None:
    ratio = shell.clip(sessions.km_ratio(frame))
    shell.lead(
        "Tempo przyrostu (km 7 d / średnia z 28 d)",
        "Czy kilometrów nie przybywa szybciej, niż ścięgna zdążą się przyzwyczaić. Obciążenie wszystkich "
        "sportów jest na stronie Forma.",
        terms=["run_ratio"],
        how="Szary pas 0,8–1,3 to zakres stopniowego przyrostu.",
    )
    figure = tz.timeseries(ratio, "day", {"iloraz": "ratio"}, y_title="iloraz", end_labels=True, decimals=2)
    if figure is not None:
        tz.band(figure, 0.8, 1.3)
        tz.threshold(figure, 1.5, label="1.5")
    tz.show(figure, table=ratio[["day", "acute_km", "chronic_km", "ratio"]].dropna().tail(30),
            note="Przy średniej z 28 dni poniżej 5 km/tydz. iloraz nie jest liczony — po przerwie każdy bieg "
            "dawałby „skok”.", key="load_ratio")
    if st.button("Obciążenie wszystkich sportów (Forma) →", key="load_to_form"):
        routing.goto("forma")


def _breaks(frame: pd.DataFrame) -> None:
    edge = shell.cutoff()
    end = frame["day"].max()
    start = edge if edge is not None else frame["day"].min()
    info = sessions.gaps(frame, start, end)
    shell.lead("Dni odpoczynku i przerwy", "W wybranym zakresie czasu.")
    columns = st.columns(4)
    columns[0].metric("Dni z biegiem", info["run_days"])
    columns[1].metric("Dni bez biegu", info["rest_days"])
    columns[2].metric("Najdłuższa przerwa", f"{info['longest_break']} dni")
    columns[3].metric("Od ostatniego biegu", f"{info['days_since_last']} dni")
    days = pd.Series(sorted(frame["day"].unique()))
    gaps = days.diff().dt.days.dropna()
    breaks = pd.DataFrame({"od": days.shift(1), "do": days, "dni": days.diff().dt.days})
    breaks = breaks[(breaks["dni"] >= 10)]
    if edge is not None:
        breaks = breaks[breaks["do"] >= edge]
    if not breaks.empty:
        st.dataframe(
            pd.DataFrame({
                "ostatni bieg przed": pd.to_datetime(breaks["od"]).dt.strftime("%d.%m.%Y"),
                "pierwszy po": pd.to_datetime(breaks["do"]).dt.strftime("%d.%m.%Y"),
                "dni przerwy": (breaks["dni"] - 1).astype(int),
            }).sort_values("pierwszy po", ascending=False),
            hide_index=True, width="stretch",
        )
        st.caption("Przerwy ≥ 10 dni. Po takiej przerwie dobrze wrócić od ~70% wcześniejszej objętości.")
    elif len(gaps):
        st.caption(f"Bez przerw ≥ 10 dni. Typowy odstęp między biegami: {gaps.median():.0f} dni.")


def _recovery() -> None:
    daily = shell.clip(shell.daily())
    columns = [c for c in ("readiness", "hrv_deviation", "sleep_h") if c in daily.columns]
    if daily.empty or not columns or daily[columns].notna().sum().max() < 7:
        st.caption("Brak danych o regeneracji (gotowość, HRV, sen) w tym zakresie — sekcja pominięta.")
        return
    shell.lead(
        "Regeneracja w tle",
        "Gotowość Garmina i HRV względem własnej średniej, żeby obciążenie czytać razem z odpowiedzią "
        "organizmu. Pełna analiza: strona Regeneracja.",
        terms=["readiness", "hrv", "deviation"],
    )
    figure = tz.stacked_panels(
        daily, "day",
        [
            {"title": "gotowość treningowa", "series": {"gotowość": "readiness"}, "kind": "line"},
            {"title": "HRV — odchylenie od średniej 7 d", "series": {"HRV Δ": "hrv_deviation"}, "kind": "bar"},
        ],
        height=360,
    )
    tz.show(figure, key="load_recovery")
