# Dane: tabele i kolumny

## Korekta wysokości z NMT (opcjonalna)

`terrain.json` w katalogu osoby włącza korektę od lokalnej daty `since`.
Oryginalne JSON-y Garmina pozostają nietknięte. Starsze aktywności zachowują
dotychczasowe wartości, także przy kolejnej przebudowie. Osoby bez ustawienia
nie korzystają z korekty; obecnie obsługiwane jest źródło Garmin.

Źródło: [NMT GUGiK, usługa WCS](https://www.geoportal.gov.pl/pl/usluga/uslugi-pobierania-wcs/),
`DTM_PL-EVRF2007-NH`, układ poziomy EPSG:2180, siatka pobierana co 2 m.
Publiczne, stałe kwadraty 2 × 2 km z zakładką 2 m są przechowywane w
`data/terrain/gugik_nmt_evrf2007_2m_v1/`. Serwer pobiera kwadraty potrzebne
do nowych tras; GUGiK otrzymuje zasięg kwadratu, nigdy ślad GPS ani identyfikator
aktywności. Przeliczenie współrzędnych i interpolacja dwuliniowa odbywają się lokalnie.
NMT opisuje grunt: mosty, tunele i bieżnie wewnątrz budynków wymagają odrębnej
interpretacji. Korekta nie jest stosowana do aktywności bez śladu GPS.

| Tabela | Kolumny korekty |
|---|---|
| `routes` | `elevation_m` — wysokość terenu; `elevation_original_m` — zapis Garmina; `elevation_source` — kod źródła; `elevation_gain_cum_m`, `elevation_loss_cum_m` — narastające podejścia i zejścia |
| `activities`, `route_summary`, `run_laps` | `elevation_gain_m` — podejścia z NMT; `elevation_gain_original_m` — wcześniejsza wartość; `elevation_source` — kod źródła |

Podejścia liczone są ze wspólnego profilu: interpolacja co 10 m dystansu,
średnia pięciu próbek, suma dodatnich zmian. Okrążenia i splity dzielą narastającą
sumę po dystansie; mapa odczytuje tę samą sumę. Nie zmienia to czasu, tempa,
GPS ani wskaźników wysiłku Garmina. Starsze trasy nadal korzystają ze swojej
dotychczasowej metody. Etykieta wysokości na mapie i wykresie wskazuje NMT GUGiK.

Uruchomienie (jawnie wybrana osoba):

```bash
GARMIN_USER=<id> .venv/bin/python -m etl.terrain --since 2026-11-01 --prepare
GARMIN_USER=<id> .venv/bin/python etl/run.py --rebuild-only
```

Koordynator `fetch.rebuild` uzupełnia brakujące kafle przed budową tabel.
Sam `etl/load.py` używa wyłącznie cache’u i nie wysyła zapytań sieciowych.
Brak kafla, brak danych w NMT lub trasa poza Polską przerywają korektę przed
publikacją tabel zamiast mieszać wysokość terenową z zapisem zegarka.

Opis hurtowni: co jest w każdej tabeli. Zasady i pułapki są w `AGENTS.md`.

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

## Tabele pochodne (etl/analytics.py)

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
| `intensity_distribution` | tydzień ISO | minuty i % we własnych strefach (`zone_time`): `easy` = Z1–2 (< VT1), `middle` = Z3–4, `hard` = Z5 (≥ LTHR), `model` (etykieta opisowa) |
| `zone_time` | aktywność | sekundy w Z1–Z5 ze strumienia tętna w strefach z dnia aktywności (`zone_lthr`, `zone_vt1`, `zone_basis`) |
| `quadrants` | dzień | `hrv_z`, `rhr_z` wobec bazy 60 d + `quadrant` (zregenerowany / obciążony / pobudzony / stłumiony) |

`data/tables/models.json` trzyma dopasowanie modelu Banistera (τ sprawności,
τ zmęczenia, k1, k2, R², `taper_days_to_peak`).

## Tabele surowe wewnątrzdobowe

| tabela | ziarno | zawartość |
|---|---|---|
| `sleep_stages` | segment hipnogramu | `stage` (deep/light/rem/awake), `start_local`, `end_local`, `minutes` |
| `night_series` | próbka nocna | `metric` ∈ {hr, hrv, body_battery, stress, restless}, `t_local`, `value` |
| `intraday` | próbka 3-min | `stress`, `body_battery`, `hour` — pełna doba (metryka `stress` w ETL) |
