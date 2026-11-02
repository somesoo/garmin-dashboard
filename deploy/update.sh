#!/usr/bin/env bash
# Nowa wersja kodu na serwerze: git pull, zaleznosci, restart uslugi.
# Dane (data/) nie ida przez gita i tu sie nie zmieniaja.
#
#   sudo /opt/garmin-dashboard/deploy/update.sh
#
# Zmiana w deploy/ (unit, proxy)? Wtedy raczej: sudo deploy/install.sh <domena>.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Uruchom przez sudo."; exit 1; }
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Ten sam uzytkownik, ktory dostal katalog w install.sh (garmin albo root).
RUN_AS="$(stat -c %U "$APP")"
HOME_DIR="$(getent passwd "$RUN_AS" | cut -d: -f6)"
as_user() { runuser -u "$RUN_AS" -- env HOME="$HOME_DIR" "$@"; }

as_user git -C "$APP" pull --ff-only
as_user "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
# Streamlit nie przeladowuje zaimportowanych modulow - bez restartu stary kod zostaje w pamieci.
systemctl restart garmin-dashboard.service
for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8501/_stcore/health >/dev/null 2>&1; then
        echo "ok: $(as_user git -C "$APP" log --oneline -1)"
        exit 0
    fi
    sleep 2
done
echo "Dashboard nie wstal: journalctl -u garmin-dashboard -n 50"
exit 1
