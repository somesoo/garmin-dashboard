# Prywatność i RODO

Dashboard przechowuje **dane dotyczące zdrowia** (sen, tętno, HRV, stres, treningi
z trasami GPS) — to szczególna kategoria danych z art. 9 RODO. Gdy na serwerze jest
ktoś poza Tobą, jesteś **administratorem danych** tej osoby, a dostawca serwera
**podmiotem przetwarzającym**. Wyjątek „czysto osobisty” (art. 2 ust. 2 lit. c) TSUE
czyta wąsko: dane innych osób na serwerze w internecie już pod niego nie wchodzą.

Ten plik mówi, co robi kod, czego kod zrobić nie może (lista dla Ciebie na końcu)
i co odpowiedzieć, gdy ktoś zapyta albo coś wycieknie. To praktyczne opracowanie,
nie porada prawna — przed otwarciem dla obcych osób daj politykę i treść zgody do
przejrzenia komuś od RODO.

## Kto jest kim

| rola | kto | w kodzie |
|---|---|---|
| administrator danych | osoba z `admin: true`, osoba starego układu (`root: "."`) albo jedyna osoba w rejestrze | `privacy.controller()` — nie widzi ekranu zgody |
| osoba, której dane dotyczą | każdy inny w `data/users.json` | ekran zgody przed czymkolwiek (`views/consent.py`) |
| podmiot przetwarzający | dostawca VPS | `host` w `data/privacy.json` → polityka |
| odbiorcy | Google (logowanie), Garmin (źródło, wysyłka planu po kliknięciu) | polityka, sekcja „Kto je widzi” |

Dopóki jesteś jedyną osobą na serwerze, nic się dla Ciebie nie zmienia: brak
ekranu zgody, tokeny po cichu przechodzą na zaszyfrowane przy pierwszym pobraniu.

## Co robi kod

| wymóg RODO | jak |
|---|---|
| podstawa prawna: wyraźna zgoda (art. 9 ust. 2 lit. a) | ekran zgody po zalogowaniu, przed wyborem źródła; zaznaczenie + przycisk; zapis `consent.json` (wersja zasad, czas, język) i wpis w dzienniku |
| zgoda na aktualne zasady | `POLICY_VERSION` w `core/privacy.py`; nowa wersja = prośba o zgodę jeszcze raz |
| bez zgody nic się nie dzieje | timer nie pobiera ani nie przelicza (`sync.check_all`), API odpowiada 403 i nie zapisuje paczki z iPhone'a, dashboard stoi na ekranie zgody |
| obowiązek informacyjny (art. 13) | `privacy.policy()` PL/EN: na ekranie logowania (rozwijane), na ekranie zgody, na Koncie → Prywatność; `python -m core.privacy policy` |
| wycofanie zgody (art. 7 ust. 3) | Konto → Prywatność → „Wycofaj zgodę” (po wpisaniu imienia) = usunięcie wszystkiego + odłączenie Garmina |
| dostęp i przenoszenie (art. 15, 20) | Konto → Twoje dane → archiwum: wszystkie pliki osoby + `access_log.jsonl` z jej wpisami dziennika |
| usunięcie (art. 17) | Konto → Twoje dane → „Usuń wszystkie moje dane”; z kopii zapasowych znika po `backup_days` |
| rozliczalność, bezpieczeństwo (art. 5 ust. 2, art. 32) | dziennik dostępu `data/audit/<RRRR-MM>.jsonl` (0600): logowania, odmowy, odczyty aplikacji telefonu (max raz na godzinę na klucz), paczki z iPhone'a, archiwa, usunięcia, zgody, (od)łączenie Garmina, działania admina na cudzych danych. **Bez wartości zdrowotnych**. Każda osoba widzi swoje wpisy na Koncie, admin wszystkie na stronie Admin |
| minimalizacja przechowywania (art. 5 ust. 1 lit. e) | konto nieużywane `inactive_days` (365) → `python -m core.privacy retention --apply`; dziennik 92 dni; kopie `backup_days` (30) |
| szyfrowanie | tokeny Garmina: Fernet, klucz **poza** `data/` (`GARMIN_KEY_FILE`, domyślnie `~/.config/garmin-dashboard/data.key`); kopie zapasowe: X25519 + AES-256-GCM, serwer zna tylko klucz publiczny (`tools/backup.py`); transmisja: HTTPS |
| poufność między osobami | bez zmian: katalog osoby, cache kluczowany osobą, DuckDB zamknięty w `tables/` osoby, nazwy plików z HMAC |
| admin nie ogląda danych zdrowotnych | strona Admin: rozmiary, liczby, godziny; podgląd logu pobierania wycina imię z Garmina i parametry modelu Banistera (`monitor.redact`) |
| brak zautomatyzowanych decyzji (art. 22) | aplikacja niczego o osobie nie rozstrzyga; polityka to mówi |

