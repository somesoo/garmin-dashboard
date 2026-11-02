"""Who is looking: the person behind this browser session, before any page reads data.

``gate()`` runs first in app.py on every rerun. It puts the person's id in the
session (``tenant.SESSION_KEY``), and from then on every path, cache key and
query of the run answers for that person (tenant.py). Nobody recognised = a
sign-in screen and ``st.stop()`` -- never a default person.

Ways in, first match wins:

1. **Single person** (no ``data/users.json``, or one person in it): as before,
   no sign-in at all.
2. **Google sign-in** (``st.login``, OIDC): when ``data/secrets.toml`` has an
   ``[auth]`` section (``python -m auth setup`` writes one; serve.py passes the
   file to Streamlit). The verified e-mail of the Google account must be in
   someone's ``identities``. Sign in with Apple is not offered: on the web it
   needs a paid Apple Developer Program membership (a Services ID).
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

import argparse
import ipaddress
import os
import secrets
import sys

import streamlit as st

import config
import i18n
import tenant

HEADER_ENV = "GARMIN_AUTH_HEADER"
# Sign-in secrets live with the data, not the code: per server, never in git.
SECRETS = config.DATA / "secrets.toml"
GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"
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
        # An address the provider has not verified proves nothing: anyone can
        # type a friend's e-mail into a fresh account at some providers.
        if st.user.get("email_verified") is False:
            return None, email or None
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
           "(ustaw logowanie Google: `python -m auth setup` albo `GARMIN_AUTH_HEADER` za `tailscale serve`).",
        en="It is not known whose data to show. This server has several people and the connection carries no "
           "identity (set up Google sign-in: `python -m auth setup` or `GARMIN_AUTH_HEADER` behind "
           "`tailscale serve`).",
    ))


# ------------------------------------------------------------------ setup (CLI)

TEMPLATE = """# Google sign-in for the dashboard (auth.py). Per server, never in git (data/ is ignored).
# 1. https://console.cloud.google.com/apis/credentials -> Create credentials -> OAuth client ID
#    -> Web application. Authorised redirect URI: exactly the redirect_uri below.
# 2. Paste the client ID and secret here, restart the server (serve.py passes this file).
# 3. Each person's Google e-mail goes into data/users.json -> "identities".
[auth]
redirect_uri = "{redirect_uri}"
cookie_secret = "{cookie_secret}"
client_id = "PASTE-CLIENT-ID.apps.googleusercontent.com"
client_secret = "PASTE-CLIENT-SECRET"
server_metadata_url = "{metadata}"
"""


def setup(argv: list[str] | None = None) -> int:
    """Write ``data/secrets.toml`` with a fresh cookie secret and Google's endpoints."""
    parser = argparse.ArgumentParser(prog="python -m auth setup")
    parser.add_argument("url", help="public HTTPS address of the dashboard, e.g. https://mac.tailnet.ts.net")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)
    if not args.url.startswith("https://") and not args.url.startswith("http://localhost"):
        print(i18n.tr(pl="Adres musi być HTTPS (Google nie przyjmie innego poza localhost) — np. z `tailscale serve`.",
                      en="The address must be HTTPS (Google accepts nothing else but localhost) — e.g. `tailscale serve`."))
        return 1
    if SECRETS.exists() and not args.force:
        print(i18n.tr(pl=f"{SECRETS} już istnieje (--force nadpisuje)", en=f"{SECRETS} exists (--force overwrites)"))
        return 1
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    body = TEMPLATE.format(redirect_uri=args.url.rstrip("/") + "/oauth2callback",
                           cookie_secret=secrets.token_urlsafe(48), metadata=GOOGLE_METADATA)
    fd = os.open(SECRETS, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(body)
    print(i18n.tr(pl=f"Zapisano {SECRETS} — wklej client_id i client_secret z Google Cloud Console.",
                  en=f"Wrote {SECRETS} — paste client_id and client_secret from Google Cloud Console."))
    return 0


if __name__ == "__main__":
    command, *rest = sys.argv[1:] or ["help"]
    if command != "setup":
        print("python -m auth setup <https://adres-dashboardu>")
        raise SystemExit(1)
    raise SystemExit(setup(rest))
