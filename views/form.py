"""Training load: the Banister chart, both ACWR formulations, Foster's strain."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import glossary
import i18n
import shell
import theme as tz


def render() -> None:
    pmc = shell.table("pmc")
    weekly = shell.table("load_weekly")
    models = shell.models()

    tr = i18n.tr
    bento.header(
        i18n.page("forma"),
        tr(pl="Model Banistera: każdy trening buduje wolną sprawność (CTL, 42 dni) i szybkie zmęczenie (ATL, 7 dni). "
              "Forma to ich różnica z dnia poprzedniego.",
           en="The Banister model: every session builds slow fitness (CTL, 42 days) and fast fatigue (ATL, 7 days). "
              "Form is their difference as of the day before."),
    )
    view = shell.clip(pmc)
    if view.empty:
        shell.missing("pmc", tr(pl="Uruchom `analytics.py`.", en="Run `analytics.py`."))
        return

    ready = pmc.dropna(subset=["ctl"])
    current = ready.tail(1).iloc[0]
    week_ago = ready.tail(8).head(1).iloc[0] if len(ready) >= 8 else None
    bento.kpis(current, week_ago, [
        ("ctl", tr(pl="CTL — sprawność", en="CTL — fitness"), ""),
        ("atl", tr(pl="ATL — zmęczenie", en="ATL — fatigue"), "", "off"),
        ("tsb", tr(pl="TSB — forma", en="TSB — form"), ""),
        ("acwr_ewma", "ACWR", "", "off"),
    ])
    zone = _zone_labels().get(current.get("form_zone"))
    zone_text = tr(pl=f"strefa formy: <b>{zone}</b>", en=f"form zone: <b>{zone}</b>") if zone else None

    left, right = bento.row(2, 2)
    with left, bento.tile(
        "Performance Management Chart", rows=2, key="pmc", terms=["ctl", "atl", "tsb", "training_load"],
        caption=zone_text or tr(pl="Sprawność, zmęczenie i świeżość — podstawa planowania odpoczynku.",
                                en="Fitness, fatigue and freshness — the basis for planning rest."),
        how=tr(pl="Dzienny load jest osobnym panelem pod spodem, na wspólnej osi czasu.",
               en="Daily load is a separate panel below, on the shared time axis."),
    ) as t:
        figure = tz.stacked_panels(
            view, "day",
            [
                {"title": "CTL / ATL", "series": {tr(pl="CTL (sprawność)", en="CTL (fitness)"): "ctl",
                                                  tr(pl="ATL (zmęczenie)", en="ATL (fatigue)"): "atl"},
                 "kind": "line", "height": 1.5},
                {"title": tr(pl="TSB — forma", en="TSB — form"), "series": {"TSB": "tsb"}, "kind": "line",
                 "height": 1.0},
                {"title": tr(pl="Load dzienny", en="Daily load"), "series": {"load": "load_day"}, "kind": "bar",
                 "height": 0.8},
            ],
            height=400,
        )
        if figure is not None:
            tz.band(figure, -10, 5, row=2)
        t.chart(figure, table=view[["day", "ctl", "atl", "tsb", "ramp_7d", "load_day"]].tail(40))
    with right:
        with bento.tile(
            tr(pl="ACWR: dwa wzory", en="ACWR: two formulas"), key="acwr", terms=["acwr"],
            caption=tr(pl="Pas 0,8–1,3 to bezpieczny zakres.", en="The 0.8–1.3 band is the safe range."),
            how=tr(pl="Kroczący (Gabbett) to suma 7 dni przez średnią z 28; wykładniczy (Williams) używa wag CTL/ATL. "
                      "Tygodnie, w których się rozjeżdżają, to te, gdzie wniosek „przetrenowanie” zależy od wzoru.",
                   en="Rolling (Gabbett) is the 7-day sum over the 28-day average; exponential (Williams) uses the "
                      "CTL/ATL weights. Weeks where they diverge are those where an “overtraining” verdict depends "
                      "on the formula."),
        ) as t:
            figure = tz.timeseries(view, "day", {tr(pl="kroczący", en="rolling"): "acwr_rolling",
                                                 tr(pl="wykładniczy", en="exponential"): "acwr_ewma"},
                                   y_title=tr(pl="iloraz", en="ratio"))
            if figure is not None:
                tz.band(figure, 0.8, 1.3)
                tz.threshold(figure, 1.5, label="1.5")
            t.chart(figure, table=view[["day", "acwr_rolling", "acwr_ewma"]].tail(40))
        ramp = current.get("ramp_7d")
        with bento.tile(
            tr(pl="Tempo narastania sprawności", en="Fitness ramp rate"), key="ramp", terms=["ramp", "ctl"],
            caption=(tr(pl=f"ostatnie 7 dni: <b>{ramp:+.1f}</b> CTL · powyżej ~5/tydz. progresja wyprzedza adaptację",
                        en=f"last 7 days: <b>{ramp:+.1f}</b> CTL · above ~5/week progression outruns adaptation")
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


def _zone_labels() -> dict[str, str]:
    """Display names of the codes analytics.pmc stores in form_zone."""
    tr = i18n.tr
    return {"przetrenowanie": tr(pl="przetrenowanie", en="overreaching"),
            "budowanie": tr(pl="budowanie", en="building"), "neutralnie": tr(pl="neutralnie", en="neutral"),
            "swiezosc": tr(pl="świeżość", en="fresh"), "roztrenowanie": tr(pl="roztrenowanie", en="detraining")}


def _earlier() -> str:
    return i18n.tr(pl="wcześniej", en="earlier")


def _recent(weekly: pd.DataFrame) -> pd.DataFrame:
    frame = weekly.dropna(subset=["monotony"]).tail(80).copy() if not weekly.empty else weekly
    if not frame.empty:
        frame["okres"] = _earlier()
        frame.loc[frame.index[-4:], "okres"] = i18n.tr(pl="ostatnie 4 tygodnie", en="last 4 weeks")
    return frame


def _few_weeks() -> None:
    st.caption(i18n.tr(pl="Za mało tygodni z treningami.", en="Too few weeks with training."))


def _foster(weekly) -> None:
    tr = i18n.tr
    with bento.tile(
        tr(pl="Monotonia i strain (Foster)", en="Monotony and strain (Foster)"), rows=2, key="foster",
        terms=["monotony", "strain"],
        caption=tr(pl="Wysoki load przy wysokiej monotonii to klasyczny podpis przeciążenia.",
                   en="High load with high monotony is the classic signature of overload."),
        how=tr(pl="Każdy punkt to tydzień; ostatnie cztery są wyróżnione.",
               en="Each point is a week; the last four are highlighted."),
    ) as t:
        frame = _recent(weekly)
        if frame.empty:
            _few_weeks()
            return
        figure = tz.scatter(frame.sort_values("okres"), "load_sum", "monotony", color="okres",
                            color_kind="categorical", hover=("iso_week", "sessions", "strain"),
                            x_title=tr(pl="load tygodniowy", en="weekly load"),
                            y_title=tr(pl="monotonia", en="monotony"))
        if figure is not None:
            # History recedes to grey; the recent weeks keep the accent.
            for trace in figure.data:
                if trace.name == _earlier():
                    trace.marker.color = tz._alpha(tz.tokens()["muted"], 0.45)
            figure.data = tuple(sorted(figure.data, key=lambda trace: trace.name != _earlier()))
            tz.threshold(figure, 2.0, label=tr(pl="monotonia 2.0", en="monotony 2.0"))
        t.chart(figure, table=frame[["iso_week", "load_sum", "sessions", "monotony", "strain", "hrv", "rhr"]]
                .sort_values("iso_week", ascending=False).head(20))


def _strain(weekly) -> None:
    with bento.tile(i18n.tr(pl="Strain tygodniowy", en="Weekly strain"), key="strain", terms=["strain"],
                    caption=i18n.tr(pl="Suma obciążenia × monotonia.", en="Load total × monotony.")) as t:
        frame = _recent(weekly)
        if frame.empty:
            _few_weeks()
            return
        weeks = frame.assign(week=pd.to_datetime(frame["iso_week"] + "-1", format="%G-W%V-%u", errors="coerce"))
        t.chart(tz.bars(weeks, "week", "strain"), table=weeks[["iso_week", "strain"]].tail(20))


def _banister(models: dict) -> None:
    fit = (models or {}).get("banister", {})
    good = (fit.get("r2") or 0) > 0.3
    tr = i18n.tr
    verdict = (tr(pl="Model realnie tłumaczy zmienność wydolności.",
                  en="The model genuinely explains the variation in fitness.") if good else
               tr(pl="R² za niskie na prognozę — czytaj jako ciekawostkę, nie plan taperu.",
                  en="R² too low for a forecast — read it as a curiosity, not a taper plan."))
    with bento.tile(
        tr(pl="Dopasowanie modelu Banistera", en="Banister model fit"), key="banister", terms=["banister", "r2"],
        caption=verdict if fit.get("fitted") else None,
    ):
        if not fit.get("fitted"):
            reason = fit.get("reason") or tr(pl="brak danych", en="no data")
            st.caption(tr(pl=f"Nie dopasowano: {reason}", en=f"Not fitted: {reason}"))
            return
        columns = st.columns(4)
        columns[0].metric(tr(pl="τ sprawności", en="τ fitness"), f"{fit['tau_fitness_days']} d")
        columns[1].metric(tr(pl="τ zmęczenia", en="τ fatigue"), f"{fit['tau_fatigue_days']} d")
        columns[2].metric("R²", f"{fit['r2']}", help=glossary.short("r2"))
        columns[3].metric(tr(pl="Szczyt po", en="Peak after"), f"{fit['taper_days_to_peak']} d",
                          help=tr(pl=f"n = {fit['n']} pomiarów", en=f"n = {fit['n']} measurements"))