### Czego kod nie szyfruje i dlaczego

Parquety i surowy JSON leżą na dysku jawnie: DuckDB czyta je przy każdym widoku,
a pobieranie w tle i analityka muszą je otwierać bez udziału osoby. Szyfrowanie
„tylko osoba ma klucz” wykluczyłoby timer pobierania i aplikację na telefon. Przed
kradzieżą dysku czy migawki chroni **szyfrowanie całego dysku** po stronie hosta
(lista na końcu), przed rootem na działającym serwerze nic w aplikacji nie chroni.
To uczciwie opisuje polityka („administrator ma techniczny dostęp do serwera”).

## Rejestr czynności przetwarzania (art. 30)

Zwolnienie dla małych podmiotów z art. 30 ust. 5 **nie obejmuje** danych szczególnej
kategorii, więc rejestr ma być — wystarczy ta tabela, uzupełniona o Twoje dane.

| pole | wartość |
|---|---|
| administrator | `controller` / `contact` z `data/privacy.json` |
| cel | pokazanie osobie jej danych z zegarka i ich analiz (dashboard, aplikacja na telefon) |
| kategorie osób | znajomi administratora dodani do `data/users.json` |
| kategorie danych | e-mail i imię (Google); dane o zdrowiu i aktywności z Garmin Connect / Apple Health; ślady GPS; dane wpisane ręcznie (starty, plan, strefy); dziennik dostępu (czas, rodzaj, IP) |
| podstawa | art. 9 ust. 2 lit. a + art. 6 ust. 1 lit. a (zgoda); dziennik: art. 6 ust. 1 lit. f |
| odbiorcy | dostawca VPS (`host`); Google — tylko logowanie; Garmin — źródło danych i (po kliknięciu) kalendarz treningów |
| przekazanie poza EOG | brak dla danych zdrowotnych (serwer w UE — **sprawdź `location`**); logowanie Google to przetwarzanie po stronie Google |
| terminy usunięcia | konto: do usunięcia / wycofania zgody / `inactive_days` nieaktywności; kopie: `backup_days`; dziennik: 92 dni |
| środki bezpieczeństwa | sekcja „Co robi kod” + lista dla administratora |

## Ocena skutków (DPIA, art. 35) — wersja krótka

Kilka osób to nie „duża skala”, więc pełna DPIA raczej nie jest obowiązkowa, ale
krótka ocena kosztuje mniej niż jej brak:

| ryzyko | prawdopodobieństwo | skutek | środek |
|---|---|---|---|
| obcy loguje się cudzym kontem | niskie | wysoki | tylko zweryfikowany e-mail z listy; odmowy w dzienniku |
| osoba A widzi dane B | niskie | wysoki | izolacja per osoba + testy (`tests/test_tenant.py`, `test_auth.py`) |
| wyciek kopii zapasowej | średnie | wysoki | szyfrowana do klucza właściciela; rotacja |
| kradzież tokenów Garmina | niskie | wysoki (dostęp do konta Garmin) | zaszyfrowane, klucz poza `data/`; odłączenie na Koncie |
| przejęcie serwera | niskie | wysoki | aktualizacje, tylko klucz SSH, porty 22/80/443, szyfrowanie dysku |
| klucz telefonu wycieka | średnie | średni | jedna osoba, jeden zakres, odwołanie na Koncie, odczyty w dzienniku |
| admin zagląda w dane | — | wysoki | zasada niżej + strona Admin bez danych zdrowotnych |

