"""Zespół: the coach's wall of sticky notes -- one per athlete, the ones that need a look first.

Registered only for someone the registry names as a coach (app.py). Each note
is one athlete's week against their own norm (analysis/team.py), its paper
coloured by what it asks of the coach (``STATE_COLORS``, an ordered scale):

- coral -- attention: two recovery flags, or two missed sessions in a week;
- yellow -- watch: one of those, or a planned run past the 30-day rule;
- grey -- silent: no watch data for two days (a day without the watch is not a bad night);
- mint -- on track;
- a dashed outline -- no consent yet: the name only, nothing of theirs is read.

"Otwórz" opens the athlete's own dashboard (ui/coaching.py), as far as their
consent goes; "Notatka" writes in the thread both of them see (core/team.py).
Like every page but *Dziś*, nothing here advises -- the coach decides.
"""

from __future__ import annotations

import datetime as dt
import html

import streamlit as st

from analysis import team as cards
from core import i18n
from core import team
from core import tenant
from running import text
from running import units
from ui import bento
from ui import coaching
from ui import shell

COLUMNS = 4
# Paper, not data ink: solid colours, darker ink on top. Ordered by urgency.
STATE_COLORS = {"attention": "#f2a69c", "watch": "#f3d67a", "silent": "#c8c8c4", "ok": "#b7e0bf", "empty": "#c8c8c4"}
INK = "#1b1b1b"


def _labels() -> dict[str, str]:
    tr = i18n.tr
    return {"attention": tr(pl="wymaga uwagi", en="needs a look"), "watch": tr(pl="do obserwacji", en="keep an eye"),
            "silent": tr(pl="bez danych", en="no data"), "ok": tr(pl="w normie", en="on track"),
            "empty": tr(pl="jeszcze nic", en="nothing yet"), "pending": tr(pl="czeka na zgodę", en="awaiting consent")}


@st.cache_data(ttl=900, show_spinner=False, max_entries=64)
def _card(build: str, athlete_id: str, scope: str, day: str, lang: str, stamp: str) -> dict:
    """One note's numbers; ``build`` (the athlete's ``<id>@<built_at>``) and ``stamp`` (plan files) key it."""
    return cards.load(tenant.get(athlete_id), dt.date.fromisoformat(day), scope)


def _load(athlete: tenant.User, today: dt.date) -> dict:
    from views import run_common as rc

    with tenant.use(athlete.id):
        build, stamp = shell.build_id(), rc.store_stamp()
    return _card(build, athlete.id, team.scope(athlete) or "training", today.isoformat(), i18n.lang(), stamp)


def render() -> None:
    tr = i18n.tr
    coach = tenant.viewer()
    people = team.athletes(coach)
    if not people:
        bento.header(i18n.page("zespol"), tr(pl="Nikt nie ma Cię jeszcze wpisanego jako trenera.",
                                             en="Nobody has you down as their coach yet."))
        return
    today = dt.date.today()
    open_, pending = [], []
    for athlete in people:
        if team.allowed(coach.id, athlete):
            try:
                open_.append((athlete, _load(athlete, today)))
            except Exception:  # noqa: BLE001 -- one athlete's broken tables must not cost the coach the wall
                open_.append((athlete, {"state": "empty", "reasons": [], "error": True}))
        else:
            pending.append(athlete)
    ordered = cards.order(open_)
    bento.header(i18n.page("zespol"), _headline(ordered, pending))
    _legend()
    notes = [(a, c) for a, c in ordered] + [(a, None) for a in pending]
    for start in range(0, len(notes), COLUMNS):
        columns = st.columns(COLUMNS, gap="medium")
        for offset, (athlete, card) in enumerate(notes[start:start + COLUMNS]):
            with columns[offset]:
                _note(athlete, card, start + offset, coach)
    st.html(_style())


def _headline(ordered: list, pending: list) -> str:
    """What the wall says, in one sentence: how many need a look, how many are quiet."""
    tr = i18n.tr
    counts = {state: sum(1 for _, c in ordered if c.get("state") == state) for state in cards.STATES}
    parts = []
    if counts["attention"]:
        n = counts["attention"]
        who = i18n.plural(n, pl=("osoba wymaga", "osoby wymagają", "osób wymaga"),
                          en=("person needs", "people need"))
        parts.append(tr(pl=f"{n} {who} uwagi", en=f"{n} {who} a look"))
    if counts["watch"]:
        parts.append(tr(pl=f"{counts['watch']} do obserwacji", en=f"{counts['watch']} to keep an eye on"))
    if counts["silent"]:
        parts.append(tr(pl=f"{counts['silent']} bez danych od 2+ dni", en=f"{counts['silent']} without data for 2+ days"))
    if counts["ok"]:
        parts.append(tr(pl=f"{counts['ok']} w normie", en=f"{counts['ok']} on track"))
    if pending:
        parts.append(tr(pl=f"{len(pending)} czeka na zgodę", en=f"{len(pending)} awaiting consent"))
    return " · ".join(parts) + "." if parts else ""


