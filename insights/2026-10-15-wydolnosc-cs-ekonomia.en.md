---
title: Fitness without a laboratory — CS, D′, Riegel and running economy
created: 2026-10-15
tags: [fitness, cs, riegel, economy]
pinned: false
---

## Critical speed from your own best efforts

Garmin records the best kilometre, mile and 5 km inside every run. Three
points on the time–distance curve are enough to fit the two-parameter model
`d = CS·t + D′`: CS is the pace held aerobically, D′ the finite reserve of
distance above it. It is the same mathematics cycling knows as FTP/W′ — only
computed from running and without a threshold test.

Read `r2`: with three points the fit almost always looks great, but a window
with `distances = 2` is in practice a line through two points.

```sql
SELECT
  day::DATE          AS window_to,
  cs_ms              AS cs_m_s,
  cs_pace_min_km     AS cs_pace,
  d_prime_m          AS d_prime,
  pred_5k_s / 60.0   AS pred_5k_min,
  pred_10k_s / 60.0  AS pred_10k_min,
  r2,
  distances          AS distance_count
FROM critical_speed
ORDER BY day DESC
LIMIT 20
```

```sql chart=line x=day y=cs_ms,d_prime_scaled title="CS (m/s) and D′ (hundreds of metres)"
SELECT
  day,
  cs_ms,
  round(d_prime_m / 100.0, 2) AS d_prime_scaled
FROM critical_speed
ORDER BY day
```

CS and D′ usually move in opposite directions: an aerobic block raises CS and
lowers D′, a speed block the reverse. If both rise, it is either a real jump
in form or simply harder efforts within the window.

## The Riegel exponent: how fast pace fades with distance

`t = a · d^b`. The value `b` is your personal endurance signature, not a
physical constant — the classic 1.06 comes from the results of elite runners.
A higher `b` means longer distances cost you proportionally more.

```sql chart=line x=day y=riegel_b title="Riegel exponent (lower = better endurance)"
SELECT day, riegel_b
FROM riegel
ORDER BY day
```

## Running economy: metres per heartbeat

The cheapest available indicator of aerobic progress: grade-adjusted speed
divided by heart rate. A single session means nothing (heat, terrain, sleep),
but the 10-session median is surprisingly stable.

```sql chart=line x=day y=ef,ef_roll10 title="EF: metres per heartbeat"
SELECT day, ef, ef_roll10
FROM efficiency
ORDER BY day
```

If EF rises at a steady heart rate, the improvement is real. If it rises only
because you run faster at a higher heart rate — that is not progress, just
harder training. Separating the two cases:

```sql
SELECT
  CASE
    WHEN avg_hr < 140 THEN '1. < 140 bpm'
    WHEN avg_hr < 150 THEN '2. 140-150'
    WHEN avg_hr < 160 THEN '3. 150-160'
    ELSE                   '4. >= 160'
  END                            AS hr_band,
  count(*)                       AS sessions,
  round(median(ef), 3)           AS ef_median,
  round(median(distance_km), 1)  AS distance_median,
  round(median(hr_per_kmh), 2)   AS hr_per_kmh_median
FROM efficiency
GROUP BY hr_band
HAVING count(*) >= 5
ORDER BY hr_band
```

## Intensity distribution: what you really do, not what you plan

```sql
SELECT
  iso_week      AS week,
  total_min     AS minutes,
  easy_pct,
  middle_pct,
  hard_pct,
  model
FROM intensity_distribution
WHERE total_min > 0
ORDER BY iso_week DESC
LIMIT 20
```

The `model` label is a descriptive rule, not a published index: polarised
(spolaryzowany: ≥70% easy, ≥10% hard, <15% in the middle), pyramidal
(piramidalny), threshold (progowy) or mixed (mieszany) — the column holds the
Polish code. Most amateurs who "train polarised" come out as threshold in the
data — worth checking which side you are on.
