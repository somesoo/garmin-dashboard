# Zadania

## Do zrobienia

### Wiele osób → SaaS (plan 2026-11-02, zasady w CLAUDE.md → „Wiele osób”)

Osoba X — Garmin, osoba Y — Apple Watch (iPhone); dane całkowicie osobne.
Bez App Store: iPhone przez PWA, dane z Apple Health wypychane na serwer.

- [x] 1. Osobne dane: `tenant.py` (rejestr, `data/users/<id>/`, migracja),
      ścieżki per osoba, cache per osoba, SQL zamknięty w katalogu osoby,
      pobieranie per osoba, insighty tylko dla swojej osoby.
- [x] 2. Kto patrzy: `auth.py` — jedna osoba bez logowania, OIDC (`st.login`),
      nagłówek `tailscale serve`, przeglądarka lokalna; nieznany = odmowa.
- [x] 3. Model wielu źródeł: `etl/schema.py` (wspólne kolumny `daily`/`activities`,
      puste, gdy źródło ich nie zna), kolumny `source` i `load_source`; HRV Apple (SDNN)
      w `hrv_sdnn`, nigdy w `hrv_last_night`; TRIMP Banistera jako `training_load` dla
      Apple; core → light. Przebudowa Garmina na danych X: identyczne wartości, tylko
      nowe kolumny. Wszystkie 18 widoków renderuje się dla obu osób.
  - [x] HRV z Apple Watcha (nocne SDNN, własna norma, `hrv_kind`), teksty „Twoja norma”,
        TRIMP / effort score w Treningu, typy Watcha (temperatura, SpO2, oddech, moc,
        dynamika, strefy, HR recovery), `night_series` z zegarka.
  - [x] Syntetyczny eksport Apple Watcha (`tools/synthetic_watch.py`, osoba `demo`).
  - [x] Kafle tylko-Garminowe (readiness, Body Battery, stres, ocena snu, mapa doby)
        znikają, gdy źródło osoby ich nie zapisuje (`shell.has`, `bento.pair` — drugi kafel
        bierze cały rząd); KPI Regeneracji: kroki i długość snu zamiast readiness/oceny.
- [x] Konta: z logowaniem Google każda osoba jest przypięta do swojego konta Google
      (`identities`); `local` i nagłówek proxy działają tylko bez Google.
- [-] Web Push i natywna aplikacja na Androida — odłożone (decyzja 2026-11-02).
  - [ ] Po przyjściu zegarka: eksport z prawdziwego Watcha, porównanie z `demo`
        (nazwy typów, jednostki, `WorkoutEvent` z okrążeniami → `run_laps`).
- [x] 4a. Import `export.zip`: `GARMIN_USER=y python -m etl.apple import <zip>` →
      `raw/apple/exports/`, budowa w `etl/apple.py`. Eksport Y: 444 dni, 39 treningów.
      **W eksporcie Y nie ma Apple Watcha**: tętno, sen z fazami i biegi 2025-08…2026-04
      zapisał Garmin Connect, reszta to krokomierz iPhone'a. Jeśli Y ma Garmina,
      bogatsze dane da `source: garmin` z jego kontem.
- [x] 4b. `POST /api/ingest/apple` (`api.py`, `etl/apple_push.py`): format Skrótu
      `garmin-dashboard/1` i Health Auto Export, paczki w `raw/apple/push/` (idempotentnie),
      przebudowa w tle z kolejką (`rebuild.pending`), tokeny per osoba (hash, zakres).
      Sprawdzone na żywo: paczka → 202 → nowy dzień w tabelach po ~11 s.
  - [ ] Zbudować i przetestować Skrót na prawdziwym iPhonie (format w DOSTEP.md);
        sprawdzić Health Auto Export na prawdziwej paczce.
