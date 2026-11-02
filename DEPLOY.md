# Wdrożenie na VPS pod własną domeną

Cel: `https://garmin.twojadomena.pl` (kup domenę gdziekolwiek — tu: Vercel),
logowanie przez Google, każda osoba widzi tylko swoje dane, telefony wysyłają
dane i otwierają PWA pod `/api`. Wszystko na jednym małym serwerze w UE.

```
przeglądarka / iPhone ──HTTPS──▶ Caddy albo nginx (80/443, certyfikat Let's Encrypt)
                                   ├─ /        ▶ 127.0.0.1:8501  Streamlit (dashboard, WebSocket)
                                   └─ /api/... ▶ 127.0.0.1:8502  API (pushe z iPhone'a, PWA)
                                 serve.py (systemd): oba porty + pobieranie z Garmina co 6 h
```

**Dlaczego nie na samym Vercelu:** Vercel uruchamia krótkie funkcje bezserwerowe.
Streamlit to jeden stale żyjący proces z WebSocketem do każdej karty, obok niego
API, pobieranie w tle i ~100 MB parquet/JSON na dysku. Vercel zostaje tylko
**DNS-em** domeny — strona główna domeny może dalej stać na Vercelu.

**Kod idzie przez git, dane przez scp.** `data/` jest w `.gitignore` celowo:
to historia zdrowia i ślady GPS kilku osób.

Szybka ścieżka (szczegóły w sekcjach niżej):

```bash
# 0. Vercel: rekord A  garmin -> <IP serwera>
ssh root@<IP>
git clone https://github.com/somesoo/garmin-dashboard.git /opt/garmin-dashboard
/opt/garmin-dashboard/deploy/install.sh garmin.twojadomena.pl
# dane z Maca (sekcja 4), client_id/secret Google (sekcja 5), restart
```

## 1. Serwer

- **Rozmiar**: 2 GB RAM, 1–2 vCPU, 20 GB dysku wystarczą (pomiar w sekcji 9).
  Np. Hetzner Cloud CX22 (2 vCPU, 4 GB, ~4–5 €/mies.) albo podobny VPS u innego dostawcy.
- **Lokalizacja w UE** (Niemcy, Finlandia, Polska): to dane zdrowotne (art. 9 RODO).
- **System**: Ubuntu 24.04 LTS (Python 3.12 w systemie). Debian 12 ma 3.11 — za stary.
- **Dostęp**: klucz SSH przy tworzeniu serwera. Jeśli dostawca ma zaporę w panelu,
  otwórz 22, 80 i 443 (nic więcej — 8501/8502 słuchają tylko na 127.0.0.1).

## 2. DNS na Vercelu

Domena kupiona na Vercelu ma DNS Vercela, więc rekord dodajesz tam:

*Vercel → Domains → twojadomena.pl → DNS Records → Add*:

| Name | Type | Value | TTL |
|---|---|---|---|
| `garmin` | `A` | IPv4 serwera | 60 |
| `garmin` | `AAAA` | IPv6 serwera (opcjonalnie) | 60 |

Albo z terminala: `vercel dns add twojadomena.pl garmin A <IPv4>`.

Sprawdzenie (przed instalacją — bez tego certyfikat nie powstanie):

```bash
dig +short garmin.twojadomena.pl     # ma zwrócić IP serwera
```

Rekordy subdomeny nie ruszają strony głównej domeny ani innych projektów na Vercelu.
Domena trzymana gdzie indziej (OVH, Cloudflare…) — ten sam rekord A u tamtego dostawcy;
przy Cloudflare z pomarańczową chmurką włącz *WebSockets* (domyślnie są włączone).

## 3. Instalacja: `deploy/install.sh`

```bash
ssh root@<IP>
git clone https://github.com/somesoo/garmin-dashboard.git /opt/garmin-dashboard
/opt/garmin-dashboard/deploy/install.sh garmin.twojadomena.pl          # Caddy
# albo: ... install.sh garmin.twojadomena.pl --nginx --email=ty@domena  # nginx + certbot
```

Repo jest prywatne? `git clone` zapyta o login — użyj tokenu GitHuba (*Settings →
Developer settings → Fine-grained token*, tylko odczyt tego repo) albo klucza
*Deploy key* dodanego w ustawieniach repo.

