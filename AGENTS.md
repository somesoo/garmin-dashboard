# Garmin dashboard — zasady i pułapki

Lokalny pipeline: Garmin Connect / Apple Health → surowy JSON → parquet →
Streamlit na `localhost:8501`. Dane zdrowotne, wszystko zostaje na dysku;
jeden serwer może obsłużyć kilka osób.

Tu są tylko **zasady** (czego pilnować) i **pułapki** (co wygląda na błąd,
a nim nie jest, albo odwrotnie). Jak co działa i dlaczego tak wyszło: `docs/`
(spis w `docs/README.md`).

## Układ

```
app.py  api.py  serve.py   punkty wejścia: Streamlit (router), HTTP obok dashboardu, launcher
core/       platforma bez widoków: config, tenant (osoby), auth (kto patrzy), i18n,
            db (DuckDB), sync (pobieranie w tle), lifecycle (idle-exit), monitor (Admin)
etl/        API → data/raw → parquet: fetch, load, run, apple, apple_push, schema,
            analytics (tabele pochodne), login, garmin_auth, exclude, push_plan
analysis/   liczby i zdania dla stron (czyste pandas): facts, hero (strona Dzień),
            summary (JSON dla telefonu), insights (parser notatek)
running/    logika biegowa (bez Streamlita): sesje, prognoza, plan, biblioteka,
            segmenty, strefy tętna (hrzones), brief dla asystenta
sport/      pozostałe dyscypliny (bez Streamlita): katalog, gotowość, ranking
ui/         wspólne klocki stron: shell (stan, dane, style), bento (siatka), story
            (nagłówek, pętla, górna linia), theme (wykresy), guide, routing, globe,
            herochart, webapp, glossary(+_en); components/ — statyczne komponenty JS
views/      po jednym module na stronę (run_* = grupa „Bieganie”, hubs = dwa widoki pod jednym wpisem)
pwa/        aplikacja na telefon; tools/ — skrypty pomocnicze; deploy/ — serwer
insights/   wnioski: proza + SQL liczony na żywo (para .md + .en.md)
tests/      unittest
data/       NIGDY w gicie: raw/ (źródło prawdy), tables/, coach/, users/<id>/
```

**Kierunek zależności**: `views → ui → analysis → running/sport → core`;
`etl` korzysta z `core` i `running`. `core` nie importuje widoków (wyjątek:
`core.auth` leniwie bierze styl ekranu logowania z `ui.shell`). `analysis`,
`running`, `sport`, `etl` **nie importują Streamlita** — to czyste pandas,
testowane bez serwera. Moduły importuj z pakietem: `from core import tenant`,
`from ui import shell` (korzeń repo jest na `sys.path`).

## Polecenia

```bash
.venv/bin/python -m unittest discover -s tests -t .      # testy (Windows: .venv/Scripts/python.exe)
.venv/bin/python etl/load.py                             # odbudowa tabel z data/raw, bez API
.venv/bin/python etl/analytics.py                        # same tabele pochodne
.venv/bin/python -m core.tenant [init|add|migrate|list|admin|remove]
.venv/bin/python -m core.auth setup https://<adres>
.venv/bin/python -m core.db                              # lista kolumn wszystkich tabel
.venv/bin/python -c "from core import db; print(db.query('SELECT * FROM daily ORDER BY day DESC LIMIT 5').to_string())"
```

Python: `.venv` w repo (macOS — główna maszyna, Python 3.13; Linux; Windows 3.12+).
`garminconnect` to zwykła zależność z `requirements.txt`.
Na Windowsie 3 testy padają zawsze (uprawnienia 0600, blokada pliku tymczasowego) —
to nie regresja.

## Konwencje

- Własne, prywatne repo: kod commituj normalnie; `data/` **nigdy** (historia zdrowia,
  ślady GPS). Na serwer dane idą przez `scp` (`docs/DEPLOY.md`).
- Tokeny Garmina (`~/.garminconnect/`, `data/users/<id>/garmin/`) mają wartość
  hasła — nie wypisuj ich w logach, nie kopiuj do repo.
- Nowy wniosek = plik w `insights/` (`/garmin-insight`) **i** `<nazwa>.en.md`
  z tym samym SQL-em i aliasami kolumn (wzór `_template.en.md`; test pilnuje pary).
  Nie dotykaj `app.py`, żeby dodać panel.