- [x] Logowanie Google (`st.login`, `python -m auth setup`, tylko zweryfikowany e-mail),
      serwer na 127.0.0.1 przy kilku osobach, strona **Konto** (wgranie eksportu,
      klucze do wysyłki i odczytu, odwołanie). Sign in with Apple wymaga płatnego konta.
  - [ ] Utworzyć klienta OAuth w Google Cloud i przejść logowanie w przeglądarce.
- [x] 5. API dla aplikacji (`/api/manifest`, `/api/db` SQLite, `/api/summary?lang=`) i PWA
      (`pwa/`, `/api/app/`): nagłówki z `facts.py` liczone na serwerze (`summary.py`),
      offline z ostatniej kopii, parowanie kluczem (link z fragmentem), PL/EN, CSP.
      Zamiast sql.js w telefonie — JSON ~10 KB (mniej kodu, bez drugiej implementacji liczb).
      Sprawdzone: renderowanie `app.js` w Node na prawdziwym API (PL/EN, odwołany klucz).
  - [ ] Obejrzeć na prawdziwym S23 i iPhonie (bez przeglądarki tutaj nie było zrzutów).
- [x] 6a. Prawa osoby na stronie Konto: archiwum wszystkich swoich danych (bez
      sekretów: hashy kluczy, tokenów Garmina, cache) i usunięcie wszystkiego po wpisaniu
      nazwy; `python -m tenant remove <id> --yes` usuwa też wpis z rejestru.
- [ ] 6. SaaS: zgoda i polityka (dane zdrowotne = art. 9 RODO), eksport/usunięcie
      konta, szyfrowanie, kopie per osoba, hosting (nie eve302).
      **Ryzyko**: `garminconnect` to nieoficjalny login — dla obcych użytkowników
      trzeba oficjalnego Garmin Developer Program.

### Angielska wersja interfejsu (`i18n.py`, zasady w CLAUDE.md → „Języki”)

- [x] **Etap 1** — moduł `i18n.py`, przełącznik PL/EN w szynie, menu i tytuły
      stron, szyna (zakres, pobieranie, status), chrome kafli (`bento.py`,
      pomoc „Co to jest?”), daty na osiach i podpisy builderów (`theme.py`).
- [x] **Etap 2** — wszystkie strony w `views/` (w `i18n.BILINGUAL`), słownik
      pojęć (`glossary_en.py`), teksty globu (przekazywane z `globe.py`).
      Kody zapisywane przez analitykę i `running/` (`form_zone`, `quadrant`,
      `model`, typ treningu, pewność, decyzja dnia, status celu, fazy planu)
      zostają kodami — tłumaczy je widok.
- [x] **Etap 3** — `running/` i CLI w `etl/` (w `i18n.BILINGUAL`): plan zapisuje
      kody (`text`), zdania składa `running/text.py`; stare plany migrowane przy
      pierwszym odczycie. `kind_reason`, `source`, powód Banistera jako kody.
      Coach, prognoza, walidacja i CLI (`--lang`) przez `tr`.
- [x] **Etap 4** — insighty: `insights/<nazwa>.en.md` obok polskiego pliku,
      strona bierze wersję w języku interfejsu (brak tłumaczenia → polska).

### Jakość planowania (audyt 2026-10-28)

Cel: plan zgodny z aktualnymi badaniami, nie tylko wygodny dla aplikacji.
Po każdej większej zmianie: przejrzeć wcześniejsze punkty i to, co już
zrobione — czy nowa reguła czegoś nie unieważnia (wpis „Przegląd wstecz”).

- [x] **1. Reguła pojedynczego biegu (Garmin-RUNSAFE, BJSM 2025)** — żaden bieg
      planu > 1,1× najdłuższego z 30 dni (realne + zaplanowane); ACWR 1,3 przestaje
      być bezpiecznikiem (iloraz tydzień/tydzień nie przewidywał kontuzji).
      Decyzja dnia skraca sesję, gdy realna historia jest krótsza niż plan zakładał.
