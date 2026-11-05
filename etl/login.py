"""Refresh the stored Garmin tokens with an interactive password login.

Only needed when the refresh token expires or after a password change. The
password is read with getpass and dropped as soon as the login returns; what
lands on disk is the token file the ETL uses from then on.
"""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config  # noqa: E402

from garminconnect import Garmin  # noqa: E402


def main() -> int:
    # Several people: GARMIN_USER=<id> picks whose tokens these are (tenant.py).
    person = config._person()
    store = config.tokenstore()
    print(f"Osoba: {person.id} -> {store}")
    email = os.getenv("GARMIN_EMAIL") or input("E-mail Garmin: ").strip()
    password = getpass("Haslo Garmin: ")

    api = Garmin(email=email, password=password, return_on_mfa=True)
    password = None
    status, client_state = api.login(store)

    if status == "needs_mfa":
        api.resume_login(client_state, input("Kod MFA: ").strip())

    # Tokens are as good as the password: only the server's user may read them.
    Path(store).expanduser().mkdir(parents=True, exist_ok=True, mode=0o700)
    api.client.dump(store)
    print(f"OK, zalogowany jako {api.get_full_name()}")
    print(f"Tokeny zapisane w {store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
