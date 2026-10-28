---
title: Tytuł wniosku
created: 2026-10-15
tags: [hrv, sen]
pinned: false
---

Krótki akapit: co widać w danych i co z tego wynika. Tekst jest interpretacją —
liczby pod nim liczą się na nowo przy każdym odświeżeniu strony, więc wniosek
nie zestarzeje się po cichu. Obok zawsze `<nazwa>.en.md` (patrz `_template.en.md`)
z tym samym SQL-em, angielską prozą i aliasami kolumn.

```sql chart=line x=day y=hrv_last_night,hrv_last_night_roll7 title="HRV"
SELECT day, hrv_last_night, hrv_last_night_roll7
FROM daily
WHERE day >= current_date - INTERVAL 90 DAY
ORDER BY day
```

Opcje bloku: `chart=line|area|bar|scatter|table|metric`, `x=`, `y=kol1,kol2`,
`title=`. Bez `chart` wychodzi tabela.