- [x] **2. Biblioteka treningów z progresją** — drabinki dla progu (Daniels:
      odcinki → ciągły, ≤ 10% tygodnia, min. 20 min), interwałów (≤ 8%, min.
      12 min), podbiegów, tempa startowego (≤ 20%); rotacja typów przy jednym
      akcencie w tygodniu; tydzień lżejszy = szczebel niżej; przebieżki w krokach
      zegarka.
- [x] **3. Trening siłowy w planie** (Blagrove 2018, Llanos-Lagos 2024) —
      adaptacja → siła ciężka + plyometria → utrzymanie → lekko w taperze; w dniu
      akcentu po biegu, nie w przeddzień mocnego dnia; dopasowanie do aktywności
      `strength_training` z Garmina; przełącznik w ustawieniach.
- [x] **4. Akcent w tygodniu startu** (Bosquet 2007, Mujika) — krótkie odcinki
      w tempie startowym 4–6 dni przed startem zamiast samych spokojnych.
- [x] **5. Dwa starty A blisko siebie** — przy < 8 tyg. między startami A plan
      pyta, który jest główny (drugi blok to dziś regeneracja + 1 tydzień + taper).
- [x] **6. Strefy od progu** — tętno progowe z wysiłku 18–60 min bliskiego
      maksymalnego, strefy Friela; biegi spokojne na zegarku po tętnie.
      Prędkość krytyczna **odłożona**: dzisiejsze `critical_speed` bierze najlepsze
      odcinki Garmina z treningów (z przerwami) i wychodzi wolniej niż próg z
      VDOT (5:14 vs 5:03–5:10) — patrz 6b.
- [x] **6b. Prędkość krytyczna z czystych wysiłków** — dopasowanie CS tylko do
      `run_efforts` z `near_max` (bez odcinków z przerwami); dopiero wtedy jako
      kontrola tempa progowego (T nie szybciej niż CS).
- [x] **7. Progresja z wykonania** — szczebel drabinki z tego, co faktycznie
      zrobione (okrążenia `run_laps`: odcinki w tempie, tętno na odcinkach),
      nie z liczby zaplanowanych sesji.
- [x] **8. Adaptacja tygodnia z reakcji** — trend HRV (7 d vs baza 60 d i SWC),
      EF przy stałym tętnie, realizacja planu decydują: rośnie / stoi / lżej,
      zamiast sztywnego „co 3.–4. tydzień”.
- [x] **9. Odporność na zmęczenie (durability)** — w długich biegach fazy
      szczytu progresja odcinka w tempie startowym i kontrola dryfu tętna.
- [x] **10. Sprawdzenie wstecz planu** — symulacja generatora na historii:
      ile reguł złamanych, jak plan nadążał za realnym wykonaniem.
- [x] **11. Stałe bez źródła** (`PEAK_KM`, `LONG_TARGET_KM`, udział długiego,
      granice faz, `QUALITY_ROOM_KM`, `keep_one`) — każdą uzasadnić źródłem albo
      wyprowadzić z danych biegacza; opisać w docstringu.
- [x] **12. Siła na zegarek** — trening siłowy jako workout Garmina
      (`sportType` strength), dziś wysyłane są tylko biegi.
- [x] **13. Brief dla asystenta** — szczebel drabinki i lista skoków z realnej
      historii w `running.coach` (najdłuższy bieg z 30 dni i limit następnego
      biegu już są w `load_signals`).
- [x] **14. Skoki w realnej historii na stronie Obciążenie biegowe** — kafel:
      każdy bieg vs 1,1× najdłuższego z 30 dni (u Ciebie 04.10 i 18.10 to skoki
      +66% i +40%), zamiast pasa ACWR jako głównego sygnału.

**Przegląd wstecz po 1–3 (2026-10-28):** ACWR wycofany jako reguła także poza
planem — decyzja dnia nie traktuje już ilorazu > 1,5 jako sygnału regeneracji,
brief nie ocenia go pasmem 0,8–1,3, słownik (`acwr`, `run_ratio`) i podpisy
Forma/Obciążenie mówią „opis, nie granica”; `/trener` dostał nowe reguły
i kody sesji; `--validate` sprawdza regułę 30 dni. Punkt 4 (akcent w tygodniu
startu) wpasuje się w `library.rotation("race")` — dziś tydzień startu ma 0
akcentów (`quality_count`).

