---
title: Przegląd tygodnia — regeneracja vs obciążenie
created: 2026-10-15
tags: [tydzien, hrv, obciazenie]
pinned: true
---

## Ostatnie 7 dni

Panel startowy: zestawia obciążenie treningowe z tym, jak organizm je znosi.
Rosnące `load_acute` przy spadającym HRV i rosnącym tętnie spoczynkowym to
klasyczny sygnał, że tydzień był za ciężki — odwrotny układ znaczy, że jest
zapas na mocniejszy bodziec.

```sql chart=metric y=dni,sen_h,hrv,rhr,readiness
SELECT
  count(*)                        AS dni,
  round(avg(sleep_h), 1)          AS sen_h,
  round(avg(hrv_last_night), 1)   AS hrv,
  round(avg(rhr), 1)              AS rhr,
  round(avg(readiness), 1)        AS readiness
FROM daily
WHERE day >= (SELECT max(day) FROM daily) - INTERVAL 6 DAY
```

## Obciążenie a regeneracja, tydzień po tygodniu

```sql chart=line x=iso_week y=load_acute,hrv,rhr title="Tygodniowe średnie"
SELECT
  iso_week,
  round(avg(load_acute), 0)      AS load_acute,
  round(avg(hrv_last_night), 1)  AS hrv,
  round(avg(rhr), 1)             AS rhr
FROM daily
WHERE day >= (SELECT max(day) FROM daily) - INTERVAL 120 DAY
GROUP BY iso_week
ORDER BY iso_week
```

## Dni z HRV wyraźnie pod własną bazą

Odchylenie liczone względem własnej średniej 7-dniowej, więc nie zależy od
tego, czy akurat masz wysokie czy niskie HRV w ogóle.

```sql
SELECT
  day::DATE                AS dzien,
  hrv_last_night           AS hrv,
  hrv_deviation            AS odchylenie,
  rhr,
  sleep_h,
  round(load_acute, 0)     AS load_acute,
  training_status
FROM daily
WHERE hrv_deviation <= -5
ORDER BY day DESC
LIMIT 20
```