- Nowe pole z API: metryka w `config.DAILY_METRICS`, mapowanie w `etl/load.py`,
  wpis w tabeli kolumn w `docs/dane.md`. Wspólne kolumny obu źródeł: `etl/schema.py`.
- Nowa strona: moduł w `views/` + wpis w `PAGES` w `app.py` (z własnym
  `url_path` — wszystkie funkcje nazywają się `render`) + pytanie i linki „Dalej”
  w `ui/guide.py` (test pilnuje). `url_path` zostają polskie w obu językach.
- `app.py` jest wyłącznie routerem — żadnej logiki widoków.
- Nowy wskaźnik na stronie = hasło w `ui/glossary.py` **i** `ui/glossary_en.py`
  (co / po co / jak czytać); test pilnuje kluczy z `terms=[...]`.
- `data/coach/` (starty, plany, segmenty) i `zones.json` są wpisane ręcznie —
  nie da się ich odbudować z `raw/`; kopiuj razem z resztą `data/`.
- Plan dalszych etapów i postęp tłumaczenia: `TASKS.md`.

## Wiele osób

- **Ścieżki osoby tylko przez funkcje**: `config.raw()`, `tables()`, `state_file()`,
  `excluded_nights()`, `tokenstore()`, `store.races_path()` / `plans_dir()` /
  `segments_path()`, `sport.store.settings_path()`, `i18n.settings_path()`,
  `sync.lock_path()`. **Nie wracaj do stałych modułu** (`config.TABLES`) —
  liczyłyby się raz, dla pierwszej osoby. Nowy plik osoby → `tenant.OWNED`.
- **Kto jest bieżący**: `tenant.current()` (`with tenant.use(id)` → sesja Streamlita
  → `GARMIN_USER` → jedyna osoba). Kilka osób i nic z tego = `tenant.NoUser`,
  **nigdy** domyślna osoba. Tożsamość podana, ale nieznana = odmowa, bez
  przejścia na „lokalną”.
- **Cache**: każdy `@st.cache_data` dostaje `shell.build_id()` (`<id>@<built_at>`)
  w argumencie — nowa funkcja cache'owana też musi. Parametry, od których zależy
  wynik, **nie mogą** zaczynać się od `_` (Streamlit ich nie hashuje).
- **Dane tylko przez `shell.table/query/daily/clip`** — cache jest kluczowany
  buildem, więc przebudowa sama unieważnia widok.
- SQL jest zamknięty w `tables/` osoby (`db.connect`: `allowed_directories`,
  `enable_external_access = false`, `lock_configuration`) — nie luzuj tego.
- Pliki serwowane przeglądarce mają w nazwie `User.file_key(...)` (HMAC) —
  zgadywalna nazwa = wyciek i kasowanie cudzych plików przy sprzątaniu.
- Insighty to proza o liczbach jednej osoby — tylko dla `"insights": true`.
- Osoba Apple nie ma przycisku „Pobierz”; timer pobierania chodzi tylko po `source: garmin`.
- Strona Admin: **żadnych danych zdrowotnych**; przeliczenia/pobrania **jedno
  naraz** (serwer ma 1 GB RAM). Dla nie-admina strona nie jest rejestrowana.
- Dane w kształcie Apple Watcha bez zegarka: `tools/synthetic_watch.py` → osoba
  `demo`. **Nigdy** do katalogu prawdziwej osoby.
- Testy zamykają cały przebieg w tymczasowym rejestrze (`tests/__init__.py`);
  własna osoba: `tests.helpers.person()` / `people({...}, current=...)`.

## Języki (`core/i18n.py`)

- **Każda nowa funkcja od razu w obu językach**: tekst przez `tr(pl=..., en=...)`
  (oba obowiązkowe), liczba z rzeczownikiem przez `plural(n, pl=(1, 2–4, 5+), en=(1, wiele))`,
  daty przez `day_month` / `months()` / `weekdays()`, tytuł strony przez `page(url_path)`.
- Tłumaczenie stoi przy wywołaniu (f-string zostaje jednym zdaniem), nie w katalogu kluczy.
- `tr` liczy się w chwili wywołania — **stała modułu z `tr` zamarza** w języku
  pierwszego importu. Tabele etykiet buduj w funkcji.
