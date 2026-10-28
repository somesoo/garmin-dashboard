"""Interface language: Polish (default) and English.

Every sentence a person reads is written in both languages at the place it is
used, not under a key in a catalogue::

    st.caption(i18n.tr(pl=f"dziś {value} ms", en=f"today {value} ms"))
    noun = i18n.plural(n, pl=("dzień", "dni", "dni"), en=("day", "days"))

Both keywords are required, so a sentence with one language is a TypeError at
the first render, not a silent gap -- and a sentence built from numbers stays
one readable f-string per language instead of a template with placeholders
that drift apart. ``tests/test_i18n.py`` fails on Polish text left outside
``pl=`` in the modules that are already bilingual (``BILINGUAL``).

The choice lives in ``st.session_state["lang"]`` (the rail picker) and is
remembered in ``data/ui.json``, so a reload or a new tab keeps it. Outside a
Streamlit run (tests, ``running.coach``) the remembered language applies.

``tr`` is evaluated when called: a module-level constant built with it is
frozen in the language of the first import. Build such tables in a function.
"""

from __future__ import annotations

import json
from typing import Any

import config

LANGS = {"pl": "Polski", "en": "English"}
DEFAULT = "pl"
KEY = "lang"
SETTINGS = config.DATA / "ui.json"

# Modules whose user-facing text is fully bilingual; the test keeps them so.
# glossary.py is bilingual through glossary_en.py (its own parity test).
BILINGUAL = ["app.py", "shell.py", "bento.py", "routing.py", "theme.py", "globe.py",
             *(f"views/{name}.py" for name in (
                 "activities", "atlas", "form", "notebook", "physio", "recovery", "reference", "routes",
                 "run_common", "run_forecast", "run_load", "run_overview", "run_plan", "run_races", "run_segments",
                 "run_session", "sleep", "stats", "today", "trends")),
             *(f"running/{name}.py" for name in (
                 "coach", "forecast", "garmin_workout", "physio", "pipeline", "plan", "segments", "sessions", "store",
                 "text", "units", "workouts")),
             "etl/push_plan.py", "etl/exclude.py", "analytics.py"]


def saved() -> str:
    """The language remembered from the last choice in the rail."""
    try:
        value = json.loads(SETTINGS.read_text(encoding="utf-8")).get(KEY)
    except (OSError, ValueError, AttributeError):
        return DEFAULT
    return value if value in LANGS else DEFAULT


def remember(value: str) -> None:
    if value not in LANGS:
        return
    try:
        current = json.loads(SETTINGS.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current[KEY] = value
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        pass  # the session still has it; only the next tab falls back


_forced: str | None = None


def force(value: str | None) -> None:
    """Pin the language for a command-line run (``--lang``); None undoes it."""
    global _forced
    _forced = value if value in LANGS else None


def lang() -> str:
    """The language of the current page render."""
    if _forced:
        return _forced
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx(suppress_warning=True) is not None:
            value = st.session_state.get(KEY)
            if value in LANGS:
                return value
    except Exception:  # noqa: BLE001 -- no Streamlit, no session: use the file
        pass
    return saved()


def tr(*, pl: str, en: str) -> str:
    """The text in the current language."""
    return en if lang() == "en" else pl


def pick(values: dict[str, Any]) -> Any:
    """A per-language value that is not a sentence (a list of month names)."""
    return values.get(lang(), values[DEFAULT])


def plural(count: float, *, pl: tuple[str, str, str], en: tuple[str, str]) -> str:
    """The noun form for ``count``: Polish has three (1 dzień, 2 dni, 5 dni),
    English two. Returns the word only; the number is the caller's."""
    n = abs(int(count))
    if lang() == "en":
        return en[0] if n == 1 else en[1]
    if n == 1:
        return pl[0]
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return pl[1]
    return pl[2]


# ------------------------------------------------------------------ calendar

_MONTHS = {
    "pl": ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
_WEEKDAYS = {
    "pl": ["pon", "wt", "śr", "czw", "pt", "sob", "nd"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
_WEEKDAYS_LONG = {
    "pl": ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}


def months() -> list[str]:
    """Short month names, January first."""
    return pick(_MONTHS)


def weekdays(long: bool = False) -> list[str]:
    """Weekday names, Monday first (``date.weekday()`` indexes them)."""
    return pick(_WEEKDAYS_LONG if long else _WEEKDAYS)


def day_month(day: Any) -> str:
    """``26 lip`` / ``26 Jul``: a date where the year is obvious."""
    return f"{day.day} {months()[day.month - 1]}"


# --------------------------------------------------------------------- pages

# Menu groups and page titles, by the page's url_path. The url paths stay
# Polish in both languages: they are addresses, and links keep working.
_GROUPS = {
    "overview": ("Przegląd", "Overview"),
    "running": ("Bieganie", "Running"),
    "body": ("Ciało", "Body"),
    "training": ("Trening", "Training"),
    "analysis": ("Analiza", "Analysis"),
}
_PAGES = {
    "dzis": ("Dziś", "Today"),
    "atlas": ("Atlas", "Atlas"),
    "trasy": ("Trasy", "Routes"),
    "aktywnosci": ("Aktywności", "Activities"),
    "bieganie": ("Bieganie", "Running"),
    "prognoza": ("Prognoza wyników", "Race forecast"),
    "plan": ("Plan treningowy", "Training plan"),
    "zawody": ("Zawody i cele", "Races and goals"),
    "bieg": ("Trening", "Workout"),
    "segmenty": ("Segmenty", "Segments"),
    "obciazenie-biegowe": ("Obciążenie biegowe", "Running load"),
    "regeneracja": ("Regeneracja", "Recovery"),
    "sen": ("Rytm i sen", "Rhythm and sleep"),
    "trendy": ("Trendy", "Trends"),
    "forma": ("Forma", "Form"),
    "fizjologia": ("Fizjologia", "Physiology"),
    "statystyka": ("Statystyka", "Statistics"),
    "insights": ("Insights", "Insights"),
    "sql": ("SQL", "SQL"),
    "slownik": ("Słownik", "Glossary"),
}


def group(key: str) -> str:
    pl, en = _GROUPS[key]
    return tr(pl=pl, en=en)


def page(url_path: str) -> str:
    """A page's title: the menu entry and the page header say the same."""
    pl, en = _PAGES[url_path]
    return tr(pl=pl, en=en)
