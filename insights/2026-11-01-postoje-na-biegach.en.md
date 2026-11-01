---
title: Stops on runs — collecting before correcting anything
created: 2026-11-01
tags: [running, pace, segments]
pinned: false
---

You run without auto-pause, so standing at traffic lights goes into the time
and the pace. The watch counts moving time separately — the difference is the
stop (`run_sessions.stop_s`, the list of stops from 5 s in `run_stops`). For
now **nothing is corrected**: pace, splits and segments stay in timer time,
the stop is only shown next to them. On the data from 2026-11: a stop in ~3 of
4 runs, a median of ~27 s per run (~1% of pace). In a few weeks check here
whether stops change segment rankings or spoil same-route comparisons — only
then decide whether to compare on moving pace (never in the forecast).

```sql chart=bar x=month y=runs_with_a_stop_pct,stop_pct_of_time title="How often and how much"
SELECT
  strftime(start_local, '%Y-%m')                             AS month,
  count(*)                                                   AS runs,
  round(100 * avg(CASE WHEN stops > 0 THEN 1 ELSE 0 END), 0) AS runs_with_a_stop_pct,
  round(median(stop_s), 0)                                   AS median_stop_s,
  round(100 * sum(stop_s) / sum(duration_min * 60), 1)       AS stop_pct_of_time
FROM run_sessions
WHERE stop_s IS NOT NULL
  AND start_local >= current_date - INTERVAL 365 DAY
GROUP BY 1
ORDER BY 1
```

The same crossings come back: stops grouped in ~100 m cells.

```sql
SELECT
  round(lat, 3)                       AS lat,
  round(lon, 3)                       AS lon,
  count(*)                            AS stops,
  count(DISTINCT activity_id)         AS runs,
  round(median(seconds), 0)           AS median_s,
  round(max(seconds), 0)              AS longest_s
FROM run_stops
WHERE lat IS NOT NULL
GROUP BY 1, 2
HAVING count(DISTINCT activity_id) >= 3
ORDER BY stops DESC
LIMIT 15
```

Runs where stops ate the most pace. In intervals this includes standing recoveries,
not only traffic lights.

```sql
SELECT
  strftime(start_local, '%Y-%m-%d')   AS day,
  name                                AS run,
  round(distance_km, 1)               AS km,
  stops                               AS stops,
  round(stop_s, 0)                    AS stop_s,
  round(stop_s / distance_km, 1)      AS s_per_km
FROM run_sessions
WHERE stop_s > 0
ORDER BY s_per_km DESC
LIMIT 10
```
