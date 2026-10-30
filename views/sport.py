"""Sport: readiness for any training today and what to do next, across disciplines.

The engine is ``sport/`` (readiness, ranking, variety); this page draws it. It
reads the running plan only to say what is already planned today and to keep
the legs fresh before tomorrow's key run -- it never changes the plan.
"""

from __future__ import annotations

import datetime as dt
import html

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import shell
import theme as tz
from running import store as run_store
from sport import catalog, readiness, recommend, store, text, variety


@st.cache_data(show_spinner=False, max_entries=8)
def _sessions(build: str) -> pd.DataFrame:
    return readiness.sessions(shell.table("activities"))


@st.cache_data(show_spinner=False, max_entries=8)
def _history(build: str) -> pd.DataFrame:
    return readiness.history(shell.daily(), shell.table("activities"), 90)


def frame() -> pd.DataFrame:
    """Every activity with its discipline and load, cached per warehouse build."""
    return _sessions(shell.build_id())


def recent_disciplines(sessions: pd.DataFrame, now: pd.Timestamp) -> set[str]:
    return set(variety.window(sessions, now, 365)["discipline"])


def render() -> None:
    tr = i18n.tr
    today, now = dt.date.today(), pd.Timestamp.now().floor("min")
    bento.header(i18n.page("sport"), tr(
        pl="Gotowość na każdy trening, nie tylko bieg — i co z tego wynika: trzy pomysły z tego, co już uprawiasz, "
           "coś nowego do spróbowania i to, czego brakowało w ostatnich tygodniach.",
        en="Readiness for any training, not just a run — and what follows: three ideas from what you already do, "
           "something new to try and what the last weeks were missing."))
    sessions, days = frame(), shell.daily()
    state = readiness.assess(days, shell.table("activities"), today, now, frame=sessions)
    available = store.available(recent_disciplines(sessions, now))
    planned = recommend.from_plan(run_store.current_plan(), today)
    result = recommend.rank(state, sessions, today, available=available, before_key=planned["before_key"], now=now)
    chosen = recommend.picks(result, state["level"])
    trend = _history(shell.build_id())

    _kpis(state, sessions, now, trend)
    if state["stale_days"] is not None and state["stale_days"] > 1:
        st.caption(tr(pl=f"Ostatnia noc w danych jest sprzed {state['stale_days']} dni — gotowość liczy tylko "
                         "obciążenie. Zsynchronizuj zegarek.",
                      en=f"The last night in the data is {state['stale_days']} days old — readiness counts only the "
                         "load. Sync the watch."))

    left, right = bento.row(2, 2)
    with left, bento.tile(tr(pl="Co dziś", en="What today"), rows=2, key="sport_picks",
                          terms=["sport_pick", "sport_conditions"], caption=text.level_advice(state["level"])):
        _picks(chosen, planned)
    with right:
        with bento.tile(tr(pl="Z czego ta liczba", en="What the number is made of"), key="sport_parts",
                        terms=["sport_readiness"]):
            _parts(state)
        with bento.tile(tr(pl="Zmęczenie układów", en="Fatigue by body system"), key="sport_systems",
                        terms=["body_systems"], caption=_systems_note(state["systems"])) as t:
            _systems(t, state["systems"])

    left, right = bento.row(2, 2)
    with left, bento.tile(tr(pl="Gotowość, 90 dni", en="Readiness, 90 days"), key="sport_trend",
                          terms=["sport_readiness"], how=tr(
                              pl="Kropki to dni, linia to średnia 7 d; pas 52–68 to „umiarkowanie”, nad nim dzień "
                                 "na mocny trening, pod nim na spokojny.",
                              en="Dots are days, the line is the 7-day mean; the 52–68 band is “moderate”, above it "
                                 "a day for hard training, below it an easy one.")) as t:
        _trend(t, trend)
    with right, bento.tile(tr(pl="Czego brakowało w 28 dniach", en="What the last 28 days lacked"),
                           key="sport_profile", terms=["quality_mix"],
                           caption=_profile_note(result["profile"])) as t:
        _profile(t, result["profile"])

    _conditions(available, result["skipped"])


