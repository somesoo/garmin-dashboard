"""Local entry point for the server: ``python serve.py [streamlit options]``.

Same as ``streamlit run app.py``, plus the idle watchdog from lifecycle.py,
started with the process -- so a server nobody ever opened stops too, not
only one whose last tab was closed -- and the Garmin pull timer from sync.py.
The launchers use this; the systemd unit keeps plain ``streamlit run`` and
stays up.

``python serve.py --stop-if-stale`` stops a running server that was started
from older code. Streamlit re-runs a changed ``app.py`` but keeps modules it
already imported (without ``watchdog`` it does not watch them), so a server
left open across a code change runs new pages against old helpers and fails
with ``module 'shell' has no attribute ...``. The launchers call this first;
the port check that follows then starts a fresh server.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import sync

ROOT = Path(__file__).resolve().parent
RECORD = ROOT / "data" / "server.json"
# Same as .streamlit/config.toml: Streamlit reads that file from the working
# directory, and a launcher double-clicked in Finder starts in $HOME.
THEME = ["--theme.base", "dark", "--theme.backgroundColor", "#1a1c20",
         "--theme.secondaryBackgroundColor", "#23262c", "--theme.textColor", "#fafafa",
         "--theme.primaryColor", "#3987e5"]
SKIP = {".venv", "data", "__pycache__", ".git", "cache"}


def code_stamp() -> float:
    """Newest modification time of the code the server imports."""
    newest = 0.0
    for path in ROOT.rglob("*"):
        if path.suffix not in (".py", ".js", ".html", ".toml") or SKIP & set(path.relative_to(ROOT).parts):
            continue
        newest = max(newest, path.stat().st_mtime)
    return newest


def security_flags(given: list[str]) -> list[str]:
    """Streamlit options that keep several people's health data private.

    - the sign-in secrets (``data/secrets.toml``, auth.py) are passed explicitly:
      Streamlit would otherwise only look next to the working directory;
    - with more than one person the server listens on 127.0.0.1 only, so the
      way in is the HTTPS proxy in front (``tailscale serve``) -- a trusted
      sign-in header from anywhere else would be a forgery;
    - no usage statistics leave the browser.
    An option given on the command line wins.
    """
    import auth
    import tenant

    def unset(name: str) -> bool:
        return not any(arg == f"--{name}" or arg.startswith(f"--{name}=") for arg in given)

    flags = []
    if auth.SECRETS.exists() and unset("secrets.files"):
        flags += ["--secrets.files", str(auth.SECRETS)]
    if len(tenant.users()) > 1 and unset("server.address"):
        flags += ["--server.address", "127.0.0.1"]
    if unset("browser.gatherUsageStats"):
        flags += ["--browser.gatherUsageStats", "false"]
    if unset("server.maxUploadSize"):
        # A full Apple Health export with years of watch data is hundreds of MB (views/devices.py).
        flags += ["--server.maxUploadSize", "2048"]
    return flags


def start_api() -> int | None:
    """With more than one person (or GARMIN_API_PORT set) the API runs next to the dashboard
    in this process: pushes from iPhones and the warehouse for the apps (api.py)."""
    import threading

    import tenant

    port = os.environ.get("GARMIN_API_PORT")
    if not port and len(tenant.users()) < 2:
        return None
    import api

    number = int(port or 8502)
    threading.Thread(target=api.serve, args=(number,), daemon=True, name="api").start()
    return number


def stop_if_stale() -> int:
    try:
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        pid, stamp = int(record["pid"]), float(record["stamp"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    if not sync.alive(pid, "serve.py") or code_stamp() <= stamp:
        return 0
    print(f"== Kod zmienił się od startu serwera (pid {pid}) — restart ==", flush=True)
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not sync.alive(pid, "serve.py"):
            break
        time.sleep(0.25)
    RECORD.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--stop-if-stale"]:
        sys.exit(stop_if_stale())

    import lifecycle
    from streamlit.web import cli

    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps({"pid": os.getpid(), "stamp": code_stamp()}), encoding="utf-8")
    lifecycle.idle_exit()
    sync.auto()
    start_api()
    theme = [] if any(arg.startswith("--theme.") for arg in sys.argv[1:]) else THEME
    sys.argv = ["streamlit", "run", str(ROOT / "app.py"), *theme, *security_flags(sys.argv[1:]), *sys.argv[1:]]
    sys.exit(cli.main())
