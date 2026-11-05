#!/usr/bin/env bash
# Instalacja dashboardu na VPS (Ubuntu 24.04) pod wlasna domena.
# Mozna puszczac wielokrotnie: przy kolejnym razie dociaga paczki, przepisuje
# unit i proxy, restartuje usluge. Dane (data/) i sekrety zostaja nietkniete.
#
#   git clone https://github.com/<ty>/garmin-dashboard.git /opt/garmin-dashboard
#   sudo /opt/garmin-dashboard/deploy/install.sh garmin.twojadomena.pl            # Caddy + HTTPS (domyslnie)
#   sudo /opt/garmin-dashboard/deploy/install.sh garmin.twojadomena.pl --nginx    # nginx + certbot
#   sudo .../install.sh eve302-30302.mikrus.cloud --http-port=30302 --user=root   # HTTPS robi platforma (mikr.us)
#
# Opcje: --email=adres (certbot bez pytan), --user=nazwa (domyslnie garmin; root
# dla katalogu w /root), --http-port=N (zwykly HTTP na porcie N, IPv4 i IPv6,
# bez certyfikatu - gdy HTTPS konczy sie na proxy dostawcy). Opis: docs/DEPLOY.md.
set -euo pipefail

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

DOMAIN=""
PROXY=caddy
EMAIL=""
RUN_AS=garmin
HTTP_PORT=""
for arg in "$@"; do
    case "$arg" in
        --nginx) PROXY=nginx ;;
        --caddy) PROXY=caddy ;;
        --email=*) EMAIL="${arg#--email=}" ;;
        --user=*) RUN_AS="${arg#--user=}" ;;
        --http-port=*) HTTP_PORT="${arg#--http-port=}"; PROXY=nginx ;;
        -h|--help) usage ;;
        -*) echo "Nieznana opcja: $arg"; usage ;;
        *) DOMAIN="$arg" ;;
    esac
done
[[ -n "$DOMAIN" ]] || usage
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || { echo "To nie wyglada na domene: $DOMAIN"; exit 1; }
[[ -z "$HTTP_PORT" || "$HTTP_PORT" =~ ^[0-9]{2,5}$ ]] || { echo "Zly port: $HTTP_PORT"; exit 1; }
[[ "$RUN_AS" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "Zla nazwa uzytkownika: $RUN_AS"; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Uruchom przez sudo."; exit 1; }
command -v apt-get >/dev/null || { echo "Skrypt jest dla Ubuntu/Debiana (apt)."; exit 1; }

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $RUN_AS == root ]]; then HOME_DIR=/root; else HOME_DIR=/home/$RUN_AS; fi
step() { printf '\n== %s ==\n' "$*"; }
as_user() { runuser -u "$RUN_AS" -- env HOME="$HOME_DIR" "$@"; }

step "Paczki systemowe"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip curl ca-certificates >/dev/null
if [[ $PROXY == caddy ]]; then
    apt-get install -y -qq caddy >/dev/null
elif [[ -n $HTTP_PORT ]]; then
    if ! command -v nginx >/dev/null; then
        # Pakiet startuje nginx z domyslna strona na porcie 80; gdy 80 jest zajety
        # (inna aplikacja), nieudany start przerywa apt. Start po konfiguracji nizej.
        printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
        chmod +x /usr/sbin/policy-rc.d
        apt-get install -y -qq nginx >/dev/null || { rm -f /usr/sbin/policy-rc.d; exit 1; }
        rm -f /usr/sbin/policy-rc.d
    fi
else
    apt-get install -y -qq nginx certbot python3-certbot-nginx >/dev/null
fi
python3 - <<'PY' || { echo "Potrzebny Python 3.12+ (Ubuntu 24.04 ma go w systemie)."; exit 1; }
import sys; sys.exit(sys.version_info < (3, 12))
PY

step "Uzytkownik $RUN_AS i katalog $APP"
id "$RUN_AS" >/dev/null 2>&1 || adduser --system --group --home "$HOME_DIR" --shell /bin/bash "$RUN_AS"
mkdir -p "$APP/data" "$HOME_DIR/.garminconnect"
chown -R "$RUN_AS:$RUN_AS" "$APP" "$HOME_DIR/.garminconnect"
[[ $RUN_AS == root ]] || chown "$RUN_AS:$RUN_AS" "$HOME_DIR"
# Dane zdrowotne i tokeny: tylko wlasciciel.
chmod 700 "$APP/data" "$HOME_DIR/.garminconnect"
git config --system --add safe.directory "$APP" 2>/dev/null || true

step "Swap (ETL przy otwartym dashboardzie potrzebuje ~0,8 GB)"
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ $(swapon --show --noheadings | wc -l) -eq 0 && $mem_mb -lt 3000 ]]; then
    if fallocate -l 2G /swapfile 2>/dev/null && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile 2>/dev/null; then
        grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
        echo "Dodano 2 GB swapu."
    else
        rm -f /swapfile
        echo "Swapu nie da sie tu wlaczyc (kontener?) - przy ${mem_mb} MB RAM pobieranie w trakcie uzywania moze dostac OOM."
    fi
