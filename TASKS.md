# Zadania

## Do zrobienia

### Angielska wersja interfejsu (`i18n.py`, zasady w CLAUDE.md → „Języki”)

- [x] **Etap 1** — moduł `i18n.py`, przełącznik PL/EN w szynie, menu i tytuły
      stron, szyna (zakres, pobieranie, status), chrome kafli (`bento.py`,
      pomoc „Co to jest?”), daty na osiach i podpisy builderów (`theme.py`).
- [ ] **Etap 2** — strony po kolei (podpisy, KPI, kafle, tabele, `how=`)
      i słownik pojęć (`glossary.py`: `Term` z obu językami, `FIELDS`).
      Glob: napisy z `globe_component/index.html` / `globe.js` przekazywane
      z Pythona. Każdy przetłumaczony moduł → `i18n.BILINGUAL`.
- [ ] **Etap 3** — moduł biegowy (`running/`): opisy sesji planu (`main`,
      `purpose`), `kind_reason`, brief `running.coach`, opisy workoutów na
      zegarek. Zapisane plany w `data/coach/` mają tekst po polsku — zdecydować,
      czy przejść na klucze, czy zostawić stare plany po polsku.
- [ ] **Etap 4** (opcjonalnie) — insighty (`insights/*.en.md`).

## Czeka na zgodę

Języki inne niż polski i angielski. Nic nie jest implementowane, dopóki
użytkownik nie zgodzi się wprost.

_(pusto)_
