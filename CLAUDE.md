# Garmin dashboard — kontekst dla Claude Code

Lokalny pipeline: Garmin Connect → surowy JSON → parquet → Streamlit na
`localhost:8501`. Dane zdrowotne jednej osoby, wszystko zostaje na dysku.

## Układ

```
garmin-dashboard/
  config.py          ścieżki, rejestr metryk, throttle, okno re-fetchu
  etl/fetch.py       API → data/raw/<metryka>/<YYYY-MM-DD>.json
  etl/load.py        raw → data/tables/*.parquet (jawne mapowanie pól)
  etl/run.py         przyrostowa aktualizacja (wejście dla Dashboard.command/.cmd)
  etl/login.py       odświeżenie tokenów hasłem (raz na rok / po zmianie hasła)
  serve.py           start serwera z launcherów: streamlit run app.py + lifecycle
  lifecycle.py       lokalnie serwer gaśnie N min po zamknięciu ostatniej karty
  sync.py            pobieranie w tle: przycisk w szynie + automat co N h
  analytics.py       modele fizjologiczne i statystyka -> tabele pochodne
  db.py              DuckDB in-memory z widokami na parquet
  theme.py           system wykresów: paleta, buildery, mapy, glob
  shell.py           wspólny stan stron: dane, zakres czasu, style
  bento.py           siatka stron: kafle, KPI, panele (układ każdej strony)
  insights.py        parser notatek z insights/
  glossary.py        słownik pojęć: co to jest, po co, jak czytać (pomoc na stronach)
  i18n.py            język interfejsu (pl/en): tr(pl=, en=), plural, miesiące, tytuły stron
  glossary_en.py     angielski tekst słownika pojęć (te same klucze co glossary.TERMS)
  app.py             router (st.navigation) — bez logiki widoków
  routing.py         rejestr stron: przejście z widoku do widoku bez reloadu
  globe.py           opakowanie komponentu globu (dane + motyw + klik)
  globe_component/   statyczny komponent: index.html, globe.js, world.json,
                     vendor/ (d3-geo, d3-array), test.html (podgląd renderera)
  views/             po jednym module na stronę (atlas, routes, form, ...);
                     run_*.py to grupa „Bieganie”
  running/           logika modułu biegowego (bez Streamlita): klasyfikacja,
                     prognoza, plan, biblioteka treningów (`library.py`),
                     magazyn celów, brief dla asystenta
  tests/             unittest: `.venv/bin/python -m unittest discover -s tests -t .`
  insights/*.md      wnioski: proza + bloki SQL liczone na żywo
  data/raw/          źródło prawdy (nie usuwać — odbudowa tabel bez API)
  data/tables/       daily.parquet, activities.parquet
  data/coach/        zawody, plany i segmenty wpisane przez biegacza (JSON, poza gitem)
```

Python: `.venv` w katalogu repo — `.venv/bin/python` na macOS (główna maszyna,
Python 3.13 z Homebrew) i Linuxie, `.venv/Scripts/python.exe` na Windowsie (3.12+). `garminconnect` to zwykła zależność
z `requirements.txt`, nie editable install z sąsiedniego repo.

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

## Uruchamianie lokalne

`Dashboard.command` / `Dashboard.cmd`: `serve.py` w tle → przeglądarka. **Launcher
nie pobiera danych** (chyba że dostanie argumenty, np. `--backfill` — wtedy
`etl/run.py` w oknie przed startem). Pobieranie to `sync.py`: przycisk „Pobierz
z Garmina” w szynie (`shell.footer`) i wątek startowany przez `serve.py`, który co
10 min sprawdza, czy ostatnia próba jest starsza niż `GARMIN_AUTO_FETCH_H` h
(launchery: 6; nieudana sieciowo — po 30 min; wygasły token — po pełnym odstępie).
Oba odpalają `etl/run.py` jako osobny, odłączony proces (log `data/fetch.log`),
więc przeżywa idle-exit serwera. `etl/run.py` bierze `data/fetch.lock` (O_EXCL, pid)
i zapisuje próbę w `data/fetch.json` (`started_at`, `finished_at`, `code`); fragment
w szynie odpytuje blokadę co 3 s w trakcie i co 60 s poza nim, a po końcu robi
pełny rerun — nowy build sam unieważnia cache.
Serwer **nie chodzi w nieskończoność**: `lifecycle.py` liczy aktywne sesje
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

## Zapytania

```bash
.venv/bin/python -c "import db; print(db.query('SELECT * FROM daily ORDER BY day DESC LIMIT 5').to_string())"
```

Pełna lista kolumn: `.venv/bin/python db.py`.

## Tabela `daily` (jeden wiersz = jeden dzień kalendarzowy)

Kluczowe kolumny i ich znaczenie:

| kolumna | znaczenie |
|---|---|
| `day` | data (TIMESTAMP, znormalizowana do północy) |
| `steps`, `distance_m`, `calories`, `active_calories` | aktywność dzienna |
| `intensity_moderate`, `intensity_vigorous` | minuty intensywności |
| `rhr`, `rhr_7d`, `hr_min`, `hr_max` | tętno spoczynkowe i skrajne |
| `sleep_h`, `sleep_deep_h`, `sleep_light_h`, `sleep_rem_h`, `sleep_awake_h` | długość snu i faz (godziny) |
| `sleep_score`, `sleep_qualifier` | ocena snu Garmina (0–100 / EXCELLENT…POOR) |
| `hrv_last_night`, `hrv_weekly`, `hrv_status` | HRV nocne, średnia 7d Garmina, status (BALANCED/UNBALANCED/LOW) |
| `hrv_baseline_low`, `hrv_baseline_high` | granice „zrównoważonego" zakresu HRV wg Garmina |
| `readiness`, `readiness_level`, `f_*` | training readiness i jego składowe (procentowy wkład czynnika) |
| `load_acute`, `load_chronic`, `load_ratio`, `load_ratio_status` | obciążenie 7d / 28d, ich iloraz (ACWR), ocena Garmina |
| `load_4w_*`, `load_balance_feedback` | rozkład obciążenia 4-tygodniowego na low/high aerobic/anaerobic |
| `vo2max`, `training_status` | VO2max (precyzyjny) i etykieta statusu (Productive, Maintaining…) |
| `bb_high`, `bb_low`, `bb_wake`, `bb_charged`, `bb_drained` | Body Battery |
| `stress_avg`, `stress_max`, `sleep_stress` | stres dzienny i podczas snu |
| `weight_kg`, `body_fat_pct`, `muscle_mass_kg` | pomiary wagi (często puste — brak wagi z BT) |

Kolumny wyliczane w ETL (nie z API):

- `*_roll7` / `vo2max_roll28` — średnia krocząca, `min_periods=3`
- `hrv_deviation`, `rhr_deviation` — odchylenie od własnej średniej 7d; **do
  porównań używaj ich, nie wartości bezwzględnych**
- `weekday`, `iso_week` (`2026-W42`), `month` (`2026-10`) — gotowe klucze grupowania

## Tabela `activities` (jeden wiersz = jeden trening)