**Przegląd wstecz po 6 (2026-10-28):** klasyfikacja biegów (`sessions.py`) ocenia
tętno jako % HRmax, ale etykietę jakości daje tylko przy tempie bliskim M — bieg
spokojny na górze nowej strefy (≤ 159 bpm) zostaje „easy”, więc dopasowanie
planu się nie psuje; bez zmian. Odcinki podbiegów pokazują pasmo strefy I, którego
60–90 s nie osiągnie — opis i tak mówi „po wysiłku”. Przy punkcie 7 strefy od
LTHR mogą być miarą wykonania (tętno odcinków vs pasmo T).

**Przegląd wstecz po 6b i 7 (2026-10-28):** tętno progowe z punktu 6 pochodzi
z `block` — to jeden ciągły blok pracy (reps == 1), więc jest czystym wysiłkiem
i zostaje. `rc.active_plan` (automatyczna przebudowa po zmianie startów) dostał
okrążenia i aktywności, żeby też liczył szczeble z wykonania. Akcent tygodnia
startu (`sharpen`) nie przesuwa drabinki. Do zrobienia przy 8: ta sama
ocena wykonania (`outcomes`) może sterować wzrostem tygodnia.

- [x] **8b. EF przy stałym tętnie jako sygnał postępu** — w 8 weszły HRV,
      tętno spoczynkowe i realizacja; EF (`efficiency`) wymaga grupowania po
      przedziale tętna (pułapka z CLAUDE.md), więc osobno.

**Przegląd wstecz po 8 (2026-10-28):** decyzja dnia (`coach.next_session`)
i tydzień planu patrzą na HRV z dwóch stron — rano status Garmina dla jednej
sesji, przy przebudowie własna baza 60 d dla objętości tygodnia; to dwa poziomy,
nie dubel. `rc.active_plan` przekazuje `daily`, więc automatyczna przebudowa
po zmianie startów też ocenia reakcję.

**Przegląd wstecz po 9 (2026-10-28):** dryf liczony z okrążeń daje na Twoich
długich biegach −5…+6% (18.10: +0,8%), więc próg 5% rozróżnia realne przypadki.
Długość samego długiego biegu dalej rośnie z `_volumes` niezależnie od dryfu —
wstrzymanie długości przy dryfie to kandydat do 8b (ten sam sygnał postępu co EF).

**Przegląd wstecz po 10 (2026-10-28):** generator na 9 punktach Twojej historii
nie łamie żadnej reguły (także po 1–9). Realność 26% mówi, że plan zakłada
ciągłość, której w danych nie było — kandydat do 11: start planu po przerwie
(dziś `no_running` tylko ostrzega) i/lub mniejszy pierwszy krok po przerwie.

**Przegląd wstecz po 11 (2026-10-28):** każda liczba w `plan.py` ma w docstringu
etykietę [S] źródło / [C] konwencja / [H] heurystyka; test pilnuje, że szczyt
objętości i długi bieg nie spadną poniżej tego, co prognoza uznaje za pełne
przygotowanie. Heurystyki zostają heurystykami — najsłabsze to udział długiego
biegu (42–50% przy 3–4 dniach) i granice faz.

**Przegląd wstecz po 8b, 12, 13, 14 (2026-10-28):** wysyłka na zegarek obejmuje
teraz siłę — licznik zmian przy przycisku na stronie Plan liczy ją razem z
biegami. Do sprawdzenia przez użytkownika: pierwszy wysłany trening siłowy
i pierwszy bieg z celem tętna na zegarku (format z biblioteki, nie z próby).

## Czeka na zgodę

Języki inne niż polski i angielski. Nic nie jest implementowane, dopóki
użytkownik nie zgodzi się wprost.

_(pusto)_