def _kpis(state: dict, sessions: pd.DataFrame, now: pd.Timestamp, trend: pd.DataFrame) -> None:
    tr = i18n.tr
    columns = bento.row(1, 1, 1, 1)
    score = state["score"]
    week = trend[trend["day"] <= now.normalize() - pd.Timedelta(days=7)].tail(1)
    delta = f"{score - int(week['score'].iloc[0]):+d}" if score is not None and not week.empty else None
    bento.stat(columns[0], tr(pl="Gotowość", en="Readiness"), f"{score}/100" if score is not None else "—",
               catalog.level_label(state["level"]), key="sport_score", delta=delta,
               help=tr(pl="Twoja gotowość na dowolny trening (0–100); zmiana wobec tygodnia wcześniej.",
                       en="Your readiness for any training (0–100); change against a week earlier."))
    garmin = state["parts"].get("garmin")
    bento.stat(columns[1], tr(pl="Readiness Garmina", en="Garmin readiness"),
               f"{garmin['value']:.0f}" if garmin else "—", garmin.get("level") if garmin else None,
               key="sport_garmin")
    load = state["parts"].get("load")
    bento.stat(columns[2], tr(pl="Obciążenie 7/28 d", en="Load 7/28 d"), f"{load['value']:.2f}" if load else "—",
               tr(pl="wszystkie sporty", en="all sports"), key="sport_load",
               help=tr(pl="Suma obciążenia z 7 dni wobec średniego tygodnia z 28 dni — bieg, rower, mecze, siłownia "
                          "razem.",
                       en="Load of the last 7 days against the average week of the last 28 — runs, rides, matches "
                          "and the gym together."))
    part = variety.window(sessions, now, 28)
    effective = variety.effective_number(part.groupby("discipline")["minutes"].sum())
    count = part["discipline"].nunique()
    bento.stat(columns[3], tr(pl="Różnorodność 28 d", en="Variety 28 d"), f"{effective:.1f}",
               tr(pl=f"{count} {i18n.plural(count, pl=('dyscyplina', 'dyscypliny', 'dyscyplin'), en=('discipline', 'disciplines'))}",
                  en=f"{count} {i18n.plural(count, pl=('dyscyplina', 'dyscypliny', 'dyscyplin'), en=('discipline', 'disciplines'))}"),
               key="sport_variety", help=tr(pl="Efektywna liczba dyscyplin: 1 = tylko jedna, 3 = czas jak gdyby "
                                               "równo między trzy.",
                                            en="Effective number of disciplines: 1 = only one, 3 = time as if split "
                                               "evenly between three."))


def _card(item: dict, tag: str | None = None) -> str:
    name = html.escape(catalog.label(item["discipline"]))
    what = f"{catalog.level_label(item['level'])} · ~{item['minutes']} min"
    lead = f"<span class='tile-caption'>{html.escape(tag)}</span><br>" if tag else ""
    why = html.escape(text.reasons(item["reasons"]))
    return f"<div style='margin:0 0 .7rem'>{lead}<b>{name}</b> — {what}<br><span class='tile-caption'>{why}</span></div>"


def _picks(chosen: dict, planned: dict) -> None:
    tr = i18n.tr
    if planned["today"]:
        titles = " + ".join(s.get("title") or s.get("type", "") for s in planned["today"])
        st.markdown(tr(pl=f"**Plan biegowy na dziś:** {html.escape(titles)}. Propozycje niżej są obok albo zamiast.",
                       en=f"**Running plan today:** {html.escape(titles)}. The ideas below go next to it or instead."))
        if st.button(tr(pl="Decyzja dnia →", en="Today's decision →"), key="sport_to_today", type="tertiary"):
            routing.goto("dzis")
    if planned["tomorrow"]:
        st.markdown("<div class='tile-caption'>" + html.escape(tr(
            pl=f"Jutro: {planned['tomorrow'].get('title', '')} — nogi dziś najwyżej umiarkowanie.",
            en=f"Tomorrow: {planned['tomorrow'].get('title', '')} — legs at most moderate today.")) + "</div>",
            unsafe_allow_html=True)
    if not chosen["main"]:
        st.caption(tr(pl="Nic z tego, co uprawiasz, nie pasuje dziś do warunków — zaznacz niżej, co masz pod ręką.",
                      en="Nothing you do fits today's conditions — tick below what is within reach."))
    cards = [_card(item) for item in chosen["main"]]
    if chosen["new"]:
        novel = chosen["new"]
        cards.append(_card(novel, tr(pl="coś nowego", en="something new")).replace(
            "</div>", f"<br><span class='tile-caption'>{html.escape(catalog.blurb(novel['discipline']))}</span></div>"))
    if chosen["addon"]:
        cards.append(_card(chosen["addon"], tr(pl="dołóż do czegokolwiek", en="add to anything")))
    st.markdown("".join(cards), unsafe_allow_html=True)


