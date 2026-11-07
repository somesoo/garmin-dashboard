"""The note thread between an athlete and their coach (core/team.py): read it, write in it.

On *Dziś* for the athlete -- and for a coach looking at them -- and behind
"Notatka" on each sticky note of the team page. The thread lives in the
athlete's directory; only the athlete and their coach write there.

``auto_read``: a thread on a page is read by being shown; a thread in a
popover is not (Streamlit runs a popover's body while it is closed), so there
"read" is a button -- or answering.
"""

from __future__ import annotations

import datetime as dt
import html

import streamlit as st

from core import i18n
from core import team
from core import tenant


def _name(person_id: str) -> str:
    try:
        return tenant.get(person_id).name
    except tenant.NoUser:
        return person_id


def _when(stamp: str) -> str:
    try:
        moment = dt.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return ""
    return f"{i18n.day_month(moment.date())} {moment:%H:%M}"


def thread(athlete: tenant.User, author: tenant.User, *, key: str, limit: int = 8, auto_read: bool = False) -> None:
    tr = i18n.tr
    found = team.notes(athlete)
    fresh = {n["id"] for n in team.unread(athlete, author.id)}
    if not found:
        st.caption(tr(pl="Jeszcze nic. Pierwsza notatka zaczyna wątek, który widzicie oboje.",
                      en="Nothing yet. The first note starts a thread you both see."))
    for note in found[:limit]:
        new = " <span class='nt-new'>" + tr(pl="nowa", en="new") + "</span>" if note["id"] in fresh else ""
        st.markdown(f"<div class='nt'><div class='nt-h'><b>{html.escape(_name(note['by']))}</b> "
                    f"<span>{_when(note.get('at'))}</span>{new}</div>"
                    f"<div class='nt-t'>{html.escape(note['text'])}</div></div>", unsafe_allow_html=True)
    with st.form(f"{key}_form", clear_on_submit=True, border=False):
        body = st.text_area(tr(pl="Notatka", en="Note"), key=f"{key}_text", max_chars=team.NOTE_MAX, height=90,
                            label_visibility="collapsed",
                            placeholder=tr(pl="Napisz notatkę…", en="Write a note…"))
        if st.form_submit_button(tr(pl="Wyślij", en="Send")) and body.strip():
            team.add_note(athlete, author, body)
            team.mark_read(athlete, author.id)
            st.rerun()
    if fresh:
        if auto_read:
            team.mark_read(athlete, author.id)
        elif st.button(tr(pl="Oznacz jako przeczytane", en="Mark as read"), key=f"{key}_read", type="tertiary"):
            team.mark_read(athlete, author.id)
            st.rerun()
    st.html("""<style>
      .nt { margin: 0.2rem 0 0.6rem; }
      .nt-h { font-size: 0.78rem; opacity: 0.85; }
      .nt-h span { opacity: 0.7; margin-left: 0.3rem; }
      .nt-new { font-weight: 700; margin-left: 0.4rem; text-transform: uppercase; font-size: 0.68rem; letter-spacing: 0.05em; }
      .nt-t { font-size: 0.9rem; white-space: pre-wrap; }
    </style>""")
