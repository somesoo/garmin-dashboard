"""How much machine the dashboard needs: disk, ETL peak, page renders, server.

    .venv/bin/python tools/resources.py            everything below
    .venv/bin/python tools/resources.py --skip-etl  pages + server only (no rebuild)

Stdlib + ``ps`` only (no psutil), so it runs unchanged on macOS and on the
Linux box in the cloud. Measurements:

* disk   -- data/ (grows with history) and .venv (fixed)
* etl    -- etl/load.py and analytics.py as child processes, memory sampled
            every 0.1 s: the RAM peak of the whole app, so the box is sized
            for this, not for the web server
* pages  -- every page rendered in a fresh process through Streamlit's
            AppTest (the same script run a browser session triggers): time
            per page and the process peak, i.e. a server after one visitor
            has opened everything
* server -- the running server (data/server.json), if any: RSS and CPU time
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
MB = 1024 * 1024

PAGES = {
    "Dziś": "today.render()", "Atlas": "atlas.render()", "Trasy": "routes.render()",
    "Aktywności": "activities.render()", "Bieganie": "run_overview.render()",
    "Prognoza": "run_forecast.render()", "Plan": "run_plan.render()", "Zawody": "run_races.render()",
    "Trening": "run_session.render()", "Obciążenie": "run_load.render()", "Regeneracja": "recovery.render()",
    "Sen": "sleep.render()", "Trendy": "trends.render()", "Forma": "form.render()",
    "Fizjologia": "physio.render()", "Statystyka": "stats.render()", "Insights": "notebook.insights()",
    "SQL": "notebook.sql()", "Słownik": "reference.render()",
}


def du(path: Path) -> float:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            pass
    return total / MB


def tree_rss(root_pid: int) -> float:
    """RSS of a process and all its descendants, MB."""
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True).stdout
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        pid, ppid, kb = map(int, parts)
        children.setdefault(ppid, []).append(pid)
        rss[pid] = kb
    total, stack = 0, [root_pid]
    while stack:
        pid = stack.pop()
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, []))
    return total / 1024


def run_sampled(args: list[str], label: str) -> dict:
    """Run a command, sample its memory, return peak / time / CPU."""
    import resource

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    proc = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    peak = 0.0
    while proc.poll() is None:
        peak = max(peak, tree_rss(proc.pid))
        time.sleep(0.1)
    output = proc.stdout.read() if proc.stdout else ""
    wall = time.perf_counter() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return {"step": label, "ok": proc.returncode == 0, "peak_mb": round(peak), "wall_s": round(wall, 1),
            "cpu_s": round(cpu, 1), "tail": output.strip().splitlines()[-1:] if output else []}


PAGE_PROBE = r'''
import json, resource, sys, time, pathlib, gc
sys.path.insert(0, ".")
def rss():
    out = __import__("subprocess").run(["ps", "-o", "rss=", "-p", str(__import__("os").getpid())],
                                       capture_output=True, text=True).stdout
    return int(out.strip() or 0) / 1024
from streamlit.testing.v1 import AppTest
import pandas, pyarrow, duckdb, plotly  # noqa: F401 - what every page imports
base = rss()
pages = json.loads(sys.argv[1])
times = {}
for name, call in pages.items():
    module = call.split(".")[0]
    script = f"import sys; sys.path.insert(0, '.')\nimport streamlit as st, shell\nst.markdown(shell.page_style('dark'), unsafe_allow_html=True)\nfrom views import {module}\n{call}\n"
    t0 = time.perf_counter()
    at = AppTest.from_string(script, default_timeout=300).run()
    first = time.perf_counter() - t0
    t0 = time.perf_counter()
    at.run()  # a rerun: what a click or a widget change costs, caches warm
    rerun = time.perf_counter() - t0
    times[name] = {"first_s": round(first, 2), "rerun_s": round(rerun, 2),
                   "errors": len(at.exception)}
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
peak_mb = peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
print(json.dumps({"after_imports_mb": round(base), "peak_mb": round(peak_mb), "now_mb": round(rss()),
                  "pages": times}))
'''


def pages() -> dict:
    proc = subprocess.run([PY, "-c", PAGE_PROBE, json.dumps(PAGES, ensure_ascii=False)], cwd=ROOT,
                          capture_output=True, text=True)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    if not lines:
        return {"error": proc.stderr.strip().splitlines()[-3:]}
    return json.loads(lines[-1])


def server() -> dict | None:
    record = ROOT / "data" / "server.json"
    try:
        pid = int(json.loads(record.read_text())["pid"])
    except (OSError, ValueError, KeyError):
        return None
    out = subprocess.run(["ps", "-o", "rss=,time=,etime=", "-p", str(pid)], capture_output=True, text=True).stdout.split()
    if len(out) < 3:
        return None
    return {"pid": pid, "rss_mb": round(int(out[0]) / 1024), "cpu_time": out[1], "uptime": out[2]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zużycie zasobów dashboardu")
    parser.add_argument("--skip-etl", action="store_true", help="bez przebudowy tabel")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report: dict = {"disk_mb": {"data": round(du(ROOT / "data")), "data/raw": round(du(ROOT / "data" / "raw")),
                                "data/tables": round(du(ROOT / "data" / "tables")), ".venv": round(du(ROOT / ".venv"))}}
    if not args.skip_etl:
        report["etl"] = [run_sampled([PY, "etl/load.py"], "etl/load.py"),
                         run_sampled([PY, "analytics.py"], "analytics.py")]
    report["pages"] = pages()
    report["server"] = server()

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print("== Dysk (MB) ==")
    for name, size in report["disk_mb"].items():
        print(f"  {name:12s} {size:6d}")
    for step in report.get("etl", []):
        print(f"== {step['step']}: szczyt RAM {step['peak_mb']} MB, {step['wall_s']} s, CPU {step['cpu_s']} s"
              + ("" if step["ok"] else "  (BŁĄD)"))
    page = report["pages"]
    if "error" in page:
        print("== Strony: błąd", page["error"])
    else:
        print(f"== Strony: po importach {page['after_imports_mb']} MB, szczyt {page['peak_mb']} MB")
        for name, item in page["pages"].items():
            flag = f"  błędy: {item['errors']}" if item["errors"] else ""
            print(f"  {name:12s} pierwsze wejście {item['first_s']:5.2f} s · ponownie {item['rerun_s']:5.2f} s{flag}")
    if report["server"]:
        s = report["server"]
        print(f"== Serwer (pid {s['pid']}): {s['rss_mb']} MB RSS, CPU {s['cpu_time']} przez {s['uptime']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
