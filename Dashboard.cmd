@echo off
setlocal
title Garmin Dashboard

rem Shortcut entry point: make sure the local site is up and open it.
rem Data is pulled from the sidebar button or by the server on its own once the
rem last pull is GARMIN_AUTO_FETCH_H hours old (sync.py). Arguments run
rem etl\run.py in this window first, e.g. Dashboard.cmd --backfill

set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
set "PYW=%HERE%.venv\Scripts\pythonw.exe"
set "PORT=8501"
set "URL=http://localhost:%PORT%"
rem The server stops itself this many minutes after the last tab is closed
rem (lifecycle.py); the next double-click starts it again.
if not defined GARMIN_IDLE_EXIT_MIN set "GARMIN_IDLE_EXIT_MIN=5"
if not defined GARMIN_AUTO_FETCH_H set "GARMIN_AUTO_FETCH_H=6"

if not exist "%PY%" goto :no_venv

if "%~1"=="" goto :serve
echo == Aktualizacja danych z Garmin Connect ==
"%PY%" "%HERE%etl\run.py" %*
if errorlevel 2 goto :token_expired

:serve

rem A server left running across a code change keeps old modules loaded;
rem stop it so the check below starts a fresh one.
"%PY%" "%HERE%serve.py" --stop-if-stale
ping -n 2 127.0.0.1 >nul

rem Port check via PowerShell: netstat output columns differ between locales.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 goto :start_server
echo == Serwer juz dziala na %URL% ==
goto :open_browser

:start_server
echo == Start serwera na %URL% ==
start "Garmin Dashboard" /min "%PYW%" "%HERE%serve.py" --server.port %PORT% --server.headless true --browser.gatherUsageStats false
rem Give the server a moment before the browser asks for the page.
ping -n 5 127.0.0.1 >nul

:open_browser
start "" "%URL%"
goto :eof

:no_venv
echo Nie znaleziono %PY%
echo Utworz venv w tym katalogu: python -m venv .venv
echo a potem: .venv\Scripts\pip install -r requirements.txt
pause
goto :eof

:token_expired
echo.
echo Token Garmin wygasl - zaloguj sie raz haslem:
echo    "%PY%" "%HERE%etl\login.py"
pause
goto :eof
