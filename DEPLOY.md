# Wdrozenie na serwerze Linux

Zalozenia: Ubuntu/Debian z systemd, Python 3.12+, dostep do roota.
Sciezki w przykladach: aplikacja w `/opt/garmin-dashboard`, uzytkownik `garmin`.

Podzial jest taki, ze **kod idzie przez git, a dane przez scp**. Dane sa w
`.gitignore` celowo: to historia zdrowia i slady GPS, a do tego 86 MB w ~9000
plikach, czego nie chcesz w repozytorium.

## 1. Uzytkownik i katalog

```bash
sudo adduser --system --group --home /home/garmin --shell /bin/bash garmin
sudo mkdir -p /opt/garmin-dashboard
sudo chown garmin:garmin /opt/garmin-dashboard
```

## 2. Kod

```bash
sudo -u garmin git clone <adres-twojego-repo> /opt/garmin-dashboard
```

Przy kazdej kolejnej zmianie na Windowsie: `git push` lokalnie, a na serwerze

```bash
sudo -u garmin git -C /opt/garmin-dashboard pull
sudo systemctl restart garmin-dashboard
```

## 3. Virtualenv

Virtualenv nie jest w repo - jest zalezny od platformy i trzeba go zrobic
na serwerze od zera.

```bash
cd /opt/garmin-dashboard
sudo -u garmin python3 -m venv .venv
sudo -u garmin .venv/bin/pip install -r requirements.txt
```

Instalacja wazy ~700 MB-1 GB (pyarrow, duckdb, scipy, statsmodels).
Szczyt zuzycia RAM to nie dashboard, a `etl/load.py` przeliczajacy wszystkie
tabele - przy 1 GB RAM bez swapu moze polec na OOM.

## 4. Dane przez scp

Na Windowsie spakuj katalog `data/` (albo uzyj gotowego archiwum, ktore
lezy obok repo po pierwszym przygotowaniu):

```powershell
tar czf garmin-data.tar.gz data
scp garmin-data.tar.gz user@serwer:/tmp/
```

Na serwerze:

```bash
sudo -u garmin tar xzf /tmp/garmin-data.tar.gz -C /opt/garmin-dashboard
rm /tmp/garmin-data.tar.gz
sudo -u garmin cat /opt/garmin-dashboard/data/state.json   # kontrola: ile dni
```

Dzieki temu nic nie jest ciagane ponownie z API. ETL dociaga tylko brakujace
dni od `last_day` ze `state.json`, plus ostatnie `RECHECK_DAYS` na wypadek
poznych synchronizacji zegarka.

## 5. Logowanie do Garmina

Tokeny trzymane sa poza repo, w katalogu wskazanym przez `GARMIN_TOKENSTORE`
(domyslnie `~/.garminconnect`). Dwie drogi:

**A. Zaloguj sie na serwerze** - `etl/login.py` jest interaktywny (pyta o
haslo przez `getpass`, czasem o kod MFA), wiec musi isc przez zwykla sesje
SSH z terminalem, nigdy z crona:

```bash
sudo -u garmin -H GARMIN_TOKENSTORE=/home/garmin/.garminconnect \
    /opt/garmin-dashboard/.venv/bin/python /opt/garmin-dashboard/etl/login.py
```

**B. Albo przenies tokeny z Windowsa** (`%USERPROFILE%\.garminconnect`):

```bash
scp -r ~/.garminconnect user@serwer:/tmp/gt
sudo mv /tmp/gt /home/garmin/.garminconnect
sudo chown -R garmin:garmin /home/garmin/.garminconnect
sudo chmod 700 /home/garmin/.garminconnect
sudo chmod 600 /home/garmin/.garminconnect/*
```

Plik z tokenami ma wartosc hasla - trzymaj go z prawami 600.

## 6. Usluga i timer

```bash
sudo cp deploy/garmin-dashboard.service /etc/systemd/system/
sudo cp deploy/garmin-etl.service /etc/systemd/system/
sudo cp deploy/garmin-etl.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-dashboard.service
sudo systemctl enable --now garmin-etl.timer
```

Kontrola:

```bash
systemctl status garmin-dashboard
systemctl list-timers garmin-etl.timer
journalctl -u garmin-etl -n 50          # log ostatniego ETL
sudo systemctl start garmin-etl.service # recznie, od razu
```

`etl/run.py` konczy sie **kodem 2**, gdy token wygasl. Na serwerze nikt tego
nie zobaczy, wiec warto podlaczyc powiadomienie (`OnFailure=` w unicie) albo
raz w tygodniu zerknac w `journalctl -u garmin-etl`.

## 6b. Wariant z pm2 (zamiast systemd)

Jesli na serwerze masz juz inne procesy pod pm2 i wolisz miec wszystko w
jednym `pm2 list`, uzyj `deploy/ecosystem.config.js`:

```bash
cd /opt/garmin-dashboard
pm2 start deploy/ecosystem.config.js
pm2 save
pm2 startup        # wypisze komende z sudo - wykonaj ja, inaczej pm2 nie
                   # wstanie po reboocie serwera
pm2 logs garmin-dashboard
```

Plik ustawia `autorestart` bez limitu restartow i `cron_restart` na ETL o
7:30, wiec timer systemd nie jest wtedy potrzebny. Przy czystej instalacji
wybralbym jednak systemd - nie wymaga Node.js tylko po to, zeby pilnowac
procesu Pythona, i sam dba o kolejnosc startu po sieci.

## 7. Dostep

Dashboard slucha tylko na `127.0.0.1:8501` - Streamlit nie ma zadnej
autoryzacji, wiec nie wystawiaj go wprost na swiat.

**Domyslnie: tunel SSH.** Na swoim komputerze:

```bash
ssh -N -L 8501:127.0.0.1:8501 user@serwer
```

i wchodzisz na `http://localhost:8501`.

**Na domenie:** `deploy/nginx-garmin.conf` ma gotowa konfiguracje z basic auth
i przepuszczaniem WebSocketa (bez tego Streamlit wisi na "Connecting...").
Podmien `garmin.twojadomena.pl`, zaloz haslo przez `htpasswd` i puszcz
`certbot --nginx`.