- W sesji trzymaj klucz, nie etykietę (etykieta przez `format_func`).
- **Kody w danych zostają kodami** (`form_zone`, `quadrant`, `model`, typ treningu,
  pewność, decyzja dnia, status celu, fazy planu). Czytają je insighty SQL;
  widok tłumaczy przy wyświetlaniu (`rc.kind_label`, `rc.confidence`…).
- **Nic zapisywanego nie trzyma zdania w jednym języku**: plan ma kody `text`
  i `{"key": ...}`, `kind_reason` to JSON z kodem; zdania składa `running/text.py`.
  `store.save_plan` usuwa `title`/`main`/`purpose`.
- Wynik cache'owany, który niesie zdania, ma język w kluczu cache. CLI mają `--lang`.
  Testy przypinają polski.
- Odcisk workoutu na zegarku liczy się z kodu `text`, nie z tytułu.
- `i18n.BILINGUAL` = moduły w pełni dwujęzyczne; `tests/test_i18n.py` oblewa
  polski literał poza `pl=` (pominięte: docstringi, linie z `# i18n: key`).
  Po przetłumaczeniu modułu dopisz go do listy. Strażnik widzi tylko polskie znaki.
- **Trzeci język nie wchodzi bez zgody użytkownika** — dopisz do `TASKS.md`
  („Czeka na zgodę”) i zapytaj.

## Wykresy (`ui/theme.py`)

- Każda figura przez buildery `theme.py` (`trend`, `range_bars`, `trail`, `hbars`,
  `timeseries`, `bars`, `stacked`, `scatter`, `heatmap`, `stacked_panels`,
  `route_map`, `profile`; dekoratory `band`, `threshold`, `zero_lines`; legenda
  `key(...)`). **Żadnego `px.*` ani `go.Figure` w widokach.** Wyjątki to dwa
  komponenty JS: glob i wykres główny (`herochart`) — Plotly nie umie tekstu na
  marginesie z linią do punktu.
- **Żadnych gradientów. Nigdy.** Ani w tle, ani w kaflach („refleks”, „połysk”),
  ani za globem, ani w wykresach. Jednolite kolory; głębię daje krawędź, cień,
  odstęp. Użytkownik odrzucał to trzy razy — nie proponuj.
- **Żadnych tytułów w figurze** — tytuł to nagłówek kafla.
- **Żadnych podwójnych osi** — dwie skale → `stacked_panels`.
- **Kolor według zadania**: tożsamość → kategorialna (max 3 serie), wielkość →
  jedna rampa niebieska, biegunowość → niebiesko-czerwona z szarym środkiem,
  kategorie uporządkowane → porządkowa. Fazy snu → `sleep_stage_colors()`,
  intensywność → `intensity_colors()` (nie `ordinal_colors`).
- Dzienna metryka → `trend` (kropki dni + średnia krocząca + szary pas normy),
  nie surowa linia. Zakres dnia → `range_bars`; ranking → `hbars`.
- **Tempo nigdy jako ułamek minut** (5.72 ≠ 5:43): kafelki `shell.pace`, tabele
  `shell.pace_column`, osie `scatter(pace_y=True)` / panel `"pace": True` /
  `route_map(pace=True)`; w podpowiedzi `customdata` z `units.fmt_pace`, nigdy
  `%{y}`. Różnice tempa w sekundach nazywaj `Δ s/km` (kolumna z „tempo”/„pace”
  w nazwie przechodzi przez `readable_paces`).
- Daty na osiach w języku interfejsu (`local_dates`); ręczne `go.Figure` przepuść jawnie.
- Nie ustawiaj marginesów ręcznie (`automargin`).
- Mapy dostają `uirevision` zmieniające się dokładnie wtedy, gdy reset widoku
  jest pożądany (ślad trasy: `route-{activity_id}`).
- `route_map` rysuje **linie, nie punkty** (hover na niewidocznych markerach).
- Aplikacja jest **zawsze ciemna** (motyw przypięty w `serve.py` i
  `.streamlit/config.toml`); `theme.mode()` czyta najpierw przypięty motyw.

Zachowania celowe (nie „naprawiaj”):

- `scatter` porzuca kanał koloru przy pokryciu < 60%.
- `threshold` nie rysuje linii daleko poza zakresem danych.
- Rampy są przycinane do kwantyli 5–95%.

## Strony i układ

- Strona = nagłówek-wniosek (`facts.py`: tylko to, co się wydarzyło, wobec
  własnej normy; **nic nie radzi**) + pętla + jeden wykres główny + „Szczegóły”.
  Co zrobić, mówi wyłącznie *Dziś* (`coach.next_session`).
