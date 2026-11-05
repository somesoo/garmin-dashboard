"""The HTTP side next to the dashboard: pushes from the iPhone in, the warehouse out for the apps.

    .venv/bin/python api.py [--port 8502]                       serve on 127.0.0.1
    .venv/bin/python -m api token add y --name "iPhone" --scope ingest
    .venv/bin/python -m api token list y
    .venv/bin/python -m api token revoke y <prefix>

Endpoints (``Authorization: Bearer <token>``):

- ``POST /api/ingest/apple`` (scope ``ingest``): one push from the iOS Shortcut or
  Health Auto Export (etl/apple_push.py). Stored as received under the person's
  ``raw/apple/push/`` (the same body twice is one file), then the tables are
  rebuilt in the background (sync.request_rebuild). 202 with what was stored.
- ``GET /api/manifest`` (scope ``read``): whose data, when it was built, tables.
- ``GET /api/db`` (scope ``read``): the person's warehouse as one SQLite file,
  with an ETag -- an app keeps it as its offline cache and asks again with
  ``If-None-Match`` (304 when nothing changed).
- ``GET /api/health``: no token; ``{"ok": true}``.

Tokens: random, shown once, stored only as SHA-256 in ``data/users/<id>/tokens.json``,
each with a scope. A token opens exactly one person's data. Like Streamlit, the
API listens on 127.0.0.1 only; ``tailscale serve --set-path /api`` puts it on
HTTPS next to the dashboard (docs/DOSTEP.md).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path
from typing import Any

from core import tenant

SCOPES = ("ingest", "read")
MAX_BODY = 64 * 1024 * 1024  # a day of watch samples is ~1-3 MB; a week's backfill fits too
TOKEN_PREFIX = "gd_"


# ------------------------------------------------------------------ tokens


def tokens_path(person: tenant.User) -> Path:
    return person.root / "tokens.json"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _read_tokens(person: tenant.User) -> list[dict[str, Any]]:
    try:
        value = json.loads(tokens_path(person).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _write_tokens(person: tenant.User, items: list[dict[str, Any]]) -> None:
    path = tokens_path(person)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.part")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(items, out, indent=2)
    tmp.replace(path)


def create_token(person: tenant.User, name: str, scope: str) -> str:
    """A new token for ``person``; the only time it exists in clear text is this return value."""
    if scope not in SCOPES:
        raise ValueError(f"scope: {', '.join(SCOPES)}")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    items = _read_tokens(person)
    items.append({"name": name, "scope": scope, "sha256": _digest(token), "prefix": token[:10],
                  "created": dt.datetime.now().isoformat(timespec="seconds"), "last_used": None})
    _write_tokens(person, items)
    return token


def revoke_token(person: tenant.User, prefix: str) -> int:
    items = _read_tokens(person)
    kept = [t for t in items if not t["prefix"].startswith(prefix)]
    _write_tokens(person, kept)
    return len(items) - len(kept)


def list_tokens(person: tenant.User) -> list[dict[str, Any]]:
    return [{k: v for k, v in t.items() if k != "sha256"} for t in _read_tokens(person)]


def verify(token: str | None, scope: str) -> tenant.User | None:
    """The person a token belongs to, when it carries ``scope``; None otherwise."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    wanted = _digest(token)
    for person in tenant.users().values():
        items = _read_tokens(person)
        for item in items:
            if hmac.compare_digest(item.get("sha256", ""), wanted):
                if item.get("scope") != scope:
                    return None
                item["last_used"] = dt.datetime.now().isoformat(timespec="seconds")
                _write_tokens(person, items)
                return person
    return None


# ------------------------------------------------------------------ the warehouse as SQLite


