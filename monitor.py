"""What the admin page shows: the people, the app's processes, the machine, the pulls.

Pure Python, no Streamlit, so the tests run it. Linux numbers come from
``/proc`` -- psutil is not a dependency. Where a value cannot be read (a Mac
in development, a container hiding a file) it is None, never a guess.

Nothing here reads anyone's health data: sizes, counts, timestamps and exit
codes only. The page is for whoever runs the server (``tenant.User.admin``).

Mind the container: on a mikr.us VPS (LXC) the load average is the host's,
not ours, and ``/proc/meminfo`` is the container's own (lxcfs). CPU use is
therefore measured from ``/proc/stat`` over a short interval, not from load.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import config
import tenant

PROC = Path("/proc")
ROOT = Path(__file__).resolve().parent
# Warning thresholds; the page puts them into words.
MEMORY_LOW = 0.15      # available RAM / total
DISK_LOW = 0.10        # free disk / total
STALE_PULL_H = 24      # a connected Garmin person without a successful pull for this long
LOG_LINES = 40


# ------------------------------------------------------------------ small readers


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _when(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def size(path: Path) -> int:
    """Bytes under ``path`` (a file or a directory); 0 when it does not exist."""
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for folder, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total


def tail(path: Path, lines: int = LOG_LINES) -> str:
    text = _text(path)
    return "\n".join(text.splitlines()[-lines:]) if text else ""


# ------------------------------------------------------------------ people


def person(user: tenant.User) -> dict[str, Any]:
    """One person as the admin sees them: where the data is, how big, when built and pulled."""
    import sync

    with tenant.use(user.id):
        record = sync.last()
        running = sync.running()
    state = _json(user.state_file)
    if user.legacy:
        # The old layout's data/ also holds the other people and the server's files.
        total = sum(size(user.root / name) for name in tenant.OWNED)
    else:
        total = size(user.root)
    garmin = None
    if user.source == "garmin":
        from etl import garmin_auth

        garmin = garmin_auth.connected(user.tokenstore)
    try:
        import api

        keys = len(api.list_tokens(user))
    except Exception:  # noqa: BLE001 - a broken key file must not hide the person
        keys = None
    tables = user.tables
    return {
        "id": user.id, "name": user.name, "source": user.source, "admin": user.admin,
        "identities": list(user.identities), "legacy": user.legacy,
        "bytes": total, "raw_bytes": size(user.raw), "tables_bytes": size(tables),
        "tables": len(list(tables.glob("*.parquet"))) if tables.is_dir() else 0,
        "built_at": state.get("built_at"), "days": state.get("days"), "activities": state.get("activities"),
        "first_day": state.get("first_day"), "last_day": state.get("last_day"),
        "pull_started": record.get("started_at"), "pull_finished": record.get("finished_at"),
        "pull_code": record.get("code"), "running": running,
        "pending": (user.root / "rebuild.pending").exists(),
        "garmin": garmin, "keys": keys, "zones": user.zone_settings.exists(),
    }


def people() -> list[dict[str, Any]]:
    out = []
    for user in tenant.users().values():
        try:
            out.append(person(user))
        except Exception as exc:  # noqa: BLE001 - one unreadable person must not blank the page
            out.append({"id": user.id, "name": user.name, "source": user.source, "error": str(exc)})
    return out


# ------------------------------------------------------------------ processes and the machine


def _ticks() -> int:
    try:
        return os.sysconf("SC_CLK_TCK")
    except (AttributeError, ValueError, OSError):
        return 100


def _process_ticks(pid: int) -> int | None:
    text = _text(PROC / str(pid) / "stat")
    if not text:
        return None
    # The command name sits in parentheses and may contain spaces: split after it.
    fields = text[text.rfind(")") + 2:].split()
    return int(fields[11]) + int(fields[12])  # utime + stime


def _system_ticks() -> tuple[int, int] | None:
    """(busy, total) CPU ticks of the whole machine."""
    text = _text(PROC / "stat")
    if not text:
        return None
    values = [int(v) for v in text.splitlines()[0].split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values) - idle, sum(values)


def _status(pid: int) -> dict[str, int]:
    out = {}
    for line in (_text(PROC / str(pid) / "status") or "").splitlines():
        key, _, value = line.partition(":")
        if key in ("VmRSS", "Threads"):
            out[key] = int(value.split()[0])
    return out


def _started(pid: int) -> float | None:
    """Seconds the process has been running."""
    text, uptime = _text(PROC / str(pid) / "stat"), _text(PROC / "uptime")
    if not text or not uptime:
        return None
    start = int(text[text.rfind(")") + 2:].split()[19]) / _ticks()
    return max(0.0, float(uptime.split()[0]) - start)


def _role(command: str) -> str:
    if "serve.py" in command or "streamlit" in command:
        return "server"
    if "run.py" in command:
        return "etl"
    if "api" in command or "uvicorn" in command:
        return "api"
    return "other"


def app_processes() -> list[dict[str, Any]]:
    """Every process started from this checkout (its working directory is the repo)."""
    if not PROC.is_dir():
        return [{"pid": os.getpid(), "role": "server", "command": "", "rss_kb": None, "threads": None,
                 "uptime_s": None}]
    found = []
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if Path(os.readlink(entry / "cwd")).resolve() != ROOT:
                continue
        except OSError:
            continue
        command = (_text(entry / "cmdline") or "").replace("\x00", " ").strip()
        if not command or "python" not in command:
            continue
        pid = int(entry.name)
        status = _status(pid)
        found.append({"pid": pid, "role": _role(command), "command": command[:160],
                      "rss_kb": status.get("VmRSS"), "threads": status.get("Threads"), "uptime_s": _started(pid)})
    return sorted(found, key=lambda p: (p["role"] != "server", p["pid"]))


def memory() -> dict[str, int | None]:
    values = {}
    for line in (_text(PROC / "meminfo") or "").splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            values[key] = int(rest.split()[0])
    return {"total_kb": values.get("MemTotal"), "available_kb": values.get("MemAvailable"),
            "swap_total_kb": values.get("SwapTotal"), "swap_free_kb": values.get("SwapFree")}


def disk() -> dict[str, int]:
    usage = shutil.disk_usage(config.DATA if config.DATA.exists() else ROOT)
    return {"total": usage.total, "used": usage.used, "free": usage.free, "data": size(config.DATA)}


def snapshot(interval: float = 0.3) -> dict[str, Any]:
    """The machine and the app's processes now; CPU in % measured over ``interval`` seconds.

    Process CPU is in % of one core (two busy cores = 200%); the machine's in %
    of all of them.
    """
    processes = app_processes()
    before = {p["pid"]: _process_ticks(p["pid"]) for p in processes}
    system_before = _system_ticks()
    started = time.monotonic()
    time.sleep(interval)
    elapsed = time.monotonic() - started
    for proc in processes:
        now = _process_ticks(proc["pid"])
        then = before.get(proc["pid"])
        proc["cpu_pct"] = round(100 * (now - then) / _ticks() / elapsed, 1) if now is not None and then is not None \
            else None
    system_after = _system_ticks()
    cpu = None
    if system_before and system_after and system_after[1] > system_before[1]:
        cpu = round(100 * (system_after[0] - system_before[0]) / (system_after[1] - system_before[1]), 1)
    return {"at": dt.datetime.now().isoformat(timespec="seconds"), "processes": processes,
            "memory": memory(), "disk": disk(), "cpu_pct": cpu, "cores": os.cpu_count(),
            "sessions": sessions()}


def sessions() -> int | None:
    """Browser tabs connected to this server right now (Streamlit's private counter)."""
    import lifecycle

    return lifecycle._active_sessions()


def code() -> dict[str, Any]:
    """The commit on disk, and whether the running server is older than the code (needs a restart)."""
    head = _text(ROOT / ".git" / "HEAD") or ""
    commit = None
    if head.startswith("ref:"):
        commit = (_text(ROOT / ".git" / head.split()[1]) or "").strip()[:7] or None
    elif head.strip():
        commit = head.strip()[:7]
    record = _json(ROOT / "data" / "server.json")
    stale = None
    if record.get("stamp"):
        import serve

        stale = serve.code_stamp() > float(record["stamp"])
    return {"commit": commit, "server_pid": record.get("pid"), "stale": stale}


# ------------------------------------------------------------------ what needs attention


def warnings(machine: dict[str, Any], folks: list[dict[str, Any]], version: dict[str, Any] | None = None,
             now: dt.datetime | None = None) -> list[dict[str, Any]]:
    """Codes of what needs attention, most urgent first: ``{"code", "person", "value"}``."""
    now = now or dt.datetime.now()
    out: list[dict[str, Any]] = []
    mem = machine.get("memory") or {}
    if mem.get("total_kb") and mem.get("available_kb") is not None \
            and mem["available_kb"] / mem["total_kb"] < MEMORY_LOW:
        out.append({"code": "memory_low", "person": None, "value": round(100 * mem["available_kb"] / mem["total_kb"])})
    room = machine.get("disk") or {}
    if room.get("total") and room["free"] / room["total"] < DISK_LOW:
        out.append({"code": "disk_low", "person": None, "value": round(100 * room["free"] / room["total"])})
    if (version or {}).get("stale"):
        out.append({"code": "code_stale", "person": None, "value": None})
    busy = [p["id"] for p in folks if p.get("running")]
    if len(busy) > 1:
        out.append({"code": "parallel_runs", "person": None, "value": len(busy)})
    for p in folks:
        if p.get("error"):
            out.append({"code": "unreadable", "person": p["id"], "value": p["error"]})
            continue
        if not p.get("built_at"):
            out.append({"code": "no_build", "person": p["id"], "value": None})
        if p.get("pull_code") == 2:
            out.append({"code": "token_expired", "person": p["id"], "value": None})
        elif p.get("pull_code") not in (0, None) and not p.get("running"):
            out.append({"code": "pull_failed", "person": p["id"], "value": p.get("pull_code")})
        elif p.get("pull_started") and p.get("pull_code") is None and not p.get("running"):
            out.append({"code": "pull_died", "person": p["id"], "value": None})
        if p.get("source") == "garmin" and p.get("garmin") is False:
            out.append({"code": "not_connected", "person": p["id"], "value": None})
        elif p.get("source") == "garmin" and p.get("garmin") and not p.get("running"):
            # A failed or dead pull already has its own warning; the record keeps only the last attempt.
            if not p.get("pull_started"):
                out.append({"code": "pull_stale", "person": p["id"], "value": None})
            elif p.get("pull_code") == 0:
                finished = _when(p.get("pull_finished"))
                if finished is None or (now - finished).total_seconds() > STALE_PULL_H * 3600:
                    hours = round((now - finished).total_seconds() / 3600) if finished else None
                    out.append({"code": "pull_stale", "person": p["id"], "value": hours})
        if p.get("pending") and not p.get("running"):
            out.append({"code": "rebuild_waiting", "person": p["id"], "value": None})
    order = ["memory_low", "disk_low", "unreadable", "token_expired", "pull_failed", "pull_died", "code_stale",
             "parallel_runs", "no_build", "pull_stale", "rebuild_waiting", "not_connected"]
    return sorted(out, key=lambda w: order.index(w["code"]))


def logs(user: tenant.User, lines: int = LOG_LINES) -> str:
    return tail(user.fetch_log, lines)


def server_log(lines: int = LOG_LINES) -> str:
    return tail(ROOT / "data" / "streamlit.log", lines)
