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

import config  # noqa: E402

from garminconnect import Garmin  # noqa: E402


def main() -> int:
    email = os.getenv("GARMIN_EMAIL") or input("E-mail Garmin: ").strip()
    password = getpass("Haslo Garmin: ")

    api = Garmin(email=email, password=password, return_on_mfa=True)
    password = None
    status, client_state = api.login(config.TOKENSTORE)

    if status == "needs_mfa":
        api.resume_login(client_state, input("Kod MFA: ").strip())

    api.client.dump(config.TOKENSTORE)
    print(f"OK, zalogowany jako {api.get_full_name()}")
    print(f"Tokeny zapisane w {config.TOKENSTORE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
