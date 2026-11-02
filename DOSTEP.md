# Dostęp dla znajomych: osoby, logowanie, HTTPS

Dashboard trzyma dane zdrowotne kilku osób na jednym komputerze (`tenant.py`).
Każda osoba widzi tylko swoje dane; kto patrzy, rozstrzyga `auth.py` przed
każdą stroną. Ta instrukcja ustawia to od zera.

## 1. Osoby

```bash
.venv/bin/python -m tenant init x --name "X" --local --identity x@gmail.com   # dane, które są dziś w data/
.venv/bin/python -m tenant add y --name "Y" --source apple --identity y@gmail.com
.venv/bin/python -m tenant migrate x        # opcjonalnie: data/ -> data/users/x/
.venv/bin/python -m tenant list
```

- `--identity` to e-mail konta Google, którym osoba będzie się logować (można kilka).
- `--local` = przeglądarka na tym komputerze bez logowania (tylko jedna osoba).
- Osoba z Garminem: `GARMIN_USER=<id> .venv/bin/python etl/login.py` (tokeny trafiają
  do `data/users/<id>/garmin/`).
- Osoba z Apple: `GARMIN_USER=<id> .venv/bin/python -m etl.apple import export.zip`
  (Zdrowie → profil → Eksportuj wszystkie dane).

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
.venv/bin/python -m auth setup https://<komputer>.<tailnet>.ts.net
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

**Sign in with Apple** nie jest dostępne: na stronie WWW wymaga płatnego Apple
Developer Program (Services ID). Osoba z iPhone'em loguje się kontem Google.

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