else
    echo "RAM ${mem_mb} MB, swap: $(swapon --show --noheadings | wc -l) - bez zmian."
fi

step "Virtualenv i zaleznosci (~1 GB, kilka minut za pierwszym razem)"
as_user python3 -m venv "$APP/.venv"
as_user "$APP/.venv/bin/pip" install -q --upgrade pip
as_user "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

step "Logowanie Google (data/secrets.toml)"
secrets="$APP/data/secrets.toml"
if [[ ! -f "$secrets" ]]; then
    (cd "$APP" && as_user .venv/bin/python -m core.auth setup "https://$DOMAIN")
elif ! grep -q "https://$DOMAIN/oauth2callback" "$secrets"; then
    echo "UWAGA: $secrets ma inny redirect_uri niz https://$DOMAIN/oauth2callback."
    echo "       Popraw go recznie albo: .venv/bin/python -m core.auth setup https://$DOMAIN --force"
    echo "       (--force losuje nowy cookie_secret i kasuje wklejone client_id/secret)."
else
    echo "Jest, redirect_uri zgadza sie z domena."
fi

step "Usluga systemd"
sed -e "s#/opt/garmin-dashboard#$APP#g" -e "s#/home/garmin#$HOME_DIR#g" \
    -e "s#^User=garmin#User=$RUN_AS#" -e "s#^Group=garmin#Group=$RUN_AS#" \
    "$APP/deploy/garmin-dashboard.service" > /etc/systemd/system/garmin-dashboard.service
# Po dawnym wdrozeniu jednoosobowym: timer ETL zastapil timer w serve.py (sync.py).
if [[ -f /etc/systemd/system/garmin-etl.timer ]]; then
    systemctl disable --now garmin-etl.timer || true
    rm -f /etc/systemd/system/garmin-etl.timer /etc/systemd/system/garmin-etl.service
fi
systemctl daemon-reload
systemctl enable garmin-dashboard.service >/dev/null
systemctl restart garmin-dashboard.service

if [[ $PROXY == caddy ]]; then
    step "Reverse proxy: Caddy na https://$DOMAIN"
    sed "s/DOMENA/$DOMAIN/g" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
    systemctl enable caddy >/dev/null
    systemctl reload caddy 2>/dev/null || systemctl restart caddy
elif [[ -n $HTTP_PORT ]]; then
    step "Reverse proxy: nginx na porcie $HTTP_PORT (HTTPS po stronie platformy)"
    sed -e "s/DOMENA/$DOMAIN/g" -e "s/listen 80;/listen $HTTP_PORT;/" -e "s/listen \[::\]:80;/listen [::]:$HTTP_PORT;/" \
        "$APP/deploy/nginx-garmin.conf" > /etc/nginx/sites-available/garmin
    ln -sf /etc/nginx/sites-available/garmin /etc/nginx/sites-enabled/garmin
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    systemctl enable nginx >/dev/null
    systemctl reload nginx 2>/dev/null || systemctl restart nginx
else
    step "Reverse proxy: nginx + certbot na https://$DOMAIN"
    sed "s/DOMENA/$DOMAIN/g" "$APP/deploy/nginx-garmin.conf" > /etc/nginx/sites-available/garmin
    ln -sf /etc/nginx/sites-available/garmin /etc/nginx/sites-enabled/garmin
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    systemctl reload nginx
    if [[ ! -d /etc/letsencrypt/live/$DOMAIN ]]; then
        if [[ -n $EMAIL ]]; then
            certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
        else
            certbot --nginx -d "$DOMAIN" --redirect
        fi
    fi
fi

if [[ -z $HTTP_PORT ]] && command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    step "Zapora (ufw): 22, 80, 443"
    ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
fi

step "Sprawdzenie"
for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:8502/api/health >/dev/null 2>&1 && break
    sleep 2
done
curl -fsS http://127.0.0.1:8501/_stcore/health >/dev/null && echo "dashboard: ok" || echo "dashboard: NIE ODPOWIADA (journalctl -u garmin-dashboard -n 50)"
curl -fsS http://127.0.0.1:8502/api/health >/dev/null && echo "api: ok" || echo "api: NIE ODPOWIADA (journalctl -u garmin-dashboard -n 50)"
curl -fsS -o /dev/null "https://$DOMAIN/api/health" && echo "https://$DOMAIN: ok" \
    || echo "https://$DOMAIN: jeszcze nie (DNS? certyfikat? proxy?)"

cat <<EOF

Gotowe. Dalej (docs/DEPLOY.md):
  1. Dane z Maca:   tar do $APP/data (sekcja 4), potem: systemctl restart garmin-dashboard
  2. Google:        Authorised redirect URI = https://$DOMAIN/oauth2callback,
                    client_id/client_secret do $APP/data/secrets.toml, restart uslugi (sekcja 5)
  3. Osoby:         cd $APP && .venv/bin/python -m core.tenant list
  4. Aktualizacja:  $APP/deploy/update.sh
EOF
