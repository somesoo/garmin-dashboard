---
title: Sleep, daily rhythm and what is left of them the next day
created: 2026-10-15
tags: [sleep, rhythm, sri, hrv]
pinned: false
---

## Sleep length vs sleep regularity

The popular assumption: what counts is how long you sleep. The chronobiology
literature says that **when** often matters more. You have both measurements,
so it can be settled on your own data: below, HRV and readiness by sleep
length, and further down the same for the stability of the rhythm.

```sql
SELECT
  CASE
    WHEN sleep_h < 6   THEN '1. < 6 h'
    WHEN sleep_h < 7   THEN '2. 6-7 h'
    WHEN sleep_h < 7.5 THEN '3. 7-7.5 h'
    WHEN sleep_h < 8   THEN '4. 7.5-8 h'
    ELSE                    '5. >= 8 h'
  END                                   AS sleep_band,
  count(*)                              AS nights,
  round(median(hrv_last_night), 1)      AS hrv_median,
  round(median(rhr), 1)                 AS rhr_median,
  round(median(readiness), 1)           AS readiness_median,
  round(median(sleep_score), 1)         AS score_median
FROM daily
WHERE sleep_h IS NOT NULL
GROUP BY sleep_band
HAVING count(*) >= 5
ORDER BY sleep_band
```

Now regularity. SRI (Sleep Regularity Index) is the probability that at the
same minute of the day you are in the same state two nights in a row — it
measures repeatability only, regardless of sleep length.

```sql chart=line x=day y=sri_pair,sri_30d title="Sleep regularity (SRI)"
SELECT day, sri_pair, sri_30d
FROM sleep_regularity
ORDER BY day
```

## A shifted rhythm and the cost the next day

The sleep midpoint is the night's centre of gravity (hours counted
continuously past midnight, so 26.5 = 02:30). Nights shifted from your own
normal are the equivalent of a small time-zone change — the question is
whether it shows in the morning HRV.

```sql
SELECT
  CASE
    WHEN c.midpoint_hour < 26.5 THEN '1. early (< 02:30)'
    WHEN c.midpoint_hour < 27.5 THEN '2. typical (02:30-03:30)'
    ELSE                             '3. late (> 03:30)'
  END                                      AS sleep_midpoint,
  count(*)                                 AS nights,
  round(median(d.hrv_last_night), 1)       AS hrv_median,
  round(median(d.sleep_score), 1)          AS score_median,
  round(median(d.readiness), 1)            AS readiness_median,
  round(median(d.sleep_h), 2)              AS length_median
FROM circadian c
JOIN daily d USING (day)
WHERE c.midpoint_hour IS NOT NULL
GROUP BY sleep_midpoint
HAVING count(*) >= 5
ORDER BY sleep_midpoint
```

## The structure of the night, not just its length

The share of deep sleep rises after heavy load, and REM is the first to go
with stress and after alcohol. Below, the stages per week as a percentage of
the night — length does not distort the comparison.

```sql chart=line x=week y=deep_pct,rem_pct,light_pct title="Sleep stages as % of the night"
WITH per_week AS (
  SELECT
    strftime(day, '%G-W%V')                                AS week,
    sum(CASE WHEN stage = 'deep'  THEN minutes ELSE 0 END) AS deep,
    sum(CASE WHEN stage = 'rem'   THEN minutes ELSE 0 END) AS rem,
    sum(CASE WHEN stage = 'light' THEN minutes ELSE 0 END) AS light,
    sum(minutes)                                           AS total
  FROM sleep_stages
  GROUP BY week
)
SELECT
  week,
  round(100.0 * deep  / nullif(total, 0), 1) AS deep_pct,
  round(100.0 * rem   / nullif(total, 0), 1) AS rem_pct,
  round(100.0 * light / nullif(total, 0), 1) AS light_pct
FROM per_week
WHERE total > 0
ORDER BY week
```

## Outlier nights

Nights when the heart rate stayed high relative to its own minimum — a
pattern typical of alcohol, a late meal or a late hard session. Column
`hr_excess` is the night's average heart rate minus its minimum.

```sql
WITH nightly AS (
  SELECT
    day,
    avg(CASE WHEN metric = 'hr'  THEN value END) AS hr_avg,
    min(CASE WHEN metric = 'hr'  THEN value END) AS hr_min,
    avg(CASE WHEN metric = 'hrv' THEN value END) AS hrv_avg
  FROM night_series
  GROUP BY day
)
SELECT
  n.day::DATE                        AS day,
  round(n.hr_avg, 1)                 AS hr_avg,
  round(n.hr_min, 1)                 AS hr_min,
  round(n.hr_avg - n.hr_min, 1)      AS hr_excess,
  round(n.hrv_avg, 1)                AS hrv_avg,
  d.sleep_score,
  d.sleep_h
FROM nightly n
JOIN daily d ON d.day = n.day
WHERE n.hr_avg - n.hr_min >= 12
ORDER BY hr_excess DESC
LIMIT 15
```
