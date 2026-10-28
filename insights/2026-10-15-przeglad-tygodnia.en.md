---
title: The week in review — recovery vs load
created: 2026-10-15
tags: [week, hrv, load]
pinned: true
---

## The last 7 days

The opening panel: it sets training load against how the body copes with it.
Rising `load_acute` with falling HRV and a rising resting heart rate is the
classic sign that the week was too hard — the reverse pattern means there is
room for a stronger stimulus.

```sql chart=metric y=days,sleep_h,hrv,rhr,readiness
SELECT
  count(*)                        AS days,
  round(avg(sleep_h), 1)          AS sleep_h,
  round(avg(hrv_last_night), 1)   AS hrv,
  round(avg(rhr), 1)              AS rhr,
  round(avg(readiness), 1)        AS readiness
FROM daily
WHERE day >= (SELECT max(day) FROM daily) - INTERVAL 6 DAY
```

## Load against recovery, week by week

```sql chart=line x=iso_week y=load_acute,hrv,rhr title="Weekly averages"
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

## Days with HRV clearly below your own baseline

The deviation is measured against your own 7-day average, so it does not
depend on whether your HRV is high or low in general.

```sql
SELECT
  day::DATE                AS day,
  hrv_last_night           AS hrv,
  hrv_deviation            AS deviation,
  rhr,
  sleep_h,
  round(load_acute, 0)     AS load_acute,
  training_status
FROM daily
WHERE hrv_deviation <= -5
ORDER BY day DESC
LIMIT 20
```
