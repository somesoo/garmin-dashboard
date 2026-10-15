---
title: Wydolność bez laboratorium — CS, D′, Riegel i ekonomia biegu
created: 2026-10-15
tags: [wydolnosc, cs, riegel, ekonomia]
pinned: false
---

## Prędkość krytyczna z własnych rekordów odcinków

Garmin zapisuje najlepszy kilometr, milę i 5 km wewnątrz każdego biegu. Trzy
punkty na krzywej czas–dystans wystarczają, by dopasować model dwuparametrowy
`d = CS·t + D′`: CS to tempo utrzymywane tlenowo, D′ to skończony zapas
dystansu ponad nim. To ta sama matematyka, którą w kolarstwie zna się jako
FTP/W′ — tylko liczona z biegania i bez testu na progu.

Czytaj `r2`: przy trzech punktach dopasowanie prawie zawsze wygląda świetnie,
ale okno z `distances = 2` to w praktyce prosta przez dwa punkty.

```sql
SELECT
  day::DATE          AS okno_do,
  cs_ms              AS cs_m_s,
  cs_pace_min_km     AS cs_tempo,
  d_prime_m          AS d_prime,
  pred_5k_s / 60.0   AS pred_5k_min,
  pred_10k_s / 60.0  AS pred_10k_min,
  r2,
  distances          AS liczba_dystansow
FROM critical_speed
ORDER BY day DESC
LIMIT 20
```

```sql chart=line x=day y=cs_ms,d_prime_scaled title="CS (m/s) i D′ (setki metrów)"
SELECT
  day,
  cs_ms,
  round(d_prime_m / 100.0, 2) AS d_prime_scaled
FROM critical_speed
ORDER BY day
```

CS i D′ zwykle idą w przeciwnych kierunkach: blok tlenowy podnosi CS i obniża
D′, blok szybkościowy odwrotnie. Jeśli oba rosną, to albo realny skok formy,
albo po prostu mocniejsze starty w oknie.

## Wykładnik Riegela: jak szybko tempo siada z dystansem

`t = a · d^b`. Wartość `b` to twoja osobista sygnatura wytrzymałości, nie
stała fizyczna — klasyczne 1.06 pochodzi z wyników biegaczy wyczynowych.
Wyższe `b` znaczy, że dłuższe dystanse kosztują cię proporcjonalnie więcej.

```sql chart=line x=day y=riegel_b title="Wykładnik Riegela (niżej = lepsza wytrzymałość)"
SELECT day, riegel_b
FROM riegel
ORDER BY day
```

## Ekonomia biegu: metry na uderzenie serca

Najtańszy dostępny wskaźnik postępu tlenowego: prędkość skorygowana
o nachylenie podzielona przez tętno. Pojedyncza sesja nic nie znaczy (upał,
teren, sen), ale mediana z 10 sesji jest zaskakująco stabilna.

```sql chart=line x=day y=ef,ef_roll10 title="EF: metry na uderzenie serca"
SELECT day, ef, ef_roll10
FROM efficiency
ORDER BY day
```

Jeśli EF rośnie przy stałym tętnie, poprawa jest realna. Jeśli rośnie tylko
dlatego, że biegasz szybciej na wyższym tętnie — to nie postęp, to po prostu
mocniejszy trening. Rozdzielenie tych dwóch przypadków:

```sql
SELECT
  CASE
    WHEN avg_hr < 140 THEN '1. < 140 bpm'
    WHEN avg_hr < 150 THEN '2. 140-150'
    WHEN avg_hr < 160 THEN '3. 150-160'
    ELSE                   '4. >= 160'
  END                            AS przedzial_hr,
  count(*)                       AS sesje,
  round(median(ef), 3)           AS ef_mediana,
  round(median(distance_km), 1)  AS dystans_mediana,
  round(median(hr_per_kmh), 2)   AS hr_na_kmh_mediana
FROM efficiency
GROUP BY przedzial_hr
HAVING count(*) >= 5
ORDER BY przedzial_hr
```

## Rozkład intensywności: co naprawdę robisz, a nie co planujesz

```sql
SELECT
  iso_week      AS tydzien,
  total_min     AS minuty,
  easy_pct      AS latwo_pct,
  middle_pct    AS srodek_pct,
  hard_pct      AS mocno_pct,
  model
FROM intensity_distribution
WHERE total_min > 0
ORDER BY iso_week DESC
LIMIT 20
```

Etykieta `model` to reguła opisowa, nie opublikowany indeks: spolaryzowany
(≥70% łatwo, ≥10% mocno, <15% w środku), piramidalny, progowy albo mieszany.
Większość amatorów, którzy "trenują polarnie", w danych wychodzi progowo —
warto sprawdzić, po której stronie jesteś.
