"""What is within reach: the conditions the viewer ticked, in ``data/sport.json``.

Hand-entered state like ``data/coach/`` -- it cannot be rebuilt from ``raw/``.
Unknown codes are dropped on read, so a renamed condition never blocks a page.

Before anything is saved the default is what the record proves: conditions of
disciplines done in the last year, minus ``catalog.TRAVEL`` -- water, wind, snow
and mountains are a trip, ticked for the days away, never assumed.
"""

from __future__ import annotations

import json
from pathlib import Path

import config
from sport import catalog

PATH = config.DATA / "sport.json"


def default_available(recent: list[str] | set[str]) -> list[str]:
    """``recent``: disciplines done in the last year."""
    proven = catalog.needs_of(recent)
    return [code for code in catalog.CONDITIONS if code in proven and code not in catalog.TRAVEL]


def available(recent: list[str] | set[str] = (), path: Path | None = None) -> list[str]:
    """Ticked conditions; the record's default when nothing was ever saved."""
    path = path or PATH
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("available")
    except (OSError, ValueError, AttributeError):
        saved = None
    if not isinstance(saved, list):
        return default_available(recent)
    return [code for code in catalog.CONDITIONS if code in saved]


def save_available(codes: list[str], path: Path | None = None) -> None:
    path = path or PATH
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current["available"] = [code for code in catalog.CONDITIONS if code in codes]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
