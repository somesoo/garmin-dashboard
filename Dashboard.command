#!/bin/bash
# Shortcut entry point on macOS: update data, then make sure the local site is up.
# Double-click in Finder (opens Terminal) or run from a shell; extra arguments
# go to etl/run.py, e.g. ./Dashboard.command --backfill

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
PORT=8501
URL="http://localhost:$PORT"
LOG="$HERE/data/streamlit.log"

if [ ! -x "$PY" ]; then
    echo "Nie znaleziono $PY"
    echo "Utworz venv w tym katalogu: python3 -m venv .venv"
    echo "a potem: .venv/bin/pip install -r requirements.txt"
    read -r -p "Enter, aby zamknac..."
    exit 1
fi

echo "== Aktualizacja danych z Garmin Connect =="
"$PY" "$HERE/etl/run.py" "$@"
if [ $? -eq 2 ]; then
    echo
    echo "Token Garmin wygasl - zaloguj sie raz haslem:"
    echo "   \"$PY\" \"$HERE/etl/login.py\""
    read -r -p "Enter, aby zamknac..."
    exit 2
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "== Serwer juz dziala na $URL =="
else
    echo "== Start serwera na $URL (log: $LOG) =="
    mkdir -p "$HERE/data"
    # nohup + disown: the server outlives the Terminal window that started it.
    nohup "$PY" -m streamlit run "$HERE/app.py" \
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