- Siatka bento: 4 kolumny, `bento.row(...)` sumuje się do 4; kafel bez stałej
  wysokości; **oś czasu ≥ 2 kolumny**; dwa panele `stacked_panels` wymagają `rows=2`.
- **KPI zawsze po 4** (`bento.kpis` / `stat` / `empty_stat`); `delta_color`
  `"inverse"` dla RHR/stresu, `"off"` dla zmęczenia i ilorazów.
- Tabela w kaflu nigdy się nie przewija (`t.table`); formularze, edytory,
  długie tabele i proza → `bento.panel`.
- **Tabele przez `ui/tables.py`, nie `st.dataframe`** (siatka w ramce, kolumna
  checkboksów, ucięta kolumna na telefonie): `tables.show` (tylko do czytania),
  `tables.pick` (dotknięcie wiersza; `sticky=True`, gdy wiersz steruje mapą obok),
  `tables.chooser` (jedna aktywność z wielu: karta warstwowa + lista, bez pola
  tekstowego). Wyjątek: Notatnik SQL.
- **Nic nie wysuwa klawiatury bez pola do pisania**: wybór z listy przez
  `tables.chooser`; `ui/gesture.py` daje selectboxom `inputmode="none"` na dotyku.
- **Bieg ma jedną stronę** (*Trening*: Przegląd z mapą · Splity · Wykresy ·
  Porównanie · Segmenty, jak w Stravie/Garmin Connect). *Trasy* pokazują tylko
  aktywności inne niż bieg; `routing.open_activity` kieruje bieg do *Treningu*.
  Mapę i tabelę splitów dają `routes.map_tile` / `routes.split_table` — nie kopiuj.
- **Strona z wieloma pytaniami → zakładki** (`st.tabs`, wzór: *Trening*): nad
  nimi wybór i 4 KPI, w każdej zakładce jedno pytanie; zakładka bez danych nie
  powstaje. Telefon przełącza je przesunięciem palca (`ui/gesture.py`).
- **Wykres śpi do podwójnego dotknięcia / dwukliku** (`ui/gesture.py` + `.armed`
  w `page_style`): przewijanie ani pojedyncze dotknięcie nie zoomuje i nie
  przypina podpowiedzi; pojedyncze pokazuje tylko „dotknij dwa razy”. Nie zdejmuj tego przez `config` Plotly.
- Kontrolki jednego kafla → `with t.header:` z `label_visibility="collapsed"`;
  opis znaczników wykresu → `how=` w „?”, nie do podpisu.
- Kafle bez ramek; przyciski bez prostokątów (akcja główna `type="primary"`).
  Klucze kontenerów `wgt_`/`wgthd_`/`kpi_`/`pnl_` — CSS wybiera po prefiksach.
- Nawigacja przez `ui/routing.py` (`goto`, `goto_view`), nie linkiem — link to
  reload i utrata zakresu czasu. Strona domyślna ma `url_path == ""` — dlatego
  `routing.named` / `routing.name(page)`.
- Bloki z własnymi kontrolkami → `@st.fragment`.
- **Telefon to ta sama strona, krótsza** (`docs/interfejs.md` → „Telefon”).
  Układ robi CSS po szerokości okna (`@media (max-width: 760px)` w
  `page_style`), treść — Python po nagłówku żądania (`shell.phone()`).
  Zawijaj **tylko rzędy kolumn** (`:has(> [data-testid="stColumn"])`) — kontener
  poziomy musi zostać w linii. Pasek KPI na telefonie to jeden rząd czterech (bez notki i „?”).
  Nowa strona, która sypie kafle wprost (nie przez `story.frame_page`), oddaje
  drugi plan do `story.second(label, render, key=...)` — to **funkcja**, bo na
  telefonie treść nie ma się policzyć, dopóki nikt nie naciśnie „Szczegóły”.
  `?layout=phone` / `?layout=wide` wymusza układ do przeglądu.
