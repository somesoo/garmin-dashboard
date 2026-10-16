"""Statistics: lagged correlations under FDR control, ACF, change points."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

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
    st.title("Statystyka")
    st.caption(
        "Testów jest tu kilkaset, więc samo *p* nic nie znaczy. Wszędzie, gdzie pada "
        "słowo „istotne”, stoi za nim wartość **q** po kontroli FDR "
        "(Benjamini-Hochberg)."
    )
    _correlations()
    _acf()
    _changepoints()
    _weekdays()


@st.fragment
def _correlations() -> None:
    corr = shell.table("correlations")
    shell.lead(
        "Korelacje z opóźnieniem",
        "Co z jednego dnia wiąże się z twoim stanem kilka dni później.",
        terms=["correlation"],
        how="Spearman między czynnikiem z dnia *t−lag* a odpowiedzią w dniu *t*. Podpisane są tylko komórki "
            "z q < 0,05. Niebieski = dodatnia, czerwony = ujemna, szary środek = brak związku.",
    )
    if corr.empty:
        shell.missing("correlations", "Potrzeba min. 25 wspólnych dni na parę.")
        return

    response = st.selectbox(
        "Odpowiedź", sorted(corr["response"].unique()), index=0, key="corr_response"
    )
    subset = corr[corr["response"] == response]
    grid = subset.pivot_table(index="driver", columns="lag_days", values="rho")
    mask = subset.pivot_table(index="driver", columns="lag_days", values="q")
    labels = grid.round(2).astype(str)
    if not mask.empty:
        labels = labels.where(mask < 0.05, "")
    tz.show(
        tz.heatmap(
            grid, kind="diverging", mid=0.0, height=440,
            x_title="lag (dni)", color_title="rho", text=labels,
        ),
        table=subset[["driver", "lag_days", "rho", "q", "n"]].sort_values("q").head(25),
        key=f"corr_{response}",
    )

    significant = corr[corr["significant"]] if "significant" in corr.columns else pd.DataFrame()
    shell.sub("Co przeszło kontrolę FDR")
    if significant.empty:
        st.caption(
            "Nic. Przy tej liczbie dni to normalny wynik — i uczciwszy niż wykres "
            "z dorysowaną linią trendu."
        )
    else:
        st.dataframe(
            significant[["driver", "response", "lag_days", "rho", "q", "n"]].head(30),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Uwaga na trend długoterminowy: `ctl` i `rhr` korelują mocno również "
            "dlatego, że przez dwa lata rosła sprawność, a tętno spoczynkowe spadało. "
            "To wspólny trend, nie efekt z dnia na dzień."
        )


@st.fragment
def _acf() -> None:
    acf = shell.table("acf")
    shell.lead(
        "Autokorelacja",
        "Jak długo wczoraj przewiduje dziś. Słupki poza przedziałem ufności to realna "
        "pamięć szeregu; wyraźny pik przy lagu 7 oznacza rytm tygodniowy, nie fizjologię.",
        terms=["acf"],
    )
    if acf.empty:
        shell.missing("acf")
        return
    metric = st.selectbox(
        "Metryka", sorted(acf["metric"].unique()), key="acf_metric"
    )
    subset = acf[acf["metric"] == metric]
    tokens = tz.tokens()
    figure = go.Figure()
    figure.add_bar(
        x=subset["lag_days"],
        y=subset["acf"],
        name="ACF",
        marker=dict(color=tokens["series"][0], line=dict(width=0)),
        hovertemplate="lag %{x}: %{y:.3f}<extra></extra>",
    )
    figure.add_scatter(
        x=list(subset["lag_days"]) + list(subset["lag_days"])[::-1],
        y=list(subset["ci_high"]) + list(subset["ci_low"])[::-1],
        fill="toself",
        fillcolor=tz._alpha(tokens["muted"], 0.16),
        line=dict(width=0),
        name="95% CI",
        hoverinfo="skip",
    )
    figure.update_layout(**tz.base_layout(legend=True, height=340))
    figure.update_xaxes(title_text="lag (dni)")
    figure.update_yaxes(title_text="autokorelacja")
    tz.show(
        tz.style_axes(figure),
        table=subset[["lag_days", "acf", "ci_low", "ci_high"]].head(20),
        note=f"n = {int(subset['n'].iloc[0])} dni",
        key=f"acf_{metric}",
    )


def _changepoints() -> None:
    points = shell.table("changepoints")
    shell.lead(
        "Punkty zmiany bazy",
        "Daty, od których metryka trwale się przesunęła — zmiana, nie szum.",
        terms=["changepoint"],
        how="Segmentacja binarna na z-score: podział musi zmniejszyć sumę kwadratów bardziej niż kara "
            "~2·ln(n), więc szum nie przechodzi.",
    )
    if points.empty:
        shell.missing("changepoints", "Żadne przesunięcie nie przebiło kary.")
        return
    st.dataframe(
        points.assign(day=pd.to_datetime(points["day"]).dt.date),
        width="stretch",
        hide_index=True,
    )


@st.fragment
def _weekdays() -> None:
    effects = shell.table("weekday_effects")
    shell.lead(
        "Efekt dnia tygodnia",
        "Czy twoje dni tygodnia różnią się naprawdę — nawyki, nie fizjologia.",
        terms=["weekday"],
    )
    if effects.empty:
        shell.missing("weekday_effects")
        return
    metric = st.selectbox(
        "Metryka", sorted(effects["metric"].unique()), key="weekday_metric"
    )
    subset = effects[effects["metric"] == metric]
    subset = subset.set_index("weekday").reindex(list(WEEKDAYS)).reset_index()
    subset["dzień"] = [WEEKDAYS[w] for w in subset["weekday"]]
    figure = tz.bars(subset, "dzień", "delta_vs_overall", diverging=True, height=320,
                     y_title="odchylenie")
    p_values = subset["kruskal_p"].dropna()
    note = None
    if not p_values.empty:
        value = float(p_values.iloc[0])
        note = (
            f"Kruskal-Wallis p = {value:.4f} — "
            + ("różnice są istotne." if value < 0.05 else "brak istotnych różnic.")
        )
    tz.show(
        figure,
        table=subset[["dzień", "mean", "sd", "n", "delta_vs_overall"]],
        note=note,
        key=f"weekday_{metric}",
    )
