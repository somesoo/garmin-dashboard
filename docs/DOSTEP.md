# Dostęp dla znajomych: osoby, logowanie, HTTPS

Dashboard trzyma dane zdrowotne kilku osób na jednym komputerze (`core/tenant.py`).
Każda osoba widzi tylko swoje dane; kto patrzy, rozstrzyga `core/auth.py` przed
każdą stroną. Ta instrukcja ustawia to od zera.

## 1. Osoby

```bash
.venv/bin/python -m core.tenant init x --name "X" --local --identity x@gmail.com   # dane, które są dziś w data/
.venv/bin/python -m core.tenant add y --name "Y" --source apple --identity y@gmail.com
.venv/bin/python -m core.tenant migrate x        # opcjonalnie: data/ -> data/users/x/
.venv/bin/python -m core.tenant list
```

- `--identity` to e-mail konta Google, którym osoba będzie się logować (można kilka).
- `--local` = przeglądarka na tym komputerze bez logowania (tylko jedna osoba).
- Osoba z Garminem: `GARMIN_USER=<id> .venv/bin/python etl/login.py` (tokeny trafiają
  do `data/users/<id>/garmin/`).
- Osoba z Apple: `GARMIN_USER=<id> .venv/bin/python -m etl.apple import export.zip`
  (Zdrowie → profil → Eksportuj wszystkie dane).

## Jak to wygląda dla znajomego

1. Otwiera adres → ekran z jednym przyciskiem **Zaloguj przez Google** (konto spoza
   listy dostaje „to konto nie ma jeszcze dostępu” i „Zaloguj innym kontem”).
2. Pierwsze wejście bez danych → od razu strona **Konto** z „Zacznijmy”: wybiera
   źródło (Garmin / Apple Health) i je łączy — Garmin e-mailem i hasłem (hasło użyte
   raz, nie zapisywane; kod weryfikacyjny Garmina obsługiwany), Apple eksportem z
   aplikacji Zdrowie. Garmin od razu pobiera rok historii.
3. Gdy przyjdą pierwsze dane, dashboard otwiera się sam. Imię z Google trafia do
   profilu przy pierwszym logowaniu (do zmiany w Konto → Profil).
4. Potem imię w prawym górnym rogu = Konto: źródło, telefon, klucze, pobranie lub
   usunięcie swoich danych, wylogowanie.

Administrator dodaje tylko e-mail: `python -m core.tenant add <id> --identity <gmail>`
(+ test user w Google Cloud). Resztę osoba robi sama.

## 2. HTTPS przez Tailscale (bez wystawiania portów do internetu)

Znajomi instalują Tailscale i dostają zaproszenie do Twojej sieci (albo
udostępniasz im tylko ten komputer: *Share node*). Na komputerze z dashboardem:

```bash
tailscale serve --bg 8501          # https://<komputer>.<tailnet>.ts.net -> 127.0.0.1:8501
```

Przy więcej niż jednej osobie `serve.py` sam ustawia `--server.address 127.0.0.1`:
do Streamlita da się wejść tylko przez ten proxy (albo z tego komputera).

## 3. Logowanie Google

```bash
.venv/bin/python -m core.auth setup https://<komputer>.<tailnet>.ts.net
```

