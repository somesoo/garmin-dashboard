"""Sleep and circadian structure: regularity, hypnogram, night profile, day map."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bento
import glossary
import i18n
import shell
import theme as tz


def render() -> None:
    bento.header(
        i18n.page("sen"),
        "Długość snu to jedna liczba; regularność, struktura nocy i moment wyciszenia organizmu mówią więcej.",
    )
    _headline()

    left, right = bento.row(2, 2)
    with left:
        _window()
    with right:
        _regularity()
        _thirds()

    _night()

    left, right = bento.row(2, 2)
    with left:
        _profile()
    with right:
        _daymap()


def _headline() -> None:
    sri = shell.table("sleep_regularity")
    circ = shell.table("circadian")
    if sri.empty and circ.empty:
        shell.missing("sleep_regularity", "Potrzebne noce z hipnogramem.")
        return
    columns = bento.row(1, 1, 1, 1)
    last = sri.dropna(subset=["sri_30d"]).tail(1) if not sri.empty else sri
    if not last.empty:
        bento.stat(columns[0], "SRI (30 nocy)", f"{last['sri_30d'].iloc[0]:.0f} / 100", key="sri",
                   help=glossary.short("sri"))
    else:
        bento.empty_stat(columns[0], "sri")
    mid = pd.to_numeric(circ.get("midpoint_hour"), errors="coerce").dropna() if not circ.empty else pd.Series()
    if not mid.empty:
        hour = float(mid.tail(30).mean()) % 24
        bento.stat(columns[1], "Środek snu (30 nocy)", f"{int(hour):02d}:{int((hour % 1) * 60):02d}",
                   key="midpoint", help=glossary.short("midpoint"))
    else:
        bento.empty_stat(columns[1], "midpoint")
    sd = pd.to_numeric(circ.get("midpoint_sd_30d"), errors="coerce").dropna() if not circ.empty else pd.Series()
    if not sd.empty:
        bento.stat(columns[2], "Rozrzut środka snu", f"±{sd.iloc[-1]:.1f} h", key="midpoint_sd",
                   help=glossary.short("midpoint"))
    else:
        bento.empty_stat(columns[2], "midpoint_sd")
    weekend = circ.groupby("is_weekend")["midpoint_hour"].mean() if not circ.empty else pd.Series()
    if len(weekend) == 2:
        bento.stat(columns[3], "Social jetlag", f"{float(weekend.loc[True] - weekend.loc[False]):+.2f} h",
                   key="jetlag", help=glossary.short("social_jetlag"))
    else:
        bento.empty_stat(columns[3], "jetlag")


def _window() -> None:
    circ = shell.clip(shell.table("circadian"))
    with bento.tile("Okno snu", rows=2, key="sleep_window",
                    caption="Równe słupki w jednej linii to regularny rytm.",
                    how="Każdy słupek to jedna noc: od zaśnięcia do wybudzenia, wieczór u góry. "
                        "Ostatnia noc jest wyróżniona.") as t:
        if circ.empty:
            shell.missing("circadian", "Potrzebne noce z hipnogramem.")
            return
        frame = circ.copy()
        bed = pd.to_datetime(frame["bedtime"])
        wake = pd.to_datetime(frame["waketime"])
        frame["bed"] = pd.to_numeric(frame["bed_hour_cont"], errors="coerce")
        frame["wake"] = frame["bed"] + (wake - bed).dt.total_seconds() / 3600
        t.chart(tz.range_bars(frame, "day", "bed", "wake", clock=True),
                table=frame[["day", "bed_hour_cont", "wake_hour", "midpoint_hour", "midpoint_sd_30d"]].tail(30))


def _regularity() -> None:
    sri = shell.table("sleep_regularity")
    with bento.tile("Regularność snu (SRI)", key="sri_trend", terms=["sri", "midpoint", "social_jetlag"],
                    caption="Stałe pory snu poprawiają sen niezależnie od jego długości.",
                    how=glossary.TREND_HOW) as t:
        if sri.empty:
            shell.missing("sleep_regularity")
            return
        t.chart(tz.trend(shell.clip(sri), "day", {"SRI": ("sri_pair", "sri_30d")}, smooth_label="średnia 30 nocy"),
                table=sri.tail(30))


def _thirds() -> None:
    profile = shell.clip(shell.table("night_profile"))
    with bento.tile("HRV w ciągu nocy", key="hrv_thirds", terms=["hrv_slope"],
                    caption="Koniec nocy powyżej początku = noc nadrabiała.",
                    how="Pierwsza i ostatnia trzecia nocy. " + glossary.TREND_HOW) as t:
        if profile.empty:
            shell.missing("night_profile")
            return
        thirds = profile.sort_values("day").copy()
        for column in ("hrv_first_third", "hrv_last_third"):
            thirds[f"{column}_roll7"] = pd.to_numeric(thirds[column], errors="coerce").rolling(7, min_periods=3).mean()
        t.chart(tz.trend(thirds, "day", {"początek": ("hrv_first_third", "hrv_first_third_roll7"),
                                         "koniec": ("hrv_last_third", "hrv_last_third_roll7")}),
                table=thirds[["day", "hrv_first_third", "hrv_last_third"]].tail(30))


@st.fragment
def _night() -> None:
    """One night: hypnogram and the overnight series share the night picker,
    so the whole row is one fragment and changing the night redraws only it."""
    stages = shell.table("sleep_stages")
    if stages.empty:
        shell.missing("sleep_stages")
        return
    frame = stages.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    available = sorted(frame["day"].dt.date.unique(), reverse=True)
    chosen = st.session_state.get("night_pick", available[0])
    if chosen not in available:
        chosen = available[0]

    left, right = bento.row(2, 2)
    with left:
        with bento.tile("Hipnogram", key="hypnogram", terms=["sleep_stages"], caption=_night_caption(chosen)) as t:
            with t.header:
                chosen = st.selectbox("Noc", available, index=available.index(chosen), key="night_pick",
                                      label_visibility="collapsed", width=140)
            night = frame[frame["day"].dt.date == chosen].copy()
            figure, summary = _hypnogram(night)
            t.chart(figure, table=summary, key=f"hypno_{chosen}")
        _stage_share(frame)
    with right:
        with bento.tile("Przebieg nocy", rows=2, key="night_series",
                        caption="Każda metryka na własnym panelu, wspólna oś czasu.") as t:
            t.chart(_night_panels(chosen), key=f"night_{chosen}", empty="Brak próbek nocnych dla tej nocy.")


def _night_caption(day) -> str | None:
    profile = shell.table("night_profile")
    if profile.empty:
        return None
    row = profile[pd.to_datetime(profile["day"]).dt.date == day]
    if row.empty:
        return None
    row = row.iloc[0]
    parts = [f"tętno min <b>{row['hr_min']:.0f}</b>", f"nadir po {row['nadir_at_pct']:.0f}% nocy"]
    if pd.notna(row.get("hrv_slope_per_h")):
        parts.append(f"HRV {row['hrv_slope_per_h']:+.1f}/h")
    return " · ".join(parts)


def _hypnogram(night: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    night["start_local"] = pd.to_datetime(night["start_local"])
    night["end_local"] = pd.to_datetime(night["end_local"])
    tokens = tz.tokens()
    colours = tz.sleep_stage_colors()
    levels = {"deep": 0, "light": 1, "rem": 2, "awake": 3}
    figure = go.Figure()
    for row in night.itertuples(index=False):
        level = levels.get(row.stage, 0)
        figure.add_scatter(
            x=[row.start_local, row.end_local], y=[level, level], mode="lines",
            line=dict(width=14, color=colours.get(row.stage, tokens["muted"])),
            name=tz.sleep_stage_labels().get(row.stage, row.stage), showlegend=False,
            hovertemplate=f"{tz.sleep_stage_labels().get(row.stage, row.stage)}: {row.minutes} min<extra></extra>",
        )
    figure.update_layout(**tz.base_layout(legend=False, height=200, hover="closest"))
    figure.update_yaxes(tickmode="array", tickvals=[0, 1, 2, 3],
                        ticktext=[tz.sleep_stage_labels()[s] for s in tz.SLEEP_STAGE_ORDER], showgrid=False)
    summary = (
        night.groupby("stage")["minutes"].sum().reindex(tz.SLEEP_STAGE_ORDER).dropna()
        .rename_axis("faza").reset_index(name="minuty")
    )
    summary["faza"] = summary["faza"].map(tz.sleep_stage_labels())
    return tz.local_dates(tz.style_axes(figure), night["start_local"]), summary


def _night_panels(day) -> go.Figure | None:
    nights = shell.table("night_series")
    if nights.empty:
        return None
    series = nights.copy()
    series["day"] = pd.to_datetime(series["day"])
    series = series[(series["day"].dt.date == day) & series["metric"].isin(["hr", "hrv", "body_battery", "stress"])]
    if series.empty:
        return None
    series["t_local"] = pd.to_datetime(series["t_local"])
    wide = series.pivot_table(index="t_local", columns="metric", values="value", aggfunc="mean").reset_index()
    panels = [
        {"title": title, "series": {title: column}, "kind": "line"}
        for column, title in (("hr", "Tętno (bpm)"), ("hrv", "HRV (ms)"), ("body_battery", "Body Battery"),
                              ("stress", "Stres"))
        if column in wide.columns and wide[column].notna().any()
    ]
    return tz.stacked_panels(wide, "t_local", panels, height=400)


def _stage_share(frame: pd.DataFrame) -> None:
    with bento.tile("Struktura snu w czasie", key="stage_share", terms=["sleep_stages"],
                    caption="Udział faz w nocy, średnia z 7 nocy.") as t:
        pivot = frame.groupby([frame["day"].dt.date, "stage"])["minutes"].sum().unstack(fill_value=0)
        columns = [s for s in tz.SLEEP_STAGE_ORDER if s in pivot.columns]
        share = pivot[columns].div(pivot[columns].sum(axis=1), axis=0).mul(100)
        share = share.rolling(7, min_periods=3).mean().dropna().round(1)
        share.index = pd.to_datetime(share.index)
        share = shell.clip(share.rename_axis("day").reset_index())
        t.chart(tz.stacked(share, "day", columns, tz.sleep_stage_labels(), y_title="% nocy",
                           colors=tz.sleep_stage_colors(), area=True),
                table=share.tail(30))


def _profile() -> None:
    profile = shell.table("night_profile")
    with bento.tile(
        "Profil nocy", rows=2, key="night_profile", terms=["night_profile", "hrv_slope"],
        caption="Nadir tętna wcześnie = szybkie wyciszenie; późno = regeneracja trwała do budzika.",
        how="Każdy punkt to noc: kiedy wypadło minimum tętna (oś pozioma) i jak Garmin ocenił sen (pionowa).",
    ) as t:
        if profile.empty:
            shell.missing("night_profile", "Potrzebne noce z zapisem tętna i HRV.")
            return
        view = shell.clip(profile)
        t.chart(tz.scatter(view, "nadir_at_pct", "sleep_score", hover=("day", "hr_min", "sleep_h", "readiness"),
                           x_title="nadir tętna (% nocy)", y_title="sleep score"),
                table=view[["day", "hr_min", "hr_drop", "nadir_at_pct", "hrv_trend", "sleep_score"]]
                .sort_values("day", ascending=False).head(30))


@st.fragment
def _daymap() -> None:
    intraday = shell.table("intraday")
    with bento.tile(
        "Mapa doby", rows=2, key="daymap", terms=["stress", "body_battery"],
        caption="Wiersz to dzień, kolumna pół godziny; próbki co 3 min.",
        how="Pionowe pasy to rytm dobowy, poziome — dni odstające.",
    ) as t:
        if intraday.empty:
            shell.missing("intraday", "Pobierz metrykę `stress` (3-minutowe próbki stresu i Body Battery).")
            return
        with t.header:
            what = st.segmented_control(
                "Metryka", ["stress", "body_battery"], default="stress", label_visibility="collapsed",
                format_func=lambda v: {"stress": "stres", "body_battery": "BB"}[v], key="daymap_metric",
            ) or "stress"
        frame = intraday.copy()
        frame["day"] = pd.to_datetime(frame["day"])
        heat = shell.clip(frame)
        heat["hour_bin"] = (pd.to_numeric(heat["hour"], errors="coerce") * 2).round() / 2
        grid = heat.pivot_table(index=heat["day"].dt.date, columns="hour_bin", values=what, aggfunc="mean").round(1)
        grid = grid.sort_index(ascending=False)  # newest day on top
        figure = tz.heatmap(grid, kind="sequential", x_title="godzina doby",
                            color_title="stres" if what == "stress" else "Body Battery")
        if figure is not None:
            figure.update_xaxes(tickmode="array", tickvals=list(range(0, 24, 3)),
                                ticktext=[f"{h:02d}:00" for h in range(0, 24, 3)])
        t.chart(figure, key=f"daymap_{what}")
