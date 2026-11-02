"""The frame every page is told in: a headline, the loop, one hero, details on request.

The research behind it (2026-11-01): self-tracking reads best as a cycle that
ties the facets of one's life together (Li, Dey & Forlizzi 2010), a chart
explains best when the reader is led first and explores after (Segel & Heer's
"martini glass") and annotations next to the data they describe help it stick
(Borkin et al. 2015). So a page is:

* **a headline that states the finding**, computed from the data, with one
  sentence under it on how to read the chart;
* **the loop** to the right of it -- stimulus (load) -> response (recovery,
  sleep) -> adaptation (fitness) -> goal (plan, race) -- each stage with its
  number of the day and its pages. It is the navigation: there is no sidebar;
* **one hero chart** (``herochart.py``) with the facts that explain it on both
  sides and strips from the neighbouring stages on the same time axis;
* **details** -- the old tiles -- behind one link, in a layer over the page, so
  the page itself fits one screen.

The top line (``topbar``) carries what the sidebar used to: the everyday pages,
the lab, the time range, the language and the Garmin pull.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

import streamlit as st

import facts
import i18n
import routing
import shell
import sync

# The loop: stage key -> the pages that belong to it (url paths), in menu order.
STAGE_PAGES = {
    "load": ["bieganie", "obciazenie-biegowe", "sport"],
    "response": ["regeneracja", "sen"],
    "adapt": ["prognoza", "fizjologia", "segmenty"],
    "goal": ["plan", "dzis"],
}
EVERYDAY = ["dzien", "dzis", "atlas"]
LAB = ["statystyka", "insights", "sql", "slownik"]


def stage_of(url_path: str) -> str | None:
    return next((key for key, pages in STAGE_PAGES.items() if url_path in pages), None)


def _stage_names() -> dict[str, tuple[str, str]]:
    tr = i18n.tr
    return {"load": (tr(pl="Bodziec", en="Stimulus"), tr(pl="Obciążenie", en="Load")),
            "response": (tr(pl="Odpowiedź", en="Response"), tr(pl="Regeneracja i sen", en="Recovery and sleep")),
            "adapt": (tr(pl="Adaptacja", en="Adaptation"), tr(pl="Forma", en="Fitness")),
            "goal": (tr(pl="Cel", en="Goal"), tr(pl="Start i plan", en="Race and plan"))}


@st.cache_data(show_spinner=False)
def _loop_values(build: str, day: str, lang: str, stamp: str) -> dict[str, str]:
    from views import run_common as rc
    today = dt.date.fromisoformat(day)
    return facts.loop_values(shell.daily(), rc.runs(), shell.table("run_forecast"), rc.upcoming_races(today), today)


def loop_values() -> dict[str, str]:
    from views import run_common as rc
    return _loop_values(shell.build_id(), dt.date.today().isoformat(), i18n.lang(), rc.store_stamp())


def loop(current: str) -> None:
    """The loop as navigation: four stages, their numbers, their pages; the current one lit."""
    here = stage_of(current)
    values = loop_values()
    names = _stage_names()
    with st.container(key="loop"):
        for index, (key, pages) in enumerate(STAGE_PAGES.items(), start=1):
            stage, title = names[key]
            lit = "on" if key == here else ""
            st.markdown(f"<div class='lp {lit}'><span class='lp-i'>{index}</span><span class='lp-n'>{title}</span>"
                        f"<span class='lp-v'>{values.get(key, '—')}</span></div>", unsafe_allow_html=True)
            with st.container(horizontal=True, key=f"lp_pages_{index}", gap="small", vertical_alignment="center"):
                for url in pages:
                    page = routing.page(url)
                    if page is None:
                        continue
                    if url == current:
                        st.markdown(f"<span class='lp-here'>{i18n.page(url)}</span>", unsafe_allow_html=True,
                                    width="content")
                    else:
                        st.page_link(page, label=i18n.page(url))
        st.markdown(f"<div class='lp-again'>↺ {i18n.tr(pl='cel wyznacza kolejny bodziec', en='the goal sets the next stimulus')}</div>",
                    unsafe_allow_html=True)


def head(current: str, headline: str, sub: str | None = None) -> None:
    """The finding on the left, the loop on the right."""
    import bento
    bento.HEADED = True
    left, right = st.columns([2.6, 1], gap="large", vertical_alignment="top")
    with left:
        st.markdown(f"<h1 class='story-h'>{headline}</h1>" + (f"<p class='story-sub'>{sub}</p>" if sub else ""),
                    unsafe_allow_html=True)
    with right:
        loop(current)


def details(label: str, render: Callable[[], None], *, key: str) -> None:
    """The page's second plan -- the old tiles -- behind one link, in a layer over the page."""
    tr = i18n.tr
    with st.container(horizontal=True, key=f"story_more_{key}", vertical_alignment="bottom"):
        opened = st.button(tr(pl="Szczegóły", en="Details"), key=f"more_{key}")
        st.markdown(f"<span class='story-more-note'>{label}</span>", unsafe_allow_html=True, width="content")
    if opened:
        st.dialog(tr(pl="Szczegóły", en="Details") + " · " + label, width="large")(render)()