Zapisuje `data/secrets.toml` (prawa 600, poza gitem) z losowym `cookie_secret`.
Potem w [Google Cloud Console](https://console.cloud.google.com/apis/credentials):

1. *Create credentials → OAuth client ID → Web application*.
2. *Authorised redirect URIs*: dokładnie `https://<komputer>.<tailnet>.ts.net/oauth2callback`.
3. *OAuth consent screen*: tryb *Testing* i dodaj e-maile znajomych jako *test users*
   (do kilkudziesięciu osób nie trzeba weryfikacji aplikacji przez Google).
4. Wklej `client_id` i `client_secret` do `data/secrets.toml`, zrestartuj serwer.

Logowanie przyjmuje tylko **zweryfikowany** e-mail, który jest w `identities`
którejś osoby. Inne konto Google dostaje odmowę, nie domyślną osobę.

**Z Google każda osoba jest przypięta do swojego konta** — także na komputerze z
serwerem: `"local": true` i `GARMIN_AUTH_HEADER` przestają działać, wchodzi się
wyłącznie przez „Zaloguj”. Konto X → dane X, konto Y → dane Y, na każdym urządzeniu.

Na samym komputerze (bez Tailscale) wystarczy adres lokalny — Google przyjmuje
`http://localhost` jako redirect:

```bash
.venv/bin/python -m core.auth setup http://localhost:8501
# w Google Cloud: Authorised redirect URI = http://localhost:8501/oauth2callback
```

**Sign in with Apple** nie jest dostępne: na stronie WWW wymaga płatnego Apple
Developer Program (Services ID). Osoba z iPhone'em loguje się kontem Google.

## 4. Apple Watch: codzienna wysyłka z iPhone'a (API)

Przy więcej niż jednej osobie `serve.py` uruchamia obok dashboardu API
(`api.py`, 127.0.0.1:8502). Na HTTPS wystawia je ten sam Tailscale:

```bash
tailscale serve --bg --set-path /api http://127.0.0.1:8502
```

Osoba z Apple Watchem robi resztę sama na stronie **Konto (imię w prawym górnym rogu)**:

1. *Historia z Apple Health*: wgrywa `export.zip` (Zdrowie → zdjęcie profilu →
   Eksportuj wszystkie dane) — raz, na start.
2. *Utwórz klucz do wysyłki* — klucz widać raz; w pliku zostaje tylko jego hash.
3. Na iPhonie jedna z dwóch dróg:
   - **Health Auto Export** (płatna, działa w tle, najprościej): *Automations → New → REST API*,
     URL `https://<komputer>.<tailnet>.ts.net/api/ingest/apple`, format JSON (v2),
     nagłówek `Authorization: Bearer <klucz>`, zakres „ostatnie 3 dni”, co godzinę/dzień.
   - **Skrót** (bezpłatny): automatyzacja *Pora dnia 9:00 → Uruchom od razu*. Akcje:
     *Znajdź próbki zdrowia* dla tętna, HRV, tętna spoczynkowego, kroków, snu (od 3 dni),
     z każdej próbki *Słownik* `{type, start, end, value, unit, source}` (daty w ISO 8601),
     całość w `{"format": "garmin-dashboard/1", "records": [...], "sleep": [...]}`,
     *Pobierz zawartość URL*: POST, JSON, nagłówek `Authorization: Bearer <klucz>`.
     Pełny format: docstring `etl/apple_push.py`.

Paczka trafia do `data/users/<id>/raw/apple/push/` (ta sama treść drugi raz — nic),
tabele przeliczają się w tle (`sync.request_rebuild`; paczka w trakcie trwającej
przebudowy czeka na znacznik `rebuild.pending`). Dane z eksportu i z paczek łączą się
bez dublowania.

Klucz *do odczytu* (ta sama strona) otwiera `GET /api/manifest` i `GET /api/db`
(cała baza osoby jako SQLite z ETag) — pod aplikację na telefon. Klucze z terminala:
`.venv/bin/python -m api token add|list|revoke <osoba> ...`.

## 5. Aplikacja na telefon (PWA — iPhone i Android, bez App Store)

Ta sama ścieżka `/api` serwuje aplikację: `https://<komputer>.<tailnet>.ts.net/api/app/`.

1. **Konto → Utwórz klucz do odczytu** — strona pokazuje klucz i link
   `…/api/app/#token=…` (klucz we fragmencie adresu nie trafia do serwera ani logów).
2. **Android**: otwórz link w Chrome → *Zainstaluj aplikację*.
   **iPhone**: Safari → *Udostępnij → Do ekranu początkowego*, otwórz aplikację z ekranu
   i wklej klucz (aplikacja z ekranu początkowego ma osobną pamięć od Safari).
3. Aplikacja pokazuje: nagłówki-wnioski z dashboardu (regeneracja, sen, bieganie),
   dzisiejsze liczby wobec normy, 90 dni HRV/snu, km tygodniowo, ostatnie treningi.
   Ostatnia kopia zostaje w telefonie — bez sieci działa na niej („offline — ostatnia kopia”).

Liczy wszystko serwer (`analysis/summary.py`, ~10 KB JSON per język, ETag); aplikacja (`pwa/`)
tylko rysuje. Odwołany klucz = ekran łączenia. CSP: tylko własne pliki, bez ramek.

## Alternatywa bez Google: tożsamość z Tailscale

Jeśli wszyscy są w Twojej sieci Tailscale, logowanie może dać sam Tailscale:

```bash
GARMIN_AUTH_HEADER=Tailscale-User-Login .venv/bin/python serve.py
```

`tailscale serve` dopisuje login osoby do każdego żądania; w `identities` wpisz
login Tailscale (zwykle e-mail). Tylko z serwerem na 127.0.0.1 — inaczej nagłówek
da się podrobić.

## Co jest chronione i jak

| ryzyko | zabezpieczenie |
|---|---|
| ktoś obcy otwiera stronę | brak tożsamości = ekran logowania i `st.stop()`, nigdy domyślna osoba |
| osoba A czyta dane B | ścieżki, cache (`build_id`) i zapytania liczone dla jednej osoby (`tenant.current`) |
| zakładka SQL czyta cudze pliki | DuckDB zamknięty w `tables/` osoby (`allowed_directories`, zablokowana konfiguracja) |
| zgadnięcie adresu pliku z trasami | nazwa z HMAC per osoba (`data/server.secret`) |
| podrobiony nagłówek tożsamości | serwer na 127.0.0.1, nagłówek tylko gdy `GARMIN_AUTH_HEADER` ustawiony |
| niezweryfikowany e-mail | odrzucany (`email_verified`) |
| dane w gicie | `data/`, `secrets.toml`, `export*.zip` w `.gitignore` |
| klucz telefonu wycieknie | klucz otwiera jedną osobę i jeden zakres; odwołanie na stronie Konto |
| aplikacja na telefonie | CSP: tylko własne pliki i własny adres, bez ramek; klucz we fragmencie linku |

## Prawa każdej osoby

Na stronie **Konto → Twoje dane** każdy sam: pobiera archiwum wszystkiego, co
o nim jest (bez sekretów), albo usuwa wszystko (po wpisaniu swojej nazwy). Administrator:
`.venv/bin/python -m core.tenant remove <id> --yes` usuwa też wpis z rejestru.
