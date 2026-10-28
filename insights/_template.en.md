---
title: The finding's title
created: 2026-10-15
tags: [hrv, sleep]
pinned: false
---

A short paragraph: what the data shows and what follows from it. The text is
an interpretation — the numbers under it are recomputed on every page load,
so a finding never goes stale quietly. Keep the SQL the same as in the Polish
note; only the prose and the column aliases change.

```sql chart=line x=day y=hrv_last_night,hrv_last_night_roll7 title="HRV"
SELECT day, hrv_last_night, hrv_last_night_roll7
FROM daily
WHERE day >= current_date - INTERVAL 90 DAY
ORDER BY day
```

Block options: `chart=line|area|bar|scatter|table|metric`, `x=`, `y=col1,col2`,
`title=`. Without `chart` you get a table.
