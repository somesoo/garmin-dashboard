# Zadania

## Do zrobienia

### Angielska wersja interfejsu (`i18n.py`, zasady w CLAUDE.md → „Języki”)

- [x] **Etap 1** — moduł `i18n.py`, przełącznik PL/EN w szynie, menu i tytuły
      stron, szyna (zakres, pobieranie, status), chrome kafli (`bento.py`,
      pomoc „Co to jest?”), daty na osiach i podpisy builderów (`theme.py`).
- [x] **Etap 2** — wszystkie strony w `views/` (w `i18n.BILINGUAL`), słownik
      pojęć (`glossary_en.py`), teksty globu (przekazywane z `globe.py`).
      Kody zapisywane przez analitykę i `running/` (`form_zone`, `quadrant`,
      `model`, typ treningu, pewność, decyzja dnia, status celu, fazy planu)
      zostają kodami — tłumaczy je widok.
- [ ] **Etap 3** — proza generowana w `running/` i `analytics.py`, która w EN
      wciąż jest po polsku:
      - `coach.py`: obserwacje (*Co mówią dane*), sygnały regeneracji, powody
        decyzji dnia, brief;
      - `forecast.py`: ostrzeżenia, `notes`, `advice`, `confidence_reasons`,
        `reason` przy braku prognozy, źródło kotwicy;
      - `sessions.py`: `kind_reason`, `source` najlepszych odcinków;
      - `workouts.py`: nazwy segmentów z interwałów („Odcinek 1 km (interwały)”);
      - `segments.py`: nazwy segmentów auto (miasto + długość);
      - `plan.py`: tytuły i opisy sesji (`title`, `main`, `purpose`, rozgrzewka),
        historia zmian, opisy workoutów na zegarek (`garmin_workout.py`);
      - `analytics.py`: powód niedopasowania modelu Banistera (`models.json`).
      Zapisane plany w `data/coach/` mają tekst po polsku — zdecydować, czy
      przejść na klucze, czy zostawić stare plany po polsku.
- [ ] **Etap 4** (opcjonalnie) — insighty (`insights/*.en.md`).

## Czeka na zgodę

Języki inne niż polski i angielski. Nic nie jest implementowane, dopóki
użytkownik nie zgodzi się wprost.

_(pusto)_
