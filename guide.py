"""Wayfinding: what each page answers, where to go next, a first-visit tour.

A visitor who has not built this app does not know that the plan lives under
Running or that recovery and sleep are two pages. Three small things carry
them, all rendered by the router around every page, so no view has to
remember them:

* ``eyebrow`` -- the question the page answers, above its title;
* ``next_steps`` -- a "Dalej" strip at the bottom with two or three pages that
  follow from this one (on *Dziś* chosen from today's state), so no page is a
  dead end;
* ``tour`` -- a dismissible panel on *Dziś* with the four stops of the app;
  dismissing it is remembered in ``data/ui.json``, the rail button brings it back.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import shell
from running import store as run_store
from views import hubs, run_common as rc

TOUR_KEY = "tour_done"


def _questions() -> dict[str, str]:
    tr = i18n.tr
    return {
        "dzien": tr(pl="Co się dziś wydarzyło — w liczbach, na tle ostatnich dni?",
                    en="What happened today — in numbers, against the last few days?"),
        "dzis": tr(pl="Co dziś zrobić — i czy organizm jest na to gotowy?",
                   en="What to do today — and is the body ready for it?"),
        "sport": tr(pl="Na jaki trening jestem dziś gotów, także poza bieganiem?",
                    en="What training am I ready for today, running or not?"),
        "atlas": tr(pl="Gdzie i co trenowałem?", en="Where and what have I trained?"),
        "trasy": tr(pl="Jak wyglądał ten trening na mapie?", en="What did this session look like on the map?"),
        "bieganie": tr(pl="Ile i jak biegam ostatnio?", en="How much and how have I been running lately?"),
        "plan": tr(pl="Co biegać do następnego startu?", en="What to run until the next race?"),
        "prognoza": tr(pl="Na jaki czas mogę liczyć na zawodach?", en="What time can I count on in a race?"),
        "bieg": tr(pl="Jak poszedł ten bieg?", en="How did this run go?"),
        "segmenty": tr(pl="Czy na tych samych odcinkach jestem szybszy?",
                       en="Am I getting faster on the same stretches?"),
        "obciazenie-biegowe": tr(pl="Dokładać czy odpuścić?", en="Add more or back off?"),
        "regeneracja": tr(pl="Czy organizm nadąża za treningiem?", en="Is the body keeping up with the training?"),
        "sen": tr(pl="Jak śpię i czy ten sen regeneruje?", en="How do I sleep, and does it restore me?"),
        "fizjologia": tr(pl="Co same treningi mówią o mojej wydolności?",
                         en="What do the sessions alone say about my fitness?"),
        "statystyka": tr(pl="Co naprawdę wiąże się z czym w moich danych?",
                         en="What really goes with what in my data?"),
        "insights": tr(pl="Jakie wnioski już wyciągnęliśmy?", en="What conclusions have we drawn so far?"),
        "sql": tr(pl="Własne pytanie do danych.", en="Your own question to the data."),
        "slownik": tr(pl="Co znaczy ten wskaźnik?", en="What does this indicator mean?"),
    }


# Where each page leads: (url_path, switch, view). A view of a shared page
# (views/hubs.py) is opened through its switch.
NEXT: dict[str, list[tuple[str, str | None, str | None]]] = {
    "dzien": [("dzis", None, None), ("sen", None, None), ("bieganie", None, None)],
    "sport": [("dzis", None, None), ("regeneracja", None, None), ("sport", hubs.SPORT, "disciplines")],
    "atlas": [("bieganie", None, None), ("sport", hubs.SPORT, "disciplines"), ("dzis", None, None)],
    "trasy": [("atlas", None, None), ("bieganie", None, None)],
    "bieganie": [("plan", None, None), ("prognoza", None, None), ("segmenty", None, None)],
    "plan": [("dzis", None, None), ("prognoza", None, None), ("obciazenie-biegowe", None, None)],
    "prognoza": [("plan", hubs.PLAN, "races"), ("plan", hubs.PLAN, "plan"), ("fizjologia", None, None)],
    "bieg": [("segmenty", None, None), ("bieganie", None, None)],
    "segmenty": [("bieganie", None, None), ("atlas", None, None)],
    "obciazenie-biegowe": [("regeneracja", None, None), ("plan", hubs.PLAN, "plan"),
                           ("obciazenie-biegowe", hubs.LOAD, "all")],
    "regeneracja": [("sen", None, None), ("obciazenie-biegowe", None, None), ("dzis", None, None)],
    "sen": [("regeneracja", None, None), ("statystyka", None, None)],
    "fizjologia": [("prognoza", None, None), ("statystyka", None, None)],
    "statystyka": [("insights", None, None), ("sql", None, None)],
    "insights": [("sql", None, None), ("slownik", None, None)],
    "sql": [("insights", None, None), ("slownik", None, None)],
    "slownik": [("dzis", None, None)],
}

_VIEW_TITLES = {("plan", "races"): "zawody", ("plan", "plan"): "plan", ("obciazenie-biegowe", "all"): "forma",
                ("obciazenie-biegowe", "run"): "obciazenie-biegowe", ("sport", "disciplines"): "dyscypliny",
                ("sport", "today"): "sport"}


def eyebrow(url_path: str) -> None:
    """The question the page answers, in small type above everything else."""
    question = _questions().get(url_path)
    if question:
        st.markdown(f"<div class='page-eyebrow'>{question}</div>", unsafe_allow_html=True)


def _label(url_path: str, view: str | None) -> str:
    key = _VIEW_TITLES.get((url_path, view)) if view else None
    return i18n.view(key) if key else i18n.page(url_path)


def _today_steps() -> list[tuple[str, str | None, str | None, str | None]]:
    """Dziś points where today's state says to look: a race to add, a race to
    aim at, a poor night -- then the usual next stops."""
    tr = i18n.tr
    steps: list[tuple[str, str | None, str | None, str | None]] = []
    try:
        races = rc.upcoming_races(dt.date.today())
    except Exception:  # noqa: BLE001 -- wayfinding must never break the page
        races = []
    if not races:
        steps.append(("plan", hubs.PLAN, "races", tr(pl="Dodaj start, a plan ułoży się sam",
                                                     en="Add a race and the plan builds itself")))
    elif _no_plan():
        steps.append(("plan", hubs.PLAN, "plan", tr(pl=f"Ułóż plan do „{races[0]['name']}”",
                                                    en=f"Build a plan for “{races[0]['name']}”")))
    if races and (dt.date.fromisoformat(races[0]["date"]) - dt.date.today()).days <= 42:
        steps.append(("prognoza", None, None, tr(pl=f"Prognoza na „{races[0]['name']}”",
                                                 en=f"Forecast for “{races[0]['name']}”")))
    try:
        row = shell.latest_day()
    except Exception:  # noqa: BLE001
        row = None
    if row is not None:
        readiness, score = row.get("readiness"), row.get("sleep_score")
        if (pd.notna(readiness) and readiness < 40) or (pd.notna(score) and score < 60):
            steps.append(("sen", None, None, tr(pl="Słabsza noc — zobacz, co poszło nie tak",
                                                en="A weaker night — see what went wrong")))
    for url_path, switch, view in (("plan", hubs.PLAN, "plan"), ("regeneracja", None, None), ("atlas", None, None)):
        if all(step[0] != url_path for step in steps):
            steps.append((url_path, switch, view, None))
    return steps[:3]


def _no_plan() -> bool:
    try:
        return run_store.current_plan() is None
    except Exception:  # noqa: BLE001 -- wayfinding must never break the page
        return False


def next_steps(url_path: str) -> None:
    """The "Dalej" strip at the bottom of the page."""
    if url_path == "dzis":
        steps = _today_steps()
    else:
        steps = [(target, switch, view, None) for target, switch, view in NEXT.get(url_path, [])]
    # Never the page (or the view of a shared page) the visitor is already on.
    steps = [step for step in steps if routing.page(step[0]) is not None
             and not (step[0] == url_path and (step[1] is None or st.session_state.get(step[1]) == step[2]))]
    if not steps:
        return
    with st.container(key="guide_next", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"<div class='guide-next-label'>{i18n.tr(pl='Dalej', en='Next')}</div>", unsafe_allow_html=True,
                    width="content")
        for index, (target, switch, view, label) in enumerate(steps):
            text = label or _label(target, view)
            if st.button(text, key=f"guide_next_{index}", icon=":material/arrow_forward:", type="secondary"):
                if switch:
                    routing.goto_view(target, switch, view)
                else:
                    routing.goto(target)


# ------------------------------------------------------------------ the tour


def _settings() -> dict[str, Any]:
    try:
        value = json.loads(i18n.SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _remember(done: bool) -> None:
    current = _settings()
    current[TOUR_KEY] = done
    try:
        i18n.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        i18n.SETTINGS.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        pass  # the session still hides it; only the next visit shows it again
    st.session_state[TOUR_KEY] = done


def _done() -> bool:
    if TOUR_KEY not in st.session_state:
        st.session_state[TOUR_KEY] = bool(_settings().get(TOUR_KEY))
    return bool(st.session_state[TOUR_KEY])


def tour() -> None:
    """The four stops of the app, on Dziś until dismissed."""
    if _done():
        return
    tr = i18n.tr
    stops = [
        (":material/today:", i18n.page("dzis"),
         tr(pl="Zaczynaj tu każdego ranka: trening na dziś z planu, obok stan regeneracji i przyciski, żeby go "
               "zmiękczyć albo przesunąć.",
            en="Start here every morning: today's session from the plan, next to it the state of recovery and "
               "buttons to soften or move it.")),
        (":material/calendar_month:", i18n.page("plan"),
         tr(pl="Wpisz start w zakładce *Zawody i cele* — plan ułoży się sam, dopasuje do tego, jak reagujesz, "
               "i wyśle treningi na zegarek.",
            en="Enter a race under *Races and goals* — the plan builds itself, adapts to how you respond and "
               "sends the sessions to the watch.")),
        (":material/monitor_heart:", i18n.group("body"),
         tr(pl="*Regeneracja* i *Sen*: czy organizm nadąża — HRV, tętno spoczynkowe, sen, zawsze względem "
               "Twojej własnej normy.",
            en="*Recovery* and *Sleep*: is the body keeping up — HRV, resting heart rate, sleep, always against "
               "your own normal.")),
        (":material/public:", i18n.page("atlas"),
         tr(pl="Glob z każdym treningiem (przybliż — zobaczysz mapę ciepła tras) i pełny dziennik aktywności.",
            en="A globe with every session (zoom in for a heat map of your routes) and the full activity log.")),
    ]
    with bento.panel(tr(pl="Jak czytać ten dashboard", en="How to read this dashboard"), key="tour",
                     caption=_inline(tr(pl="Cztery przystanki. Reszta menu to szczegóły, a *Laboratorium* — dla "
                                           "dociekliwych.",
                                        en="Four stops. The rest of the menu is detail, and the *Lab* is for the "
                                           "curious."))):
        for column, (icon, title, body) in zip(st.columns(4, gap="medium"), stops):
            with column:
                st.markdown(f"{icon} **{title}**")
                st.markdown(f"<div class='tile-caption'>{_inline(body)}</div>", unsafe_allow_html=True)
        st.caption(tr(pl="Każdy kafel ma w nagłówku „?” z objaśnieniem, a na dole każdej strony są linki *Dalej*. "
                         "Zakres czasu i pobieranie z Garmina są w szynie po lewej.",
                      en="Every tile has a “?” in its header with an explanation, and every page ends with *Next* "
                         "links. The time range and the Garmin pull are in the rail on the left."))
        if st.button(tr(pl="Rozumiem, schowaj", en="Got it, hide this"), key="tour_hide", icon=":material/check:"):
            _remember(True)
            st.rerun()


def _inline(text: str) -> str:
    """*emphasis* inside an HTML caption (markdown is not parsed there)."""
    parts = text.split("*")
    return "".join(f"<i>{part}</i>" if index % 2 else part for index, part in enumerate(parts))


def rail() -> None:
    """The way back to the tour once it was dismissed."""
    if not _done():
        return
    if st.sidebar.button(i18n.tr(pl="Jak czytać ten dashboard", en="How to read this dashboard"),
                         icon=":material/explore:", type="tertiary", key="tour_show"):
        _remember(False)
        routing.goto("dzis")