def _legend() -> None:
    labels = _labels()
    chips = "".join(f"<span class='sn-key'><i style='background:{STATE_COLORS[s]}'></i>{labels[s]}</span>"
                    for s in ("attention", "watch", "silent", "ok"))
    chips += f"<span class='sn-key'><i class='sn-dash'></i>{labels['pending']}</span>"
    st.markdown(f"<div class='sn-legend'>{chips}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------ one note


def _signed(value: float | None, unit: str) -> str | None:
    if value is None:
        return None
    if round(value) == 0:
        return f"±0 {unit}"
    return f"{value:+.0f} {unit}".replace("-", "−")


def _hours(value: float) -> str:
    """``7,5 h`` / ``7.5 h``."""
    return f"{text._n(value)} h"


def _reason(item: dict) -> str:
    tr, plural = i18n.tr, i18n.plural
    key, n = item.get("key"), int(item.get("n", 0))
    if key == "recovery":
        signal = plural(n, pl=("sygnał", "sygnały", "sygnałów"), en=("signal", "signals"))
        return tr(pl=f"{n} {signal} regeneracji", en=f"{n} recovery {signal}")
    if key == "missed":
        missed = plural(n, pl=("sesja opuszczona", "sesje opuszczone", "sesji opuszczonych"),
                        en=("session missed", "sessions missed"))
        return tr(pl=f"{n} {missed} w 7 dni", en=f"{n} {missed} in 7 days")
    if key == "spike":
        when = i18n.day_month(dt.date.fromisoformat(item["date"]))
        planned, cap = text.km(item["km"]), text.km(item["cap_km"])
        return tr(pl=f"{when}: {planned} ponad limit {cap} (reguła 30 dni)",
                  en=f"{when}: {planned} over the {cap} cap (30-day rule)")
    if key == "silent":
        days = int(item.get("days", 0))
        word = plural(days, pl=("dnia", "dni", "dni"), en=("day", "days"))
        return tr(pl=f"bez danych z zegarka od {days} {word}", en=f"no watch data for {days} {word}")
    if key == "no_plan":
        return tr(pl="bez planu", en="no plan")
    return str(key)


def _verdict(code: str | None) -> str:
    tr = i18n.tr
    return {"done": tr(pl="zgodnie z planem", en="as planned"), "modified": tr(pl="inaczej niż w planie", en="changed"),
            "skipped": tr(pl="pominięty", en="skipped")}.get(code or "", tr(pl="poza planem", en="outside the plan"))


def _body(card: dict) -> str:
    """The note's text as HTML (every value escaped)."""
    tr = i18n.tr
    esc = html.escape
    lines = []
    session = card.get("today")
    if session is not None:
        if session["type"] == "rest" and not session.get("title"):
            what = tr(pl="wolne", en="rest")
        else:
            what = esc(session.get("title") or text.kind_label(session["type"]))
        mark = " <span class='sn-pen' title='coach'>✎</span>" if session.get("coach") else ""
        lines.append(f"<div class='sn-line'><b>{tr(pl='Dziś', en='Today')}</b> {what}{mark}</div>")
    body = card.get("recovery")
    if body:
        bits = []
        hrv = _signed(body.get("hrv_deviation"), "ms")
        if hrv:
            bits.append(f"HRV {hrv}")
        rhr = _signed(body.get("rhr_deviation"), "bpm")
        if rhr:
            bits.append(tr(pl=f"tętno spocz. {rhr}", en=f"RHR {rhr}"))
        if body.get("sleep_h") is not None:
            norm = body.get("sleep_norm_h")
            sleep = _hours(body["sleep_h"])
            bits.append(tr(pl=f"sen {sleep}", en=f"sleep {sleep}")
                        + (f" <span class='sn-dim'>({tr(pl='norma', en='norm')} {_hours(norm)})</span>" if norm else ""))
        if bits:
            night = dt.date.fromisoformat(body["day"])
            # Not last night: say which night these numbers are from.
            when = "" if (dt.date.today() - night).days <= 1 else \
                f"<span class='sn-dim'>{tr(pl='noc', en='night of')} {i18n.day_month(night)}:</span> "
            lines.append(f"<div class='sn-line sn-body'>{when}{' · '.join(bits)}</div>")
    week = card.get("week") or {}
    if week:
        planned = week.get("plan_km")
        done = week.get("done_km") or 0
        share = min(100, round(100 * done / planned)) if planned else None
        label = tr(pl="Tydzień", en="Week")
        km = text._n(round(done)) + (f" / {text._n(round(planned))}" if planned else "") + " km"
        sessions = f" · {week['done_n']}/{week['plan_n']}" if week.get("plan_n") else ""
        bar = f"<div class='sn-bar'><i style='width:{share}%'></i></div>" if share is not None else ""
        lines.append(f"<div class='sn-week'><span><b>{label}</b> {km}{sessions}</span>{bar}</div>")
    run = card.get("last_run")
    if run:
        when = i18n.day_month(dt.date.fromisoformat(run["day"]))
        pace = units.fmt_pace(run.get("pace"))
        lines.append(f"<div class='sn-line'><b>{tr(pl='Ostatni bieg', en='Last run')}</b> {when} · "
                     f"{text.km(run['km'])} · {pace} · <span class='sn-dim'>{_verdict(run.get('verdict'))}</span></div>")
    race = card.get("race")
    if race:
        name = esc(race.get("name") or text.race_label(race.get("distance")))
        days = race["days"]
        word = i18n.plural(days, pl=("dzień", "dni", "dni"), en=("day", "days"))
        when = tr(pl="dziś", en="today") if days == 0 else tr(pl=f"za {days} {word}", en=f"in {days} {word}")
        lines.append(f"<div class='sn-line'><b>{tr(pl='Start', en='Race')}</b> {name} {when}</div>")
    reasons = [r for r in card.get("reasons") or []]
    if reasons:
        lines.append("<ul class='sn-why'>" + "".join(f"<li>{esc(_reason(r))}</li>" for r in reasons) + "</ul>")
    return "".join(lines)


def _note(athlete: tenant.User, card: dict | None, index: int, coach: tenant.User) -> None:
    tr = i18n.tr
    labels = _labels()
    state = "pending" if card is None else card.get("state", "empty")
    tilt = ("l", "r", "n")[index % 3]
    with st.container(key=f"sticky_{state}_{tilt}_{athlete.id}"):
        unread = team.unread(athlete, coach.id) if card is not None else []
        badge = f"<span class='sn-mail'>✉ {len(unread)}</span>" if unread else ""
        st.markdown(f"<div class='sn-head'><span class='sn-name'>{html.escape(athlete.name)}</span>{badge}</div>"
                    f"<div class='sn-state'>{labels.get(state, state)}</div>", unsafe_allow_html=True)
        if card is None:
            st.markdown(f"<div class='sn-line sn-dim'>{tr(pl='Zgodę daje zawodnik albo rodzic na stronie Konto. Do tego czasu nic nie widać.', en='The athlete or a parent consents on the Account page. Until then nothing is visible.')}</div>",
                        unsafe_allow_html=True)
            return
        st.markdown(_body(card), unsafe_allow_html=True)
        if card.get("last_day"):
            st.markdown(f"<div class='sn-foot'>{tr(pl='dane z', en='data from')} "
                        f"{i18n.day_month(dt.date.fromisoformat(card['last_day']))}</div>", unsafe_allow_html=True)
        with st.container(horizontal=True, key=f"snbtn_{athlete.id}", gap="small"):
            if st.button(tr(pl="Otwórz", en="Open"), key=f"sn_open_{athlete.id}", type="tertiary"):
                coaching.start(athlete.id)
            run = card.get("last_run")
            if run and st.button(tr(pl="Ostatni bieg", en="Last run"), key=f"sn_run_{athlete.id}", type="tertiary"):
                coaching.start(athlete.id, "bieg", run_activity_request=int(run["activity_id"]))
            with st.popover(tr(pl="Notatka", en="Note") + (f" ({len(unread)})" if unread else ""), type="tertiary"):
                _thread(athlete, coach)


def _thread(athlete: tenant.User, coach: tenant.User) -> None:
    from ui import notes

    notes.thread(athlete, coach, key=f"sn_{athlete.id}", limit=5)


def _style() -> str:
    colors = "".join(
        f"div[class*='st-key-sticky_{state}_'] {{ background: {color}; }}" for state, color in STATE_COLORS.items())
    return f"""<style>
    div[class*='st-key-sticky_'] {{
      color: {INK}; border-radius: 3px; padding: 1.1rem 1rem 0.7rem; position: relative;
      box-shadow: 0 10px 18px rgba(0,0,0,0.55), 0 1px 0 rgba(0,0,0,0.25);
      transition: transform 160ms ease; margin: 0.6rem 0.2rem 1rem;
    }}
    {colors}
    div[class*='st-key-sticky_pending_'] {{
      background: transparent; color: inherit; box-shadow: none; border: 1.5px dashed #6b6b6b;
    }}
    div[class*='st-key-sticky_'][class*='_l_'] {{ transform: rotate(-1.4deg); }}
    div[class*='st-key-sticky_'][class*='_r_'] {{ transform: rotate(1.1deg); }}
    div[class*='st-key-sticky_']:hover {{ transform: rotate(0deg) translateY(-2px); }}
    div[class*='st-key-sticky_']:not([class*='st-key-sticky_pending_'])::before {{
      content: ''; position: absolute; top: -9px; left: 50%; width: 64px; height: 18px; margin-left: -32px;
      background: rgba(255,255,255,0.38); transform: rotate(-2deg);
    }}
    div[class*='st-key-sticky_'] p, div[class*='st-key-sticky_'] li, div[class*='st-key-sticky_'] b {{ color: inherit; }}
    .sn-head {{ display: flex; justify-content: space-between; align-items: baseline; }}
    .sn-name {{ font-size: 1.25rem; font-weight: 700; letter-spacing: -0.01em; }}
    .sn-mail {{ font-size: 0.8rem; font-weight: 600; }}
    .sn-state {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.7;
                 margin: 0.05rem 0 0.55rem; }}
    .sn-line {{ font-size: 0.86rem; line-height: 1.35; margin: 0.18rem 0; }}
    .sn-dim {{ opacity: 0.68; }}
    .sn-pen {{ font-size: 0.8rem; }}
    .sn-week {{ font-size: 0.86rem; margin: 0.35rem 0; }}
    .sn-bar {{ height: 5px; background: rgba(0,0,0,0.14); border-radius: 3px; margin-top: 0.25rem; overflow: hidden; }}
    .sn-bar i {{ display: block; height: 100%; background: rgba(0,0,0,0.62); }}
    ul.sn-why {{ margin: 0.45rem 0 0.2rem 0; padding: 0; list-style: none; }}
    ul.sn-why li {{ font-size: 0.8rem !important; line-height: 1.3; margin: 0.08rem 0 !important; padding: 0 0 0 0.9rem;
                    position: relative; }}
    ul.sn-why li::before {{ content: '–'; position: absolute; left: 0; }}
    .sn-foot {{ font-size: 0.72rem; opacity: 0.6; margin-top: 0.45rem; }}
    div[class*='st-key-sticky_'] button {{ color: {INK} !important; padding-left: 0; padding-right: 0.6rem; }}
    div[class*='st-key-sticky_'] button p {{ color: {INK} !important; font-weight: 600; text-decoration: underline;
                                             text-underline-offset: 3px; text-decoration-thickness: 1px; }}
    div[class*='st-key-sticky_pending_'] button, div[class*='st-key-sticky_pending_'] button p {{ color: inherit !important; }}
    .sn-legend {{ display: flex; flex-wrap: wrap; gap: 0.9rem; font-size: 0.8rem; opacity: 0.85; margin: 0 0 0.6rem; }}
    .sn-key i {{ display: inline-block; width: 0.8rem; height: 0.8rem; border-radius: 2px; margin-right: 0.35rem;
                 vertical-align: -0.1rem; }}
    .sn-key i.sn-dash {{ border: 1.5px dashed #8a8a8a; }}
    @media (prefers-reduced-motion: reduce) {{ div[class*='st-key-sticky_'] {{ transition: none; }} }}
    /* A phone: one note a row, straight -- a tilted note would poke past the screen's edge. */
    @media (max-width: 760px) {{ div[class*='st-key-sticky_'][class*='_'] {{ transform: none; margin: 0.6rem 0 1rem; }} }}
    </style>"""
