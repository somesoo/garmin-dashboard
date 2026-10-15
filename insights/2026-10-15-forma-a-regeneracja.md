---
title: Forma, obciążenie i odpowiedź autonomiczna
created: 2026-10-15
tags: [pmc, hrv, obciazenie, acwr]
pinned: true
---

## Czy obciążenie przekłada się na HRV — i z jakim opóźnieniem

Pytanie jest proste: po ilu dniach od mocnej sesji widać ją w HRV i tętnie
spoczynkowym? Tabela poniżej pokazuje korelacje Spearmana dla każdego opóźnienia,
liczone na całej dostępnej historii. Kolumna `q` to wartość po kontroli FDR
(Benjamini-Hochberg) — przy kilkuset testach samo `p` nic nie znaczy.
Jeśli nic nie przechodzi `q < 0.05`, to **też jest wynik**: znaczy, że na tej
liczbie dni efekt jest nieodróżnialny od szumu.

```sql
SELECT
  driver        AS czynnik,
  response      AS odpowiedz,
  lag_days      AS lag,
  rho,
  q,
  n,
  CASE WHEN q < 0.05 THEN 'tak' ELSE 'nie' END AS istotne
FROM correlations
WHERE response IN ('hrv_last_night', 'hrv_deviation', 'rhr')
  AND driver IN ('load_day', 'atl', 'tsb', 'ctl')
ORDER BY abs(rho) DESC
LIMIT 25
```

## Czy TSB rzeczywiście opisuje "formę"

TSB to konstrukcja matematyczna, nie pomiar. Jeśli ma jakikolwiek sens dla
ciebie, dni o wysokim TSB powinny mieć systematycznie wyższy readiness i HRV
niż dni głęboko na minusie. Poniżej rozkład po strefach formy — porównuj
**medianę i n**, nie same średnie.

```sql
SELECT
  p.form_zone                             AS strefa_formy,
  count(*)                                AS dni,
  round(median(d.readiness), 1)           AS readiness_mediana,
  round(median(d.hrv_last_night), 1)      AS hrv_mediana,
  round(median(d.rhr), 1)                 AS rhr_mediana,
  round(median(d.sleep_h), 2)             AS sen_mediana_h
FROM pmc p
JOIN daily d USING (day)
WHERE p.form_zone IS NOT NULL AND p.form_zone <> 'nan'
GROUP BY p.form_zone
HAVING count(*) >= 10
ORDER BY dni DESC
```

## Dwie wersje ACWR nie mówią tego samego

Kroczący (Gabbett) liczy sumę 7 dni przez średnią z 28; wykładniczy (Williams)
używa tych samych wag co CTL/ATL. Po przerwie w treningach pierwszy skacze,
drugi płynie. Tygodnie, w których różnią się najmocniej, to te, w których
wniosek "przetrenowanie / niedotrenowanie" zależy wyłącznie od wyboru wzoru.

```sql chart=line x=day y=acwr_rolling,acwr_ewma title="ACWR: dwa wzory, jedna rzeczywistość"
SELECT day, acwr_rolling, acwr_ewma
FROM pmc
WHERE acwr_rolling IS NOT NULL
  AND day >= (SELECT max(day) FROM pmc) - INTERVAL 365 DAY
ORDER BY day
```

## Monotonia: tygodnie, które były ciężkie bez bycia dużymi

Foster: monotonia to średnia dzienna podzielona przez odchylenie w tygodniu.
Tydzień siedmiu identycznych biegów ma wysoką monotonię przy umiarkowanej
objętości — i to on, nie tydzień z jedną dużą sesją, częściej kończy się
spadkiem HRV.

```sql
SELECT
  iso_week          AS tydzien,
  round(load_sum)   AS load,
  sessions          AS sesje,
  monotony          AS monotonia,
  round(strain)     AS strain,
  hrv,
  rhr,
  sleep_h
FROM load_weekly
WHERE monotony IS NOT NULL
ORDER BY strain DESC
LIMIT 15
```
