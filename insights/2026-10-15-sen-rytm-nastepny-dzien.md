---
title: Sen, rytm dobowy i to, co z nich zostaje na drugi dzień
created: 2026-10-15
tags: [sen, rytm, sri, hrv]
pinned: false
---

## Długość snu vs regularność snu

Popularne założenie: liczy się ile śpisz. Literatura chronobiologiczna mówi,
że **kiedy** często decyduje mocniej. Masz oba pomiary, więc da się to
rozstrzygnąć na własnych danych: poniżej HRV i readiness w zależności od
długości snu, a dalej to samo dla stabilności rytmu.

```sql
SELECT
  CASE
    WHEN sleep_h < 6   THEN '1. < 6 h'
    WHEN sleep_h < 7   THEN '2. 6-7 h'
    WHEN sleep_h < 7.5 THEN '3. 7-7.5 h'
    WHEN sleep_h < 8   THEN '4. 7.5-8 h'
    ELSE                    '5. >= 8 h'
  END                                   AS przedzial_snu,
  count(*)                              AS noce,
  round(median(hrv_last_night), 1)      AS hrv_mediana,
  round(median(rhr), 1)                 AS rhr_mediana,
  round(median(readiness), 1)           AS readiness_mediana,
  round(median(sleep_score), 1)         AS score_mediana
FROM daily
WHERE sleep_h IS NOT NULL
GROUP BY przedzial_snu
HAVING count(*) >= 5
ORDER BY przedzial_snu
```

Teraz regularność. SRI (Sleep Regularity Index) liczy prawdopodobieństwo, że
o tej samej minucie doby jesteś w tym samym stanie dwie noce z rzędu —
mierzy wyłącznie powtarzalność, niezależnie od długości snu.

```sql chart=line x=day y=sri_pair,sri_30d title="Regularność snu (SRI)"
SELECT day, sri_pair, sri_30d
FROM sleep_regularity
ORDER BY day
```

## Przesunięcie rytmu a koszt następnego dnia

Środek snu to środek ciężkości nocy (godziny liczone ciągle przez północ, więc
26.5 = 02:30). Noce przesunięte względem własnej normy to odpowiednik lekkiej
zmiany strefy czasowej — pytanie, czy widać to rano w HRV.

```sql
SELECT
  CASE
    WHEN c.midpoint_hour < 26.5 THEN '1. wczesny (< 02:30)'
    WHEN c.midpoint_hour < 27.5 THEN '2. typowy (02:30-03:30)'
    ELSE                             '3. pozny (> 03:30)'
  END                                      AS srodek_snu,
  count(*)                                 AS noce,
  round(median(d.hrv_last_night), 1)       AS hrv_mediana,
  round(median(d.sleep_score), 1)          AS score_mediana,
  round(median(d.readiness), 1)            AS readiness_mediana,
  round(median(d.sleep_h), 2)              AS dlugosc_mediana
FROM circadian c
JOIN daily d USING (day)
WHERE c.midpoint_hour IS NOT NULL
GROUP BY srodek_snu
HAVING count(*) >= 5
ORDER BY srodek_snu
```

## Struktura nocy, nie tylko jej długość

Udział snu głębokiego rośnie po dużym obciążeniu, a REM pierwszy znika przy
stresie i po alkoholu. Poniżej fazy tygodniowo, w procentach nocy — długość
nie zaburza porównania.

```sql chart=line x=tydzien y=glebokie_pct,rem_pct,lekkie_pct title="Fazy snu jako % nocy"
WITH per_week AS (
  SELECT
    strftime(day, '%G-W%V')                                AS tydzien,
    sum(CASE WHEN stage = 'deep'  THEN minutes ELSE 0 END) AS glebokie,
    sum(CASE WHEN stage = 'rem'   THEN minutes ELSE 0 END) AS rem,
    sum(CASE WHEN stage = 'light' THEN minutes ELSE 0 END) AS lekkie,
    sum(minutes)                                           AS razem
  FROM sleep_stages
  GROUP BY tydzien
)
SELECT
  tydzien,
  round(100.0 * glebokie / nullif(razem, 0), 1) AS glebokie_pct,
  round(100.0 * rem      / nullif(razem, 0), 1) AS rem_pct,
  round(100.0 * lekkie   / nullif(razem, 0), 1) AS lekkie_pct
FROM per_week
WHERE razem > 0
ORDER BY tydzien
```

## Noce odstające

Noce, w których tętno trzymało się wysoko względem własnego minimum — wzorzec
typowy dla alkoholu, późnego posiłku albo późnej ciężkiej sesji. Kolumna
`nadwyzka_hr` to średnie tętno nocy minus jej minimum.

```sql
WITH nocne AS (
  SELECT
    day,
    avg(CASE WHEN metric = 'hr'  THEN value END) AS hr_srednie,
    min(CASE WHEN metric = 'hr'  THEN value END) AS hr_min,
    avg(CASE WHEN metric = 'hrv' THEN value END) AS hrv_srednie
  FROM night_series
  GROUP BY day
)
SELECT
  n.day::DATE                            AS dzien,
  round(n.hr_srednie, 1)                 AS hr_srednie,
  round(n.hr_min, 1)                     AS hr_min,
  round(n.hr_srednie - n.hr_min, 1)      AS nadwyzka_hr,
  round(n.hrv_srednie, 1)                AS hrv_srednie,
  d.sleep_score,
  d.sleep_h
FROM nocne n
JOIN daily d ON d.day = n.day
WHERE n.hr_srednie - n.hr_min >= 12
ORDER BY nadwyzka_hr DESC
LIMIT 15
```
