---
title: Postoje na biegach — zbieramy, zanim cokolwiek poprawimy
created: 2026-11-01
tags: [bieganie, tempo, segmenty]
pinned: false
---

Biegasz bez autopauzy, więc stanie na światłach wchodzi do czasu i tempa.
Zegarek liczy osobno czas w ruchu — różnica to postój (`run_sessions.stop_s`,
lista postojów od 5 s w `run_stops`). Na razie **nic nie jest korygowane**:
tempo, splity i segmenty zostają w czasie stopera, postój jest tylko
pokazywany obok. Na danych z 2026-11: postój w ~3 na 4 biegi, mediana ~27 s
na bieg (~1% tempa). Po kilku tygodniach sprawdź tu, czy postoje zmieniają
ranking segmentów albo psują porównania tej samej trasy — dopiero wtedy
decyzja, czy przejść na tempo w ruchu do porównań (nigdy w prognozie).

```sql chart=bar x=miesiac y=udzial_biegow_z_postojem_pct,postoj_pct_czasu title="Jak często i ile"
SELECT
  strftime(start_local, '%Y-%m')                             AS miesiac,
  count(*)                                                   AS biegi,
  round(100 * avg(CASE WHEN stops > 0 THEN 1 ELSE 0 END), 0) AS udzial_biegow_z_postojem_pct,
  round(median(stop_s), 0)                                   AS mediana_postoju_s,
  round(100 * sum(stop_s) / sum(duration_min * 60), 1)       AS postoj_pct_czasu
FROM run_sessions
WHERE stop_s IS NOT NULL
  AND start_local >= current_date - INTERVAL 365 DAY
GROUP BY 1
ORDER BY 1
```

Te same skrzyżowania wracają: postoje zgrupowane w kratkach ~100 m.

```sql
SELECT
  round(lat, 3)                       AS lat,
  round(lon, 3)                       AS lon,
  count(*)                            AS postoje,
  count(DISTINCT activity_id)         AS biegi,
  round(median(seconds), 0)           AS mediana_s,
  round(max(seconds), 0)              AS najdluzej_s
FROM run_stops
WHERE lat IS NOT NULL
GROUP BY 1, 2
HAVING count(DISTINCT activity_id) >= 3
ORDER BY postoje DESC
LIMIT 15
```

Biegi, w których postoje zjadły najwięcej tempa. W interwałach to także przerwy na stojąco,
nie tylko światła.

```sql
SELECT
  strftime(start_local, '%Y-%m-%d')   AS dzien,
  name                                AS bieg,
  round(distance_km, 1)               AS km,
  stops                               AS postoje,
  round(stop_s, 0)                    AS postoj_s,
  round(stop_s / distance_km, 1)      AS s_na_km
FROM run_sessions
WHERE stop_s > 0
ORDER BY s_na_km DESC
LIMIT 10
```
