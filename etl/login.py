"""Refresh the stored Garmin tokens with an interactive password login.

Only needed when the refresh token expires or after a password change (the
account page does the same from the browser). The password is read with
getpass and dropped as soon as the login returns; what lands on disk is the
sealed token file the ETL uses from then on (etl/garmin_auth.py).
"""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config  # noqa: E402
from etl import garmin_auth  # noqa: E402


def main() -> int:
    # Several people: GARMIN_USER=<id> picks whose tokens these are (tenant.py).
    person = config._person()
    store = config.tokenstore()
    print(f"Osoba: {person.id} -> {store}")
    email = os.getenv("GARMIN_EMAIL") or input("E-mail Garmin: ").strip()
    password = getpass("Haslo Garmin: ")

    status, result = garmin_auth.start(email, password, store)
    password = None
    if status == "mfa":
        name = garmin_auth.finish(result, input("Kod MFA: ").strip(), store)
    else:
        name = result
    print(f"OK, zalogowany jako {name or '?'}")
    print(f"Tokeny zapisane (zaszyfrowane) w {store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
