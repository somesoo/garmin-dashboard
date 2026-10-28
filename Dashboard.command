#!/bin/bash
# Shortcut entry point on macOS: make sure the local site is up and open it.
# Data is pulled from the sidebar button or by the server on its own once the
# last pull is GARMIN_AUTO_FETCH_H hours old (sync.py). Arguments run etl/run.py
# in this window first, e.g. ./Dashboard.command --backfill

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
PORT=8501
URL="http://localhost:$PORT"
LOG="$HERE/data/streamlit.log"
# The server stops itself this many minutes after the last tab is closed
# (lifecycle.py); the next double-click starts it again.
export GARMIN_IDLE_EXIT_MIN="${GARMIN_IDLE_EXIT_MIN:-5}"
export GARMIN_AUTO_FETCH_H="${GARMIN_AUTO_FETCH_H:-6}"

if [ ! -x "$PY" ]; then
    echo "Nie znaleziono $PY"
    echo "Utworz venv w tym katalogu: python3 -m venv .venv"
    echo "a potem: .venv/bin/pip install -r requirements.txt"
    read -r -p "Enter, aby zamknac..."
    exit 1
fi

if [ $# -gt 0 ]; then
    echo "== Aktualizacja danych z Garmin Connect =="
    "$PY" "$HERE/etl/run.py" "$@"
    if [ $? -eq 2 ]; then
        echo
        echo "Token Garmin wygasl - zaloguj sie raz haslem:"
        echo "   \"$PY\" \"$HERE/etl/login.py\""
        read -r -p "Enter, aby zamknac..."
        exit 2
    fi
fi

# A server left running across a code change keeps old modules loaded;
# stop it so the check below starts a fresh one (serve.py --stop-if-stale).
"$PY" "$HERE/serve.py" --stop-if-stale

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "== Serwer juz dziala na $URL =="
else
    echo "== Start serwera na $URL (log: $LOG) =="
    mkdir -p "$HERE/data"
    # nohup + disown: the server outlives the Terminal window that started it.
    nohup "$PY" "$HERE/serve.py" \
        --server.port "$PORT" --server.address 127.0.0.1 \
        --server.headless true --browser.gatherUsageStats false \
        >"$LOG" 2>&1 &
    disown
    # Give the server a moment before the browser asks for the page.
    for _ in $(seq 1 20); do
        lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && break
        sleep 0.5
    done
fi

open "$URL"
