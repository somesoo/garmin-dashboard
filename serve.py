"""Local entry point for the server: ``python serve.py [streamlit options]``.

Same as ``streamlit run app.py``, plus the idle watchdog from lifecycle.py,
started with the process -- so a server nobody ever opened stops too, not
only one whose last tab was closed. The launchers use this; the systemd unit
keeps plain ``streamlit run`` and stays up.
"""

from __future__ import annotations

import sys
from pathlib import Path

import lifecycle
from streamlit.web import cli

if __name__ == "__main__":
    lifecycle.idle_exit()
    sys.argv = ["streamlit", "run", str(Path(__file__).resolve().parent / "app.py"), *sys.argv[1:]]
    sys.exit(cli.main())