- **Na telefonie nawigacja jest jedna: szuflada z lewej** (`ui/drawer.py`) —
  górna linia, pętla i „Dalej” ustępują jej miejsca. Nowa strona musi trafić
  do `drawer.EVERYDAY`/`drawer.LAB` albo do etapu pętli (`story.STAGE_PAGES`),
  inaczej z telefonu nie da się do niej dojść (test pilnuje). Widżet (zakres,
  język, pobranie, wylogowanie) stoi **albo** w szufladzie, **albo** w górnej
  linii — nigdy w obu, bo dwa widżety na jednym kluczu to wyjątek Streamlita.
  Na biurku szuflada jest **dodatkowo** obok górnej linii, ale tylko z linkami
  (widżety zostają w górnej linii). CSS szuflady (`shell.drawer_style`) idzie
  przez `st.html` z samym `<style>` — w szynie przegrałby z `display: none`
  z `page_style`, bo szyna stoi w DOM przed stroną.
- Komponenty JS obsługują **zdarzenia wskaźnika, nie myszy**: `onmousemove`
  nigdy nie odpala na telefonie. Żaden handler odczytu nie woła
  `preventDefault` — palec, który zaczął na wykresie, musi przewinąć stronę.
- Streamlit trzyma DOM między rerunami — animacje grają tylko przy wejściu;
  `prefers-reduced-motion` wyłącza wszystko.
- Pułapki CSS: bloki markdown mają `margin-bottom: -1rem` (zerowane dla
  `.tile-caption/.tile-list/.tile-title`); ujemny margines podpisu na kontenerze
  elementu, nigdy na tekście. Grupa śladów Plotly to `.cartesianlayer .overplot`.
- Glob: `d3-geo` zwendorowane (`ui/components/globe/vendor/`), **nigdy CDN**;
  klipowania wielokątów nie pisz od nowa (Afryka+Eurazja to jeden wielokąt).
  Kafelki płaskiej mapy z OSM (CARTO raster chce dziś klucza). Podgląd bez
  Streamlita: `docs/interfejs.md` → „Glob”.

## Uruchamianie: pułapki

- **Launcher nie pobiera danych** (poza argumentami, np. `--backfill`); pobiera
  `core/sync.py` — przycisk w górnej linii i timer co `GARMIN_AUTO_FETCH_H` h,
  jako odłączony `etl/run.py` (blokada `fetch.lock`, zapis `fetch.json`).
- Lokalnie serwer **gaśnie sam** `GARMIN_IDLE_EXIT_MIN` min po ostatniej karcie
  (`core/lifecycle.py`); bez zmiennej (systemd) nic się nie zmienia.
- Serwer zostawiony przez zmianę kodu trzyma stare moduły i sypie
  `module 'shell' has no attribute …` — launchery wołają `serve.py --stop-if-stale`.
- **`built_at` przesuwa się dopiero po analityce** (`load.mark_built` na końcu
  `fetch.rebuild` i `pipeline.rebuild`) — inaczej cache łapie stare tabele
  pochodne pod nowym kluczem.
- `analytics.zone_tables` wołają i `analytics.main`, i `running.pipeline.rebuild`
  — inaczej `run_sessions` wraca do stref Garmina.
- Oficjalne API Garmina (Personal) **nie** zastępuje `garminconnect`: nie ma
  VO2max, readiness, statusu ani wysyłki treningów. Plan awaryjny — `docs/platforma.md`.
- **Ikona na ekranie telefonu bez paska adresu wymaga service workera**
  obejmującego `start_url` — sam manifest daje zakładkę z paskiem. Dashboard ma
  `pwa/dashboard-sw.js` (zasięg `/`, nagłówek `Service-Worker-Allowed` z `api.py`),
  aplikacja telefonowa `pwa/sw.js` (zasięg `/api/app/`). Cache dzielą po adresie,
  więc każdy kasuje tylko swój prefiks; po zmianie podbij `VERSION`.

## Pułapki w danych

- **Dzień bez zegarka wygląda jak dzień ze zerami** — `steps` niskie, `sleep_h`
  / `hrv_last_night` NULL. Filtruj `WHERE sleep_h IS NOT NULL`.
- **Garmin dopisuje dane wstecz** (`RECHECK_DAYS`) — 2–3 ostatnie dni mogą się zmienić.
- **`training_status`** to etykieta z `trainingStatusFeedbackPhrase`; kod jest w `training_status_code`.
- **HRV tylko względem własnej bazy** (`hrv_deviation`). Garmin = RMSSD, Apple
  Watch = SDNN — `hrv_kind` mówi którą; **dwie miary nigdy w jednej serii**.
  Teksty o normie przez `facts.hrv_norm_words`.
