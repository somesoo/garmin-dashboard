"""Sleep and circadian structure: regularity, hypnogram, night profile, day map."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import glossary
import shell
import theme as tz


def render() -> None:
    st.title("Rytm i sen")
    st.caption(
        "Długość snu to jedna liczba; regularność, struktura nocy i moment "
        "wyciszenia organizmu mówią więcej — i wszystkie trzy są w tych danych."
    )

    _headline()
    _regularity()
    _window()
    _hypnogram()
    _profile()
    _daymap()


def _headline() -> None:
    sri = shell.table("sleep_regularity")
    circ = shell.table("circadian")
    if sri.empty and circ.empty:
        shell.missing("sleep_regularity", "Potrzebne noce z hipnogramem.")
        return
    columns = st.columns(4)
    if not sri.empty:
        last = sri.dropna(subset=["sri_30d"]).tail(1)
        if not last.empty:
            columns[0].metric("SRI (30 nocy)", f"{last['sri_30d'].iloc[0]:.0f} / 100",
                              help=glossary.short("sri"))
    if not circ.empty:
        mid = pd.to_numeric(circ["midpoint_hour"], errors="coerce").dropna()
        if not mid.empty:
            hour = float(mid.tail(30).mean()) % 24
            columns[1].metric("Środek snu", f"{int(hour):02d}:{int((hour % 1) * 60):02d}",
                              help=glossary.short("midpoint"))
        sd = pd.to_numeric(circ.get("midpoint_sd_30d"), errors="coerce").dropna()
        if not sd.empty:
            columns[2].metric("Rozrzut środka snu", f"±{sd.iloc[-1]:.1f} h", help=glossary.short("midpoint"))
        weekend = circ.groupby("is_weekend")["midpoint_hour"].mean()
        if len(weekend) == 2:
            columns[3].metric("Social jetlag", f"{float(weekend.loc[True] - weekend.loc[False]):+.2f} h",
                              help=glossary.short("social_jetlag"))


def _regularity() -> None:
    sri = shell.table("sleep_regularity")
    if sri.empty:
        return
    shell.lead(
        "Regularność snu (SRI)",
        "Czy kładziesz się i wstajesz o stałych porach — regularność poprawia sen niezależnie od jego długości.",
        terms=["sri", "midpoint", "social_jetlag"],
        how=glossary.TREND_HOW,
    )
    tz.show(
        tz.trend(shell.clip(sri), "day", {"SRI": ("sri_pair", "sri_30d")},
                 smooth_label="średnia 30 nocy", height=240),
        table=sri.tail(30),
        key="sri_trend",
    )


def _window() -> None:
    circ = shell.clip(shell.table("circadian"))
    if circ.empty:
        return
    frame = circ.copy()
    bed = pd.to_datetime(frame["bedtime"])
    wake = pd.to_datetime(frame["waketime"])
    frame["bed"] = pd.to_numeric(frame["bed_hour_cont"], errors="coerce")
    frame["wake"] = frame["bed"] + (wake - bed).dt.total_seconds() / 3600
    shell.lead(
        "Okno snu",
        "Kiedy śpisz: równe słupki w jednej linii to regularny rytm, przesunięty o kilka godzin — podróż "
        "albo zarwana noc.",
        how="Każdy słupek to jedna noc: od zaśnięcia do wybudzenia, wieczór u góry. Ostatnia noc jest wyróżniona.",
    )
    tz.show(
        tz.range_bars(frame, "day", "bed", "wake", clock=True, height=300),
        table=frame[["day", "bed_hour_cont", "wake_hour", "midpoint_hour", "midpoint_sd_30d"]].tail(30),
        key="sleep_window",
    )


@st.fragment
def _hypnogram() -> None:
    stages = shell.table("sleep_stages")
    nights = shell.table("night_series")
    shell.lead("Hipnogram", "Pojedyncza noc, segment po segmencie.", terms=["sleep_stages"])
    if stages.empty:
        shell.missing("sleep_stages")
        return

    frame = stages.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    available = sorted(frame["day"].dt.date.unique(), reverse=True)
    chosen = st.selectbox("Noc", available, index=0, key="night_pick")
    night = frame[frame["day"].dt.date == chosen].copy()
    night["start_local"] = pd.to_datetime(night["start_local"])
    night["end_local"] = pd.to_datetime(night["end_local"])

    tokens = tz.tokens()
    colours = tz.sleep_stage_colors()
    levels = {"deep": 0, "light": 1, "rem": 2, "awake": 3}
    import plotly.graph_objects as go

    figure = go.Figure()
    seen: set[str] = set()
    for row in night.itertuples(index=False):
        level = levels.get(row.stage, 0)
        figure.add_scatter(
            x=[row.start_local, row.end_local],
            y=[level, level],
            mode="lines",
            line=dict(width=18, color=colours.get(row.stage, tokens["muted"])),
            name=tz.SLEEP_STAGE_LABELS.get(row.stage, row.stage),
            legendgroup=row.stage,
            showlegend=row.stage not in seen,
            hovertemplate=f"{tz.SLEEP_STAGE_LABELS.get(row.stage, row.stage)}: {row.minutes} min<extra></extra>",
        )
        seen.add(row.stage)
    figure.update_layout(**tz.base_layout(legend=True, height=260, hover="closest"))
    figure.update_yaxes(
        tickmode="array",
        tickvals=[0, 1, 2, 3],
        ticktext=[tz.SLEEP_STAGE_LABELS[s] for s in tz.SLEEP_STAGE_ORDER],
        showgrid=False,
    )
    summary = (
        night.groupby("stage")["minutes"].sum().reindex(tz.SLEEP_STAGE_ORDER).dropna()
        .rename_axis("faza").reset_index(name="minuty")
    )
    summary["faza"] = summary["faza"].map(tz.SLEEP_STAGE_LABELS)
    tz.show(tz.style_axes(figure), table=summary, key=f"hypno_{chosen}")

    if not nights.empty:
        series = nights.copy()
        series["day"] = pd.to_datetime(series["day"])
        series = series[series["day"].dt.date == chosen]
        series = series[series["metric"].isin(["hr", "hrv", "body_battery", "stress"])]
        if not series.empty:
            series["t_local"] = pd.to_datetime(series["t_local"])
            wide = series.pivot_table(
                index="t_local", columns="metric", values="value", aggfunc="mean"
            ).reset_index()
            shell.sub(
                "Przebieg nocy",
                "Każda metryka ma inną skalę, więc każda dostaje własny panel na "
                "wspólnej osi czasu.",
            )
            panels = [
                {"title": title, "series": {title: column}, "kind": "line"}
                for column, title in (
                    ("hr", "Tętno (bpm)"),
                    ("hrv", "HRV (ms)"),
                    ("body_battery", "Body Battery"),
                    ("stress", "Stres"),
                )
                if column in wide.columns and wide[column].notna().any()
            ]
            tz.show(
                tz.stacked_panels(wide, "t_local", panels, height=120 * len(panels) + 60),
                key=f"night_{chosen}",
            )

    shell.sub(
        "Struktura snu w czasie",
        "Udział faz jako procent nocy, wygładzony średnią z 7 nocy — długość snu "
        "nie zaburza porównania, a pojedyncza noc nie szarpie wykresem.",
        terms=["sleep_stages"],
    )
    pivot = frame.groupby([frame["day"].dt.date, "stage"])["minutes"].sum().unstack(fill_value=0)
    columns = [s for s in tz.SLEEP_STAGE_ORDER if s in pivot.columns]
    share = pivot[columns].div(pivot[columns].sum(axis=1), axis=0).mul(100)
    share = share.rolling(7, min_periods=3).mean().dropna().round(1)
    share.index = pd.to_datetime(share.index)
    share = shell.clip(share.rename_axis("day").reset_index())
    tz.show(
        tz.stacked(
            share, "day", columns, tz.SLEEP_STAGE_LABELS,
            y_title="% nocy", height=300, colors=tz.sleep_stage_colors(), area=True,
        ),
        key="stage_share",
    )


def _profile() -> None:
    profile = shell.table("night_profile")
    shell.lead(
        "Profil nocy",
        "Minimum tętna i **moment** jego wystąpienia. Nadir w pierwszej połowie nocy "
        "znaczy, że organizm wyciszył się szybko; nadir pod koniec — że regeneracja "
        "trwała jeszcze, gdy zadzwonił budzik.",
        terms=["night_profile", "hrv_slope"],
    )
    if profile.empty:
        shell.missing("night_profile", "Potrzebne noce z zapisem tętna i HRV.")
        return
    view = shell.clip(profile)
    last = profile.tail(1).iloc[0]
    columns = st.columns(4)
    columns[0].metric("Tętno minimalne", f"{last['hr_min']:.0f}")
    columns[1].metric("Spadek od 1. godziny", f"{last['hr_drop']:.1f}")
    columns[2].metric("Nadir po", f"{last['nadir_at_pct']:.0f}% nocy", help=glossary.short("night_profile"))
    if pd.notna(last.get("hrv_slope_per_h")):
        columns[3].metric("Nachylenie HRV", f"{last['hrv_slope_per_h']:+.2f} /h", help=glossary.short("hrv_slope"))

    tz.show(
        tz.scatter(
            view,
            "nadir_at_pct",
            "sleep_score",
            hover=("day", "hr_min", "sleep_h", "readiness"),
            x_title="nadir tętna (% nocy)",
            y_title="sleep score",
            height=400,
        ),
        table=view[["day", "hr_min", "hr_drop", "nadir_at_pct", "hrv_trend", "sleep_score"]]
        .sort_values("day", ascending=False)
        .head(30),
    )

    shell.sub("HRV w ciągu nocy", "Pierwsza i ostatnia trzecia nocy — czy noc nadrabiała.")
    thirds = view.sort_values("day").copy()
    for column in ("hrv_first_third", "hrv_last_third"):
        thirds[f"{column}_roll7"] = (
            pd.to_numeric(thirds[column], errors="coerce").rolling(7, min_periods=3).mean()
        )
    tz.show(
        tz.trend(
            thirds, "day",
            {"początek": ("hrv_first_third", "hrv_first_third_roll7"),
             "koniec": ("hrv_last_third", "hrv_last_third_roll7")},
            unit="", height=260,
        ),
        note="Linie to średnie 7-nocne, kropki — pojedyncze noce. Koniec nocy powyżej "
        "początku znaczy, że noc nadrabiała.",
        key="hrv_thirds",
    )


@st.fragment
def _daymap() -> None:
    intraday = shell.table("intraday")
    shell.lead(
        "Mapa doby",
        "Stres i Body Battery w ciągu doby: jak rozkłada się obciążenie dnia.",
        terms=["stress", "body_battery"],
        how="Każdy wiersz to jeden dzień, każda kolumna pół godziny. Pionowe pasy to rytm dobowy, "
            "poziome — dni odstające.",
    )
    if intraday.empty:
        shell.missing(
            "intraday",
            "Pobierz metrykę `stress` (3-minutowe próbki stresu i Body Battery).",
        )
        return
    frame = intraday.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    what = st.segmented_control(
        "Metryka",
        ["stress", "body_battery"],
        default="stress",
        format_func=lambda v: {"stress": "stres", "body_battery": "Body Battery"}[v],
        key="daymap_metric",
    ) or "stress"
    heat = shell.clip(frame)
    heat["hour_bin"] = (pd.to_numeric(heat["hour"], errors="coerce") * 2).round() / 2
    grid = heat.pivot_table(
        index=heat["day"].dt.date, columns="hour_bin", values=what, aggfunc="mean"
    ).round(1)
    # Newest night at the top: the heatmap puts the first row there.
    grid = grid.sort_index(ascending=False)
    figure = tz.heatmap(
        grid,
        kind="sequential",
        height=560,
        x_title="godzina doby",
        color_title="stres" if what == "stress" else "Body Battery",
    )
    if figure is not None:
        figure.update_xaxes(tickmode="array", tickvals=list(range(0, 24, 3)),
                            ticktext=[f"{h:02d}:00" for h in range(0, 24, 3)])
    tz.show(
        figure,
        note="Próbkowanie co 3 minuty, agregowane do pół godziny.",
        key=f"daymap_{what}",
    )
