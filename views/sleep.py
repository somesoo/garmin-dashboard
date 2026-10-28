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
        i18n.tr(pl="Długość snu to jedna liczba; regularność, struktura nocy i moment wyciszenia organizmu mówią "
                   "więcej.",
                en="Sleep length is one number; regularity, the structure of the night and the moment the body "
                   "settles say more."),
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
        shell.missing("sleep_regularity", _needs_hypnogram())
        return
    tr = i18n.tr
    columns = bento.row(1, 1, 1, 1)
    last = sri.dropna(subset=["sri_30d"]).tail(1) if not sri.empty else sri
    if not last.empty:
        bento.stat(columns[0], tr(pl="SRI (30 nocy)", en="SRI (30 nights)"), f"{last['sri_30d'].iloc[0]:.0f} / 100",
                   key="sri",
                   help=glossary.short("sri"))
    else:
        bento.empty_stat(columns[0], "sri")
    mid = pd.to_numeric(circ.get("midpoint_hour"), errors="coerce").dropna() if not circ.empty else pd.Series()
    if not mid.empty:
        hour = float(mid.tail(30).mean()) % 24
        bento.stat(columns[1], tr(pl="Środek snu (30 nocy)", en="Sleep midpoint (30 nights)"),
                   f"{int(hour):02d}:{int((hour % 1) * 60):02d}",
                   key="midpoint", help=glossary.short("midpoint"))
    else:
        bento.empty_stat(columns[1], "midpoint")
    sd = pd.to_numeric(circ.get("midpoint_sd_30d"), errors="coerce").dropna() if not circ.empty else pd.Series()
    if not sd.empty:
        bento.stat(columns[2], tr(pl="Rozrzut środka snu", en="Midpoint spread"), f"±{sd.iloc[-1]:.1f} h",
                   key="midpoint_sd",
                   help=glossary.short("midpoint"))
    else:
        bento.empty_stat(columns[2], "midpoint_sd")
    weekend = circ.groupby("is_weekend")["midpoint_hour"].mean() if not circ.empty else pd.Series()
    if len(weekend) == 2:
        bento.stat(columns[3], "Social jetlag", f"{float(weekend.loc[True] - weekend.loc[False]):+.2f} h",
                   key="jetlag", help=glossary.short("social_jetlag"))
    else:
        bento.empty_stat(columns[3], "jetlag")


def _needs_hypnogram() -> str:
    return i18n.tr(pl="Potrzebne noce z hipnogramem.", en="Needs nights with a hypnogram.")


def _window() -> None:
    tr = i18n.tr
    circ = shell.clip(shell.table("circadian"))
    with bento.tile(tr(pl="Okno snu", en="Sleep window"), rows=2, key="sleep_window",
                    caption=tr(pl="Równe słupki w jednej linii to regularny rytm.",
                               en="Even bars in one line are a regular rhythm."),
                    how=tr(pl="Każdy słupek to jedna noc: od zaśnięcia do wybudzenia, wieczór u góry. "
                              "Ostatnia noc jest wyróżniona.",
                           en="Each bar is one night: from falling asleep to waking up, evening on top. "
                              "The last night is highlighted.")) as t:
        if circ.empty:
            shell.missing("circadian", _needs_hypnogram())
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
    tr = i18n.tr
    with bento.tile(tr(pl="Regularność snu (SRI)", en="Sleep regularity (SRI)"), key="sri_trend",
                    terms=["sri", "midpoint", "social_jetlag"],
                    caption=tr(pl="Stałe pory snu poprawiają sen niezależnie od jego długości.",
                               en="Steady sleep times improve sleep regardless of its length."),
                    how=glossary.trend_how()) as t:
        if sri.empty:
            shell.missing("sleep_regularity")
            return
        t.chart(tz.trend(shell.clip(sri), "day", {"SRI": ("sri_pair", "sri_30d")},
                         smooth_label=tr(pl="średnia 30 nocy", en="30-night mean")),
                table=sri.tail(30))


