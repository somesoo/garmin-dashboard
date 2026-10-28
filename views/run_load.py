"""Running load: weekly volume, intensity balance, ramp and breaks."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import shell
import theme as tz
from running import sessions
from views import run_common as rc


def render() -> None:
    tr = i18n.tr
    bento.header(
        i18n.page("obciazenie-biegowe"),
        tr(pl="Wskaźniki pomagają zdecydować, czy dołożyć, czy odpuścić — nie diagnozują przetrenowania ani "
              "kontuzji. Ból, który zmienia sposób biegania, jest ważniejszy niż każdy wykres tutaj.",
           en="The indicators help decide whether to add or back off — they do not diagnose overtraining or injury. "
              "Pain that changes the way you run matters more than any chart here."),
    )
    frame = rc.guard()
    if frame is None:
        return
    weeks = shell.clip(sessions.weekly(frame), "week")
    if weeks.empty:
        st.caption(tr(pl="Brak biegów w wybranym zakresie.", en="No runs in the selected range."))
        return

    edge = shell.cutoff()
    info = sessions.gaps(frame, edge if edge is not None else frame["day"].min(), frame["day"].max())
    columns = bento.row(1, 1, 1, 1)
    def days(n: int) -> str:
        return f"{n} {i18n.plural(n, pl=('dzień', 'dni', 'dni'), en=('day', 'days'))}"

    bento.stat(columns[0], tr(pl="Dni z biegiem", en="Days with a run"), f"{info['run_days']}", key="run_days",
               note=tr(pl="w wybranym zakresie", en="in the selected range"))
    bento.stat(columns[1], tr(pl="Dni bez biegu", en="Days without a run"), f"{info['rest_days']}", key="rest_days")
    bento.stat(columns[2], tr(pl="Najdłuższa przerwa", en="Longest break"), days(info["longest_break"]),
               key="longest_break")
    bento.stat(columns[3], tr(pl="Od ostatniego biegu", en="Since the last run"), days(info["days_since_last"]),
               key="since_last")

    left, right = bento.row(2, 2)
    with left:
        _volume(weeks)
    with right:
        _ratio(frame)
        _intensity(weeks)

    left, right = bento.row(2, 2)
    with left:
        _recovery()
    with right:
        _breaks(frame, edge)


def _volume(weeks: pd.DataFrame) -> None:
    change = weeks["km"].pct_change().replace([float("inf")], pd.NA)
    jumps = weeks[(change > 0.3) & (weeks["km"] >= 15)]
    tr = i18n.tr
    with bento.tile(
        tr(pl="Kilometry i najdłuższy bieg", en="Kilometres and the longest run"), rows=2, key="load_volume",
        caption=(tr(pl="skoki > 30%: ", en="jumps > 30%: ") + ", ".join(jumps["iso_week"].tail(4)))
        if not jumps.empty else tr(pl="Długi bieg powinien rosnąć razem z objętością.",
                                   en="The long run should grow together with volume."),
        how=tr(pl="Dwa panele na wspólnej osi czasu: objętość tygodnia (linia: średnia 4 tyg.) i najdłuższy bieg. "
                  "Skok samego długiego biegu przy płaskiej objętości to typowe ryzyko. Pojedynczy skok objętości "
                  "po lżejszym tygodniu jest normalny; seria skoków — nie.",
               en="Two panels on a shared time axis: weekly volume (line: 4-week average) and the longest run. "
                  "A jump in the long run alone with flat volume is the typical risk. A single jump in volume after "
                  "a lighter week is normal; a series of jumps is not."),
    ) as t:
        view = weeks.assign(km_4w=weeks["km"].rolling(4, min_periods=2).mean().round(1))
        longest = tr(pl="najdłuższy", en="longest")
        figure = tz.stacked_panels(
            view, "week",
            [
                {"title": tr(pl="km / tydzień", en="km / week"), "series": {"km": "km"}, "kind": "bar",
                 "height": 1.3},
                {"title": tr(pl="najdłuższy bieg (km)", en="longest run (km)"), "series": {longest: "long_km"},
                 "kind": "bar", "height": 0.8},
            ],
            height=400,
        )
        if figure is not None:
            # The 4-week mean reads better as a line over the bars than as a second bar.
            line = view.dropna(subset=["km_4w"])
            mean = tr(pl="średnia 4 tyg.", en="4-week mean")
            figure.add_scatter(x=line["week"], y=line["km_4w"], mode="lines", name=mean,
                               line=dict(width=2.2, color=tz.tokens()["series"][1]), showlegend=False,
                               hovertemplate=f"%{{y:.1f}} km<extra>{mean}</extra>", row=1, col=1)
        t.chart(figure, table=view[["iso_week", "km", "km_4w", "long_km", "runs", "hours"]]
                .sort_values("iso_week", ascending=False))


def _intensity(weeks: pd.DataFrame) -> None:
    recent = weeks.tail(4)
    tr = i18n.tr
    hard = f"<b>{recent['hard'].mean():.1f}</b>"
    with bento.tile(
        tr(pl="Balans: % kilometrów spokojnie", en="Balance: % of kilometres easy"), key="load_intensity",
        terms=["quality_sessions", "run_kind"],
        caption=tr(pl=f"pas 75–80% · mocnych sesji: {hard}/tydz. (4 tyg.)",
                   en=f"band 75–80% · quality sessions: {hard}/week (4 weeks)"),
        how=tr(pl="Udział spokojnych kilometrów w tygodniu. Strefy tętna (wszystkie sporty) są na stronie Fizjologia.",
               en="The share of easy kilometres in the week. Heart rate zones (all sports) are on the Physiology "
                  "page."),
    ) as t:
        figure = tz.timeseries(weeks, "week", {tr(pl="% spokojnie", en="% easy"): "easy_km_pct"}, markers=True,
                               end_labels=True)
        if figure is not None:
            tz.band(figure, 75, 80)
        t.chart(figure, table=weeks[["iso_week", "hard", "easy_km_pct"]].sort_values("iso_week", ascending=False))


def _ratio(frame: pd.DataFrame) -> None:
    ratio = shell.clip(sessions.km_ratio(frame))
    tr = i18n.tr
    with bento.tile(
        tr(pl="Tempo przyrostu (km 7 d / 28 d)", en="Rate of increase (km 7 d / 28 d)"), key="load_ratio",
        terms=["run_ratio"],
        caption=tr(pl="Pas 0,8–1,3 to stopniowy przyrost — opis, nie granica bezpieczeństwa.",
                   en="The 0.8–1.3 band is a gradual increase — a description, not a safety limit."),
        how=tr(pl="Przy średniej z 28 dni poniżej 5 km/tydz. iloraz nie jest liczony — po przerwie każdy bieg "
                  "dawałby „skok”. Obciążenie wszystkich sportów jest na stronie Forma.",
               en="With a 28-day average below 5 km/week the ratio is not computed — after a break every run "
                  "would be a “jump”. Load across all sports is on the Form page."),
    ) as t:
        with t.header:
            if st.button("", icon=":material/arrow_forward:", type="tertiary", key="load_to_form",
                         help=tr(pl="Obciążenie wszystkich sportów (Forma)", en="Load across all sports (Form)")):
                routing.goto("forma")
        ratio_label = tr(pl="iloraz", en="ratio")
        figure = tz.timeseries(ratio, "day", {ratio_label: "ratio"}, y_title=ratio_label, end_labels=True,
                               decimals=2)
        if figure is not None:
            tz.band(figure, 0.8, 1.3)
            tz.threshold(figure, 1.5, label="1.5")
        t.chart(figure, table=ratio[["day", "acute_km", "chronic_km", "ratio"]].dropna().tail(30))


def _breaks(frame: pd.DataFrame, edge) -> None:
    days = pd.Series(sorted(frame["day"].unique()))
    gaps = days.diff().dt.days.dropna()
    breaks = pd.DataFrame({"od": days.shift(1), "do": days, "dni": days.diff().dt.days})
    breaks = breaks[(breaks["dni"] >= 10)]
    if edge is not None:
        breaks = breaks[breaks["do"] >= edge]
    tr = i18n.tr
    with bento.tile(
        tr(pl="Przerwy ≥ 10 dni", en="Breaks ≥ 10 days"), rows=2, key="breaks",
        caption=tr(pl=f"Typowy odstęp między biegami: {gaps.median():.0f} dni.",
                   en=f"Typical gap between runs: {gaps.median():.0f} days.") if len(gaps) else None,
        how=tr(pl="Po przerwie ≥ 10 dni dobrze wrócić od ~70% wcześniejszej objętości.",
               en="After a break of ≥ 10 days it is good to return at ~70% of the earlier volume."),
    ) as t:
        if breaks.empty:
            st.caption(tr(pl="Bez przerw ≥ 10 dni w tym zakresie.", en="No breaks of ≥ 10 days in this range."))
            return
        breaks = breaks.sort_values("do", ascending=False)
        t.table(
            pd.DataFrame({
                tr(pl="ostatni bieg przed", en="last run before"): pd.to_datetime(breaks["od"]).dt.strftime("%d.%m.%Y"),
                tr(pl="pierwszy po", en="first after"): pd.to_datetime(breaks["do"]).dt.strftime("%d.%m.%Y"),
                tr(pl="dni przerwy", en="days off"): (breaks["dni"] - 1).astype(int),
            }),
        )


def _recovery() -> None:
    daily = shell.clip(shell.daily())
    columns = [c for c in ("readiness", "hrv_deviation", "sleep_h") if c in daily.columns]
    tr = i18n.tr
    with bento.tile(
        tr(pl="Regeneracja w tle", en="Recovery in the background"), rows=2, key="load_recovery",
        terms=["readiness", "hrv", "deviation"],
        caption=tr(pl="Obciążenie czytane razem z odpowiedzią organizmu.",
                   en="Load read together with the body's response."),
        how=tr(pl="Gotowość Garmina i HRV względem własnej średniej 7 d. Pełna analiza: strona Regeneracja.",
               en="Garmin readiness and HRV against your own 7-day average. The full analysis: the Recovery page."),
    ) as t:
        if daily.empty or not columns or daily[columns].notna().sum().max() < 7:
            st.caption(tr(pl="Brak danych o regeneracji (gotowość, HRV, sen) w tym zakresie.",
                          en="No recovery data (readiness, HRV, sleep) in this range."))
            return
        t.chart(tz.stacked_panels(
            daily, "day",
            [
                {"title": tr(pl="gotowość treningowa", en="training readiness"),
                 "series": {tr(pl="gotowość", en="readiness"): "readiness"}, "kind": "line"},
                {"title": tr(pl="HRV — odchylenie od średniej 7 d", en="HRV — deviation from the 7-day mean"),
                 "series": {"HRV Δ": "hrv_deviation"}, "kind": "bar"},
            ],
            height=360,
        ), table=daily[["day", "readiness", "hrv_deviation"]].tail(40))