Tempo jest zapisane jako ułamek minut (5.72 = 5:43). **Nigdy nie pokazuj go
w tej postaci** (ani w podpowiedzi wykresu — `%{y}` na serii tempa to błąd;
daj `customdata` z `units.fmt_pace`): kafelki przez `shell.pace`, tabele przez
`shell.pace_column` (każda tabela w kaflu, pod ikoną danych i wynik SQL i tak
przechodzi przez `theme.readable_paces`, które zamienia kolumny *pace*/*tempo*),
osie wykresów przez `scatter(pace_y=True)` / panel `"pace": True` /
`route_map(pace=True)` (pod spodem `theme.pace_axis`, szybciej = wyżej).

`activity_id`, `start_local`, `sport`, `distance_km`, `duration_min`,
`pace_min_km` (min/km, **mniej = szybciej**), `speed_kmh`, `avg_hr`, `max_hr`,
`training_load`, `te_aerobic`, `te_anaerobic`, `avg_power`, `norm_power`,
`cadence`, `hr_z1_s`…`hr_z5_s` (sekundy w strefach), `day`, `iso_week`.

`day` łączy się z `daily.day`.

## Pułapki w tych danych

- **Dzień bez zegarka wygląda jak dzień ze zerami** — `steps` bywa niskie, a
  `sleep_h`/`hrv_last_night` są NULL. Filtruj `WHERE sleep_h IS NOT NULL`, zamiast
  liczyć średnie po wszystkim.
- **Garmin dopisuje dane wstecz** przez kilka dni (`RECHECK_DAYS` w `config.py`),
  więc 2–3 ostatnie dni mogą się jeszcze zmienić.
- **`training_status` to etykieta z `trainingStatusFeedbackPhrase`**, nie z pola
  `trainingStatus` (tam jest nieprzejrzysty kod — jest w `training_status_code`).
- **HRV ma sens tylko względem własnej bazy.** Wartości bezwzględne różnią się
  międzyosobniczo o rzędy wielkości; `hrv_deviation` jest porównywalne w czasie.
- **`load_ratio` (ACWR)** liczy Garmin, nie my. Bywa NULL, gdy brak 28 dni historii.
- **Dni bez treningu nie istnieją w `activities`** — przy łączeniu z `daily` używaj
  `LEFT JOIN`, inaczej wycina się dni odpoczynku i wszystkie średnie są zawyżone.
- **Noce na cudzym nadgarstku** wyklucza `python -m etl.exclude <dzień>` (dzień =
  ranek, którym noc się kończy). Lista siedzi w `data/excluded_nights.json`
  (ręczna, jak `data/coach/`); `etl/load.py` przy każdej budowie zeruje w `daily`
  kolumny nocne (`sleep_*`, `hrv_*`, `readiness`, `f_*`, `rhr`, `bb_wake`…),
  ustawia `night_excluded` i pomija te noce w `sleep_stages`/`night_series`.
  Średnie Garmina z kolejnych dni (`hrv_weekly`, `rhr_7d`) nadal je zawierają.
- Surowe pliki `data/raw/` są źródłem prawdy: zmiany w mapowaniu testuj przez
  `etl/load.py` (odbudowa od zera, bez odpytywania API).

## Konwencje

- Nowy wniosek = nowy plik w `insights/` (patrz `/garmin-insight`) **i obok
  `<nazwa>.en.md`** z tym samym SQL-em, angielską prozą i aliasami kolumn
  (wzór: `_template.en.md`; test pilnuje pary). Nie dotykaj `app.py`, żeby
  dodać panel.
- Nowe pole z API: dodaj metrykę w `config.DAILY_METRICS`, zmapuj w `etl/load.py`,
  opisz tutaj w tabeli kolumn.
- To jest własne, prywatne repo aplikacji. Kod commituj normalnie; `data/`
  nigdy — to historia zdrowia i ślady GPS. Na serwer idą przez `scp`
  (patrz `DEPLOY.md`), nie przez gita.
- `~/.garminconnect/garmin_tokens.json` ma wartość hasła — nie wypisuj go
  w logach ani nie kopiuj do repo.

## Języki (`i18n.py`)

Interfejs jest po polsku (domyślnie) i po angielsku; przełącznik PL/EN na dole
szyny, wybór pamiętany w `data/ui.json`. **Każda nowa funkcja od razu w obu
językach** — tekst, który ktoś czyta, idzie przez `i18n.tr(pl=..., en=...)`
(oba argumenty obowiązkowe), rzeczownik przy liczbie przez
`i18n.plural(n, pl=(1, 2–4, 5+), en=(1, wiele))`, daty przez `i18n.day_month` /
`months()` / `weekdays()`, tytuł strony przez `i18n.page(url_path)`.

- Tłumaczenie stoi przy wywołaniu, nie w katalogu kluczy: f-string z liczbami
  zostaje jednym czytelnym zdaniem w każdym języku.
- `tr` liczy się w chwili wywołania — stała modułu zbudowana z `tr` zamarza
  w języku pierwszego importu. Tabele etykiet buduj w funkcji
  (`shell.activity_columns()`, `theme.sleep_stage_labels()`).
- W sesji trzymaj klucz, nie etykietę (`shell.WINDOWS`: `"90d"`, etykieta przez
  `format_func`), inaczej zmiana języka resetuje wybór.
- `url_path` stron zostają polskie w obu językach — to adresy.
- **Kody w danych zostają kodami.** `form_zone`, `quadrant`, `model`
  (analytics), typ treningu, pewność, decyzja dnia, status celu, fazy planu
  (`running/`) są zapisywane po polsku/ASCII i czytają je insighty SQL — widok
  tłumaczy je przy wyświetlaniu (`rc.kind_label`, `rc.confidence`,
  `rc.action_label`, `rc.race_label`, `rc.effort_label`…), nie zmieniaj ich
  w hurtowni.
- Słownik pojęć: polski w `glossary.TERMS`, angielski w `glossary_en.TERMS`;
  czytaj przez `glossary.term(key)`. Nowe hasło = wpis w obu plikach (test).
- Glob dostaje słowa przez `globe._text()`; `index.html` trzyma polskie
  wartości domyślne dla `test.html`.
- **Nic, co jest zapisywane, nie trzyma zdania w jednym języku.** Plan
  (`data/coach/plans/*.json`) ma przy sesji kod `text` (`{"key": "threshold",
  "reps": 4, "rep": 1.6}`), ostrzeżenia jako `{"key": ...}`; `kind_reason`
  w `run_sessions` to JSON z kodem (`text.reason_code`), `run_efforts.source`
  to `garmin`/`whole`/`stream`/`block`, `models.json` — kod powodu. Zdania
  składa `running/text.py` przy wyświetlaniu. `store.plan()` uzupełnia
  `title`/`main`/`purpose` w bieżącym języku, `store.save_plan` je usuwa.
  Plan sprzed kodów (polskie zdania) jest rozpoznawany przy pierwszym odczycie
  (`text.migrate_plan`) i zapisywany z powrotem; nierozpoznany opis zostaje
  jako `{"key": "custom", "pl": {...}}`.
- Proza liczona na bieżąco (`coach`, `forecast`, walidacja, CLI) idzie przez
  `tr`. Wynik cache'owany, który niesie zdania, ma język w kluczu cache
  (`rc._forecast`, `rc._auto_segments`). CLI mają `--lang`; bez niego obowiązuje
  język wybrany w aplikacji (`data/ui.json`). Testy przypinają polski
  (`tests/__init__.py`).
- Odcisk workoutu na zegarku (`garmin_workout.fingerprint`) liczy się z kodu
  `text`, nie z tytułu — zmiana języka nie podmienia wysłanych treningów.
- Parametry cache'owanych funkcji, od których zależy wynik, **nie mogą**
  zaczynać się od `_` — Streamlit ich nie hashuje (tak `_build` przez długi
  czas nie unieważniał cache po przebudowie hurtowni).
- `i18n.BILINGUAL` to moduły już w pełni dwujęzyczne; `tests/test_i18n.py`
  oblewa polski literał poza `pl=` (docstringi i linie z `# i18n: key` — nazwy
  kolumn — są pominięte). Po przetłumaczeniu modułu dopisz go do listy.
  Strażnik widzi tylko polskie znaki; „Zakres” bez ogonków przejdzie.
- **Kolejny język (trzeci i dalsze) nie wchodzi bez zgody użytkownika.** Gdy
  pojawi się potrzeba, nie implementuj — dopisz go do `TASKS.md` w sekcji
  „Czeka na zgodę” i zapytaj.
- Postęp tłumaczenia reszty aplikacji (etapy 2–4) jest w `TASKS.md`.

## Tabele pochodne (analytics.py)

Liczone po każdym `etl/load.py` (wywołuje je `fetch.rebuild`). Wszystkie
materializowane do parquet, więc dashboard, zakładka SQL i pliki insightów
czytają te same liczby.

| tabela | ziarno | zawartość |
|---|---|---|
| `pmc` | dzień | `ctl` (42 d), `atl` (7 d), `tsb` = CTL−ATL z dnia poprzedniego, `ramp_7d`, `acwr_rolling` (Gabbett), `acwr_ewma` (Williams), `form_zone`, `garmin_*` do porównania |
| `load_weekly` | tydzień ISO | `load_sum`, `monotony` (Foster: średnia/SD), `strain` = suma×monotonia, `sessions` + średnie HRV/RHR/sen |
| `critical_speed` | okno 90 d, co 7 d | `cs_ms`, `cs_pace_min_km`, `d_prime_m`, `r2`, `distances`, `pred_5k_s`, `pred_10k_s` |
| `riegel` | okno 180 d, co 14 d | `riegel_b` (wykładnik z `log t = log a + b·log d`) |
| `efficiency` | bieg | `ef` (metry na uderzenie serca, prędkość skorygowana o nachylenie), `ef_roll10/30`, `hr_per_kmh` |
| `correlations` | para + lag | `rho` (Spearman), `p`, `q` (Benjamini-Hochberg), `n`, `significant` dla lagów 0–7 |
| `acf` | metryka + lag | autokorelacja z 95% CI (statsmodels) |
| `changepoints` | metryka | wykryte przesunięcia bazy (segmentacja binarna, kara ~2·ln n) |
| `weekday_effects` | metryka + dzień | średnia, SD, `delta_vs_overall`, `kruskal_p` |
| `circadian` | noc | `bed_hour_cont` (ciągła przez północ), `wake_hour`, `midpoint_hour`, `midpoint_sd_30d` (odporny rozrzut 30 d: IQR/1,349), `is_weekend` |
| `sleep_regularity` | noc | `sri_pair`, `sri_30d` — Sleep Regularity Index z minutowego hipnogramu |
| `night_profile` | noc | `hr_min`, `hr_drop` (1. godzina minus minimum), `nadir_at_pct` (kiedy w nocy wypadło minimum tętna), `hrv_first_third`/`hrv_last_third`/`hrv_slope_per_h`, `bb_gain_per_h` + dołączone `sleep_score`, `readiness` |
| `intensity_distribution` | tydzień ISO | minuty i % w strefach HR, `easy/middle/hard_pct`, `model` (etykieta opisowa) |
| `quadrants` | dzień | `hrv_z`, `rhr_z` wobec bazy 60 d + `quadrant` (zregenerowany / obciążony / pobudzony / stłumiony) |

`data/tables/models.json` trzyma dopasowanie modelu Banistera (τ sprawności,
τ zmęczenia, k1, k2, R², `taper_days_to_peak`).

## Tabele surowe wewnątrzdobowe

| tabela | ziarno | zawartość |
|---|---|---|
| `sleep_stages` | segment hipnogramu | `stage` (deep/light/rem/awake), `start_local`, `end_local`, `minutes` |
| `night_series` | próbka nocna | `metric` ∈ {hr, hrv, body_battery, stress, restless}, `t_local`, `value` |
| `intraday` | próbka 3-min | `stress`, `body_battery`, `hour` — pełna doba (metryka `stress` w ETL) |

## Pułapki w analityce

- **`tsb` jest konstrukcją, nie pomiarem.** Zanim wyciągniesz z niego wniosek,
  sprawdź w `pmc`, czy strefy formy w ogóle różnią się medianą readiness.
- **`correlations`: czytaj `q`, nie `p`.** Przy ~500 testach kilkadziesiąt
  wyników z `p < 0.05` to oczekiwany szum. Brak istotnych par to realny wynik.
- **CS z dwóch dystansów to prosta przez dwa punkty** — zawsze sprawdzaj
  `distances` i `r2` razem.
- **EF rośnie też wtedy, gdy biegasz szybciej na wyższym tętnie.** Grupuj po
  przedziale tętna, zanim nazwiesz to postępem.
- **Model Banistera na ekonomii biegu ma u tego użytkownika niskie R².**
  Nie prezentuj `taper_days_to_peak` jako rekomendacji bez podania R².
- **SRI i `circadian` liczą się tylko dla nocy z hipnogramem** — starsze lata
  go nie mają, więc `n` bywa małe.
- **Dane wewnątrzdobowe mają krótką retencję po stronie Garmina.** Endpoint
  `get_all_day_stress` odpowiada dla każdego dnia, ale tablice `stressValuesArray`
  / `bodyBatteryValuesArray` są puste poza ostatnimi ~4,5 miesiącami: z 1233
  pobranych dni dane niesie 137 (od 2026-06-01). Tabela `intraday` i mapa doby są
  więc z założenia krótsze niż reszta hurtowni — to nie błąd mapowania. Podobnie
  hipnogramy (`sleep_stages`) istnieją dopiero od momentu, gdy zegarek zaczął je
  zapisywać.

## System wykresów (`theme.py`)

Każda figura w dashboardzie powstaje przez buildery z `theme.py`. Nie dodawaj
`px.*` ani `go.Figure` bezpośrednio w `app.py` — paleta, marginesy i hover
rozjadą się w ciągu jednego PR-a.

**Żadnych gradientów. Nigdy.** Ani w tle strony, ani w kaflach (także
„refleks” czy „połysk”), ani za globem, ani na canvasie globu, ani w
wykresach. Wszystko to jednolite kolory: czarna strona, grafitowe kafle
(`#1a1c20`), płaski ocean. Głębię dają krawędź, cień i odstęp — nie przejście
tonalne. Użytkownik odrzucał to trzy razy; nie proponuj gradientu jako
„ciekawego tła”.

Trzy reguły wymuszone strukturalnie:

1. **Żadnych tytułów wewnątrz figury.** Tytuł to nagłówek kafla (`bento.tile`) nad
   wykresem (`heading()`); tytuł plotly i legenda u góry walczą o ten sam pas
   i nachodzą na siebie.
2. **Żadnych podwójnych osi.** `timeseries` przyjmuje jedną oś wartości; dwie
   wielkości o różnej skali idą do `stacked_panels` (małe wielokrotności na
   wspólnej osi X). Dopasowanie dwóch skal Y jest arbitralne i zmyśla korelacje.
3. **Kolor według zadania**: tożsamość → paleta kategorialna (max 3 serie),
   wielkość → jedna rampa niebieska jasno→ciemno, biegunowość → niebiesko-czerwona
   z szarym środkiem, kategorie uporządkowane (fazy snu, strefy HR) → rampa
   porządkowa.

Buildery: `trend`, `range_bars`, `trail`, `hbars`, `timeseries`, `bars`,
`stacked`, `scatter`, `heatmap`, `stacked_panels`, `route_map`, `profile` (+ `geo_cells`/`geo_clusters` — binowanie punktów dla globu);
dekoratory `band`, `threshold`, `zero_lines`; wspólna legenda nad grupą wykresów
`key(...)`; render w kaflu przez `t.chart(fig, table=...)` (poza siatką:
`show(fig, table=..., note=...)`), który dokłada
bliźniaczy widok tabelaryczny.

**Domyślny idiom dla dziennej metryki to `trend`**, nie `timeseries`: dni jako
blade kropki, średnia krocząca jako jedyna wyraźna linia, osobista norma jako
szary pas, ostatnia wartość podpisana na końcu linii. Surowa seria narysowana
pełną linią (piła 90 odcinków + pomarańczowa średnia na wierzchu) to dokładnie
to, co sprawiało, że dashboard wyglądał jak arkusz z 2005 roku. Kolejne zasady:

- Zakres dnia (Body Battery min–max, okno snu) → `range_bars`; `clock=True`
  daje oś godzin z wieczorem u góry.
- Ranking kategorii (miejsca) → `hbars`, nie pionowe słupki z ukośnymi etykietami.
- Udział części w czasie przy > 30 okresach → `stacked` sam przechodzi w warstwy
  (`area`), bo 90 słupków ze szczelinami to kod kreskowy.
- Fazy snu → `sleep_stage_colors()`, intensywność → `intensity_colors()`
  (łatwo / środek / mocno). Pięć sąsiednich odcieni niebieskiego jest nie do
  odróżnienia — nie wracaj do `ordinal_colors` dla tych dwóch zbiorów.
- Daty na osiach są w języku interfejsu (`local_dates`, wołane przez buildery samo);
  wykres zbudowany ręcznie przez `go.Figure` trzeba przepuścić przez nie jawnie.
- Kafelki KPI (`bento.kpis`) porównują z `shell.week_before(frame)` i mają
  czwarte pole `delta_color`: `"inverse"` dla tętna spoczynkowego / stresu,
  `"off"` dla zmęczenia i ilorazów obciążenia.

Zachowania, które wyglądają jak magia, ale są celowe:

- `scatter` **porzuca kanał koloru**, gdy kolumna ma pokrycie < 60% — inaczej
  wykres robi się szary (NaN), a skala rozciąga się na kilku punktach.
- `threshold` **nie rysuje linii**, jeśli próg leży daleko poza zakresem danych —
  rozciągałby oś i spłaszczał wszystkie realne wartości.
- Rampy sekwencyjne są przycinane do kwantyli 5–95%, żeby pojedynczy odstający
  pomiar (postój na światłach w tempie 20 min/km) nie zjadł całej skali.
- Osie mają `automargin`; nie ustawiaj marginesów ręcznie.
- **Aplikacja jest zawsze ciemna, na czarnym tle**: `serve.py` (flagi
  `--theme.*`) i `.streamlit/config.toml` przypinają `theme.base = "dark"`.
  `theme.mode()` najpierw czyta przypięty motyw, dopiero potem
  `st.context.theme.type` — ten drugi zgłasza preferencję przeglądarki, co przy
  jasnym systemie dawało jasny CSS kafli pod białym tekstem ciemnego motywu.
  `theme.backgroundColor` to kolor *wnętrza* widżetów (tabele, popovery) =
  kolor kafla; czarną stronę maluje `shell.page_style`.

## Glob na stronie Atlas

Hero Atlasu nie jest figurą plotly — to własny komponent Streamlita
(`globe.py` + `globe_component/`). Powód jest wydajnościowy: obracający się
glob w plotly trzeba przerysowywać po stronie serwera, a `st.fragment(run_every=…)`
to pełny rerun, przebudowa figury i round-trip po websockecie **na każdą
klatkę**. Tutaj animacja jest w przeglądarce i serwer nie robi nic, dopóki
nikt nie kliknie.

Jak to jest poskładane:

- **Rzutowanie i klipowanie robi `d3-geo`**, zwendorowane w `globe_component/vendor/`
  (nigdy CDN — glob ma działać offline). To świadome cofnięcie własnej
  implementacji: przycięcie wielokąta do widocznej półkuli nie jest małym
  problemem. Kiedy kontur wychodzi poza tarczę, musi wrócić wokół horyzontu
  właściwą stroną, a ani „krótszym łukiem", ani „zgodnie ze zwrotem w miejscu
  przecięcia" nie jest poprawną regułą — Afryka i Eurazja to **jeden**
  wielokąt owijający ponad połowę horyzontu, więc pierwsza reguła wycina
  w kuli kliny (widoczne, gdy patrzysz od bieguna), a druga zalewa ją lądem.
- `globe_component/globe.js` trzyma tylko to, o czym d3 nie ma zdania:
  klastrowanie, animację (`requestAnimationFrame`, pętla zatrzymuje się, gdy
  nie ma czego animować) i obsługę myszy.
- `globe_component/world.json` — Natural Earth 110 m jako GeoJSON
  (MultiPolygon + MultiLineString), współrzędne do 0,01°, oczka < 1,2° wycięte
  (112 KB). Przeglądarka pobiera go raz i trzyma we własnym cache.
- **Mapa ciepła** (od ×14 w górę): glob zamienia starty na ślady GPS, każdy
  odcinek w jednej z 5 klas „ile różnych treningów tędy przeszło” (siatka 20 m,
  sąsiedztwo 3×3, żeby kilka metrów rozrzutu GPS nie rozbijało korytarza na
  równoległe nitki), z obwódką w kolorze tła. **Liczenie jest w przeglądarce**
  (`computeHeat` w `globe.js`): Python wysyła tylko listę wybranych
  `activity_id`, więc filtr sportu nie kosztuje serwera nic. Same ślady
  `globe.tracks_url` zapisuje raz na build do `globe_component/cache/`
  (gitignorowane — to te same ślady GPS co `data/`) jako statyczny plik
  (~400 KB, delta-kodowane inty 1e-5°), który przeglądarka trzyma w cache.
  Od ×4 (płaska mapa) glob przestaje się kręcić; siatka południków jest tylko na kuli.
- **Glob jest domyślnie widoczny**; przełącznik „Pokaż glob” w Atlasie zostaje,
  żeby dało się go schować.
- **Filtry nad globem**: *Kadr* (okolica / świat / miasta — `globe.place`
  dobiera zoom do kwantyli 4–96% śladów) i *Sport*. Strona *Trasy* nie ma już
  osobnej mapy gęstości — to jest ta mapa.
- **Strona *Trasy* nie ma wpisu w menu** (`st.Page(..., visibility="hidden")`):
  to szczegół jednej aktywności (mapa kolorowana metryką, profil, strumienie),
  otwierany klikiem w wiersz Dziennika (*Aktywności*), w trening na globie
  i przyciskiem „Mapa trasy” w *Treningu*; dla biegu ma powrót „Analiza
  treningu”. Jedyny widok szczegółów dla sportów innych niż bieg.
- **Zoom**: kółko myszy, pinch na touchpadzie (Chrome/Firefox: ctrl+wheel,
  Safari: `gesture*`), pinch dwoma palcami na ekranie dotykowym, dwuklik
  i przyciski + − ○; 1×–40000×. **Punkt pod kursorem zostaje pod kursorem**:
  `setZoom` po zmianie skali dociąga obrót, aż ten sam punkt wróci pod wskaźnik.
  (Wcześniej każde zdarzenie przenosiło środek na punkt pod kursorem — touchpad
  wysyła ich dziesiątki na sekundę, więc obraz skakał.) Klastry markerów mają
  **poziomy**: siatka (26 px w stopniach) zmienia się tylko przy podwojeniu
  zoomu, a każdy poziom dzieli komórki poprzedniego na pół — grupa rozpada się
  na swoje części, zamiast tasować się przy każdym zdarzeniu. W trakcie zoomu
  markery bledną (`markerAlpha`) i wracają ~0,2 s po ostatnim zdarzeniu, więc
  przejście między poziomami dzieje się pod przygaszeniem. Na płaskiej mapie
  start to adnotacja: kropka dla jednego treningu, małe kółko z liczbą dla grupy.
- **Od ×4 (`FLAT_ZOOM`) glob staje się płaską mapą**: Mercator w ramce
  z zaokrąglonymi rogami, skala w środku dopasowana do kuli (`s = R·cos φ`),
  więc przejście nie skacze. Pod spodem kafelki **OpenStreetMap**
  (`tile.openstreetmap.org`, bez klucza, z atrybucją w `index.html`) — przygaszone
  filtrem canvas w jasnym motywie, odwrócone w ciemnym. Rastrowe kafelki CARTO
  (`light_all`/`dark_all`) odpowiadają dziś obrazkiem „API KEY REQUIRED”, stąd
  OSM. Bez internetu płaska mapa pokazuje zwendorowany kontur lądu.
  Brakujący kafelek zastępuje najbliższy wczytany przodek (rozmyty na chwilę,
  zamiast błysku oceanu). Przeciąganie na płaskiej mapie idzie dokładnie za ręką.
- **Klik**: pojedynczy trening to link — Atlas od razu przechodzi na *Trasy*
  z tym `activity_id`. Skupisko to pytanie — dialog z listą treningów.
  Licznik `clicks` w wartości komponentu odróżnia nowe kliknięcie od tej samej
  wartości po rerunie; bez niego dialog otwierałby się w kółko.
- `globe.starts(frame, build)` — ładunek (jeden wiersz na aktywność, ~34 KB)
  jest `@st.cache_data` kluczowany **id builda hurtowni**, więc liczy się po
  nowych aktywnościach, a nie przy każdym rerunie.
- Nawigacja idzie przez `routing.py`, nie przez link do `/trasy`: link to
  przeładowanie przeglądarki i utrata globalnego zakresu czasu.

Podgląd renderera bez Streamlita (tak sprawdzasz artefakty — zrzut ekranu
z headless Chrome na konkretnym ujęciu):

```bash
.venv/bin/python -m http.server 8777 --directory globe_component
# http://127.0.0.1:8777/test.html?lat=85            (bieguny — tu wychodzą kliny)
# http://127.0.0.1:8777/test.html?lat=-85
# http://127.0.0.1:8777/test.html?lat=52&lon=21&zoom=12&theme=dark
# ?zoom=250&tracks=cache/tracks-<build>.json  (płaska mapa + mapa ciepła; tiles=off bez kafelków)
# ?pinch=1                                    (tytuł strony = dryf punktu pod kursorem)
# ?from=&to= zawęża ląd do wycinka wielokątów (bisekcja po wadliwym)
```

## Trasy GPS

`etl/fetch.py` pobiera `get_activity_details` na aktywność (jeden request,
payload się nie zmienia, więc pobrany raz zostaje na zawsze) do
`data/raw/details/<activity_id>.json`. `etl/load.py` rozpakowuje je do tabel
`routes` (punkt trasy: `lat`, `lon`, `elevation_m`, `hr`, `speed_ms`,
`pace_min_km`, `distance_km`, `cadence`, `power`) i `route_summary`
(bounding box, przewyższenie liczone na wygładzonym profilu).

Mapy wymagają internetu — kafelki idą z CARTO/OpenStreetMap. Zoom liczy się
z bounding boxu po wzorze Web Mercatora dla kafli 512 px (MapLibre); stała
„na oko" zostawia trasę jako kropkę na środku mapy.

`route_map` rysuje **linie, nie punkty** — i to jest wymóg, nie styl:

- `route_map` koloruje sam ślad: każdy odcinek dostaje odcień wartości
  z jego początku (7 traców, bo plotly koloruje linię per trace). Markerów
  nie ma, bo ciąg kropek rozjeżdża się przy przybliżaniu na oddzielne
  koraliki; pod spodem leży szeroka, blada linia spinająca kształt, a hover
  siedzi na **niewidocznej** warstwie markerów (`opacity=0`), żeby wartości
  dało się odczytać punkt po punkcie bez stawiania kropek z powrotem.
- Mapa wszystkich śladów naraz żyje na globie w Atlasie (patrz wyżej). Wcześniej
  była tu mapa plotly z półprzezroczystymi liniami — po przybliżeniu rozpadała
  się na blade nitki zlewające się z ulicami podkładu, stąd liczenie przebiegów.
- Podkład map plotly idzie za motywem: `carto-darkmatter` w ciemnym (jasny raster
  w ciemnym kaflu wyglądał na wklejony zrzut), `carto-positron` w jasnym.
  `route_map` dobiera paletę do podkładu; na ciemnym rampa zaczyna się od 3.
  stopnia, bo dwa najciemniejsze toną w kafelkach mapy.

## Układ aplikacji

`app.py` jest wyłącznie routerem: strony to `st.Page` wskazujące na
`views/<nazwa>.render`. Dodanie strony = nowy moduł w `views/` + wpis w `PAGES`
(z własnym `url_path`, bo wszystkie funkcje nazywają się `render` i inaczej
kolidują ścieżkami).

Zasady układu, które trzymają spójność:

- **Siatka bento (`bento.py`) na każdej stronie — pływające widgety.** Kanwa
  (czarne tło, jednolite grafitowe karty z cieniem) to mozaika na siatce 4 kolumn. Kafel
  zajmuje 1–4 kolumny (`bento.row(2, 2)`, `row(2, 1, 1)` — suma zawsze 4)
  i 1–3 rzędy (`bento.tile(..., rows=2)`). **Kafle nie mają stałej wysokości**
  (stała wysokość = ucięta treść albo przewijanie w środku); rzędy wyrównuje
  CSS w `shell.page_style`: kolumny rzędu rozciągają się do najwyższej, kafle
  rosną (`flex: 1 0 auto` — nigdy nie kurczą się poniżej treści). `rows` ustala
  wysokość wykresu (`bento.chart_height`), dobraną tak, że wykres 2-rzędowy
  z chrome = dwa kafle 1-rzędowe. Szkielet strony: `bento.header` → pasek KPI
  → mozaika → panele. Klucze kontenerów: `wgt_` kafel, `wgthd_` jego nagłówek,
  `kpi_` liczba, `pnl_` panel — CSS wybiera po tych prefiksach.
- **Tabela w kaflu nigdy się nie przewija**: `t.table(df)` pokazuje tyle
  wierszy, ile mieści się w miejscu wykresu (`table_rows`), dokładnie na ich
  wysokość; reszta jest pod ikoną tabeli w nagłówku.
- **Ruch** (CSS, `page_style`): kafle wjeżdżają rząd po rzędzie i kolumna po
  kolumnie (zmienne `--row-delay`/`--col-delay`), wykres odsłania się od lewej
  (kierunek czasu) w chwili, gdy Plotly go narysuje, liczby KPI osiadają na
  końcu; najechanie podnosi kartę i pokazuje ikony nagłówka. Streamlit trzyma
  DOM między rerunami, więc animacja gra tylko przy wejściu na stronę.
  `prefers-reduced-motion` wyłącza wszystko.
- Pułapki CSS: Streamlit daje blokom markdown `margin-bottom: -1rem` — tekst
  w `<div>` (podpis, lista) wylewa się wtedy z kafla, dlatego `page_style`
  zeruje ten margines dla `.tile-caption/.tile-list/.tile-title`; podpis
  podciąga się ujemnym marginesem na **kontenerze elementu**, nigdy na tekście.
  Grupa śladów Plotly to `.cartesianlayer .overplot` (nie `.plot`).
- **KPI zawsze po 4**: `bento.kpis(row, previous, specs)` dla kolumn `daily`
  (podpowiedź z `glossary.FIELDS`), `bento.stat(...)` dla innych liczb,
  `bento.empty_stat` na brakujący slot.
- **Oś czasu dostaje co najmniej 2 kolumny.** Kafel 1-kolumnowy to liczba,
  krótka lista (`bento.bullets`), `theme.spark` albo wykres bez osi czasu.
  Kafel 1-rzędowy mieści jeden wykres — dwa panele `stacked_panels` wymagają
  `rows=2`.
- **Kafel ma własne chrome**: tytuł, jednozdaniowy `caption` (dzisiejsza liczba
  i jej status albo *po co* jest kafel), a w nagłówku ikony „?” (`terms` +
  `how=` — opis znaczników wykresu idzie tu, nie do podpisu) i tabeli danych
  (`t.chart(fig, table=...)`). Kontrolki sterujące jednym kaflem (wybór nocy,
  metryki) idą do `with t.header:` z `label_visibility="collapsed"`, żeby nie
  zjadały wysokości wykresu; przejście na inną stronę to ikona strzałki tamże.
  `t.chart` nadpisuje wysokość figury (`bento.chart_height`).
- **Formularze, edytory, długie tabele i proza → `bento.panel`**: ten sam
  wygląd, wysokość według treści (Plan, Zawody, SQL, Insights, Słownik).
- Nowy wskaźnik = nowe hasło w `glossary.py` (co / po co / jak czytać);
  `tests/test_glossary.py` pilnuje, że każdy klucz z `terms=[...]` istnieje.
  Wszystko widać też na stronie *Słownik*. Tytuł nigdy nie idzie do figury.
- *Dziś* (`views/today.py`) jest stroną startową: decyzja dnia to
  `coach.next_session`, przyciski kafla wołają `plan.soften` / `plan.postpone`
  (pojedyncza sesja, z regułą „mocne dni nie sąsiadują”).
- Glob w *Atlasie* zostaje poza kaflem (hero na pełną szerokość w `globe_stage`,
  na płaskim tle — bez poświaty), reszta Atlasu to zwykła mozaika.
- **Chrome w szynie bocznej**: nawigacja, jeden globalny zakres czasu
  (`shell.range_picker`) i status hurtowni (`shell.footer`). Kanwa nie
  rezerwuje miejsca na kontrolki.
- **Dane tylko przez `shell.table/query/daily/clip`** — cache jest kluczowany
  znacznikiem builda, więc przebudowa tabel sama unieważnia widok.

## Fragmenty i stan mapy

Bloki z własnymi kontrolkami (eksplorator tras, mapa doby, heatmapa korelacji,
ACF, dzień tygodnia) są oznaczone `@st.fragment`: zmiana ich widżetu przelicza
tylko ten blok, nie całą stronę.

Mapy dostają `uirevision`:

- ślad trasy — `f"route-{activity_id}"`, więc **zmiana kolorowanej metryki
  zachowuje zoom i przesunięcie**, a zmiana aktywności świadomie je resetuje;

Glob nie ma `uirevision`, bo nie jest figurą plotly — jego kąt żyje w JS
(patrz wyżej).

Jeśli dodajesz mapę, ustaw `uirevision` na coś, co zmienia się dokładnie wtedy,
gdy reset widoku jest pożądany. Bez tego każdy rerun wyrzuca użytkownika z powrotem.

## Moduł biegowy (`running/`, strony `views/run_*`)

Grupa „Bieganie” w nawigacji: przegląd, prognoza wyników, plan treningowy,
zawody i cele, szczegóły treningu, segmenty, obciążenie biegowe. Cała logika siedzi
w pakiecie `running/` (czyste pandas, testowane); strony tylko rysują.

Tabele (materializuje je `analytics.main` przez `running.pipeline.build`):

| tabela | ziarno | zawartość |
|---|---|---|
| `activity_segments` | aktywność + faza | `splitSummaries` z ETL: `INTERVAL_WARMUP/ACTIVE/RECOVERY/COOLDOWN` (workout z zegarka), `RWD_*` |
| `run_laps` | bieg + okrążenie | z ETL: `distance_m`, `duration_s`, `pace_min_km`, `avg_hr`, `cadence` (×2), `intensity` (warmup/active/recovery/rest/cooldown), `step_index` |
| `run_sessions` | bieg | kolumny `activities` + `kind` (recovery/easy/long/tempo/threshold/intervals/race), `kind_reason`, `kind_confidence`, `hr_max_used` |
| `run_splits` | bieg + km | splity ze strumienia próbek (czas stopera `duration_s`), tętno, przewyższenie, kadencja (kroki obu nóg) |
| `run_efforts` | bieg + dystans | najlepsze odcinki (1 km…maraton, blok workoutu), źródło, `vdot`, `hr_frac`, `near_max` |
| `run_forecast` | tydzień + dystans | migawka prognozy liczona tylko z danych sprzed dnia: `realistic_s`, `low_s`/`high_s` (80%), `potential_s`, `garmin_s`, `vdot`, `prep` |

Model prognozy (szczegóły w docstringu `running/forecast.py`):

- Waluta to **VDOT Danielsa** (krzywe sprawdzone testem z tabelami książki).
- Kotwica: najlepszy wysiłek z 120 dni; **bliski maksymalnego** = start albo
  ≥ 91% HRmax przez ≥ 6 min na tym odcinku strumienia. Odcinek treningowy
  poniżej tego progu to *dolna granica* — przedział jest wtedy asymetryczny.
  Starsze wysiłki maksymalne (do roku) tracą 0,3%/tydz. po 4 tygodniach.
- Tętno ↔ tempo (Swain, %HRR ≈ %VO₂R) jest **systematycznie zaniżone** u tego
  użytkownika (~33 vs ~40) — dlatego wchodzi jako *trend* od ostatniego
  wysiłku (waga rośnie z wiekiem kotwicy), a poziom tylko poszerza przedział.
- Garmin nie wchodzi do punktu, tylko do niepewności.
- Korekta wytrzymałościowa: `(D/d_kotwicy)^(0.08·(1−prep))`, `prep` z długiego
  biegu, objętości i regularności względem `REQUIREMENTS`. 5 km nigdy nie
  ekstrapoluje się na maraton bez tego podatku.
- Strona Prognoza ma **sprawdzenie wstecz**; na danych z 2026-10 mediana
  błędu ≈ 10% — szerokość przedziału jest uczciwa, nie ostrożnościowa.

Pułapki:

- **Żaden bieg nie jest oznaczony jako start** (`eventType` zawsze
  `uncategorized`). Start wpisany na stronie Zawody i powiązany z aktywnością
  dostaje `kind = race` po przeliczeniu (`running.pipeline.rebuild`).
- **HRmax to trzecie najwyższe maksimum biegów** (192), bo 201/196 to skoki
  czujnika. Etykiety typu treningu zależą od niego.
- **Splity kilometrowe są ze strumienia ~400 próbek**: dokładność kilku sekund.
  `directRunCadence` liczy jedną nogę — mnożone ×2 (tak samo kadencja okrążeń).
- **Okrążenia** (`get_activity_splits`, raz na bieg → `data/raw/splits/`, tabela
  `run_laps`) są jedynym dokładnym zapisem odcinków workoutu. Auto-lap tnie
  powtórzenie 1,2 km na 1000 + 200 m, więc powtórzenie = kolejne okrążenia
  `active` z tym samym `step_index` (`plan.rep_blocks`). Bieg bez okrążeń
  warmup/recovery nie był workoutem z zegarka i nie ma powtórzeń.
  `plan.match(..., laps=)` dokłada do sesji jakości `reps_planned/done/on_pace`
  (±3% od pasma) i `rep_paces`. Definicja odcinka jest jedna: `running/workouts.py`
  (`reps` — odcinek ze splitami i przerwą po nim, `summary` — rozjazd tempa
  i tętna, `history`/`peers` — workouty jakościowe ≥ 2 odcinków, podobne przy
  długości odcinka ±35%, `vs_hr_s` — odległość od prostej tempo ~ tętno
  odcinków z 2 lat przed treningiem). `plan.rep_blocks` to tylko jego widok.
- **Endurance score, hill score i próg mleczanowy (tempo/tętno) są u tego
  użytkownika puste** (sprawdzone 2026-10-25; jest tylko przestarzałe FTP
  biegowe). Nie dodawaj ich do hurtowni, dopóki zegarek ich nie liczy.
- Tempo/próg wymaga też **tempa** bliskiego M/T dla VDOT z tego dnia; wysokie
  tętno przy spokojnym tempie (upał) zostaje biegiem spokojnym z adnotacją.
- `data/coach/` to stan wpisany ręcznie — nie da się go odbudować z `raw/`.
  Przy przenoszeniu na serwer kopiuj razem z resztą `data/`.

Ta sama trasa i prywatne segmenty (`running/segments.py`, strony *Trening*
i *Segmenty*) — porównanie biegów bez okrążeń z zegarka, tylko z GPS:

- **Ta sama trasa** liczy się automatycznie: ślad zagęszczony do 10 m → komórki
  ~50 m; dwa biegi to jedna trasa, gdy każdy pokrywa ≥ 80% komórek drugiego
  (sąsiedztwo 3×3) i dystanse różnią się ≤ 15%. Kierunek bez znaczenia.
- **Segment** to odcinek wycięty suwakiem km z jednego biegu (punkty kontrolne
  co ~20 m) w `data/coach/segments.json` (`store.save_segment`). Przebieg =
  start i meta w promieniu 35 m, dystans 0,85–1,2× długości, każdy punkt
  kontrolny ≤ 40 m od śladu; kierunek ma znaczenie, bieg może przejść segment
  kilka razy. Tempo liczone na długości segmentu, czas ze strumienia (kilka s).
- **Wspólne odcinki** (`segments.shared`) to segmenty bez rysowania: dla
  otwartego biegu najdłuższy kawałek wspólny z każdym innym biegiem (cKDTree,
  ślady ≤ 35 m, ≥ 400 m, luki GPS do ~50 m mostkowane), o długości, jaka wyszła;
  mierzony na obu tym samym `passes`, więc kierunek się liczy. Δ tempa, Δ tętna
  i Δ efektywności (m/uderzenie) idą do kwadrantu „Szybciej czy mocniej?”;
  wiersz da się zapisać jako stały segment.
- **Segmenty auto** (`segments.frequent`, `rc.all_segments`): każdy punkt
  śladu liczy inne biegi ≤ 35 m w tym samym kierunku (cKDTree co 30 m);
  odcinki ≥ 500 m, gdzie nakłada się ≥ 4 biegów, są sprawdzane matcherem
  segmentów (całość od startu do mety, inaczej połowy) i zostają raz na
  korytarz, nigdy na zapisanym segmencie. Nie są zapisywane — liczą się po
  każdym buildzie (~1 s, cache); id to sha1 końców, nazwa to miasto z nazwy
  biegu + długość. „Zapisz jako mój” kopiuje go do `segments.json`.
- **Bieżnia i krótkie pętle** (`segments.is_loop`: cały bieg w ≤ 400 m,
  dystans ≥ 3× tyle) są wyłączone z każdego dopasowania GPS (`routable`):
  owal to jeden kłąb śladu, start i meta segmentu się pokrywają. Porównuje się
  je po dystansie zegarka — okrążenia i najlepsze odcinki.
- **Odcinki z interwałów jako segmenty** (`workouts.rep_efforts`,
  `rep_segments`, id `rep-<metry>`): każde powtórzenie workoutu trafia do
  standardowej długości (200 m…5 km, ±7%), niezależnie od miejsca; ranking po
  tempie, `seconds` = tempo × pełna długość. Tabela odcinków w *Treningu* ma
  ich miejsce, *Segmenty* — rekordy i szczegóły (bez mapy).
- **400 m / 800 m** (`sessions.SHORT_EFFORTS`, `short_efforts`) liczone w widoku
  ze strumienia, tylko do rekordów — nie do `EFFORT_DISTANCES`, bo VDOT z 400 m
  nic nie znaczy. `rc.all_efforts` = `run_efforts` + krótkie.
- Strona *Segmenty*: najpierw klikalne **rekordy na dystansach** i **rekordy
  odcinków z interwałów** (wiersz otwiera trening z rekordem), pod nimi lista
  segmentów jako `st.expander` (własne → auto → odcinki), z rekordem w etykiecie.
  Szczegóły (KPI, trend, ranking, mapa) rysują się tylko w rozwiniętym
  (`expander.open`, `on_change="rerun"`) — 26 wykresów z mapą naraz to kilka
  sekund. Klucz rozwinięcia to `run_segments.open_key(id)`: kafel
  **Dopasowane segmenty** w *Treningu* (GPS + powtórzenia) ustawia go
  i przełącza stronę, więc klik w wiersz otwiera ten segment.
- **Najlepsze odcinki** (jak best efforts Stravy) to `run_efforts` z miejscem
  w historii i w 365 dniach — bez nowej tabeli.
- Liczone w widoku, nie w ETL (`rc.paths` — ślady co 10 m raz na build,
  `rc.same_route`, `rc.shared`, `rc.segment_efforts`, cache kluczowany buildem
  i mtime pliku segmentów) — ułamki sekundy na całą historię.
- Kolumna tabeli z „tempo”/„pace” w nazwie i typem float przechodzi przez
  `readable_paces` jako m:ss — różnice tempa w sekundach nazywaj `Δ s/km`.

Plan i cele:

- **Plan jest jeden** (`store.current_plan`, zapis przez `store.save_only_plan`
  usuwa inne pliki) i prowadzi przez **wszystkie** nadchodzące starty z
  `races.json` (`plan["goals"]`). `plan.generate_goals` składa bloki: każdy
  start ma własny, budowany od miejsca, gdzie skończył się poprzedni; A — pełny
  taper dystansu, B/C — tylko lżejszy tydzień startu; po starcie A albo HM/M
  tydzień regeneracji. `request.race_date` to ostatni cel; najbliższy daje
  `plan.next_goal`.
- **Reguły tygodnia** (`plan._block_sessions`, stałe w `plan.py`): jeden akcent
  + długi bieg, drugi akcent dopiero przy 5+ dniach i 35+ km (`quality_count`);
  plan czyta biegi z 7 dni przed startem planu (`already_run`) — akcent/długi
  zrobiony w tym tygodniu zmniejsza przydział, akcent nie ląduje obok realnego
  mocnego dnia; długi ≥ 7 dni przed startem, akcent ≥ 4 dni; dzień przed
  startem rozruch tylko dla dnia biegowego przy 4+ dniach w tygodniu, inaczej
  wolne; po starcie bez akcentu/długiego przez 1 dzień na 3 km startu
  (`easy_days_after`, także w kolejnym bloku). Każda zmiana wzorca zostawia na
  sesji kod `why` (`text.why`) — strona Plan pokazuje go jako „Dlaczego tu”,
  a panel „Jak działa ten plan” wypisuje reguły z liczbami biegacza.
  `planned_km` tygodnia liczy też start.
- **Reguła pojedynczego biegu** (`plan._cap_spikes`, `SPIKE = 1.1`): żaden bieg
  planu nie jest dłuższy niż 1,1× najdłuższego z 30 dni przed nim — realne biegi
  sprzed startu planu + plan od startu; start się nie skraca, tylko liczy dalej.
  Źródło: Garmin-RUNSAFE (Frandsen i in., BJSM 2025) — skok pojedynczego biegu
  > 10% podnosił ryzyko kontuzji przeciążeniowej, iloraz tydzień/tydzień nie.
  **ACWR (1,3× średniej z 4 tyg.) nie jest już regułą ani sygnałem decyzji
  dnia** — zostaje jako liczba do oglądania (Forma, Obciążenie, słownik).
  Skrócona sesja ma `why: {"key": "spike"}`; `coach.spike_check` skraca poranną
  sesję, gdy realna historia jest krótsza, niż plan zakładał; `--validate`
  odrzuca ręcznie wpisany skok (`plan.spikes`).
- **Akcenty z biblioteki** (`running/library.py`, docstring ma źródła): rodzina
  (`threshold`, `intervals`, `hills`, `race_pace`, `tempo`) to drabinka
  szczebli, sufit pracy z objętości tygodnia (próg ≤ 10%, min. 20 min; interwały
  ≤ 8%, min. 12 min; tempo startowe HM/M ≤ 20%). Za szeroki szczebel traci
  powtórzenia, potem schodzi szczebel niżej. Licznik rodziny (`_progress`) idzie
  przez cały plan i przez `replan` (sesje z przeszłości); tydzień lżejszy =
  szczebel niżej, taper = obecny × 0,6. Przy jednym akcencie tygodnia typy
  rotują (`ROTATION`: slot A, slot B przy dwóch). `type` sesji to dalej
  `threshold`/`intervals`/`tempo` (dopasowanie do klasyfikacji biegów), rodzina
  siedzi w `text.key`. Przebieżki są krokami zegarka w obrębie dystansu biegu.
- **Siła** (`type: strength`, `distance_km: 0`, bez `steps` — na zegarek nie
  idzie): 2×/tydz. w bazie i budowie, 1× w szczycie, taperze i tygodniu lżejszym,
  0 w tygodniu startu; pierwsze 6 sesji `adapt`, potem `strength`/`maintain`/
  `light`. Licznik startuje od treningów `strength_training` z 120 dni
  (`plan.strength_done`). Najpierw dzień akcentu (po biegu), potem dzień
  spokojny, potem wolny; nigdy w przeddzień mocnego dnia, w dzień długiego
  i startu, ≤ 8 dni przed A (4 przed B/C), w dniach spokojnych po starcie.
  `postpone` przesuwa siłę razem z biegiem tego dnia, `soften` ją odwołuje
  (`rest_strength`), `match(..., activities=)` dopasowuje ją do aktywności
  siłowej z zegarka. Przełącznik w ustawieniach planu (`request.strength`).
- **Tydzień startu** (Bosquet 2007, Mujika): jeden krótki akcent 4–6 dni przed
  startem (`library.SHARPENER`, `text.sharpen`), spokojne biegi tego tygodnia
  ≤ 0,35× dystansu startu (4–8 km) — objętość przed startem ~40–60% szczytu.
- **Strefy tętna od progu** (`physio.threshold_hr`, `hr_zones`): LTHR = średnie
  tętno najmocniejszego wysiłku bliskiego maksymalnego 18–60 min z 120 dni
  (`run_efforts`; prognoza zwraca je jako `lthr`), strefy Friela jako % LTHR;
  bez takiego wysiłku — % HRmax jak dawniej. Plan zapisuje je w `plan["zones"]`.
  Przy LTHR kroki biegów spokojnych, regeneracyjnych i długich mają cel
  `"hr": [od, do]` zamiast `pace` (`garmin_workout`: `heart.rate.zone`), opis
  podaje tętno, tempo tylko orientacyjnie.
- **Szczebel drabinki z wykonania** (`plan.outcomes`, `_progress`): przy
  `replan` każda przeszła sesja jakości jest porównana z biegiem (`match` +
  okrążenia `run_laps`); rodzina idzie szczebel wyżej tylko, gdy sesja się
  odbyła, typ się zgadza, zrobione są wszystkie odcinki, ≥ ⅔ w paśmie tempa
  (±3%) i — dla progu — średnie tętno odcinków ≤ górna granica strefy T + 3 bpm.
  Inaczej szczebel stoi, a najbliższa sesja tej rodziny ma `why: rung_hold`
  z powodem (`missed` / `other_kind` / `short` / `off_pace` / `hr_high`).
  Pierwszy plan (bez przeszłości) liczy wszystko. Siła liczy się po dopasowaniu
  do aktywności siłowej z zegarka. Wywołujący `replan` podają `laps=` i
  `activities=` (bez nich okrążenia nie są sprawdzane).
- **Najbliższy tydzień według reakcji** (`plan.response`, przy `replan(...,
  daily=)` i nowym planie): HRV z 7 dni (średnia ln) poniżej bazy z 60 dni −
  0,5 SD, tętno spoczynkowe 7 d ≥ +3 bpm nad bazą, < 70% km z ostatnich 2 tyg.
  przebiegnięte. Jeden sygnał → `hold` (drugi tydzień bez przyrostu), dwa →
  `lighter` (pierwszy tydzień lżejszy −25%, cykl lżejszych tygodni liczy się od
  niego). Decyzja w `plan["response"]`, na pierwszej sesji tygodnia `why:
  response`. Dalsze tygodnie zostają w rytmie 3–4 tyg. — przyszłej reakcji nie
  znamy, więc każda przebudowa decyduje na nowo.
- **Długi bieg z finiszem** (`library.LONG_FINISH`, rodzina `long_finish`):
  w szczycie HM/M odcinek w tempie startowym na końcu długiego biegu idzie po
  drabince (HM 3 → 8 km, M 6 → 14 km, ≤ 40% biegu). Szczebel rośnie, gdy bieg
  się odbył, a dryf tempo:tętno spokojnej części (`library.drift` z okrążeń,
  bez 1. km i bez finiszu) ≤ 5%; inaczej `rung_hold` z powodem `drift`.
- **Sprawdzenie planu wstecz** (`running/plan_check.py`, `python -m
  running.plan_check`, panel „Jak działa ten plan” przez `rc.plan_check`):
  generator w dniach co 4 tyg. z ostatnich 2 lat, z danych sprzed dnia, plan do
  półmaratonu za 12 tyg. Liczy złamane reguły (`RULES` — każda > 0 to błąd
  generatora) i realność: km pierwszych 4 tygodni vs to, co potem przebiegnięto.
  Na danych z 2026-10: 9 planów, 0 złamań, mediana realności 26% — przerwy
  w bieganiu, nie przeszacowany plan.
- **Prędkość krytyczna w planie** (`physio.critical_speed`, prognoza: `cs`) jest
  liczona tylko z czystych wysiłków bliskich maksymalnego 2–20 min (`block`,
  `whole`, start) z 90 dni, min. 2 o długości różnej ≥ 2×; `cap_threshold`
  przesuwa pasmo T tak, żeby nie było szybsze niż CS. Tabela `critical_speed`
  w hurtowni (strona Forma) to inna rzecz: najlepsze odcinki Garmina *wewnątrz*
  treningów, w interwałach razem z przerwami — zaniżona, nie do temp.
- **Dwa starty A < 8 tyg. od siebie** (`A_RACE_GAP_WEEKS`): ostrzeżenie
  `close_a_races` — plan nie wybiera sam, prosi o zmianę jednego na B.
- **Zmiana startów przebudowuje plan od jutra**: `rc.active_plan` porównuje
  cele planu z `races.json` (`plan.stale`) i woła `replan(..., goals=...)`
  (historia: `goals`). Strony wołają `rc.active_plan()` przed prognozą.
- **Cel na dzień startu** jest per start (`plan.race_outlook`): plan obejmuje
  start → `forecast.target` (`target_basis = "plan"`, przygotowanie z 8 tyg.
  przed startem, w pełni dopiero przy ≥ 6 tyg.); bez planu →
  `forecast.steady` („jak teraz”: dzisiejsze przygotowanie, przyrost × regularność,
  wygasa po ~6 tyg.) i strona Zawody poleca ułożenie planu.

Treningi na zegarek:

- Każda sesja planu ma `steps` (rozgrzewka / odcinki / przerwy / schłodzenie,
  `km` albo `s`, `pace: [szybciej, wolniej]`, `repeat` jeden poziom) — generowane
  z tych samych liczb co tekst `main`, walidowane przez `store.validate_steps`.
- `running/garmin_workout.py` zamienia sesję na JSON workoutu Garmina (cel tempa
  jako `pace.zone` w m/s, wolniejsze tempo = `targetValueOne`) i liczy
  `sync_actions`: upload / replace / remove. `pydantic` nie jest zależnością,
  więc nie używamy typowanych modeli z `garminconnect.workout`.
- `python -m etl.push_plan [id] [--days 7] [--dry-run]` albo przycisk na stronie
  Plan (tylko gdy są tokeny). Wysłane treningi są zapisane w `plan["garmin"]`
  (klucz: id sesji) — rejestr jest na poziomie planu, bo `replan` nadaje
  sesjom nowe id; dzięki niemu następna wysyłka usuwa stare workouty zamiast
  zostawiać duplikaty. Przeszłych dat nie rusza.

Współpraca z asystentem: nie ma tu API modelu i żadnego nie dodajemy.
`python -m running.coach [--json]` drukuje brief (prognoza z wejściami, biegi,
obciążenie, regeneracja, plan i realizacja, `data_gaps`), `--validate <id>`
sprawdza plik planu po edycji. Komenda `/trener` (`.claude/commands/trener.md`)
opisuje kontrakt dla Claude Code.
