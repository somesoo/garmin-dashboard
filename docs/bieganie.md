# Bieganie i sport: modele, plan, segmenty

Jak liczą się prognoza, plan, segmenty i propozycje. Pułapki są w `AGENTS.md`.

## Strefy tętna (`running/hrzones.py`, strona Konto)

Strefy Garmina to 50/60/70/80/90% HRmax (u tego użytkownika HRmax 196, z
artefaktu czujnika). **Nic w aplikacji ich nie czyta**: `hr_z*_s` Garmina zostają
w `activities` i jako `garmin_hr_z*_s` w `run_sessions`, a widoki, fakty,
`intensity_distribution` i kolory śladu biorą `zone_time`. Powód (sprawdzone
2026-11-04): stały % HRmax wrzuca różne osoby w różne domeny — Iannetta i in.
2020 (MSSE 52:466), Jamnick i in. 2020 (Sports Med 50:1729), Mann i in. 2013
(Sports Med 43:613).

- **Kotwice**, w tej kolejności: wpisane z testu na Koncie (`<osoba>/zones.json`:
  `lthr`, `vt1`, `hr_max`, `method`, `measured`; w `tenant.OWNED`) → z danych
  (`physio.threshold_hr`, `robust_hr_max`) → szacunek z Esteve-Lanao i in. 2026
  (Sports 14:29, 1411 biegaczy: VT2 93,5 ± 2,5%, VT1 85,1 ± 4,6% HRpeak, stąd
  LTHR ≈ 0,935·HRmax, VT1 ≈ 0,91·LTHR). Szacunek jest tak oznaczony (`*_source`).
- **Bez danych nie ma stref** — żadnego 220 − wiek ani stałej (Apple: bez rekordu
  i daty urodzenia `hr_max_estimate` zwraca None).
- Granice Z2…Z5: 85% LTHR, VT1, 95% LTHR, LTHR (Friel dla 85/95%).
  Trzy domeny Seilera: Z1–2 < VT1, Z3–4 między progami, Z5 ≥ LTHR.
- `zone_time` liczy LTHR z dnia aktywności (120 dni wstecz); wpisane kotwice
  obowiązują dla całej historii. Trening bez strumienia tętna nie ma stref
  (NaN), poza Apple, którego podział liczy `etl/apple.py` z tych samych kotwic.
- `analytics.zone_tables` liczy `zone_time`, `intensity_distribution` i strefy
  w `run_sessions` — woła je i `analytics.main`, i `running.pipeline.rebuild`
  (po powiązaniu startu), inaczej `run_sessions` wraca do podziału Garmina.
- **Znacznik builda (`built_at`) przesuwa się dopiero po analityce**
  (`load.mark_built` na końcu `fetch.rebuild` i `pipeline.rebuild`): `load.main`
  stempluje stan po tabelach bazowych, a strona otwarta w trakcie analityki
  zapamiętywała w cache stare tabele pochodne pod nowym kluczem.
- Zapis na Koncie przelicza tabele bez pobierania (`etl/fetch.py
  --rebuild-only` przez `sync.request_rebuild`); plan bierze nowe strefy po
  „Przebuduj od jutra”.

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
| `run_splits` | bieg + km | splity ze strumienia próbek (czas stopera `duration_s`), tętno, przewyższenie, kadencja (kroki obu nóg), `stop_s` (stanie na tym km) |
| `run_stops` | bieg + postój | postoje ≥ 5 s ze stoperem w ruchu: `km`, `seconds`, `at_s`, `lat`/`lon`; w `run_sessions` suma `stop_s` (z krótkimi) i liczba `stops` |
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
- **Postoje (światła) są zbierane, nie korygowane** (`sessions.stops`, decyzja 2026-11-01).
  Biegacz nie używa autopauzy, więc stanie siedzi w czasie stopera. Postój = Δ`duration_s` − Δ`moving_s`
  między próbkami (zegarek liczy ruch co sekundę, więc rzadkie próbki nie gubią krótkich postojów).
  Widok pokazuje go obok tempa: KPI, splity, segmenty (`passes` → `stop_s`), wspólne odcinki. Tempo,
  VDOT, prognoza i plan zostają na czasie stopera. W interwałach przerwa na stojąco też jest postojem.
  Analiza, czy przejść na tempo w ruchu do porównań: insight `2026-11-01-postoje-na-biegach`.
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
- **Siła** (`type: strength`, `distance_km: 0`, bez `steps`): 2×/tydz. w bazie i budowie, 1× w szczycie, taperze i tygodniu lżejszym,
  0 w tygodniu startu; pierwsze 6 sesji `adapt`, potem `strength`/`maintain`/
  `light`. Licznik startuje od treningów `strength_training` z 120 dni
  (`plan.strength_done`). Najpierw dzień akcentu (po biegu), potem dzień
  spokojny, potem wolny; nigdy w przeddzień mocnego dnia, w dzień długiego
  i startu, ≤ 8 dni przed A (4 przed B/C), w dniach spokojnych po starcie.
  `postpone` przesuwa siłę razem z biegiem tego dnia, `soften` ją odwołuje
  (`rest_strength`), `match(..., activities=)` dopasowuje ją do aktywności
  siłowej z zegarka. Przełącznik w ustawieniach planu (`request.strength`).
  Na zegarek idzie jako trening siłowy Garmina (`sportType` 5): ćwiczenia
  etapu z `library.STRENGTH_PROGRAMMES`, nazwane jak w katalogu
  `garminconnect.exercises` (`resolve` — test pilnuje, że każde istnieje),
  jedna grupa powtórzeń na ćwiczenie (serie × powtórzenia/czas + odpoczynek).
  ID typów jak w `garminconnect.workout`; format sprawdzony testem i
  `--dry-run`, nie na zegarku.
