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
  analytics.py       modele fizjologiczne i statystyka -> tabele pochodne
  db.py              DuckDB in-memory z widokami na parquet
  theme.py           system wykresów: paleta, buildery, mapy, glob
  shell.py           wspólny stan stron: dane, zakres czasu, nagłówki
  insights.py        parser notatek z insights/
  app.py             router (st.navigation) — bez logiki widoków
  routing.py         rejestr stron: przejście z widoku do widoku bez reloadu
  globe.py           opakowanie komponentu globu (dane + motyw + klik)
  globe_component/   statyczny komponent: index.html, globe.js, world.json,
                     vendor/ (d3-geo, d3-array), test.html (podgląd renderera)
  views/             po jednym module na stronę (atlas, routes, form, ...)
  insights/*.md      wnioski: proza + bloki SQL liczone na żywo
  data/raw/          źródło prawdy (nie usuwać — odbudowa tabel bez API)
  data/tables/       daily.parquet, activities.parquet
```

Python: `.venv` w katalogu repo — `.venv/bin/python` na macOS (główna maszyna,
Python 3.13 z Homebrew) i Linuxie, `.venv/Scripts/python.exe` na Windowsie (3.12+). `garminconnect` to zwykła zależność
z `requirements.txt`, nie editable install z sąsiedniego repo.

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
- Surowe pliki `data/raw/` są źródłem prawdy: zmiany w mapowaniu testuj przez
  `etl/load.py` (odbudowa od zera, bez odpytywania API).

## Konwencje

- Nowy wniosek = nowy plik w `insights/` (patrz `/garmin-insight`). Nie dotykaj
  `app.py`, żeby dodać panel.
- Nowe pole z API: dodaj metrykę w `config.DAILY_METRICS`, zmapuj w `etl/load.py`,
  opisz tutaj w tabeli kolumn.
- To jest własne, prywatne repo aplikacji. Kod commituj normalnie; `data/`
  nigdy — to historia zdrowia i ślady GPS. Na serwer idą przez `scp`
  (patrz `DEPLOY.md`), nie przez gita.
- `~/.garminconnect/garmin_tokens.json` ma wartość hasła — nie wypisuj go
  w logach ani nie kopiuj do repo.

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

Trzy reguły wymuszone strukturalnie:

1. **Żadnych tytułów wewnątrz figury.** Tytuł to nagłówek Streamlita nad
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
`key(...)`; render przez `show(fig, table=..., note=...)`, który dokłada
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
- Daty na osiach są po polsku (`polish_dates`, wołane przez buildery samo);
  wykres zbudowany ręcznie przez `go.Figure` trzeba przepuścić przez nie jawnie.
- Kafelki (`shell.metrics`) porównują z `shell.week_before(frame)` i mają
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
- Paleta ma dwa warianty (jasny / ciemny) wybierane po `st.context.theme.type`.
  Wartości przeszły walidator ze skilla `dataviz` dla obu powierzchni.

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
  Powyżej ×6 glob przestaje się kręcić, a od ×28 znika siatka południków.
- **Filtry nad globem**: *Kadr* (okolica / świat / miasta — `globe.place`
  dobiera zoom do kwantyli 4–96% śladów) i *Sport*. Strona *Trasy* nie ma już
  osobnej mapy gęstości — to jest ta mapa.
- **Zoom**: kółko myszy i dwuklik (oraz przyciski + − ○), 1×–3000×, kotwiczony
  w punkcie pod kursorem (`projection.invert`). Promień kuli rośnie z zoomem,
  a klaster markerów jest przeliczany tak, żeby markery nie nachodziły na
  siebie: siatka to tyle stopni, ile przy obecnym promieniu ma 26 px. Dlatego
  przy przybliżaniu miasto rozpada się na parki, a w końcu na pojedyncze
  treningi.
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
- Ślady na mapach plotly biorą paletę **jasną** w obu motywach (`LIGHT`), bo
  podkład CARTO jest zawsze jasny; ciemna rampa kończy się prawie bielą.

## Układ aplikacji

`app.py` jest wyłącznie routerem: strony to `st.Page` wskazujące na
`views/<nazwa>.render`. Dodanie strony = nowy moduł w `views/` + wpis w `PAGES`
(z własnym `url_path`, bo wszystkie funkcje nazywają się `render` i inaczej
kolidują ścieżkami).

Zasady układu, które trzymają spójność:

- **Jedna kolumna.** Wykresy dostają pełną szerokość kanwy; `st.columns`
  wyłącznie na paski liczb (`shell.metrics`) i parę kontrolek obok siebie.
  Dwa wykresy obok siebie ścinają oś czasu i zmuszają do skakania wzrokiem.
- **Każda sekcja = `shell.lead(tytuł, zdanie)`** — zdanie mówi, jak czytać to,
  co pod nim. Tytuł nigdy nie idzie do figury (patrz `theme.py`).
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
