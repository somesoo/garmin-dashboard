"""Local entry point for the server: ``python serve.py [streamlit options]``.

Same as ``streamlit run app.py``, plus the idle watchdog from lifecycle.py,
started with the process -- so a server nobody ever opened stops too, not
only one whose last tab was closed. The launchers use this; the systemd unit
keeps plain ``streamlit run`` and stays up.

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
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECORD = ROOT / "data" / "server.json"
# Same as .streamlit/config.toml: Streamlit reads that file from the working
# directory, and a launcher double-clicked in Finder starts in $HOME.
THEME = ["--theme.base", "dark", "--theme.backgroundColor", "#1a1c20",
         "--theme.secondaryBackgroundColor", "#23262c", "--theme.textColor", "#fafafa"]
SKIP = {".venv", "data", "__pycache__", ".git", "cache"}


def code_stamp() -> float:
    """Newest modification time of the code the server imports."""
    newest = 0.0
    for path in ROOT.rglob("*"):
        if path.suffix not in (".py", ".js", ".html", ".toml") or SKIP & set(path.relative_to(ROOT).parts):
            continue
        newest = max(newest, path.stat().st_mtime)
    return newest


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # Guard against a recycled pid: it must still be this server.
    command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    return "serve.py" in command


def stop_if_stale() -> int:
    try:
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        pid, stamp = int(record["pid"]), float(record["stamp"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    if not _alive(pid) or code_stamp() <= stamp:
        return 0
    print(f"== Kod zmienił się od startu serwera (pid {pid}) — restart ==", flush=True)
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not _alive(pid):
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
    theme = [] if any(arg.startswith("--theme.") for arg in sys.argv[1:]) else THEME
    sys.argv = ["streamlit", "run", str(ROOT / "app.py"), *theme, *sys.argv[1:]]
    sys.exit(cli.main())
