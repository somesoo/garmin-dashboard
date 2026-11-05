# Platforma: serwer, osoby, pobieranie

Jak działa serwer, wiele osób, logowanie i strona Admin. Wdrożenie: `DEPLOY.md`, dostęp: `DOSTEP.md`.

## Uruchamianie lokalne

`Dashboard.command` / `Dashboard.cmd`: `serve.py` w tle → przeglądarka. **Launcher
nie pobiera danych** (chyba że dostanie argumenty, np. `--backfill` — wtedy
`etl/run.py` w oknie przed startem). Pobieranie to `core/sync.py`: przycisk „Pobierz
z Garmina” w górnej linii (`shell.pull_inline`) i wątek startowany przez `serve.py`, który co
10 min sprawdza, czy ostatnia próba jest starsza niż `GARMIN_AUTO_FETCH_H` h
(launchery: 6; nieudana sieciowo — po 30 min; wygasły token — po pełnym odstępie).
Oba odpalają `etl/run.py` jako osobny, odłączony proces (log `data/fetch.log`),
więc przeżywa idle-exit serwera. `etl/run.py` bierze `data/fetch.lock` (O_EXCL, pid)
i zapisuje próbę w `data/fetch.json` (`started_at`, `finished_at`, `code`); fragment
w górnej linii odpytuje blokadę co 3 s w trakcie i co 60 s poza nim, a po końcu robi
pełny rerun — nowy build sam unieważnia cache.
Serwer **nie chodzi w nieskończoność**: `core/lifecycle.py` liczy aktywne sesje
Streamlita i po `GARMIN_IDLE_EXIT_MIN` minutach (domyślnie 5) bez żadnej
otwartej karty wysyła sobie SIGTERM. Licznik startuje z procesem, więc serwer,
którego nikt nie otworzył, też gaśnie. Bez zmiennej (systemd na serwerze,
`streamlit run app.py` ręcznie) nic się nie zmienia. Serwer zostawiony otwarty przez zmianę
kodu trzyma stare moduły (Streamlit przeładowuje tylko `app.py`; bez
`watchdog` nie obserwuje importów) i sypie `module 'shell' has no attribute …`
— dlatego `serve.py` zapisuje przy starcie `data/server.json` (pid + najnowszy
mtime kodu), a launchery najpierw wołają `serve.py --stop-if-stale`, które
zatrzymuje serwer starszy niż kod; zwykłe sprawdzenie portu startuje wtedy nowy. Sesje to prywatne API
Streamlita — jeśli zniknie, watchdog się wyłącza zamiast zamykać serwer.

## Wiele osób (`core/tenant.py`, `core/auth.py`, od 2026-11-02)

Jeden serwer, osobne dane dla każdej osoby (X — Garmin, Y — Apple Watch; docelowo
SaaS). Bez `data/users.json` wszystko działa jak dawniej: jedna osoba `me`,
katalog `data/`.

- **Układ**: `data/users.json` (rejestr), `data/server.secret`, a w
  `data/users/<id>/` wszystko, co należy do osoby: `raw/`, `tables/`, `coach/`,
  `state.json`, `excluded_nights.json`, `sport.json`, `ui.json`, `fetch.*`,
  `garmin/` (tokeny). `root: "."` w rejestrze = stary układ w `data/`, aż do
  `python -m tenant migrate <id>`. CLI: `python -m tenant [init|add|migrate|list]`.
- **Ścieżki osoby tylko przez funkcje**: `config.raw()`, `tables()`,
  `state_file()`, `excluded_nights()`, `tokenstore()`, `store.races_path()` /
  `plans_dir()` / `segments_path()`, `sport.store.settings_path()`,
  `i18n.settings_path()`, `sync.lock_path()`. **Nie wracaj do stałych modułu**
  (`config.TABLES`): liczyłyby się raz, dla pierwszej osoby.