Skrypt (można go puszczać wielokrotnie, danych nie rusza):

1. instaluje Pythona, gita i proxy (Caddy domyślnie; `--nginx` = nginx + certbot),
2. zakłada użytkownika systemowego `garmin`, oddaje mu katalog, `data/` z prawami 700,
3. dodaje 2 GB swapu, jeśli serwer ma < 3 GB RAM i nie ma swapu,
4. robi `.venv` i instaluje `requirements.txt` (~1 GB, kilka minut),
5. zapisuje `data/secrets.toml` dla `https://<domena>` (`python -m auth setup`),
   jeśli go nie ma — z losowym `cookie_secret`,
6. instaluje i startuje `garmin-dashboard.service` (sprząta stary `garmin-etl.timer`),
7. stawia proxy na domenę z certyfikatem Let's Encrypt,
8. sprawdza `127.0.0.1:8501`, `127.0.0.1:8502` i `https://<domena>/api/health`.

Pliki w `deploy/`:

| plik | co |
|---|---|
| `install.sh` | instalacja / ponowna konfiguracja (wyżej) |
| `update.sh` | nowa wersja kodu: `git pull`, zależności, restart |
| `garmin-dashboard.service` | systemd: `serve.py` = Streamlit + API + pobieranie co 6 h |
| `Caddyfile` | proxy z automatycznym HTTPS (domyślne) |
| `nginx-garmin.conf` | to samo dla nginx + certbot |
| `ecosystem.config.js` | wariant pm2 zamiast systemd |

## 4. Dane z Maca

Zamknij dashboard lokalnie (żeby nic nie pisało do `data/` w trakcie pakowania), potem na Macu:

```bash
cd ~/repos/garmin-dashboard
# COPYFILE_DISABLE: bez śmieci "._plik" z atrybutami macOS po rozpakowaniu na Linuksie.
# secrets.toml zostaje: ten z Maca ma adres powrotu localhost, serwer ma własny.
COPYFILE_DISABLE=1 tar czf ~/garmin-data.tar.gz --no-xattrs \
    --exclude 'data/secrets.toml' --exclude 'data/server.json' \
    --exclude '*.lock' --exclude '*/fetch.log' data
scp ~/garmin-data.tar.gz root@<IP>:/tmp/
# tokeny Garmina osoby ze starym układem (root: "." w data/users.json):
scp -r ~/.garminconnect root@<IP>:/tmp/garminconnect
```

Na serwerze:

```bash
cd /opt/garmin-dashboard
tar xzf /tmp/garmin-data.tar.gz -C /opt/garmin-dashboard
cp -r /tmp/garminconnect/. /home/garmin/.garminconnect/
chown -R garmin:garmin data /home/garmin/.garminconnect
chmod 700 data /home/garmin/.garminconnect && chmod 600 /home/garmin/.garminconnect/*
rm -rf /tmp/garmin-data.tar.gz /tmp/garminconnect
sudo -u garmin -H .venv/bin/python -m tenant list      # kontrola: osoby, źródła, katalogi
systemctl restart garmin-dashboard
```

Przeniesione tokeny = Garmin nie widzi nowego logowania z adresu serwerowni (takie
potrafi skończyć się kodem MFA albo chwilową blokadą). Gdyby jednak trzeba było się
zalogować: strona **Konto → Garmin Connect** w przeglądarce (hasło użyte raz, kod
weryfikacyjny obsłużony) albo przez SSH:

```bash
cd /opt/garmin-dashboard && sudo -u garmin -H GARMIN_USER=<id> .venv/bin/python etl/login.py
```

Od tej chwili **źródłem prawdy jest serwer**: plany i zawody (`coach/`), pushe
z iPhone'a i nowe dni trafiają tam. Lokalna kopia na Macu dalej działa, ale się
rozjedzie — zmian w planie nie rób w dwóch miejscach. Kopia serwera na Maca: sekcja 8.

## 5. Logowanie Google