- **Tydzień startu** (Bosquet 2007, Mujika): jeden krótki akcent 4–6 dni przed
  startem (`library.SHARPENER`, `text.sharpen`), spokojne biegi tego tygodnia
  ≤ 0,35× dystansu startu (4–8 km) — objętość przed startem ~40–60% szczytu.
- **Strefy tętna od progu** (`physio.threshold_hr`, `hr_zones`): LTHR = mediana
  średniego tętna 3 najmocniejszych wysiłków bliskich maksymalnego 18–60 min
  z 120 dni (`LTHR_TOP`; jeden upalny dzień nie ustawia stref na 4 miesiące).
  **Bez takiego wysiłku w 120 dniach** obowiązuje ostatni zmierzony próg
  (`stale`, `age_days`) do roku (`LTHR_KEEP_DAYS`), dopiero potem szacunek z
  HRmax — przerwa w treningu nie przestawia stref skokiem. Gdy próg planu (górna
  granica T) różni się od dzisiejszego o ≥ 3 bpm (`plan.threshold_shift`),
  `rc.active_plan` przebudowuje plan od jutra (`replan(threshold=...)`, `why:
  new_threshold`, w historii `action: threshold`) — także po wpisie z Konta.
  (`run_efforts`; prognoza zwraca je jako `lthr`, a wpisane na Koncie — z
  `source: "manual"`), E kończy się pod VT1, reszta jak strefy Friela (% LTHR);
  bez takiego wysiłku — LTHR szacowane z HRmax (`basis: "hr_max"`, patrz
  „Strefy tętna”). Plan zapisuje je w `plan["zones"]`.
  Przy LTHR (zmierzonym albo wpisanym) kroki biegów spokojnych, regeneracyjnych i długich mają cel
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
  Czwarty sygnał (`plan.efficiency_signal`): mediana EF spokojnych biegów
  (easy/long/recovery) ze średnim tętnem w strefie E, 28 d vs 56 d wcześniej,
  spadek ≥ 3% — chyba że ostatnie biegi były ≥ 5 °C cieplejsze. Wzrost EF jest
  raportowany, ale nigdy nie przyspiesza planu.
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
- **Skoki w realnej historii**: `plan.spike_table` (każdy bieg, najdłuższy z 30 dni,
  limit 1,1×) — kafel „Skoki pojedynczego biegu” na stronie Obciążenie biegowe
  (hasło `spike_rule`), `plan.real_spikes` w briefie. Iloraz 7/28 d zszedł do
  osobnego rzędu na dole strony.
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

## Moduł sportowy (`sport/`, strony `views/sport*.py`)

Grupa „Sport”: *Gotowość i propozycje* (`sport`) i *Dyscypliny* (`dyscypliny`).
Logika w czystym pandas, testy w `tests/test_sport.py`; plan biegowy jest tylko
czytany (`recommend.from_plan`), nigdy zmieniany.

- **Katalog** (`catalog.py`): ~30 dyscyplin z ręcznymi wagami 0–1 — `load`
  (uderzenia / nogi / góra), `trains` (tlen, moc, siła, technika, mobilność),
  `levels` (najlżej–najmocniej uczciwie), `needs`, `months`. Garminowe typy
  (`kiteboarding_v2`…) mapuje `discipline_of`. Kody są danymi, słowa dają
  `label`/`blurb`/`*_label`.
- **Gotowość** (`readiness.assess`): średnia ważona sześciu części w jednej
  skali (~65 = zwykły dzień): readiness Garmina i HRV (×1,5; z ln HRV wobec 60
  nocy), RHR wobec mediany 60 d, sen, obciążenie 7/28 d **wszystkich** sportów
  (`training_load`, brak = 1/min), godziny od mocnego treningu. Progi 68/52/38 →
  hard/moderate/easy/recover; dwie części nocne < 35 przycinają do easy; noc
  starsza niż doba wypada. `systems`: zmęczenie układów z 4 dni, zanik
  wykładniczy (τ 24–30 h), 1,0 ≈ typowa sesja przed chwilą.
- **Ranking** (`recommend.rank`): sezon, warunki i sufit intensywności to
  filtry (`skipped` z powodem); reszta to punkty z kodami w `reasons` (dni od
  ostatniego razu, dominacja w 28 d, luki profilu z `variety.TARGET`, kolizja
  ze zmęczonym układem, jutrzejszy kluczowy bieg → nogi ≤ moderate). Jitter ±3
  stały w obrębie dnia.
- **Realizm, którego użytkownik wprost wymagał**: główne propozycje (`picks`)
  tylko z dyscyplin już uprawianych, po jednej z rodziny; „coś nowego” tylko bez
  wyjazdu. `catalog.TRAVEL` (woda, wiatr, śnieg, góry) jest domyślnie wyłączone
  — zaznacza się na dni wyjazdu; reszta warunków domyślnie z historii roku
  (`store.default_available`), wybór w `data/sport.json`. Sezony pod Warszawę:
  woda V–IX, rolki IV–X, MTB III–XI. Nie proponuj kajaka w październiku.
- Przy dniu ≥ moderate mobilność/joga to **dodatek**, nie główna sesja.
- Zdania z kodów składa `sport/text.py` (przecinek dziesiętny po polsku).

Współpraca z asystentem: nie ma tu API modelu i żadnego nie dodajemy.
`python -m running.coach [--json]` drukuje brief (prognoza z wejściami, biegi,
obciążenie, regeneracja, plan i realizacja, `data_gaps`), `--validate <id>`
sprawdza plik planu po edycji. Komenda `/trener` (`.claude/commands/trener.md`)
opisuje kontrakt dla Claude Code.