- **Kto jest bieżący** (`tenant.current()`): `with tenant.use(id)` → osoba z sesji
  Streamlita (ustawia ją `auth.gate()` na początku `app.py`) → poza Streamlitem
  `GARMIN_USER=<id>` (CLI, `etl/run.py` uruchamiany przez `sync.start`) → jedyna
  osoba w rejestrze. Kilka osób i nic z tego = `tenant.NoUser`, nigdy domyślna osoba.
- **Logowanie** (`auth.identify`): jedna osoba — bez logowania; OIDC (`[auth]`
  w `.streamlit/secrets.toml`, `st.login`, wymaga `Authlib`) po e-mailu
  z `identities`; nagłówek zaufanego proxy (`GARMIN_AUTH_HEADER=Tailscale-User-Login`
  za `tailscale serve`, Streamlit tylko na 127.0.0.1); przeglądarka na tym
  komputerze (brak nagłówków przekierowania) = osoba z `"local": true`.
  Tożsamość podana, ale nieznana = odmowa, bez przejścia na „lokalną”.
- **Cache**: `shell.build_id()` = `<id>@<built_at>`; każdy `@st.cache_data`
  dostaje go w argumencie — nowa funkcja cache'owana też musi.
- **SQL jest zamknięty w katalogu osoby**: `db.connect` po utworzeniu widoków
  ustawia `allowed_directories` na `tables/` osoby, `enable_external_access =
  false` i `lock_configuration` — zakładka SQL nie przeczyta cudzego parquet ani
  `/etc/passwd`.
- **Pliki serwowane przeglądarce** (ślady globu) mają w nazwie
  `User.file_key(...)` (HMAC z `server.secret`) — bez tego nazwa była zgadywalna,
  a sprzątanie starych buildów kasowało pliki innej osoby.
- **Insighty to proza o liczbach jednej osoby** — `insights.load_all` zwraca je
  tylko osobie z `"insights": true`.
- **Pobieranie** (`sync`): blokada i zapis próby per osoba; timer przechodzi po
  wszystkich osobach z `source: garmin`; osoba Apple nie ma przycisku „Pobierz”.
  Tokeny drugiej osoby: `GARMIN_USER=<id> .venv/bin/python etl/login.py`.
- **Źródło Apple Health** (`etl/apple.py`, osoba z `source: apple`):
  `GARMIN_USER=y .venv/bin/python -m etl.apple import <export.zip>` kopiuje eksport
  do `raw/apple/exports/` i przebudowuje; `etl/load.py` sam oddaje budowę temu
  modułowi, więc `fetch.rebuild`, `etl.exclude` i analityka działają bez zmian.
  Health to pula wielu źródeł (iPhone, zegarek, Garmin Connect, Strava): sumy dzienne
  biorą **największą sumę jednego źródła**, nie sumę wszystkich; sen — sesja z
  największą liczbą minut snu na poranek (core → light, samo „w łóżku” = `sleep_h`
  bez faz, `sleep_in_bed_only`); trening zapisany przez dwie aplikacje (±2 min) liczy
  się raz; plik trasy wspólny dla kilku treningów (błąd nazw Stravy) jest odrzucany.
  **HRV**: Garmin zapisuje RMSSD, Apple Watch SDNN — inne wielkości. Osoba ma jedno
  źródło, więc `hrv_last_night` niesie nocną miarę *tej osoby*, a `hrv_kind`
  (`rmssd`/`sdnn`) mówi którą; dwie miary nigdy nie są w jednej serii. U Apple to
  średnia odczytów SDNN z okna snu (dzienne odczyty tylko w `hrv_sdnn`), norma
  `hrv_baseline_low/high` = 10.–90. percentyl 60 poprzednich nocy (min. 14),
  `hrv_norm = own`; teksty („Twoja norma” / „norma Garmina”) daje
  `facts.hrv_norm_words`. Watch dokłada: `night_series` (tętno i HRV w oknie snu),
  `wrist_temp_c`, `spo2_avg`, `sleep_respiration` (pomiar wieczorny = noc kończąca
  się rano), a na trening moc, krok, oscylację, kontakt z podłożem, kadencję z
  kroków zegarka, strefy tętna (%HRmax), `effort_score`, `hr_recovery_1min`.
  `training_load` = TRIMP Banistera (`load_source = "trimp"`, HRmax = max(trzecie
  najwyższe maksimum, 208 − 0,7·wiek)). Wspólne kolumny obu źródeł: `etl/schema.py`.
