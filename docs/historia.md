# Historia decyzji

Dlaczego aplikacja wygląda tak, a nie inaczej. Najnowsze na górze. Zasady, które
z tych decyzji wynikają, są w `AGENTS.md`; szczegóły działania w pozostałych plikach `docs/`.

## 2026-11-05 — porządki w repo

- `CLAUDE.md` (1100 linii) rozdzielony: zasady i pułapki → `AGENTS.md`
  (`CLAUDE.md` tylko go importuje), opisy działania → `docs/`. `DEPLOY.md`
  i `DOSTEP.md` przeniesione do `docs/`.
- Ok. 30 modułów z korzenia repo rozłożonych na pakiety `core/`, `analysis/`,
  `ui/` (komponenty JS w `ui/components/`), `etl/analytics.py`,
  `running/hrzones.py`. Punkty wejścia (`app.py`, `api.py`, `serve.py`) zostały
  w korzeniu, więc launchery, systemd i nginx się nie zmieniły. CLI: `python -m
  core.tenant`, `python -m core.auth setup`.
- Usunięty martwy kod: stary przycisk pobierania (`shell._pull`), ekran „brak
  danych” sprzed źródła Apple, `geo_clusters`/`geo_cells` (klastry liczy
  `globe.js`), `hr_band` (strefy z % HRmax), `plans_for` (z czasów planu na
  każdy start), `forecast.Inputs`, kilka nieużywanych stałych i importów.

## 2026-11-04 — strefy tętna od progów

Stały % HRmax (strefy Garmina 50/60/70/80/90%) wrzuca różne osoby w różne domeny
intensywności — Iannetta i in. 2020 (MSSE 52:466), Jamnick i in. 2020 (Sports Med
50:1729), Mann i in. 2013 (Sports Med 43:613). Strefy liczą się od LTHR i VT1
(wpisane z testu → z danych → szacunek Esteve-Lanao i in. 2026, Sports 14:29).
Bez danych nie ma stref — żadnego 220 − wiek. LTHR = mediana 3 najmocniejszych
wysiłków, bo jeden upalny dzień ustawiał strefy na 4 miesiące; po przerwie
obowiązuje ostatni zmierzony próg do roku.

Tego samego dnia: znacznik builda przesuwa się dopiero po analityce (strona
otwarta w trakcie przeliczenia zapamiętywała stare tabele pochodne pod nowym
kluczem); strona Admin.

## 2026-11-02 — strona jako opowieść, wiele osób

- Strony przebudowane po badaniach: Li/Dey/Forlizzi 2010 (samoobserwacja jako
  cykl), Segel & Heer 2010 (najpierw prowadzić, potem zwiedzać), Borkin i in. 2015
  (tytuł-przekaz i adnotacje przy danych), NN/g (przyciski bez wypełnienia słabo
  sygnalizują klikalność). Użytkownik wybrał makiety: bez prostokątów, pętla
  po prawej od tytułu, przyciski „C”, strona w jednym ekranie. Wykres główny
  jako komponent JS, bo Plotly nie postawi tekstu na marginesie z linią do
  punktu (`axref="x domain"` nie działa dla końca strzałki).
- Jeden serwer, osobne dane każdej osoby (`core/tenant.py`), docelowo SaaS.
  Plan etapów: `TASKS.md`. Próba wdrożenia na mikr.us: `docs/DEPLOY.md`, 8c.

## 2026-11-01 — menu według pytań, postoje

- Menu z 21 wpisów do 15 (potem + Dzień), ułożone według pytań, nie rodzajów
  danych; Aktywności i Trendy wchłonięte przez inne strony.
- Postoje na światłach są zbierane, nie korygowane: biegacz nie używa autopauzy,
  a tempo w ruchu rozjechałoby porównania z historią. Analiza: insight
  `2026-11-01-postoje-na-biegach`.

## 2026-10-28 — audyt planowania

Lista usterek i kolejność poprawek planu: `TASKS.md` → „Jakość planowania”.
Wynik: ACWR (1,3× średniej z 4 tyg.) przestał być regułą planu i sygnałem
decyzji dnia — Garmin-RUNSAFE (Frandsen i in., BJSM 2025) pokazał, że ryzyko
kontuzji podnosi skok pojedynczego biegu > 10%, a nie iloraz tydzień/tydzień.
Stąd reguła 1,1× najdłuższego biegu z 30 dni.

## 2026-10-25/26 — źródła i rozmiar serwera

- Oficjalne API Garmina (Personal, od 21.10.2026) sprawdzone i odrzucone: brak
  VO2max, readiness, statusu i wysyłki treningów. Szczegóły: `docs/platforma.md`.
- Endurance score, hill score i próg mleczanowy są u tego użytkownika puste.
- Pomiar zasobów (`tools/resources.py`): `docs/DEPLOY.md`, sekcja 9.

## Bez daty — decyzje projektowe, które wracały

- **Gradienty odrzucone trzy razy** (tło, kafle, glob, wykresy). Jednolite kolory.
- **Glob jako własny komponent**, nie Plotly: obracanie w Plotly to pełny rerun
  i round-trip websocketu na każdą klatkę.
- **Klipowanie globu przez `d3-geo`**, nie własne: Afryka i Eurazja to jeden
  wielokąt owijający ponad połowę horyzontu; reguła „krótszym łukiem” wycinała
  kliny, reguła „zgodnie ze zwrotem” zalewała kulę lądem.
- **Zoom globu trzyma punkt pod kursorem** — przenoszenie środka na kursor przy
  dziesiątkach zdarzeń touchpada na sekundę dawało skaczący obraz.
- **Kafelki OSM zamiast CARTO**: rastry CARTO odpowiadają obrazkiem „API KEY REQUIRED”.
- **`route_map` rysuje linie**: kropki rozjeżdżały się przy przybliżaniu na
  koraliki; półprzezroczyste linie wszystkich tras zlewały się z ulicami —
  stąd mapa ciepła z liczeniem przebiegów na globie.
- **Surowa seria pełną linią** wyglądała jak arkusz z 2005 roku — stąd `trend`.
- **Motyw przypięty na ciemny**: `st.context.theme.type` zgłasza preferencję
  przeglądarki, co przy jasnym systemie dawało jasne kafle pod białym tekstem.
- **`_build` w parametrze cache** długo nie unieważniał cache po przebudowie —
  Streamlit nie hashuje parametrów z `_`.
- **Tętno ↔ tempo (Swain)** zaniżone u tego użytkownika (~33 vs ~40 VDOT) —
  wchodzi do prognozy jako trend od ostatniego wysiłku, nie poziom.
- **Sport: realizm** — użytkownik wprost wymagał propozycji tylko z dyscyplin już
  uprawianych i bez wyjazdu, chyba że zaznaczy dzień wyjazdu.