def _thirds() -> None:
    profile = shell.clip(shell.table("night_profile"))
    tr = i18n.tr
    with bento.tile(tr(pl="HRV w ciągu nocy", en="HRV through the night"), key="hrv_thirds", terms=["hrv_slope"],
                    caption=tr(pl="Koniec nocy powyżej początku = noc nadrabiała.",
                               en="End of the night above the start = the night was catching up."),
                    how=tr(pl="Pierwsza i ostatnia trzecia nocy. ", en="The first and last third of the night. ")
                    + glossary.trend_how()) as t:
        if profile.empty:
            shell.missing("night_profile")
            return
        thirds = profile.sort_values("day").copy()
        for column in ("hrv_first_third", "hrv_last_third"):
            thirds[f"{column}_roll7"] = pd.to_numeric(thirds[column], errors="coerce").rolling(7, min_periods=3).mean()
        t.chart(tz.trend(thirds, "day", {tr(pl="początek", en="start"): ("hrv_first_third", "hrv_first_third_roll7"),
                                         tr(pl="koniec", en="end"): ("hrv_last_third", "hrv_last_third_roll7")}),
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
        with bento.tile(i18n.tr(pl="Hipnogram", en="Hypnogram"), key="hypnogram", terms=["sleep_stages"],
                        caption=_night_caption(chosen)) as t:
            with t.header:
                chosen = st.selectbox(i18n.tr(pl="Noc", en="Night"), available, index=available.index(chosen),
                                      key="night_pick",
                                      label_visibility="collapsed", width=140)
            night = frame[frame["day"].dt.date == chosen].copy()
            figure, summary = _hypnogram(night)
            t.chart(figure, table=summary, key=f"hypno_{chosen}")
        _stage_share(frame)
    with right:
        with bento.tile(i18n.tr(pl="Przebieg nocy", en="The night as it went"), rows=2, key="night_series",
                        caption=i18n.tr(pl="Każda metryka na własnym panelu, wspólna oś czasu.",
                                        en="Each metric on its own panel, a shared time axis.")) as t:
            t.chart(_night_panels(chosen), key=f"night_{chosen}",
                    empty=i18n.tr(pl="Brak próbek nocnych dla tej nocy.", en="No overnight samples for this night."))


def _night_caption(day) -> str | None:
    profile = shell.table("night_profile")
    if profile.empty:
        return None
    row = profile[pd.to_datetime(profile["day"]).dt.date == day]
    if row.empty:
        return None
    row = row.iloc[0]
    parts = [i18n.tr(pl=f"tętno min <b>{row['hr_min']:.0f}</b>", en=f"min HR <b>{row['hr_min']:.0f}</b>"),
             i18n.tr(pl=f"nadir po {row['nadir_at_pct']:.0f}% nocy",
                     en=f"nadir at {row['nadir_at_pct']:.0f}% of the night")]
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
    stage = i18n.tr(pl="faza", en="stage")
    summary = (
        night.groupby("stage")["minutes"].sum().reindex(tz.SLEEP_STAGE_ORDER).dropna()
        .rename_axis(stage).reset_index(name=i18n.tr(pl="minuty", en="minutes"))
    )
    summary[stage] = summary[stage].map(tz.sleep_stage_labels())
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
        for column, title in (("hr", i18n.tr(pl="Tętno (bpm)", en="Heart rate (bpm)")), ("hrv", "HRV (ms)"),
                              ("body_battery", "Body Battery"), ("stress", i18n.tr(pl="Stres", en="Stress")))
        if column in wide.columns and wide[column].notna().any()
    ]
    return tz.stacked_panels(wide, "t_local", panels, height=400)


def _stage_share(frame: pd.DataFrame) -> None:
    with bento.tile(i18n.tr(pl="Struktura snu w czasie", en="Sleep structure over time"), key="stage_share",
                    terms=["sleep_stages"],
                    caption=i18n.tr(pl="Udział faz w nocy, średnia z 7 nocy.",
                                    en="Share of stages in the night, 7-night average.")) as t:
        pivot = frame.groupby([frame["day"].dt.date, "stage"])["minutes"].sum().unstack(fill_value=0)
        columns = [s for s in tz.SLEEP_STAGE_ORDER if s in pivot.columns]
        share = pivot[columns].div(pivot[columns].sum(axis=1), axis=0).mul(100)
        share = share.rolling(7, min_periods=3).mean().dropna().round(1)
        share.index = pd.to_datetime(share.index)
        share = shell.clip(share.rename_axis("day").reset_index())
        t.chart(tz.stacked(share, "day", columns, tz.sleep_stage_labels(),
                           y_title=i18n.tr(pl="% nocy", en="% of night"),
                           colors=tz.sleep_stage_colors(), area=True),
                table=share.tail(30))


