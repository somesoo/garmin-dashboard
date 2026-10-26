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

## 8. Rozmiar serwera i monitoring zasobow

### Ile to zuzywa (pomiar 2026-10-26, `tools/resources.py`)

| co | RAM (szczyt) | czas / CPU |
|---|---|---|
| serwer Streamlit bezczynny | ~150 MB | ~0 |
| serwer po otwarciu wszystkich 19 stron | ~330 MB | strona 0,05-0,3 s, ponowny render 0,01-0,15 s |
| `etl/load.py` (przebudowa tabel) | ~200 MB | 2 s |
| `analytics.py` (tabele pochodne) | ~250 MB | 6 s CPU |
| dysk: `.venv` | | ~0,6-1 GB (stale) |
| dysk: `data/` | | ~75 MB, rosnie ~20-25 MB/rok |

Wnioski:

- **CPU praktycznie nie gra roli** - render strony to ulamki sekundy, ETL raz
  dziennie kilka sekund. 1 vCPU wystarcza, 2 to zapas na instalacje paczek.
- **RAM decyduje.** Najgorszy moment to timer ETL o 7:30 w trakcie, gdy ktos
  ma otwarty dashboard: ~330 MB (serwer) + ~250 MB (analytics) + system
  (~150-250 MB na Ubuntu) = **~0,7-0,8 GB**. Do tego `pip install` przy
  instalacji potrafi chwilowo wziac kilkaset MB.
- **Rekomendacja: 2 GB RAM, 1-2 vCPU, 20 GB dysku.** To najmniejszy rozmiar
  z realnym zapasem.
- **Minimum: 1 GB RAM + 1-2 GB swapu.** Dziala, ale bez swapu ETL w trakcie
  uzywania dashboardu moze dostac OOM. Na kontenerach LXC (np. mikr.us) swapu
  zwykle nie da sie wlaczyc - tam bierz 2 GB.
- Liczba uzytkownikow nie zmienia rachunku: Streamlit trzyma jeden proces,
  sesje dziela cache tabel, kazda dodatkowa otwarta karta to kilkanascie MB.

### Pomiar na docelowej maszynie

```bash
cd /opt/garmin-dashboard
sudo -u garmin .venv/bin/python tools/resources.py            # z przebudowa tabel
sudo -u garmin .venv/bin/python tools/resources.py --skip-etl # bez przebudowy
```

Drukuje dysk, szczyt RAM i czas ETL, czas renderu kazdej strony i szczyt
pamieci procesu, ktory je wszystkie wyrenderowal. Uruchom raz po wdrozeniu -
liczby z Linuksa beda nieco inne niz z macOS.

### Monitoring na biezaco (bez instalowania niczego)

Obie uslugi maja `MemoryAccounting`/`CPUAccounting`, wiec:

```bash
systemctl status garmin-dashboard       # Memory: biezaca + (peak: ...), CPU: suma
systemctl status garmin-etl             # to samo dla ostatniego przebiegu ETL
systemd-cgtop                           # na zywo: CPU, RAM, I/O per usluga
journalctl -u garmin-etl --since today  # czy ETL dzis przeszedl
free -h && df -h /opt                   # RAM/swap i dysk calej maszyny
```

Jesli `peak` serwera po kilku dniach zbliza sie do limitu maszyny, mozna mu
postawic twarda granice w `deploy/garmin-dashboard.service` (np.
`MemoryMax=700M`) - systemd zrestartuje go zamiast pozwolic OOM-killerowi
ubic cokolwiek innego. Wykresy CPU/RAM/dysku z ostatnich dni daje zwykle za
darmo panel dostawcy VPS; ciezkie stosy (Prometheus, Grafana, netdata) zjadlyby
wiecej RAM niz sam dashboard.
