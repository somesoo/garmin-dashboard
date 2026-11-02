"""Who is looking: the person behind this browser session, before any page reads data.

``gate()`` runs first in app.py on every rerun. It puts the person's id in the
session (``tenant.SESSION_KEY``), and from then on every path, cache key and
query of the run answers for that person (tenant.py). Nobody recognised = a
sign-in screen and ``st.stop()`` -- never a default person.

Ways in, first match wins:

1. **Single person** (no ``data/users.json``, or one person in it): as before,
   no sign-in at all.
2. **OIDC** (``st.login``): when ``.streamlit/secrets.toml`` has an ``[auth]``
   section (Google or any OpenID provider; needs ``Authlib``). The e-mail of the
   signed-in account must be in someone's ``identities``.
3. **A header from a trusted proxy**: ``GARMIN_AUTH_HEADER=Tailscale-User-Login``
   with ``tailscale serve`` in front -- Tailscale puts the tailnet login of the
   visitor in that header. Only safe when Streamlit listens on 127.0.0.1 and
   the proxy is the only way in; otherwise anyone can send the header.
4. **This machine**: a browser on the server itself (no forwarding headers,
   loopback address) is the one person marked ``local`` in the registry.

A visitor whose identity is present but unknown is refused -- an unknown
e-mail never falls through to "local".
"""

from __future__ import annotations

import ipaddress
import os

import streamlit as st

import i18n
import tenant

HEADER_ENV = "GARMIN_AUTH_HEADER"
# A request that went through a proxy carries one of these; it is then not
# "a browser on this machine", even though Streamlit sees a loopback peer.
FORWARDED = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host", "tailscale-user-login")


def _oidc_configured() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:  # noqa: BLE001 - no secrets.toml at all
        return False


def _header(name: str) -> str | None:
    try:
        headers = st.context.headers
    except Exception:  # noqa: BLE001 - outside a browser session
        return None
    value = headers.get(name)
    return value.strip() if value else None


def _is_local() -> bool:
    if any(_header(name) for name in FORWARDED):
        return False
    try:
        address = st.context.ip_address
    except Exception:  # noqa: BLE001
        return False
    if address is None:  # Streamlit reports None for localhost
        return True
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def identify() -> tuple[tenant.User | None, str | None]:
    """(the person, the identity that was presented but matched nobody)."""
    everyone = tenant.users()
    if len(everyone) == 1:
        return next(iter(everyone.values())), None

    if _oidc_configured() and st.user.is_logged_in:
        email = str(st.user.get("email") or "")
        return tenant.by_identity(email), email or None

    header = os.getenv(HEADER_ENV, "").strip()
    if header:
        value = _header(header)
        if value:
            return tenant.by_identity(value), value

    if _is_local():
        return tenant.local_user(), None
    return None, None


def gate() -> tenant.User:
    """The person of this run; a sign-in screen and ``st.stop()`` when there is none."""
    person, presented = identify()
    if person is None:
        st.session_state.pop(tenant.SESSION_KEY, None)
        _refused(presented)
        st.stop()
    if st.session_state.get(tenant.SESSION_KEY) not in (None, person.id):
        # A different person in the same session (a new sign-in): nothing kept
        # in the session from the previous one may leak into this run.
        for key in list(st.session_state.keys()):
            del st.session_state[key]
    st.session_state[tenant.SESSION_KEY] = person.id
    return person


def can_sign_out() -> bool:
    return _oidc_configured() and bool(st.user.is_logged_in)


def _refused(presented: str | None) -> None:
    tr = i18n.tr
    st.title("Garmin Dashboard")
    if presented:
        st.error(tr(pl=f"Konto {presented} nie ma tu dostępu do żadnych danych.",
                    en=f"The account {presented} has no data here."))
        if can_sign_out():
            st.button(tr(pl="Wyloguj", en="Sign out"), on_click=st.logout, type="primary")
        return
    if _oidc_configured():
        st.info(tr(pl="Zaloguj się, żeby zobaczyć swoje dane.", en="Sign in to see your data."))
        st.button(tr(pl="Zaloguj", en="Sign in"), on_click=st.login, type="primary")
        return
    st.warning(tr(
        pl="Nie wiadomo, czyje dane pokazać. Ten serwer ma kilka osób, a połączenie nie niesie tożsamości "
           "(ustaw logowanie: `[auth]` w `.streamlit/secrets.toml` albo `GARMIN_AUTH_HEADER` za `tailscale serve`).",
        en="It is not known whose data to show. This server has several people and the connection carries no "
           "identity (set up sign-in: `[auth]` in `.streamlit/secrets.toml` or `GARMIN_AUTH_HEADER` behind "
           "`tailscale serve`).",
    ))