def _parts(state: dict) -> None:
    rows = sorted(state["parts"].items(), key=lambda kv: kv[1]["score"])
    items = [f"{text.part_label(k)} — {p['score']}: {text.part_detail(k, p)}" for k, p in rows]
    if state["capped"]:
        items.insert(0, i18n.tr(pl="Dwa sygnały nocne bardzo nisko — dzień przycięty do „spokojnie”.",
                                en="Two night signals very low — the day is capped at “easy”."))
    bento.bullets(items)


def _systems_note(systems: dict) -> str:
    tr = i18n.tr
    worst = max(systems, key=systems.get)
    if systems[worst] < 0.3:
        return tr(pl="Wszystko wypoczęte.", en="Everything rested.")
    return tr(pl=f"Najbardziej: {catalog.system_label(worst)}.", en=f"Most: {catalog.system_label(worst)}.")


def _systems(tile, systems: dict) -> None:
    table = pd.DataFrame({"system": [catalog.system_label(s) for s in catalog.SYSTEMS],
                          "pct": [round(systems[s] * 100) for s in catalog.SYSTEMS]})
    tile.chart(tz.hbars(table, "system", "pct", unit="%"), table=table)


def _trend(tile, trend: pd.DataFrame) -> None:
    if trend.empty:
        tile.chart(None)
        return
    data = trend.copy()
    data["smooth"] = data["score"].rolling(7, min_periods=3).mean()
    data["low"], data["high"] = 52, 68
    fig = tz.trend(data, "day", {i18n.tr(pl="gotowość", en="readiness"): ("score", "smooth")}, band=("low", "high"))
    tile.chart(fig, table=trend.assign(level=trend["level"].map(catalog.level_label)))


def _profile_note(profile: pd.DataFrame) -> str:
    tr = i18n.tr
    missing = profile[profile["gap"] >= 0.5]
    if missing.empty:
        return tr(pl="Wszystkie cechy w okolicy celu.", en="Every quality near its target.")
    names = ", ".join(catalog.quality_label(q) for q in missing["quality"])
    return tr(pl=f"Mało: {names}.", en=f"Short on: {names}.")


def _profile(tile, profile: pd.DataFrame) -> None:
    tr = i18n.tr
    table = pd.DataFrame({
        "quality": [f"{catalog.quality_label(q)} ({tr(pl='cel', en='target')} {t:.0%})"
                    for q, t in zip(profile["quality"], profile["target"])],
        "pct": (profile["share"] * 100).round(),
    })
    tile.chart(tz.hbars(table, "quality", "pct", unit="%"), table=table)


def _conditions(available: list[str], skipped: list[dict]) -> None:
    tr = i18n.tr
    with bento.panel(tr(pl="Co masz pod ręką", en="What is within reach"), key="sport_conditions",
                     terms=["sport_conditions"],
                     caption=tr(pl="Woda, wiatr, śnieg i góry to wyjazd — zaznacz je tylko na te dni.",
                                en="Water, wind, snow and mountains are a trip — tick them only for those days.")):
        chosen = st.pills(tr(pl="Warunki", en="Conditions"), catalog.CONDITIONS, selection_mode="multi",
                          default=available, format_func=catalog.condition_label, key="sport_available",
                          label_visibility="collapsed")
        if sorted(chosen or []) != sorted(available):
            store.save_available(list(chosen or []))
            st.rerun()
        if skipped:
            with st.expander(tr(pl=f"Pominięte dziś ({len(skipped)})", en=f"Left out today ({len(skipped)})")):
                bento.bullets([text.skipped(item) for item in skipped])
