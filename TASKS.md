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
- [x] **Etap 3** — `running/` i CLI w `etl/` (w `i18n.BILINGUAL`): plan zapisuje
      kody (`text`), zdania składa `running/text.py`; stare plany migrowane przy
      pierwszym odczycie. `kind_reason`, `source`, powód Banistera jako kody.
      Coach, prognoza, walidacja i CLI (`--lang`) przez `tr`.
- [x] **Etap 4** — insighty: `insights/<nazwa>.en.md` obok polskiego pliku,
      strona bierze wersję w języku interfejsu (brak tłumaczenia → polska).

## Czeka na zgodę

Języki inne niż polski i angielski. Nic nie jest implementowane, dopóki
użytkownik nie zgodzi się wprost.

_(pusto)_