`install.sh` zapisał `data/secrets.toml` z `redirect_uri = "https://<domena>/oauth2callback"`.
W [Google Cloud Console](https://console.cloud.google.com/apis/credentials):

1. *Create credentials → OAuth client ID → Web application*.
2. *Authorised redirect URIs*: dokładnie `https://garmin.twojadomena.pl/oauth2callback`.
3. *OAuth consent screen*: tryb *Testing*, każda osoba jako *test user*
   (do 100 osób bez weryfikacji aplikacji przez Google).
4. Wklej `client_id` i `client_secret`:

```bash
sudo -u garmin -H nano /opt/garmin-dashboard/data/secrets.toml
systemctl restart garmin-dashboard
```

Każda osoba musi mieć swój e-mail Google w `identities` (`python -m tenant add <id>
--identity <gmail>`; osoby z Maca już go mają). Kto i jak się loguje: `DOSTEP.md`.
Z Google nie ma „lokalnej” osoby bez logowania — także przy serwerze wchodzi się
przez „Zaloguj przez Google”.

Zmiana domeny: `.venv/bin/python -m auth setup https://nowa.domena --force`
(nowy `cookie_secret` — wszyscy logują się od nowa; client_id/secret wklej ponownie),
nowy redirect URI w Google i `install.sh nowa.domena`.

## 6. Proxy i adresy

| adres | co |
|---|---|
| `https://<domena>/` | dashboard |
| `https://<domena>/oauth2callback` | powrót z Google (obsługuje Streamlit) |
| `https://<domena>/api/app/` | aplikacja na telefon (PWA) |
| `https://<domena>/api/ingest/apple` | pushe z iPhone'a (Health Auto Export / Skrót) |
| `https://<domena>/api/health` | `{"ok": true}` — do monitoringu |

Bez basic auth: blokowałby pushe z iPhone'a i PWA, które mają własne klucze
(strona Konto). Streamlit dostaje od proxy `X-Forwarded-*`, więc nikt z sieci nie
jest brany za „osobę przy serwerze”.

Caddy sam odnawia certyfikat; przy nginx robi to timer `certbot.timer`
(`systemctl list-timers certbot*`).

## 7. Aktualizacja kodu

Na Macu `git push`, na serwerze:

```bash
/opt/garmin-dashboard/deploy/update.sh       # git pull, pip install, restart
```

Restart jest konieczny: Streamlit nie przeładowuje już zaimportowanych modułów.
Zmiana w `deploy/` (unit, proxy) — zamiast tego `deploy/install.sh <domena>`.

## 8. Na co dzień

```bash
systemctl status garmin-dashboard               # działa? Memory (peak), CPU
journalctl -u garmin-dashboard -n 100           # log serwera i API
sudo -u garmin tail -n 50 /opt/garmin-dashboard/data/users/<id>/fetch.log   # ostatnie pobranie
# (osoba ze starym układem: data/fetch.log)
```

- **Pobieranie z Garmina**: co 6 h dla każdej osoby z `source: garmin`
  (`GARMIN_AUTO_FETCH_H` w unicie), plus przycisk „Pobierz z Garmina” w górnej linii.
  Wygasły token = kod 2 w `fetch.json` osoby i komunikat w aplikacji; naprawa:
  Konto → Garmin Connect.
- **Kopia zapasowa**: `coach/` (plany, zawody, segmenty), rejestr osób, klucze
  telefonów i pushe z iPhone'a **nie dają się odtworzyć** z Garmina. Z Maca, np. raz w tygodniu:

  ```bash
  rsync -a --delete root@<IP>:/opt/garmin-dashboard/data/ ~/garmin-backup/data/
  ```

  (albo kopie zapasowe całego serwera w panelu dostawcy — u Hetznera +20% ceny).
- **Aktualizacje systemu**: `apt install unattended-upgrades` (Ubuntu ma je zwykle włączone).

## 8b. Wariant z pm2 (zamiast systemd)

Jeśli na serwerze masz już inne procesy pod pm2:

```bash
cd /opt/garmin-dashboard
sudo -u garmin pm2 start deploy/ecosystem.config.js
sudo -u garmin pm2 save
pm2 startup        # wypisze komendę z sudo - wykonaj ją, inaczej pm2 nie wstanie po reboocie
```

Wtedy wyłącz `garmin-dashboard.service` (`systemctl disable --now garmin-dashboard`).
Proxy i reszta bez zmian.

## 8c. Wariant mikr.us (próba na eve302, 2026-11-02)

Kontener LXC: porty 80/443 na IPv4 są niedostępne (na eve302 zajmuje je też inna
aplikacja w Dockerze), HTTPS kończy proxy mikr.us, swapu nie da się włączyć.
Dashboard słucha więc zwykłym HTTP na przydzielonym porcie, a adres daje platforma:

```bash
git clone <bundle albo repo> /root/garmin-dashboard
/root/garmin-dashboard/deploy/install.sh eve302-30302.mikrus.cloud --user=root --http-port=30302
```

- adres: `https://eve302-30302.mikrus.cloud` (WebSocket przechodzi; redirect URI Google:
  `https://eve302-30302.mikrus.cloud/oauth2callback`),
- SSH i scp: `-p 10302 root@eve302.mikrus.xyz`; tokeny Garmina w `/root/.garminconnect`,
- 1,5 GB RAM bez swapu: pobieranie z przebudową tabel przeszło (≈ 75 s), ale przy
  kilku osobach z Garminem naraz może zabraknąć pamięci,
- własna domena (z Vercela) na mikr.us wymaga płatnego Cytrusa albo Cloudflare
  przed IPv6 — na próbę zostaje adres `mikrus.cloud`.

## 9. Rozmiar serwera i monitoring zasobów

### Ile to zużywa (pomiar 2026-10-26, `tools/resources.py`)

| co | RAM (szczyt) | czas / CPU |
|---|---|---|
| serwer Streamlit bezczynny | ~150 MB | ~0 |
| serwer po otwarciu wszystkich 19 stron | ~330 MB | strona 0,05-0,3 s, ponowny render 0,01-0,15 s |
| `etl/load.py` (przebudowa tabel) | ~200 MB | 2 s |
| `analytics.py` (tabele pochodne) | ~250 MB | 6 s CPU |
| dysk: `.venv` | | ~0,6-1 GB (stałe) |
| dysk: `data/` | | ~75-105 MB na osobę z kilkuletnią historią, rośnie ~20-25 MB/rok |

Wnioski:

- **CPU praktycznie nie gra roli** — render strony to ułamki sekundy, pobieranie
  kilka sekund co 6 h. 1 vCPU wystarcza, 2 to zapas na instalację paczek.
- **RAM decyduje.** Najgorszy moment to pobieranie z przebudową tabel w trakcie,
  gdy ktoś ma otwarty dashboard: ~330 MB (serwer) + ~250 MB (analytics) + system
  (~150-250 MB na Ubuntu) = **~0,7-0,8 GB**. Pobierania kilku osób idą osobnymi
  procesami — przy kilku osobach naraz to kolejne ~250 MB każde.
- **Rekomendacja: 2 GB RAM, 1-2 vCPU, 20 GB dysku**; przy 4+ osobach z Garminem 4 GB.
- **Minimum: 1 GB RAM + 2 GB swapu** (`install.sh` dodaje swap sam). Na kontenerach
  LXC swapu zwykle nie da się włączyć — tam bierz 2 GB.
- Liczba otwartych kart nie zmienia rachunku: Streamlit trzyma jeden proces,
  każda karta to kilkanaście MB.

### Pomiar na docelowej maszynie

```bash
cd /opt/garmin-dashboard
sudo -u garmin -H GARMIN_USER=<id> .venv/bin/python tools/resources.py            # z przebudową tabel
sudo -u garmin -H GARMIN_USER=<id> .venv/bin/python tools/resources.py --skip-etl # bez przebudowy
```

### Monitoring na bieżąco (bez instalowania niczego)

Usługa ma `MemoryAccounting`/`CPUAccounting`, więc:

```bash
systemctl status garmin-dashboard       # Memory: bieżąca + (peak: ...), CPU: suma
systemd-cgtop                           # na żywo: CPU, RAM, I/O per usługa
free -h && df -h /opt                   # RAM/swap i dysk całej maszyny
```

Pobieranie (`etl/run.py`) startuje jako proces odłączony od serwera, ale w tej samej
grupie usługi — jego pamięć też widać w `systemctl status garmin-dashboard`.
Jeśli `peak` po kilku dniach zbliża się do limitu maszyny, postaw twardą granicę
w unicie (np. `MemoryMax=1500M`) — systemd zrestartuje usługę zamiast pozwolić
OOM-killerowi ubić cokolwiek innego. Wykresy CPU/RAM/dysku daje zwykle za darmo
panel dostawcy VPS.
