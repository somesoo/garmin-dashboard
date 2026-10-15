"""Insight files: markdown notes with live SQL blocks the dashboard renders.

An insight is a plain markdown file in insights/ that mixes prose with fenced
``sql`` blocks. Each block is executed against the warehouse when the page
loads, so an insight never goes stale -- the text is the interpretation, the
numbers come from today's data. This is the hand-off point for Claude Code:
writing a file here adds a panel to the dashboard, no code change needed.

Fence syntax::

    ```sql chart=line x=day y=hrv_last_night,hrv_last_night_roll7
    SELECT day, hrv_last_night, hrv_last_night_roll7 FROM daily
    ```

``chart`` accepts line, area, bar, scatter, table or metric (default: table).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config

FENCE = re.compile(r"```sql(?P<opts>[^\n]*)\n(?P<sql>.*?)```", re.DOTALL)
FRONTMATTER = re.compile(r"\A---\n(?P<yaml>.*?)\n---\n", re.DOTALL)


@dataclass
class Block:
    kind: str  # "text" or "sql"
    body: str
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class Insight:
    path: Path
    title: str
    meta: dict[str, Any]
    blocks: list[Block]

    @property
    def slug(self) -> str:
        return self.path.stem

    @property
    def created(self) -> str:
        return str(self.meta.get("created") or "")

    @property
    def tags(self) -> list[str]:
        tags = self.meta.get("tags")
        if isinstance(tags, str):
            return [t.strip() for t in tags.split(",") if t.strip()]
        if isinstance(tags, list):
            return [str(t) for t in tags]
        return []


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text
    raw = match.group("yaml")
    body = text[match.end() :]
    try:
        import yaml

        meta = yaml.safe_load(raw) or {}
    except Exception:
        meta = {}
        for line in raw.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
    return (meta if isinstance(meta, dict) else {}), body


OPTION = re.compile(r"(\w+)=(\"[^\"]*\"|'[^']*'|\S*)")


def _parse_options(raw: str) -> dict[str, str]:
    """Parse ``key=value`` fence options; quoted values may contain spaces."""
    opts: dict[str, str] = {}
    for key, value in OPTION.findall(raw):
        opts[key] = value.strip("\"'")
    return opts


def parse(path: Path) -> Insight:
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)

    blocks: list[Block] = []
    cursor = 0
    for match in FENCE.finditer(body):
        before = body[cursor : match.start()].strip()
        if before:
            blocks.append(Block("text", before))
        blocks.append(
            Block("sql", match.group("sql").strip(), _parse_options(match.group("opts")))
        )
        cursor = match.end()
    tail = body[cursor:].strip()
    if tail:
        blocks.append(Block("text", tail))

    title = str(meta.get("title") or "").strip()
    if not title:
        heading = next(
            (
                line.lstrip("# ").strip()
                for block in blocks
                if block.kind == "text"
                for line in block.body.splitlines()
                if line.startswith("#")
            ),
            "",
        )
        title = heading or path.stem.replace("-", " ").replace("_", " ").title()

    return Insight(path=path, title=title, meta=meta, blocks=blocks)


def load_all() -> list[Insight]:
    """Every insight file, pinned ones first, then newest by filename."""
    if not config.INSIGHTS.is_dir():
        return []
    found = []
    for path in sorted(config.INSIGHTS.glob("*.md")):
        if path.name.startswith("_") or path.name.upper() == "README.MD":
            continue
        try:
            found.append(parse(path))
        except OSError:
            continue
    found.sort(key=lambda i: (not bool(i.meta.get("pinned")), i.path.name), reverse=False)
    return found


def new_path(slug: str) -> Path:
    """Date-prefixed path for a new insight, so files sort chronologically."""
    safe = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-") or "insight"
    return config.INSIGHTS / f"{dt.date.today():%Y-%m-%d}-{safe}.md"
