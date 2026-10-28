---
title: Form, load and the autonomic response
created: 2026-10-15
tags: [pmc, hrv, load, acwr]
pinned: true
---

## Does load show up in HRV — and with what delay

The question is simple: how many days after a hard session does it show in
HRV and resting heart rate? The table below gives Spearman correlations for
each lag, computed over the whole available history. Column `q` is the value
after FDR control (Benjamini-Hochberg) — with several hundred tests `p` alone
means nothing. If nothing passes `q < 0.05`, that **is a result too**: on this
many days the effect cannot be told apart from noise.

```sql
SELECT
  driver        AS factor,
  response,
  lag_days      AS lag,
  rho,
  q,
  n,
  CASE WHEN q < 0.05 THEN 'yes' ELSE 'no' END AS significant
FROM correlations
WHERE response IN ('hrv_last_night', 'hrv_deviation', 'rhr')
  AND driver IN ('load_day', 'atl', 'tsb', 'ctl')
ORDER BY abs(rho) DESC
LIMIT 25
```

## Does TSB really describe "form"

TSB is a mathematical construct, not a measurement. If it means anything for
you, days with a high TSB should have systematically higher readiness and HRV
than days deep in the negative. Below, the distribution by form zone — compare
**the median and n**, not the means alone.

```sql
SELECT
  p.form_zone                             AS form_zone,
  count(*)                                AS days,
  round(median(d.readiness), 1)           AS readiness_median,
  round(median(d.hrv_last_night), 1)      AS hrv_median,
  round(median(d.rhr), 1)                 AS rhr_median,
  round(median(d.sleep_h), 2)             AS sleep_median_h
FROM pmc p
JOIN daily d USING (day)
WHERE p.form_zone IS NOT NULL AND p.form_zone <> 'nan'
GROUP BY p.form_zone
HAVING count(*) >= 10
ORDER BY days DESC
```

## The two ACWR versions do not say the same thing

The rolling one (Gabbett) divides the 7-day sum by the 28-day average; the
exponential one (Williams) uses the same weights as CTL/ATL. After a break in
training the first one jumps, the second one glides. The weeks where they
differ most are the ones where an "overtraining / undertraining" verdict
depends only on the choice of formula.

```sql chart=line x=day y=acwr_rolling,acwr_ewma title="ACWR: two formulas, one reality"
SELECT day, acwr_rolling, acwr_ewma
FROM pmc
WHERE acwr_rolling IS NOT NULL
  AND day >= (SELECT max(day) FROM pmc) - INTERVAL 365 DAY
ORDER BY day
```

## Monotony: weeks that were hard without being big

Foster: monotony is the daily average divided by the week's standard
deviation. A week of seven identical runs has high monotony at a moderate
volume — and that week, not the one with a single big session, more often
ends with a drop in HRV.

```sql
SELECT
  iso_week          AS week,
  round(load_sum)   AS load,
  sessions,
  monotony,
  round(strain)     AS strain,
  hrv,
  rhr,
  sleep_h
FROM load_weekly
WHERE monotony IS NOT NULL
ORDER BY strain DESC
LIMIT 15
```