def _profile() -> None:
    profile = shell.table("night_profile")
    tr = i18n.tr
    with bento.tile(
        tr(pl="Profil nocy", en="Night profile"), rows=2, key="night_profile", terms=["night_profile", "hrv_slope"],
        caption=tr(pl="Nadir tętna wcześnie = szybkie wyciszenie; późno = regeneracja trwała do budzika.",
                   en="An early heart rate nadir = settling fast; late = recovery lasted until the alarm."),
        how=tr(pl="Każdy punkt to noc: kiedy wypadło minimum tętna (oś pozioma) i jak Garmin ocenił sen (pionowa).",
               en="Each point is a night: when the heart rate minimum came (horizontal axis) and how Garmin scored "
                  "the sleep (vertical)."),
    ) as t:
        if profile.empty:
            shell.missing("night_profile", tr(pl="Potrzebne noce z zapisem tętna i HRV.",
                                              en="Needs nights with heart rate and HRV recorded."))
            return
        view = shell.clip(profile)
        t.chart(tz.scatter(view, "nadir_at_pct", "sleep_score", hover=("day", "hr_min", "sleep_h", "readiness"),
                           x_title=tr(pl="nadir tętna (% nocy)", en="heart rate nadir (% of night)"),
                           y_title="sleep score"),
                table=view[["day", "hr_min", "hr_drop", "nadir_at_pct", "hrv_trend", "sleep_score"]]
                .sort_values("day", ascending=False).head(30))


@st.fragment
def _daymap() -> None:
    intraday = shell.table("intraday")
    tr = i18n.tr
    stress = tr(pl="stres", en="stress")
    with bento.tile(
        tr(pl="Mapa doby", en="Day map"), rows=2, key="daymap", terms=["stress", "body_battery"],
        caption=tr(pl="Wiersz to dzień, kolumna pół godziny; próbki co 3 min.",
                   en="A row is a day, a column half an hour; samples every 3 min."),
        how=tr(pl="Pionowe pasy to rytm dobowy, poziome — dni odstające.",
               en="Vertical stripes are the daily rhythm, horizontal ones — outlier days."),
    ) as t:
        if intraday.empty:
            shell.missing("intraday", tr(pl="Pobierz metrykę `stress` (3-minutowe próbki stresu i Body Battery).",
                                         en="Fetch the `stress` metric (3-minute stress and Body Battery samples)."))
            return
        with t.header:
            what = st.segmented_control(
                tr(pl="Metryka", en="Metric"), ["stress", "body_battery"], default="stress",
                label_visibility="collapsed",
                format_func=lambda v: {"stress": stress, "body_battery": "BB"}[v], key="daymap_metric",
            ) or "stress"
        frame = intraday.copy()
        frame["day"] = pd.to_datetime(frame["day"])
        heat = shell.clip(frame)
        heat["hour_bin"] = (pd.to_numeric(heat["hour"], errors="coerce") * 2).round() / 2
        grid = heat.pivot_table(index=heat["day"].dt.date, columns="hour_bin", values=what, aggfunc="mean").round(1)
        grid = grid.sort_index(ascending=False)  # newest day on top
        figure = tz.heatmap(grid, kind="sequential", x_title=tr(pl="godzina doby", en="hour of day"),
                            color_title=stress if what == "stress" else "Body Battery")
        if figure is not None:
            figure.update_xaxes(tickmode="array", tickvals=list(range(0, 24, 3)),
                                ticktext=[f"{h:02d}:00" for h in range(0, 24, 3)])
        t.chart(figure, key=f"daymap_{what}")
