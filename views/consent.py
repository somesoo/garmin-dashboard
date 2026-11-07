"""Consent before anything: the screen a person sees until they agree to the current policy.

Runs in app.py right after ``auth.gate`` -- before onboarding, so no source is
connected and nothing is pulled until the person has agreed (RODO art. 9(2)(a)).
The controller never sees it (``privacy.controller``). A new ``POLICY_VERSION``
brings it back with "the rules changed"; declining then offers deleting
everything, since without consent nothing of theirs may be kept.

A child's parent or guardian consents in the child's name (``privacy.CHILD_AGE``).
A person with a coach (core/team.py) gets a second, separate box for the coach,
with its scope -- unticked by default and never needed to go on.

Always the viewer's consent (``tenant.viewer``): a coach looking at an athlete
is asked about their own data, never shown the athlete's screen.
"""

from __future__ import annotations

import streamlit as st

from core import audit
from core import auth
from core import i18n
from core import privacy
from core import team
from core import tenant
from ui import shell


def gate() -> None:
    """Stop the run on the consent screen while the current person owes one."""
    person = tenant.viewer()
    if not privacy.required(person):
        return
    _screen(person)
    st.stop()


def _ip() -> str | None:
    try:
        return audit.client_ip(st.context.headers, st.context.ip_address)
    except Exception:  # noqa: BLE001
        return None


def _screen(person: tenant.User) -> None:
    tr = i18n.tr
    renewing = privacy.consent(person) is not None
    with st.container(horizontal=True, key="consent_lang"):
        st.space("stretch")
        shell.language_picker()
    _, middle, _ = st.columns([1, 2.2, 1])
    with middle, st.container(key="consent_card"):
        st.markdown("<h1 class='signin-title'>" + (
            tr(pl="Zasady się zmieniły", en="The rules have changed") if renewing
            else tr(pl=f"Cześć, {person.name}", en=f"Hi, {person.name}")) + "</h1>", unsafe_allow_html=True)
        st.markdown(tr(
            pl="Zanim cokolwiek tu trafi, przeczytaj, co dzieje się z Twoimi danymi. Dane z zegarka to dane o "
               "zdrowiu — bez Twojej zgody dashboard ich nie pobierze ani nie pokaże.",
            en="Before anything lands here, read what happens to your data. Watch data is health data — without "
               "your consent the dashboard will neither pull nor show it."))
        st.markdown(privacy.policy())
        agreed_by, guardian = who_agrees("consent")
        agreed = st.checkbox(privacy.consent_sentence(agreed_by), key="consent_check")
        coach_scope = _coach_box(person, agreed_by)
        ready = agreed and (agreed_by == "self" or bool(guardian))
        if st.button(tr(pl="Zgadzam się, przejdź dalej", en="I agree, continue"), type="primary",
                     disabled=not ready, key="consent_accept", width="stretch"):
            privacy.accept(person, i18n.lang(), _ip(), agreed_by=agreed_by, guardian=guardian)
            if coach_scope:
                team.give(person, coach_scope, agreed_by, guardian, _ip())
            else:
                # A renewed consent without the coach box: the old consent to the coach ends too.
                team.revoke(person, _ip())
            st.rerun()
        with st.expander(tr(pl="Nie zgadzam się", en="I do not agree")):
            if renewing and not person.legacy:
                st.caption(tr(pl="Bez zgody nie możemy trzymać Twoich danych. Pobierz ich kopię, jeśli chcesz, "
                                 "i usuń wszystko.",
                              en="Without consent we cannot keep your data. Take a copy if you want one, "
                                 "then delete everything."))
                if st.button(tr(pl="Przygotuj kopię", en="Prepare a copy"), key="consent_archive"):
                    st.session_state["consent_archive_data"] = tenant.archive(person)
                    audit.record("archive", person.id, ip=_ip())
                data = st.session_state.get("consent_archive_data")
                if data:
                    st.download_button(tr(pl="Pobierz", en="Download"), data=data, file_name=f"{person.id}.zip",
                                       mime="application/zip", key="consent_download", on_click="ignore")
                if st.button(tr(pl="Usuń wszystkie moje dane", en="Delete all my data"), key="consent_erase"):
                    privacy.withdraw(person, _ip())
                    st.cache_data.clear()
                    st.success(tr(pl="Usunięto. Możesz zamknąć tę stronę.", en="Deleted. You can close this page."))
            else:
                st.caption(tr(pl="Nic nie zostało pobrane ani zapisane. Możesz zamknąć tę stronę.",
                              en="Nothing has been pulled or stored. You can close this page."))
            if auth.can_sign_out():
                st.button(tr(pl="Wyloguj", en="Sign out"), on_click=st.logout, key="consent_logout")


def who_agrees(key: str) -> tuple[str, str | None]:
    """("self" | "guardian", the guardian's name): who gives this consent. Also on the account page."""
    tr = i18n.tr
    labels = {"self": tr(pl=f"Ja — mam co najmniej {privacy.CHILD_AGE} lat",
                         en=f"Me — I am {privacy.CHILD_AGE} or older"),
              "guardian": tr(pl="Rodzic lub opiekun prawny — w imieniu dziecka",
                             en="A parent or legal guardian — for a child")}
    agreed_by = st.radio(tr(pl="Kto wyraża zgodę", en="Who gives consent"), list(labels), format_func=labels.get,
                         key=f"{key}_by", horizontal=True)
    guardian = None
    if agreed_by == "guardian":
        guardian = st.text_input(tr(pl="Imię i nazwisko rodzica lub opiekuna", en="Parent's or guardian's full name"),
                                 key=f"{key}_guardian", max_chars=80).strip() or None
    return agreed_by, guardian


def scope_labels() -> dict[str, str]:
    tr = i18n.tr
    return {"training": tr(pl="Tylko trening — biegi, plan, starty, trasy", en="Training only — runs, plan, races, routes"),
            "all": tr(pl="Wszystko — także sen, HRV i regeneracja", en="Everything — sleep, HRV and recovery too")}


def _coach_box(person: tenant.User, agreed_by: str) -> str | None:
    """The separate consent to the coach; the chosen scope, or None when the box is not ticked."""
    if not person.coach_id:
        return None
    tr = i18n.tr
    try:
        coach = tenant.get(person.coach_id)
    except tenant.NoUser:
        return None
    st.markdown(f"**{tr(pl='Trener', en='Coach')}** — " + tr(
        pl=f"{coach.name} jest przypisany jako Twój trener. To osobna zgoda: bez niej korzystasz z dashboardu "
           "normalnie, a trener nic nie widzi.",
        en=f"{coach.name} is assigned as your coach. This is a separate consent: without it you use the dashboard "
           "as usual and the coach sees nothing."))
    labels = scope_labels()
    chosen = st.radio(tr(pl="Co trener może widzieć", en="What the coach may see"), list(labels),
                      format_func=labels.get, key="consent_coach_scope")
    if st.checkbox(privacy.coach_sentence(coach.name, chosen, agreed_by), key="consent_coach"):
        return chosen
    return None