def sqlite_export(person: tenant.User) -> tuple[Path, str] | None:
    """The person's tables in one SQLite file, cached per build; (path, etag)."""
    import pandas as pd

    from core import db

    try:
        state = json.loads(person.state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    built = str(state.get("built_at", ""))
    etag = hashlib.sha256(f"{person.id}|{built}".encode()).hexdigest()[:24]
    folder = person.root / "cache"
    target = folder / f"warehouse-{etag}.sqlite"
    if target.exists():
        return target, etag
    folder.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{os.getpid()}.part")
    with tenant.use(person.id), sqlite3.connect(tmp) as con:
        for name in db.TABLE_NAMES:
            frame = db.table(name)
            if frame.empty:
                continue
            for column in frame.columns:  # SQLite has no timestamps: ISO text sorts and parses everywhere
                if pd.api.types.is_datetime64_any_dtype(frame[column]):
                    frame[column] = frame[column].dt.strftime("%Y-%m-%dT%H:%M:%S")
            frame.to_sql(name, con, index=False)
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        con.executemany("INSERT INTO meta VALUES (?, ?)",
                        [("person", person.id), ("name", person.name), ("source", person.source),
                         ("built_at", built)])
    tmp.replace(target)
    for old in folder.glob("warehouse-*.sqlite"):
        if old != target:
            old.unlink(missing_ok=True)
    return target, etag


# ------------------------------------------------------------------ the app


def _bearer(request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


def build_app():
    from starlette.applications import Starlette
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import FileResponse, JSONResponse, Response
    from starlette.middleware import Middleware
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles

    from core import sync
    from etl import apple_push

    def refused() -> JSONResponse:
        return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def ingest(request: Request) -> JSONResponse:
        person = verify(_bearer(request), "ingest")
        if person is None:
            return refused()
        if person.source != "apple":
            return JSONResponse({"error": f"{person.id} has source {person.source}"}, status_code=409)
        length = int(request.headers.get("content-length") or 0)
        if length > MAX_BODY:
            return JSONResponse({"error": "too large"}, status_code=413)
        body = await request.body()
        if len(body) > MAX_BODY:
            return JSONResponse({"error": "too large"}, status_code=413)
        try:
            payload = json.loads(body)
            counts = apple_push.describe(payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)[:200]}, status_code=400)
        def keep() -> tuple[Path, bool, str]:
            with tenant.use(person.id):
                path, new = apple_push.store(body)
                return path, new, (sync.request_rebuild() if new else "unchanged")

        path, new, rebuild = await run_in_threadpool(keep)
        return JSONResponse({"stored": path.name, "new": new, "rebuild": rebuild, **counts}, status_code=202)

    def manifest(request: Request) -> JSONResponse:  # sync: Starlette runs it in a thread (disk work)
        person = verify(_bearer(request), "read")
        if person is None:
            return refused()
        try:
            state = json.loads(person.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        exported = sqlite_export(person)
        return JSONResponse({"person": person.id, "name": person.name, "source": person.source,
                             "built_at": state.get("built_at"), "days": state.get("days"),
                             "activities": state.get("activities"),
                             "db": {"etag": exported[1], "bytes": exported[0].stat().st_size} if exported else None})

    def database(request: Request) -> Response:
        person = verify(_bearer(request), "read")
        if person is None:
            return refused()
        exported = sqlite_export(person)
        if exported is None:
            return JSONResponse({"error": "no data yet"}, status_code=404)
        path, etag = exported
        quoted = f'"{etag}"'
        if request.headers.get("if-none-match") == quoted:
            return Response(status_code=304, headers={"ETag": quoted})
        return FileResponse(path, media_type="application/vnd.sqlite3", headers={
            "ETag": quoted, "Cache-Control": "private, no-cache"}, filename=f"{person.id}.sqlite")

    def summary_json(request: Request) -> Response:
        """What the phone app shows (summary.py), per language; ETag/304."""
        from analysis import summary

        person = verify(_bearer(request), "read")
        if person is None:
            return refused()
        body, etag = summary.cached(person, request.query_params.get("lang", "pl"))
        quoted = f'"{etag}"'
        if request.headers.get("if-none-match") == quoted:
            return Response(status_code=304, headers={"ETag": quoted})
        return Response(body, media_type="application/json",
                        headers={"ETag": quoted, "Cache-Control": "private, no-cache"})

    # Under /api and at the root: `tailscale serve --set-path /api` may hand the
    # request on with or without the prefix, depending on the version.
    routes = []
    for prefix in ("/api", ""):
        routes += [Route(f"{prefix}/health", health), Route(f"{prefix}/ingest/apple", ingest, methods=["POST"]),
                   Route(f"{prefix}/manifest", manifest), Route(f"{prefix}/db", database),
                   Route(f"{prefix}/summary", summary_json),
                   Mount(f"{prefix}/app", app=StaticFiles(directory=PWA, html=True))]
    return Starlette(routes=routes, middleware=[Middleware(_AppHeaders)])


PWA = Path(__file__).resolve().parent / "pwa"
# The phone app runs only its own files and talks only to this origin.
APP_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


class _AppHeaders:
    """Security headers on the app's static files; nosniff/no-referrer on everything."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_app = "/app" in scope.get("path", "")

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {k.lower() for k, _ in headers}
                extra = APP_HEADERS if is_app else {k: v for k, v in APP_HEADERS.items()
                                                    if k in ("X-Content-Type-Options", "Referrer-Policy")}
                for key, value in extra.items():
                    if key.lower().encode() not in names:
                        headers.append((key.lower().encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, with_headers)


def serve(port: int) -> None:
    import uvicorn

    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning", proxy_headers=True,
                forwarded_allow_ips="127.0.0.1")


# ------------------------------------------------------------------ CLI


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m api")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("serve")
    run.add_argument("--port", type=int, default=int(os.environ.get("GARMIN_API_PORT", 8502)))
    token = sub.add_parser("token").add_subparsers(dest="action", required=True)
    add = token.add_parser("add")
    add.add_argument("person")
    add.add_argument("--name", required=True)
    add.add_argument("--scope", choices=SCOPES, required=True)
    token.add_parser("list").add_argument("person")
    revoke = token.add_parser("revoke")
    revoke.add_argument("person")
    revoke.add_argument("prefix")
    args = parser.parse_args(argv)
    if args.command == "token":
        person = tenant.get(args.person)
        if args.action == "add":
            print(create_token(person, args.name, args.scope))
            print("Zapisz go teraz — nie da się go odczytać ponownie.", file=sys.stderr)
        elif args.action == "list":
            for item in list_tokens(person):
                print(f"{item['prefix']}…  {item['scope']:6}  {item['name']}  utworzony {item['created']}  "
                      f"użyty {item['last_used'] or '—'}")
        else:
            print(f"odwołano: {revoke_token(person, args.prefix)}")
        return 0
    serve(getattr(args, "port", None) or int(os.environ.get("GARMIN_API_PORT", 8502)))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
