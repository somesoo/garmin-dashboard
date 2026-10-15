"""Training load: the Banister chart, both ACWR formulations, Foster's strain."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import shell
import theme as tz


def render() -> None:
    pmc = shell.table("pmc")
    weekly = shell.table("load_weekly")
    models = shell.models()

    st.title("Forma")
    st.caption(
        "Model Banistera: każdy trening buduje wolno narastającą sprawność (CTL, "
        "stała 42 dni) i szybko narastające zmęczenie (ATL, 7 dni). Forma to ich "
        "różnica z dnia poprzedniego — dzisiejsza sesja nie jest jeszcze wchłonięta."
    )

    view = shell.clip(pmc)
    if view.empty:
        shell.missing("pmc", "Uruchom `analytics.py`.")
        return

    ready = pmc.dropna(subset=["ctl"])
    current = ready.tail(1).iloc[0]
    week_ago = ready.tail(8).head(1).iloc[0] if len(ready) >= 8 else None
    shell.metrics(
        current,
        week_ago,
        [
            ("ctl", "CTL — sprawność", ""),
            ("atl", "ATL — zmęczenie", "", "off"),
            ("tsb", "TSB — forma", ""),
            ("ramp_7d", "Przyrost CTL / 7 d", "", "off"),
            ("acwr_ewma", "ACWR", "", "off"),
        ],
    )
    zone = current.get("form_zone")
    if isinstance(zone, str) and zone not in ("nan", "None"):
        st.caption(f"Strefa formy: **{zone}** (TSB = {current.get('tsb')})")

    shell.lead(
        "Performance Management Chart",
        "Dzienny load jest osobnym panelem, nie drugą osią: wspólna skala dla "
        "dwóch różnych jednostek zmyśla korelacje, których w danych nie ma.",
    )
    figure = tz.stacked_panels(
        view,
        "day",
        [
            {
                "title": "CTL / ATL — jednostki obciążenia",
                "series": {"CTL (sprawność)": "ctl", "ATL (zmęczenie)": "atl"},
                "kind": "line",
                "height": 1.5,
            },
            {"title": "TSB — forma", "series": {"TSB": "tsb"}, "kind": "line", "height": 1.0},
            {"title": "Load dzienny", "series": {"load": "load_day"}, "kind": "bar", "height": 0.8},
        ],
        height=560,
    )
    if figure is not None:
        tz.band(figure, -10, 5, row=2)
    tz.show(figure, table=view[["day", "ctl", "atl", "tsb", "ramp_7d", "load_day"]].tail(40))

    shell.lead(
        "ACWR: dwa wzory, jedna rzeczywistość",
        "Kroczący (Gabbett) to suma 7 dni przez średnią z 28; wykładniczy (Williams) "
        "używa wag CTL/ATL. Po przerwie pierwszy skacze, drugi płynie — tygodnie, "
        "w których się rozjeżdżają, to te, gdzie wniosek „przetrenowanie” zależy "
        "wyłącznie od wyboru wzoru. Pas 0.8–1.3 to tzw. sweet spot.",
    )
    figure = tz.timeseries(
        view, "day", {"kroczący": "acwr_rolling", "wykładniczy": "acwr_ewma"}, y_title="iloraz"
    )
    if figure is not None:
        tz.band(figure, 0.8, 1.3)
        tz.threshold(figure, 1.5, label="1.5 — podwyższone ryzyko")
    tz.show(figure)

    shell.lead(
        "Tempo narastania sprawności",
        "Zmiana CTL w ciągu 7 dni. Powyżej ~5 punktów na tydzień progresja zwykle "
        "wyprzedza adaptację.",
    )
    figure = tz.bars(view, "day", "ramp_7d", diverging=True, y_title="Δ CTL / 7 d", height=280)
    if figure is not None:
        tz.threshold(figure, 5, label="granica bezpiecznej progresji")
    tz.show(figure)

    _foster(weekly)
    _banister(models)


def _foster(weekly) -> None:
    shell.lead(
        "Monotonia i strain (Foster)",
        "Monotonia = średnia dzienna podzielona przez odchylenie w tygodniu. Tydzień "
        "siedmiu identycznych sesji punktuje wysoko nawet przy umiarkowanej objętości, "
        "a wysoki strain przy wysokiej monotonii to klasyczny podpis przeciążenia. "
        "Każdy punkt to tydzień; ostatnie cztery są wyróżnione.",
    )
    if weekly.empty:
        shell.missing("load_weekly")
        return
    frame = weekly.dropna(subset=["monotony"]).tail(80)
    if frame.empty:
        st.caption("Za mało tygodni z treningami.")
        return
    frame = frame.copy()
    frame["okres"] = "wcześniej"
    frame.loc[frame.index[-4:], "okres"] = "ostatnie 4 tygodnie"
    figure = tz.scatter(
        frame.sort_values("okres"),
        "load_sum",
        "monotony",
        color="okres",
        color_kind="categorical",
        hover=("iso_week", "sessions", "strain"),
        x_title="load tygodniowy",
        y_title="monotonia",
        height=380,
    )
    if figure is not None:
        # History recedes to grey; the recent weeks keep the accent.
        for trace in figure.data:
            if trace.name == "wcześniej":
                trace.marker.color = tz._alpha(tz.tokens()["muted"], 0.45)
        figure.data = tuple(sorted(figure.data, key=lambda trace: trace.name != "wcześniej"))
        tz.threshold(figure, 2.0, label="monotonia 2.0")
    tz.show(
        figure,
        table=frame[["iso_week", "load_sum", "sessions", "monotony", "strain", "hrv", "rhr"]]
        .sort_values("iso_week", ascending=False)
        .head(20),
    )

    shell.sub("Strain tygodniowy")
    weeks = frame.assign(
        week=pd.to_datetime(frame["iso_week"] + "-1", format="%G-W%V-%u", errors="coerce")
    )
    tz.show(tz.bars(weeks, "week", "strain", height=240), key="strain")


def _banister(models: dict) -> None:
    fit = (models or {}).get("banister", {})
    shell.lead("Dopasowanie modelu Banistera")
    if not fit.get("fitted"):
        st.caption(f"Nie dopasowano: {fit.get('reason', 'brak danych')}")
        return
    columns = st.columns(5)
    columns[0].metric("τ sprawności", f"{fit['tau_fitness_days']} d")
    columns[1].metric("τ zmęczenia", f"{fit['tau_fatigue_days']} d")
    columns[2].metric("R²", f"{fit['r2']}")
    columns[3].metric("Pomiarów", fit["n"])
    columns[4].metric("Szczyt po", f"{fit['taper_days_to_peak']} d")
    good = (fit.get("r2") or 0) > 0.3
    st.caption(
        "Stałe czasowe dopasowane do **twoich** danych (zamiast podręcznikowych 42/7), "
        "na ekonomii biegu jako mierze wydolności. "
        + (
            "Model realnie tłumaczy zmienność wydolności."
            if good
            else "R² jest **za niskie**, żeby traktować to jako prognozę: ekonomia biegu "
            "jest zbyt zaszumiona (teren, upał, sen), a sesji za mało. Czytaj te liczby "
            "jako ciekawostkę, nie jako plan taperu."
        )
    )