# ------------------------------------------------------------------ the top line

def topbar(current: str) -> None:
    """What the sidebar carried: everyday pages and the lab on the left; range, language, Garmin on the right."""
    import bento
    bento.HEADED = False  # a new run: no page headline yet
    tr = i18n.tr
    with st.container(horizontal=True, key="topbar", vertical_alignment="center", gap="medium"):
        for url in EVERYDAY:
            page = routing.page(url)
            if page is None:
                continue
            if url == current:
                st.markdown(f"<span class='tb-here'>{i18n.page(url)}</span>", unsafe_allow_html=True, width="content")
            else:
                st.page_link(page, label=i18n.page(url))
        with st.popover(i18n.group("lab"), type="tertiary"):
            for url in ["fizjologia", *LAB]:
                page = routing.page(url)
                if page is not None:
                    st.page_link(page, label=i18n.page(url))
            st.caption(shell.status_lines())
            import guide
            guide.rail()
        st.space("stretch")
        shell.range_picker()
        shell.language_picker()
        st.fragment(run_every=3 if sync.running() else 60)(shell.pull_inline)(sync.running())


def frame_page(current: str, *, headline: str, sub: str | None, hero: Callable[[], None],
               more: str, more_render: Callable[[], None] | None) -> None:
    """A whole page in the frame: head, hero, details."""
    head(current, headline, sub)
    hero()
    if more_render is not None:
        details(more, more_render, key=current)


def token(*parts: Any) -> str:
    """What makes a hero wipe in again: the build, the range, the language and anything else that changes it."""
    return "|".join(str(p) for p in (shell.build_id(), st.session_state.get("range_choice"), i18n.lang(), *parts))


def long_span(first, last, *, days: int = 365):
    """A hero about weeks needs at least a year: the global range, or ``days`` if the range is shorter."""
    import pandas as pd
    window = shell.window_days()
    if window is None:
        return pd.Timestamp(first), pd.Timestamp(last)
    return max(pd.Timestamp(first), pd.Timestamp(last) - pd.Timedelta(days=max(window, days))), pd.Timestamp(last)


def km_strip(runs, start, end, why: str = "") -> dict:
    """The stimulus strip: kilometres per week, quality sessions in orange (for heroes on the other stages)."""
    import facts
    import herochart as hc
    import pandas as pd
    tr = i18n.tr
    c = hc.colors()
    weeks = facts.weekly_km(runs)
    weeks = weeks[(weeks["week"] >= pd.Timestamp(start) - pd.Timedelta(days=6)) & (weeks["week"] < pd.Timestamp(end))]
    top = float(weeks["km"].max()) if not weeks.empty else 10.0
    return {"kind": "bars", "strip": True,
            "bars": [[hc.ms(r.week), [round(r.easy_km, 1), round(r.hard_km, 1)]] for r in weeks.itertuples()],
            "colors": [c["series"], c["warm"]], "names": [tr(pl="spokojne km", en="easy km"), tr(pl="mocne km", en="hard km")],
            "period": tr(pl="tydzień od", en="week of"), "y": [0, max(10.0, top * 1.1)],
            "label": {"group": tr(pl="Bodziec · Obciążenie", en="Stimulus · Load"), "head": tr(pl="km tygodniowo", en="km per week"),
                      "note": tr(pl="pomarańczowe — treningi jakościowe", en="orange — quality sessions")},
            "why": why}


def hrv_strip(start, why: str = "") -> dict:
    """The response strip: the 7-night mean of overnight HRV."""
    import herochart as hc
    import pandas as pd
    tr = i18n.tr
    # The mean runs over the whole history first, so the strip starts at the range's edge, not 4 nights in.
    nights = shell.daily().sort_values("day")
    nights["hrv7"] = nights["hrv_last_night"].rolling(7, min_periods=4).mean()
    nights = nights[nights["day"] >= pd.Timestamp(start)]
    return {"kind": "lines", "strip": True, "y": hc.span(nights["hrv7"].dropna()), "decimals": 0, "unit": "ms",
            "lines": [{"points": hc.points(nights, "day", "hrv7", 1), "color": hc.colors()["series"], "width": 2,
                       "name": tr(pl="HRV, średnia 7 nocy", en="HRV, 7-night mean")}],
            "label": {"group": tr(pl="Odpowiedź · Regeneracja", en="Response · Recovery"),
                      "head": tr(pl="HRV, średnia 7 nocy", en="HRV, 7-night mean"), "note": ""},
            "why": why}


def satellites(items: list) -> list:
    """facts.sat entries with their (day, value) anchors as the component wants them."""
    import herochart as hc
    return [{**s, "anchor": {"t": hc.ms(s["anchor"][0]), "v": float(s["anchor"][1])} if s.get("anchor") else None}
            for s in items]