## Gdy coś wycieknie (art. 33–34)

1. **Zatrzymaj**: `systemctl stop garmin-dashboard`; odwołaj klucze (`python -m api token revoke`),
   zmień `cookie_secret` w `data/secrets.toml` (wyloguje wszystkich), odłącz Garmina osobom, których
   tokeny mogły wyciec (one zmieniają hasło w Garmin Connect).
2. **Ustal**: `python -m core.privacy log` (kto, kiedy, skąd), `journalctl -u garmin-dashboard`,
   czyje katalogi i od kiedy.
3. **Zapisz** w tym pliku (sekcja niżej): co, kiedy, czyje dane, skutki, co zrobione — każde
   naruszenie, także niezgłaszane.
4. **72 godziny** od wykrycia: zgłoszenie do Prezesa UODO (biznes.gov.pl, formularz zgłoszenia
   naruszenia), chyba że naruszenie raczej nie powoduje ryzyka (np. zaszyfrowana kopia bez klucza).
5. **Bez zbędnej zwłoki** powiadom osoby, gdy ryzyko jest wysokie (dane zdrowotne prawie zawsze):
   co się stało, co mogło wyciec, co zrobiłeś, co mają zrobić.

### Rejestr naruszeń

| data wykrycia | co | czyje dane | zgłoszone do UODO | osoby powiadomione | działania |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

## Trener i dzieci (`core/team.py`, zasady `2026-11-08`)

Trener to zwykła osoba z własnymi danymi, wpisana przy zawodnikach w rejestrze
(`"coach": "<id>"`, `python -m core.tenant coach <zawodnik> <trener>`). Sam wpis nic
nie otwiera — trener widzi zawodnika dopiero, gdy jednocześnie:

1. rejestr nazywa go trenerem tej osoby,
2. osoba ma ważną zgodę na dashboard (`privacy.required` = nie),
3. osoba **osobno** zgodziła się na tego trenera, w tej wersji zasad (`coach.json`:
   trener, zakres, kto się zgodził, kiedy, wersja).

Sprawdzane przy **każdym** kliknięciu trenera (`ui/coaching.gate`): wycofanie na Koncie
działa od razu. Zgoda na trenera nigdy nie jest warunkiem zgody na dashboard (art. 7 ust. 4)
— na ekranie zgody to osobne, niezaznaczone pole.

| | jak |
|---|---|
| zakres | `all` (wszystko poza Kontem, SQL, insightami) albo `training` (biegi, plan, prognoza, segmenty, trasy, historia — **bez** stron, które gdziekolwiek czytają sen/HRV/stres: Dzień, Dziś, Regeneracja, Sen, Obciążenie, Sport, Fizjologia, Statystyka). Strona jest w zakresie albo poza nim w całości; na *Planie* powody z liczbami regeneracji (`why: response`) i poranna decyzja są ukryte |
| co trener robi | ogląda, pisze notatki (wątek w `notes.json` osoby), zmienia plan (przebudowa, korekta, edycja sesji) |
| czego nie | Konto osoby, pobieranie, Garmin, usuwanie, język i poziom osoby (`ui.json` zostaje trenera — `i18n.settings_path` czyta `tenant.viewer()`) |
| rozliczalność | pierwsze wejście w sesji przeglądarki → `coach_view` w dzienniku osoby (z `by`); zgoda i jej cofnięcie → `coach_grant` / `coach_revoke`. Osoba widzi to na Koncie w kolumnie „Kto” |
| dzieci | poniżej `privacy.CHILD_AGE` (16, art. 8 RODO; Polska nie obniżyła progu) zgodę — na dashboard i na trenera — daje rodzic albo opiekun prawny, wpisując imię i nazwisko (`by: "guardian"`, `guardian` w `consent.json` i `coach.json`) |
| notatki | leżą w katalogu zawodnika: idą z jego archiwum i znikają z jego usunięciem |

