"""Statistics: lagged correlations under FDR control, ACF, change points."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bento
import shell
import theme as tz

WEEKDAYS = {
    "Monday": "pon",
    "Tuesday": "wt",
    "Wednesday": "śr",
    "Thursday": "czw",
    "Friday": "pt",
    "Saturday": "sob",
    "Sunday": "nd",
}


def render() -> None:
    bento.header(
        "Statystyka",
        "Testów są tu setki, więc samo p nic nie znaczy: „istotne” znaczy zawsze q < 0,05 po kontroli FDR "
        "(Benjamini-Hochberg).",
    )
    corr = shell.table("correlations")
    points = shell.table("changepoints")
    columns = bento.row(1, 1, 1, 1)
    significant = corr[corr["significant"]] if not corr.empty and "significant" in corr.columns else pd.DataFrame()
    bento.stat(columns[0], "Testów korelacji", f"{len(corr)}", key="tests", help="Pary czynnik–odpowiedź × lagi 0–7.")
    bento.stat(columns[1], "Istotnych po FDR", f"{len(significant)}", key="significant",
               note="q < 0,05 — reszta to oczekiwany szum")
    bento.stat(columns[2], "Punktów zmiany bazy", f"{len(points)}", key="changepoints")
    bento.stat(columns[3], "Dni w analizie (max n)", f"{int(corr['n'].max())}" if not corr.empty else "—", key="n")

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
    with bento.tile(
        "Korelacje z opóźnieniem", rows=2, key="corr", terms=["correlation"],
        caption="Co z jednego dnia wiąże się z twoim stanem kilka dni później.",
        how="Spearman między czynnikiem z dnia t−lag a odpowiedzią w dniu t. Podpisane są tylko komórki z "
            "q < 0,05. Niebieski = dodatnia, czerwony = ujemna, szary środek = brak związku.",
    ) as t:
        if corr.empty:
            shell.missing("correlations", "Potrzeba min. 25 wspólnych dni na parę.")
            return
        with t.header:
            response = st.selectbox("Odpowiedź", sorted(corr["response"].unique()), index=0, key="corr_response",
                                    label_visibility="collapsed", width=170)
        subset = corr[corr["response"] == response]
        grid = subset.pivot_table(index="driver", columns="lag_days", values="rho")
        mask = subset.pivot_table(index="driver", columns="lag_days", values="q")
        labels = grid.round(2).astype(str)
        if not mask.empty:
            labels = labels.where(mask < 0.05, "")
        t.chart(tz.heatmap(grid, kind="diverging", mid=0.0, x_title="lag (dni)", color_title="rho", text=labels),
                table=subset[["driver", "lag_days", "rho", "q", "n"]].sort_values("q").head(25),
                key=f"corr_{response}")


def _significant(significant: pd.DataFrame) -> None:
    with bento.tile(
        "Co przeszło kontrolę FDR", rows=2, key="fdr", terms=["correlation"],
        caption="Uwaga na wspólny trend: ctl i rhr korelują też dlatego, że przez dwa lata oba się zmieniały.",
    ):
        if significant.empty:
            st.caption("Nic. Przy tej liczbie dni to normalny wynik — i uczciwszy niż wykres z dorysowaną linią trendu.")
            return
        st.dataframe(significant[["driver", "response", "lag_days", "rho", "q", "n"]].head(50),
                     width="stretch", hide_index=True, height=bento.chart_height(2, caption=True))


@st.fragment
def _acf() -> None:
    acf = shell.table("acf")
    with bento.tile(
        "Autokorelacja", key="acf", terms=["acf"],
        caption="Słupki poza pasem to pamięć szeregu; pik przy 7 = rytm tygodniowy.",
    ) as t:
        if acf.empty:
            shell.missing("acf")
            return
        with t.header:
            metric = st.selectbox("Metryka", sorted(acf["metric"].unique()), key="acf_metric",
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
        figure.update_xaxes(title_text=f"lag (dni) · n = {int(subset['n'].iloc[0])}")
        t.chart(tz.style_axes(figure), table=subset[["lag_days", "acf", "ci_low", "ci_high"]].head(20),
                key=f"acf_{metric}")


def _changepoints(points: pd.DataFrame) -> None:
    with bento.tile(
        "Punkty zmiany bazy", rows=2, key="changepoints", terms=["changepoint"],
        caption="Daty, od których metryka trwale się przesunęła — zmiana, nie szum.",
        how="Segmentacja binarna na z-score: podział musi zmniejszyć sumę kwadratów bardziej niż kara "
            "~2·ln(n), więc szum nie przechodzi.",
    ):
        if points.empty:
            shell.missing("changepoints", "Żadne przesunięcie nie przebiło kary.")
            return
        st.dataframe(points.assign(day=pd.to_datetime(points["day"]).dt.date), width="stretch", hide_index=True,
                     height=bento.chart_height(2, caption=True))


@st.fragment
def _weekdays() -> None:
    effects = shell.table("weekday_effects")
    with bento.tile("Efekt dnia tygodnia", key="weekday", terms=["weekday"],
                    caption="Nawyki, nie fizjologia.") as t:
        if effects.empty:
            shell.missing("weekday_effects")
            return
        with t.header:
            metric = st.selectbox("Metryka", sorted(effects["metric"].unique()), key="weekday_metric",
                                  label_visibility="collapsed", width=150)
        subset = effects[effects["metric"] == metric]
        subset = subset.set_index("weekday").reindex(list(WEEKDAYS)).reset_index()
        subset["dzień"] = [WEEKDAYS[w] for w in subset["weekday"]]
        p_values = subset["kruskal_p"].dropna()
        figure = tz.bars(subset, "dzień", "delta_vs_overall", diverging=True,
                         y_title="odchylenie")
        if figure is not None and not p_values.empty:
            value = float(p_values.iloc[0])
            figure.update_xaxes(title_text=f"Kruskal-Wallis p = {value:.3f} — "
                                + ("różnice istotne" if value < 0.05 else "brak istotnych różnic"))
        t.chart(figure, table=subset[["dzień", "mean", "sd", "n", "delta_vs_overall"]], key=f"weekday_{metric}")
