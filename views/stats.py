"""Statistics: lagged correlations under FDR control, ACF, change points."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bento
import i18n
import shell
import theme as tz

# analytics.weekday_effects stores English weekday names, Monday first.
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def render() -> None:
    tr = i18n.tr
    bento.header(
        i18n.page("statystyka"),
        tr(pl="Testów są tu setki, więc samo p nic nie znaczy: „istotne” znaczy zawsze q < 0,05 po kontroli FDR "
              "(Benjamini-Hochberg).",
           en="There are hundreds of tests here, so p alone means nothing: “significant” always means q < 0.05 "
              "after FDR control (Benjamini-Hochberg)."),
    )
    corr = shell.table("correlations")
    points = shell.table("changepoints")
    columns = bento.row(1, 1, 1, 1)
    significant = corr[corr["significant"]] if not corr.empty and "significant" in corr.columns else pd.DataFrame()
    bento.stat(columns[0], tr(pl="Testów korelacji", en="Correlation tests"), f"{len(corr)}", key="tests",
               help=tr(pl="Pary czynnik–odpowiedź × lagi 0–7.", en="Factor–response pairs × lags 0–7."))
    bento.stat(columns[1], tr(pl="Istotnych po FDR", en="Significant after FDR"), f"{len(significant)}",
               key="significant", note=tr(pl="q < 0,05 — reszta to oczekiwany szum",
                                          en="q < 0.05 — the rest is expected noise"))
    bento.stat(columns[2], tr(pl="Punktów zmiany bazy", en="Baseline change points"), f"{len(points)}",
               key="changepoints")
    bento.stat(columns[3], tr(pl="Dni w analizie (max n)", en="Days analysed (max n)"),
               f"{int(corr['n'].max())}" if not corr.empty else "—", key="n")

    left, right = bento.row(2, 2)
    with left:
        _correlations(corr)
    with right:
        _acf()
        _weekdays()

    left, right = bento.row(2, 2)
    with left:
        _significant(significant)
    with right:
        _changepoints(points)


@st.fragment
def _correlations(corr: pd.DataFrame) -> None:
    tr = i18n.tr
    with bento.tile(
        tr(pl="Korelacje z opóźnieniem", en="Lagged correlations"), rows=2, key="corr", terms=["correlation"],
        caption=tr(pl="Co z jednego dnia wiąże się z twoim stanem kilka dni później.",
                   en="What on one day relates to how you are a few days later."),
        how=tr(pl="Spearman między czynnikiem z dnia t−lag a odpowiedzią w dniu t. Podpisane są tylko komórki z "
                  "q < 0,05. Niebieski = dodatnia, czerwony = ujemna, szary środek = brak związku.",
               en="Spearman between the factor on day t−lag and the response on day t. Only cells with q < 0.05 "
                  "are labelled. Blue = positive, red = negative, grey middle = no relation."),
    ) as t:
        if corr.empty:
            shell.missing("correlations", tr(pl="Potrzeba min. 25 wspólnych dni na parę.",
                                             en="Needs at least 25 shared days per pair."))
            return
        with t.header:
            response = st.selectbox(tr(pl="Odpowiedź", en="Response"), sorted(corr["response"].unique()), index=0,
                                    key="corr_response",
                                    label_visibility="collapsed", width=170)
        subset = corr[corr["response"] == response]
        grid = subset.pivot_table(index="driver", columns="lag_days", values="rho")
        mask = subset.pivot_table(index="driver", columns="lag_days", values="q")
        labels = grid.round(2).astype(str)
        if not mask.empty:
            labels = labels.where(mask < 0.05, "")
        t.chart(tz.heatmap(grid, kind="diverging", mid=0.0, x_title=tr(pl="lag (dni)", en="lag (days)"),
                           color_title="rho", text=labels),
                table=subset[["driver", "lag_days", "rho", "q", "n"]].sort_values("q").head(25),
                key=f"corr_{response}")


def _significant(significant: pd.DataFrame) -> None:
    tr = i18n.tr
    with bento.tile(
        tr(pl="Co przeszło kontrolę FDR", en="What survived FDR control"), rows=2, key="fdr", terms=["correlation"],
        caption=tr(pl="Uwaga na wspólny trend: ctl i rhr korelują też dlatego, że przez dwa lata oba się zmieniały.",
                   en="Beware of a shared trend: ctl and rhr also correlate because both changed over two years."),
    ) as t:
        if significant.empty:
            st.caption(tr(pl="Nic. Przy tej liczbie dni to normalny wynik — i uczciwszy niż wykres z dorysowaną "
                             "linią trendu.",
                          en="Nothing. With this many days that is a normal result — and more honest than a chart "
                             "with a trend line drawn in."))
            return
        t.table(significant[["driver", "response", "lag_days", "rho", "q", "n"]])


@st.fragment
def _acf() -> None:
    acf = shell.table("acf")
    tr = i18n.tr
    with bento.tile(
        tr(pl="Autokorelacja", en="Autocorrelation"), key="acf", terms=["acf"],
        caption=tr(pl="Słupki poza pasem to pamięć szeregu; pik przy 7 = rytm tygodniowy.",
                   en="Bars outside the band are the series' memory; a peak at 7 = a weekly rhythm."),
    ) as t:
        if acf.empty:
            shell.missing("acf")
            return
        with t.header:
            metric = st.selectbox(tr(pl="Metryka", en="Metric"), sorted(acf["metric"].unique()), key="acf_metric",
                                  label_visibility="collapsed", width=150)
        subset = acf[acf["metric"] == metric]
        tokens = tz.tokens()
        figure = go.Figure()
        figure.add_bar(x=subset["lag_days"], y=subset["acf"], name="ACF",
                       marker=dict(color=tokens["series"][0], line=dict(width=0)),
                       hovertemplate="lag %{x}: %{y:.3f}<extra></extra>")
        figure.add_scatter(
            x=list(subset["lag_days"]) + list(subset["lag_days"])[::-1],
            y=list(subset["ci_high"]) + list(subset["ci_low"])[::-1],
            fill="toself", fillcolor=tz._alpha(tokens["muted"], 0.16), line=dict(width=0), name="95% CI",
            hoverinfo="skip",
        )
        figure.update_layout(**tz.base_layout(legend=False, height=200))
        figure.update_xaxes(title_text=tr(pl="lag (dni)", en="lag (days)") + f" · n = {int(subset['n'].iloc[0])}")
        t.chart(tz.style_axes(figure), table=subset[["lag_days", "acf", "ci_low", "ci_high"]].head(20),
                key=f"acf_{metric}")


def _changepoints(points: pd.DataFrame) -> None:
    tr = i18n.tr
    with bento.tile(
        tr(pl="Punkty zmiany bazy", en="Baseline change points"), rows=2, key="changepoints", terms=["changepoint"],
        caption=tr(pl="Daty, od których metryka trwale się przesunęła — zmiana, nie szum.",
                   en="Dates from which a metric shifted for good — a change, not noise."),
        how=tr(pl="Segmentacja binarna na z-score: podział musi zmniejszyć sumę kwadratów bardziej niż kara "
                  "~2·ln(n), więc szum nie przechodzi.",
               en="Binary segmentation on the z-score: a split must reduce the sum of squares by more than a "
                  "penalty of ~2·ln(n), so noise does not get through."),
    ) as t:
        if points.empty:
            shell.missing("changepoints", tr(pl="Żadne przesunięcie nie przebiło kary.",
                                             en="No shift beat the penalty."))
            return
        t.table(points.assign(day=pd.to_datetime(points["day"]).dt.date))


@st.fragment
def _weekdays() -> None:
    effects = shell.table("weekday_effects")
    tr = i18n.tr
    with bento.tile(tr(pl="Efekt dnia tygodnia", en="Day-of-week effect"), key="weekday", terms=["weekday"],
                    caption=tr(pl="Nawyki, nie fizjologia.", en="Habits, not physiology.")) as t:
        if effects.empty:
            shell.missing("weekday_effects")
            return
        with t.header:
            metric = st.selectbox(tr(pl="Metryka", en="Metric"), sorted(effects["metric"].unique()),
                                  key="weekday_metric", label_visibility="collapsed", width=150)
        subset = effects[effects["metric"] == metric]
        subset = subset.set_index("weekday").reindex(WEEKDAYS).reset_index()
        day = tr(pl="dzień", en="day")
        subset[day] = i18n.weekdays()
        p_values = subset["kruskal_p"].dropna()
        figure = tz.bars(subset, day, "delta_vs_overall", diverging=True,
                         y_title=tr(pl="odchylenie", en="deviation"))
        if figure is not None and not p_values.empty:
            value = float(p_values.iloc[0])
            verdict = (tr(pl="różnice istotne", en="significant differences") if value < 0.05
                       else tr(pl="brak istotnych różnic", en="no significant differences"))
            figure.update_xaxes(title_text=f"Kruskal-Wallis p = {value:.3f} — {verdict}")
        t.chart(figure, table=subset[[day, "mean", "sd", "n", "delta_vs_overall"]], key=f"weekday_{metric}")
