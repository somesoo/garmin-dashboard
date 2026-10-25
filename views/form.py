"""Training load: the Banister chart, both ACWR formulations, Foster's strain."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import glossary
import shell
import theme as tz


def render() -> None:
    pmc = shell.table("pmc")
    weekly = shell.table("load_weekly")
    models = shell.models()

    bento.header(
        "Forma",
        "Model Banistera: każdy trening buduje wolną sprawność (CTL, 42 dni) i szybkie zmęczenie (ATL, 7 dni). "
        "Forma to ich różnica z dnia poprzedniego.",
    )
    view = shell.clip(pmc)
    if view.empty:
        shell.missing("pmc", "Uruchom `analytics.py`.")
        return

    ready = pmc.dropna(subset=["ctl"])
    current = ready.tail(1).iloc[0]
    week_ago = ready.tail(8).head(1).iloc[0] if len(ready) >= 8 else None
    bento.kpis(current, week_ago, [
        ("ctl", "CTL — sprawność", ""),
        ("atl", "ATL — zmęczenie", "", "off"),
        ("tsb", "TSB — forma", ""),
        ("acwr_ewma", "ACWR", "", "off"),
    ])
    zone = current.get("form_zone")
    zone_text = f"strefa formy: <b>{zone}</b>" if isinstance(zone, str) and zone not in ("nan", "None") else None

    left, right = bento.row(2, 2)
    with left, bento.tile(
        "Performance Management Chart", rows=2, key="pmc", terms=["ctl", "atl", "tsb", "training_load"],
        caption=zone_text or "Sprawność, zmęczenie i świeżość — podstawa planowania odpoczynku.",
        how="Dzienny load jest osobnym panelem pod spodem, na wspólnej osi czasu.",
    ) as t:
        figure = tz.stacked_panels(
            view, "day",
            [
                {"title": "CTL / ATL", "series": {"CTL (sprawność)": "ctl", "ATL (zmęczenie)": "atl"},
                 "kind": "line", "height": 1.5},
                {"title": "TSB — forma", "series": {"TSB": "tsb"}, "kind": "line", "height": 1.0},
                {"title": "Load dzienny", "series": {"load": "load_day"}, "kind": "bar", "height": 0.8},
            ],
            height=400,
        )
        if figure is not None:
            tz.band(figure, -10, 5, row=2)
        t.chart(figure, table=view[["day", "ctl", "atl", "tsb", "ramp_7d", "load_day"]].tail(40))
    with right:
        with bento.tile(
            "ACWR: dwa wzory", key="acwr", terms=["acwr"],
            caption="Pas 0,8–1,3 to bezpieczny zakres.",
            how="Kroczący (Gabbett) to suma 7 dni przez średnią z 28; wykładniczy (Williams) używa wag CTL/ATL. "
                "Tygodnie, w których się rozjeżdżają, to te, gdzie wniosek „przetrenowanie” zależy od wzoru.",
        ) as t:
            figure = tz.timeseries(view, "day", {"kroczący": "acwr_rolling", "wykładniczy": "acwr_ewma"},
                                   y_title="iloraz")
            if figure is not None:
                tz.band(figure, 0.8, 1.3)
                tz.threshold(figure, 1.5, label="1.5")
            t.chart(figure, table=view[["day", "acwr_rolling", "acwr_ewma"]].tail(40))
        ramp = current.get("ramp_7d")
        with bento.tile(
            "Tempo narastania sprawności", key="ramp", terms=["ramp", "ctl"],
            caption=(f"ostatnie 7 dni: <b>{ramp:+.1f}</b> CTL · powyżej ~5/tydz. progresja wyprzedza adaptację"
                     if pd.notna(ramp) else None),
        ) as t:
            figure = tz.bars(view, "day", "ramp_7d", diverging=True, y_title="Δ CTL / 7 d")
            if figure is not None:
                tz.threshold(figure, 5, label="5")
            t.chart(figure, table=view[["day", "ramp_7d"]].tail(40))

    left, right = bento.row(2, 2)
    with left:
        _foster(weekly)
    with right:
        _strain(weekly)
        _banister(models)


def _recent(weekly: pd.DataFrame) -> pd.DataFrame:
    frame = weekly.dropna(subset=["monotony"]).tail(80).copy() if not weekly.empty else weekly
    if not frame.empty:
        frame["okres"] = "wcześniej"
        frame.loc[frame.index[-4:], "okres"] = "ostatnie 4 tygodnie"
    return frame


def _foster(weekly) -> None:
    with bento.tile(
        "Monotonia i strain (Foster)", rows=2, key="foster", terms=["monotony", "strain"],
        caption="Wysoki load przy wysokiej monotonii to klasyczny podpis przeciążenia.",
        how="Każdy punkt to tydzień; ostatnie cztery są wyróżnione.",
    ) as t:
        frame = _recent(weekly)
        if frame.empty:
            st.caption("Za mało tygodni z treningami.")
            return
        figure = tz.scatter(frame.sort_values("okres"), "load_sum", "monotony", color="okres",
                            color_kind="categorical", hover=("iso_week", "sessions", "strain"),
                            x_title="load tygodniowy", y_title="monotonia")
        if figure is not None:
            # History recedes to grey; the recent weeks keep the accent.
            for trace in figure.data:
                if trace.name == "wcześniej":
                    trace.marker.color = tz._alpha(tz.tokens()["muted"], 0.45)
            figure.data = tuple(sorted(figure.data, key=lambda trace: trace.name != "wcześniej"))
            tz.threshold(figure, 2.0, label="monotonia 2.0")
        t.chart(figure, table=frame[["iso_week", "load_sum", "sessions", "monotony", "strain", "hrv", "rhr"]]
                .sort_values("iso_week", ascending=False).head(20))


def _strain(weekly) -> None:
    with bento.tile("Strain tygodniowy", key="strain", terms=["strain"],
                    caption="Suma obciążenia × monotonia.") as t:
        frame = _recent(weekly)
        if frame.empty:
            st.caption("Za mało tygodni z treningami.")
            return
        weeks = frame.assign(week=pd.to_datetime(frame["iso_week"] + "-1", format="%G-W%V-%u", errors="coerce"))
        t.chart(tz.bars(weeks, "week", "strain"), table=weeks[["iso_week", "strain"]].tail(20))


def _banister(models: dict) -> None:
    fit = (models or {}).get("banister", {})
    good = (fit.get("r2") or 0) > 0.3
    with bento.tile(
        "Dopasowanie modelu Banistera", key="banister", terms=["banister", "r2"],
        caption=("Model realnie tłumaczy zmienność wydolności." if good else
                 "R² za niskie na prognozę — czytaj jako ciekawostkę, nie plan taperu.") if fit.get("fitted") else None,
    ):
        if not fit.get("fitted"):
            st.caption(f"Nie dopasowano: {fit.get('reason', 'brak danych')}")
            return
        columns = st.columns(4)
        columns[0].metric("τ sprawności", f"{fit['tau_fitness_days']} d")
        columns[1].metric("τ zmęczenia", f"{fit['tau_fatigue_days']} d")
        columns[2].metric("R²", f"{fit['r2']}", help=glossary.short("r2"))
        columns[3].metric("Szczyt po", f"{fit['taper_days_to_peak']} d", help=f"n = {fit['n']} pomiarów")