**Czego kod nie sprawdzi** (Twoja odpowiedzialność jako administratora):

- czy osoba, która kliknęła „Rodzic lub opiekun prawny”, naprawdę nim jest i czy dziecko
  ma mniej niż 16 lat — kod tylko zapisuje deklarację. Przy dzieciach z klubu: konto Google
  zakłada i loguje **rodzic** (jego e-mail w `identities`), nie dziecko;
- czy trener ma podstawę, żeby w ogóle prowadzić te dzieci (umowa z klubem/rodzicami) —
  dashboard przetwarza dane dla nich, nie zamiast takiej umowy;
- jeśli trener i administrator to różne osoby: trener jest **odbiorcą** danych; jeśli
  prowadzisz grupę jako klub, administratorem może być klub — wtedy `privacy setup` z jego danymi.

## Zasady dla administratora

- **Nie zaglądasz w cudze dane.** Żadnego `GARMIN_USER=<cudzy id>` w notatniku, `/trener`,
  Claude Code ani innego narzędzia na danych innej osoby — także „tylko żeby sprawdzić błąd”.
  Błąd odtwarzaj na swoich danych albo na `demo` (`tools/synthetic_watch.py`).
- Przyciski „Pobierz teraz” / „Przelicz tabele” na cudzej osobie idą do jej dziennika (`admin`).
- Kopia `data/` (scp, rsync) **zawsze** zaszyfrowana — `tools/backup.py`, nie gołe `rsync data/`.
- Zmiana tego, co zbierasz, po co albo komu przekazujesz → podbij `POLICY_VERSION`.

## Lista dla Ciebie: czego kod nie zrobi

1. **`python -m core.privacy setup`** z Twoim imieniem, adresem, nazwą dostawcy i lokalizacją
   serwera — inaczej polityka podaje imię i e-mail admina i ogólnik o hostingu.
   ```bash
   .venv/bin/python -m core.privacy setup --controller "Imię Nazwisko" --contact ty@gmail.com \
       --host "Hetzner Online GmbH" --location "Niemcy (UE)"
   ```
2. **Umowa powierzenia (DPA) z dostawcą serwera** (art. 28). Hetzner i większość dużych
   dostawców mają ją w panelu do akceptacji; sprawdź, gdzie stoi serwer.
3. **Szyfrowanie dysku** serwera (LUKS przy instalacji) i Maca (FileVault). Na **mikr.us
   (kontener LXC) się nie da**, a operator hosta ma dostęp do plików — eve302 to próba,
   docelowo własny VPS w UE.
4. **Kopie**: `tools/backup.py keygen` na Macu, klucz publiczny na serwer, cron (`docs/DEPLOY.md`
   → „Kopia zapasowa”). Klucz prywatny także w menedżerze haseł — bez niego kopie są nie do otwarcia.
5. **Klucz tokenów** (`~/.config/garmin-dashboard/data.key` użytkownika serwisu): przenosząc
   `data/` na inny komputer, przenieś też ten plik albo poproś osoby z Garminem o ponowne połączenie.
6. **Retencja**: cron `python -m core.privacy retention --apply` raz w tygodniu (`docs/DEPLOY.md`).
7. **Google OAuth**: w trybie *Testing* do 100 osób testowych. Przejście na *In production*
   wymaga adresu polityki prywatności na stronie aplikacji — polityka jest na ekranie logowania;
   jeśli Google zażąda osobnego adresu, opublikuj `python -m core.privacy policy`.
8. **Garmin**: `garminconnect` to nieoficjalny login hasłem osoby — dla kilku znajomych
   tolerowane, dla obcych łamie warunki Garmina. Przed otwarciem dla obcych: Garmin Connect
   Developer Program (ma własne wymagania: polityka, usuwanie danych po odłączeniu).
9. **Nie jest to wyrób medyczny** (MDR) dopóki nic nie diagnozuje: w tekstach unikaj „leczy”,
   „wykrywa chorobę”, „diagnoza”. *Dziś* proponuje trening — to wellness.
10. **Baner ciasteczek niepotrzebny**: jest tylko ciasteczko sesji logowania (niezbędne).
