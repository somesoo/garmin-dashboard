"""Disciplines: how varied the training has been and what is left to discover."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import i18n
import shell
import theme as tz
from sport import catalog, text, variety
from views import sport as sp


def render() -> None:
    tr = i18n.tr
    bento.header(i18n.page("dyscypliny"), tr(
        pl="Na co idzie czas, jak różnorodnie się ruszasz i co z katalogu jeszcze czeka — z tym, co trenuje "
           "i czego wymaga.",
        en="Where the time goes, how varied your movement is and what in the catalogue is still waiting — with "
           "what it trains and what it needs."))
    sessions = sp.frame()
    if sessions.empty:
        shell.missing("activities")
        return
    now = pd.Timestamp.now().floor("min")
    span = shell.window_days() or int((now - sessions["start_local"].min()).days) + 1
    part = variety.window(sessions, now, span)
    _kpis(part, sessions, now)

    weeks = max(4, min(104, span // 7))
    mix, columns = variety.weekly_mix(sessions, now, weeks)
    with bento.tile(tr(pl="Godziny tygodniowo", en="Hours per week"), rows=2, key="disc_weekly",
                    terms=["sport_variety"],
                    caption=tr(pl="Dwie dyscypliny z największą liczbą godzin w zakresie, reszta razem.",
                               en="The two disciplines with the most hours in the range, the rest together.")) as t:
        labels = {c: (tr(pl="pozostałe", en="other") if c == "other" else catalog.label(c)) for c in columns}
        fig = tz.stacked(mix, "week", columns, labels, y_title="h",
                         colors=dict(zip(columns, tz.series_colors(len(columns))))) if columns else None
        t.chart(fig, table=mix.rename(columns=labels) if columns else None)

    left, right = bento.row(2, 2)
    with left, bento.tile(tr(pl="Godziny według dyscypliny", en="Hours by discipline"), rows=2, key="disc_hours",
                          caption=tr(pl="W wybranym zakresie czasu.", en="In the selected time range.")) as t:
        hours = (part.groupby("discipline")["minutes"].sum() / 60).round(1).reset_index()
        hours["discipline"] = hours["discipline"].map(catalog.label)
        hours = hours.sort_values("minutes", ascending=False).head(12)
        t.chart(tz.hbars(hours, "discipline", "minutes", unit="h", decimals=1, height=bento.chart_height(2)),
                table=hours.rename(columns={"minutes": "h"}))
    with right, bento.tile(tr(pl="Różnorodność, rok", en="Variety, a year"), rows=2, key="disc_diversity",
                           terms=["sport_variety"], how=tr(
                               pl="Każdy punkt to 28 dni kończące się w danym tygodniu; linia to średnia z 4 punktów.",
                               en="Each point is the 28 days ending that week; the line is the mean of 4 points.")) as t:
        series = variety.diversity(sessions, now, 52)
        series["smooth"] = series["diversity"].rolling(4, min_periods=2).mean()
        fig = tz.trend(series, "day", {tr(pl="dyscypliny efektywnie", en="effective disciplines"):
                                       ("diversity", "smooth")}, decimals=1,
                       smooth_label=tr(pl="średnia 4 tyg.", en="4-week mean"))
        t.chart(fig, table=series)

    _yours(sessions, now)
    _discover(sessions, now)


def _kpis(part: pd.DataFrame, sessions: pd.DataFrame, now: pd.Timestamp) -> None:
    tr = i18n.tr
    columns = bento.row(1, 1, 1, 1)
    count = part["discipline"].nunique()
    bento.stat(columns[0], tr(pl="Dyscypliny w zakresie", en="Disciplines in range"), f"{count}",
               key="disc_count")
    recent = variety.window(sessions, now, 28)
    bento.stat(columns[1], tr(pl="Różnorodność 28 d", en="Variety 28 d"),
               f"{variety.effective_number(recent.groupby('discipline')['minutes'].sum()):.1f}", key="disc_effective",
               help=tr(pl="Efektywna liczba dyscyplin w 28 dniach.", en="Effective number of disciplines in 28 days."))
    bento.stat(columns[2], tr(pl="Godziny w zakresie", en="Hours in range"), f"{part['minutes'].sum() / 60:.0f}",
               key="disc_hours_total")
    total = part["minutes"].sum()
    top = part.groupby("discipline")["minutes"].sum().sort_values(ascending=False)
    share = f"{top.iloc[0] / total:.0%}" if total else "—"
    bento.stat(columns[3], tr(pl="Udział głównej", en="Main one's share"), share,
               catalog.label(top.index[0]) if len(top) else None, key="disc_top")


def _yours(sessions: pd.DataFrame, now: pd.Timestamp) -> None:
    tr = i18n.tr
    done = variety.last_done(sessions, now)
    with bento.panel(tr(pl="Twoje dyscypliny", en="Your disciplines"), key="disc_yours",
                     caption=tr(pl="Od najświeższej. Godziny i liczba sesji z całej historii.",
                                en="Most recent first. Hours and session counts over the whole record.")):
        table = pd.DataFrame({
            tr(pl="dyscyplina", en="discipline"): done["discipline"].map(catalog.label),
            tr(pl="rodzina", en="family"): done["discipline"].map(
                lambda k: catalog.family_label(catalog.get(k).family) if k in catalog.DISCIPLINES else "—"),
            tr(pl="ostatnio", en="last"): done["days_ago"].map(text.ago),
            tr(pl="sesje", en="sessions"): done["sessions"],
            tr(pl="w roku", en="in a year"): done["sessions_365"],
            "h": done["hours"],
        })
        st.dataframe(table, width="stretch", hide_index=True, height=bento.table_height(len(table)))


def _discover(sessions: pd.DataFrame, now: pd.Timestamp) -> None:
    tr = i18n.tr
    tried = set(sessions["discipline"])
    with bento.panel(tr(pl="Do odkrycia", en="To discover"), key="disc_discover", terms=["sport_conditions"],
                     caption=tr(pl="Dyscypliny z katalogu, których zegarek jeszcze u ciebie nie widział.",
                                en="Catalogue disciplines your watch has not seen you do yet.")):
        families = st.pills(tr(pl="Rodzina", en="Family"), catalog.FAMILIES, selection_mode="multi",
                            format_func=catalog.family_label, key="disc_family", label_visibility="collapsed")
        rows = []
        for key, d in catalog.DISCIPLINES.items():
            if key in tried or (families and d.family not in families):
                continue
            trains = sorted(d.trains, key=d.trains.get, reverse=True)[:2]
            needs = ", ".join(catalog.condition_label(n) for n in d.needs) or "—"
            season = tr(pl="cały rok", en="all year") if d.months is None else \
                f"{i18n.months()[d.months[0] - 1]}–{i18n.months()[d.months[-1] - 1]}"
            rows.append({
                tr(pl="dyscyplina", en="discipline"): catalog.label(key),
                tr(pl="po co", en="why"): catalog.blurb(key),
                tr(pl="trenuje", en="trains"): ", ".join(catalog.quality_label(q) for q in trains),
                tr(pl="potrzeba", en="needs"): needs,
                tr(pl="sezon", en="season"): season,
                tr(pl="wyjazd", en="trip"): "✓" if set(d.needs) & set(catalog.TRAVEL) else "",
            })
        if not rows:
            st.caption(tr(pl="Wszystko z tej rodziny już próbowałeś.", en="You have tried everything in this family."))
            return
        table = pd.DataFrame(rows)
        st.dataframe(table, width="stretch", hide_index=True, height=bento.table_height(len(table)))