- **Dane w kształcie Apple Watcha bez zegarka**: `tools/synthetic_watch.py out.zip`
  (ziarnisty, spójna fizjologia: mocny dzień → wyższe tętno spoczynkowe i niższe HRV)
  → osoba `demo` (`tenant add demo --source apple`). Nigdy do katalogu prawdziwej osoby.
- Testy: `tests/__init__.py` zamyka cały przebieg w tymczasowym rejestrze;
  `tests.helpers.person()` / `people({...}, current=...)` dają własną osobę.
- Plan dalszych etapów (źródło Apple, API + PWA, SaaS): `TASKS.md`.

## Strona Admin (`views/admin.py`, `core/monitor.py`)

Dla osoby z `"admin": true` w rejestrze (`python -m tenant admin <id>`, `--off`
odbiera; układ jednoosobowy bez rejestru = admin). Dla innych strona **nie jest
rejestrowana** w `app.py` (adres nie istnieje), a `render` sprawdza flagę drugi
raz. Link w menu Laboratorium.

- Pokazuje osoby (rozmiar danych, build, ostatnie pobranie, Garmin połączony,
  klucze API), procesy aplikacji (cwd = repo: serwer, API, `etl/run.py`) z RAM
  i CPU, RAM/swap/dysk maszyny, otwarte karty, commit i „kod nowszy niż serwer”
  (`serve.code_stamp` vs `data/server.json`), ostrzeżenia (`monitor.warnings`,
  kody → zdania w widoku), logi pobrań i serwera. **Żadnych danych zdrowotnych.**
- Wszystko z `/proc` — `psutil` nie jest zależnością; czego nie da się odczytać,
  jest None. W LXC (mikr.us) load average to host — CPU mierzone z `/proc/stat`
  przez 0,3 s. Część „na żywo” to fragment odświeżany co 15 s.
- Przyciski „Pobierz teraz” / „Przelicz tabele” dla dowolnej osoby, **jedno
  naraz** (serwer ma 1 GB RAM; dwa przeliczenia obok serwera zeszły do 7 MB wolnego).

## Oficjalne API Garmina (sprawdzone 2026-10-25)

Garmin otworzył Connect Developer Program 21.10.2026 z tierem **Personal**
(darmowy klucz z ustawień Garmin Connect, bez wniosku; klucz wymienia się na
token, wygasa po 30 dniach – roku, nie odnawia się z kodu). **Nie przechodzimy
na nie** — `garminconnect` daje więcej:

- Personal jest tylko do odczytu (pull): podsumowania aktywności + pliki FIT,
  sen, HRV, Body Battery, stres, kroki, RHR. **Nie ma** VO2max, training
  readiness, training status, recovery time (wycinane też z FIT), backfillu
  ani Training/Courses API (wysyłanie treningów na zegarek = tier Starter:
  publiczna strona, polityka prywatności, przegląd).
- Zakres na wywołanie: podsumowania dzienne i HRV ≤ 180 dni, sen i Body Battery
  ≤ 28 dni, stres i kroki ≤ 7 dni. Limitów zapytań brak w dokumentacji.
- `garminconnect` ma `upload_workout` / `schedule_workout` / `get_activity_splits`
  — dokładnie to, czego Personal nie daje. Personal API to plan awaryjny,
  gdyby nieoficjalny login przestał działać (pola nocne, readiness i status
  trzeba by wtedy uznać za utracone).
