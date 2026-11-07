"""Consent before anything: the screen a person sees until they agree to the current policy.

Runs in app.py right after ``auth.gate`` -- before onboarding, so no source is
connected and nothing is pulled until the person has agreed (RODO art. 9(2)(a)).
The controller never sees it (``privacy.controller``). A new ``POLICY_VERSION``
brings it back with "the rules changed"; declining then offers deleting
everything, since without consent nothing of theirs may be kept.
"""

from __future__ import annotations

import streamlit as st

from core import audit
from core import auth
from core import i18n
from core import privacy
from core import tenant
from ui import shell


def gate() -> None:
    """Stop the run on the consent screen while the current person owes one."""
    person = tenant.current()
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
        agreed = st.checkbox(privacy.consent_sentence(), key="consent_check")
        if st.button(tr(pl="Zgadzam się, przejdź dalej", en="I agree, continue"), type="primary",
                     disabled=not agreed, key="consent_accept", width="stretch"):
            privacy.accept(person, i18n.lang(), _ip())
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