- **`load_ratio` (ACWR)** liczy Garmin; bywa NULL bez 28 dni historii.
- **Dni bez treningu nie istnieją w `activities`** — z `daily` łącz `LEFT JOIN`.
- **Noce na cudzym nadgarstku**: `python -m etl.exclude <dzień>` (dzień = ranek);
  `etl/load.py` zeruje kolumny nocne, ale `hrv_weekly`/`rhr_7d` Garmina je zawierają.
- `data/raw/` to źródło prawdy — zmiany mapowania testuj `etl/load.py`, nie API.
- Apple Health to pula wielu źródeł: sumy dzienne = **największa suma jednego
  źródła**, nie suma wszystkich; trening z dwóch aplikacji (±2 min) liczy się raz.
- **Dane wewnątrzdobowe mają krótką retencję u Garmina** (~4,5 mies.), hipnogramy
  istnieją od kiedy zegarek je zapisuje — krótsza `intraday` to nie błąd mapowania.

## Pułapki w analityce

- **`tsb` jest konstrukcją, nie pomiarem** — sprawdź, czy strefy formy różnią się medianą readiness.
- **`correlations`: czytaj `q`, nie `p`** (~500 testów).
- **CS z dwóch dystansów to prosta przez dwa punkty** — `distances` i `r2` razem.
  Tabela `critical_speed` (najlepsze odcinki *wewnątrz* treningów) jest zaniżona
  — nie do temp planu (plan używa `physio.critical_speed`).
- **EF rośnie też przy szybszym biegu na wyższym tętnie** — grupuj po przedziale tętna.
- **Banister ma niskie R²** — `taper_days_to_peak` nigdy bez R².
- **SRI i `circadian` tylko dla nocy z hipnogramem** — `n` bywa małe.

## Bieganie i sport: zasady i pułapki

- **Stref Garmina (% HRmax) nic nie czyta** — tylko `zone_time` (od LTHR/VT1,
  `running/hrzones.py`). **Bez danych nie ma stref**: żadnego 220 − wiek ani stałej.
  Szacunek z HRmax jest oznaczony (`*_source`).
- **HRmax = trzecie najwyższe maksimum biegów** (pojedyncze skoki czujnika).
- **Żaden bieg nie jest oznaczony jako start** (`eventType` zawsze `uncategorized`);
  `kind = race` daje dopiero powiązanie ze startem z `races.json`.
- **Postoje są zbierane, nie korygowane** (brak autopauzy) — tempo, VDOT,
  prognoza i plan zostają na czasie stopera.
- Splity km ze strumienia (~400 próbek) mają dokładność kilku sekund;
  `directRunCadence` to jedna noga (×2). Powtórzenie = okrążenia `active` z tym
  samym `step_index`; jedyna definicja odcinka: `running/workouts.py`.
- Endurance score, hill score, próg mleczanowy są u tego użytkownika puste —
  nie dodawaj do hurtowni, dopóki zegarek ich nie liczy.
- Tętno ↔ tempo (Swain) jest u tego użytkownika zaniżone — wchodzi do prognozy
  jako trend, nie poziom. Garmin wchodzi tylko do niepewności.
- **Plan jest jeden** (`store.current_plan`) i prowadzi przez wszystkie starty.
  Reguła pojedynczego biegu: ≤ 1,1× najdłuższego z 30 dni (Garmin-RUNSAFE).
  **ACWR nie jest regułą ani sygnałem decyzji** — tylko liczbą do oglądania.
  Każda zmiana wzorca zostawia na sesji kod `why`. Szczegóły reguł: `docs/bieganie.md`.
- `replan` dostaje `laps=` i `activities=` (bez nich okrążenia nie są sprawdzane).
- Wysłane treningi są w `plan["garmin"]` (rejestr planu, bo `replan` nadaje nowe id);
  przeszłych dat nie rusza. `pydantic` nie jest zależnością.
- Bieżnia i krótkie pętle (`segments.is_loop`) są wyłączone z dopasowań GPS.
- Sport: główne propozycje **tylko z dyscyplin już uprawianych**; wyjazdowe
  (`catalog.TRAVEL`) domyślnie wyłączone; sezony pod Warszawę — nie proponuj
  kajaka w październiku. Plan biegowy jest tylko czytany.
- Asystent: brak API modelu i żadnego nie dodajemy. Brief: `python -m running.coach
  [--json]`, walidacja `--validate <id>`, kontrakt `/trener`.
