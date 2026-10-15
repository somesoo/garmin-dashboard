@echo off
setlocal
title Garmin Dashboard

rem Shortcut entry point: update data, then make sure the local site is up.
rem Put a shortcut to this file anywhere; double-clicking it does everything.

set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
set "PYW=%HERE%.venv\Scripts\pythonw.exe"
set "PORT=8501"
set "URL=http://localhost:%PORT%"

if not exist "%PY%" goto :no_venv

echo == Aktualizacja danych z Garmin Connect ==
"%PY%" "%HERE%etl\run.py" %*
if errorlevel 2 goto :token_expired

rem Port check via PowerShell: netstat output columns differ between locales.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 goto :start_server
echo == Serwer juz dziala na %URL% ==
goto :open_browser

:start_server
echo == Start serwera na %URL% ==
start "Garmin Dashboard" /min "%PYW%" -m streamlit run "%HERE%app.py" --server.port %PORT% --server.headless true --browser.gatherUsageStats false
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
