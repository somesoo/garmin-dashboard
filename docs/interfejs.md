# Interfejs: strony, wykresy, komponenty

Jak są zbudowane strony i komponenty. Zasady (wymuszone) są w `AGENTS.md`.

## Układ aplikacji

`app.py` jest wyłącznie routerem: strony to `st.Page` wskazujące na
`views/<nazwa>.render`. Dodanie strony = nowy moduł w `views/` + wpis w `PAGES`
(z własnym `url_path`, bo wszystkie funkcje nazywają się `render` i inaczej
kolidują ścieżkami) + pytanie i linki „Dalej” w `ui/guide.py` (test pilnuje).

**Menu jest ułożone według pytań, nie rodzajów danych** (przebudowa 2026-11-01,
z 21 wpisów do 15, potem +Dzień): *Na co dzień* (Dzień, Dziś, Sport, Historia), *Bieganie* (przegląd,
Plan i zawody, prognoza, segmenty, Obciążenie), *Ciało* (Regeneracja, Sen),
*Laboratorium* (Fizjologia, Statystyka, Insights, SQL, Słownik).

- **Dwa widoki pod jednym wpisem** (`views/hubs.py`, `bento.switch` nad
  nagłówkiem): Plan | Zawody i cele, Obciążenie biegowe | Forma (wszystkie
  sporty), Gotowość i propozycje | Dyscypliny. Moduły widoków zostały osobne.
  Tytuł wpisu w menu to `i18n.page(url)`, tytuł widoku `i18n.view(klucz)`.
  Inna strona otwiera konkretny widok przez
  `routing.goto_view(url, hubs.PLAN, "races")` (żądanie czeka pod
  `<klucz>_request`, bo widżetu nie da się nadpisać w tym samym przebiegu).
- **Strony szczegółów nie mają wpisu** (`visibility="hidden"`): *Trasy*
  i *Trening* (`bieg`) — otwierane z list, globu i linków.
- **Wchłonięte strony**: Aktywności → „Wszystkie treningi” pod globem na
  *Historii* (`activities.log`: cała historia bez względu na zakres, filtr
  pigułkami po kategorii `catalog.category_of`, na telefonie przed „Szczegółami”) + dwa wykresy biegowe na przeglądzie biegania
  (`activities.run_charts`); Trendy → długość snu na *Śnie*, kroki, masa ciała
  i tabela tygodniowa na dole *Regeneracji*, VO2max obok prognoz Garmina na
  *Prognozie* (`trends.*`, `physio.predictions`). Atlas nie ma już kafli HRV
  i obciążenia — ich domem jest Regeneracja i Obciążenie.
- **Prowadzenie gościa (`ui/guide.py`)**, wołane przez router wokół każdej
  strony: pytanie nad tytułem (`eyebrow`), pasek **Dalej** na dole
  (`next_steps`: stałe `NEXT`, na *Dziś* liczone ze stanu — brak startu, start
  ≤ 6 tyg., słaba noc) i przewodnik „Jak czytać ten dashboard” na *Dziś* do
  schowania (`tour_done` w `data/ui.json`; przycisk w menu Laboratorium przywraca).
- **Strona domyślna ma w Streamlicie `url_path == ""`** — dlatego `_page`
  przechodzi przez `routing.named`, a router pyta `routing.name(page)`. Bez tego
  `routing.goto("dzis")` nie znajdował strony.

### Strona = nagłówek-wniosek, pętla, jeden wykres główny (`ui/story.py`, 2026-11-02)

Przebudowa po badaniach (Li/Dey/Forlizzi 2010 — samoobserwacja jako cykl łączący
sfery życia; Segel & Heer 2010 — najpierw prowadzić, potem pozwolić zwiedzać;
Borkin i in. 2015 — tytuł-przekaz i adnotacje przy danych pomagają zapamiętać;
NN/g — przyciski bez wypełnienia słabo sygnalizują klikalność). Użytkownik wybrał
makiety: bez prostokątów, pętla po prawej od tytułu, przyciski „C”, całość
wyśrodkowana, strona mieści się w jednym ekranie.

- **Brak szyny bocznej**: `st.navigation(position="hidden")`. Górna linia
  (`story.topbar`): Dzień, Dziś, Historia, menu Laboratorium (Fizjologia
  i narzędzia, status hurtowni, przewodnik), zakres czasu, PL/EN, „Pobierz
  z Garmina” z godziną ostatniego pobrania.
- **Pętla jest nawigacją** (`story.loop`, po prawej od nagłówka): Bodziec
  (Obciążenie: przegląd biegania, obciążenie, sport) → Odpowiedź (regeneracja,
  sen) → Adaptacja (prognoza, fizjologia, segmenty) → Cel (plan i zawody, dziś)
  → kolejny cykl. Każdy etap ma liczbę dnia (`facts.loop_values`) i swoje
  strony; bieżąca świeci. Strony spoza pętli (Dzień, Historia, Lab) pokazują ją
  bez podświetlenia.
- **Nagłówek to wniosek z danych** (`<em>` = liczba w akcencie), pod nim jedno
  zdanie, jak czytać wykres. Liczy go `analysis/facts.py` (zasady jak w `analysis/hero.py`: tylko
  to, co się wydarzyło, względem własnej normy; nic nie radzi).
- **Wykres główny** (`ui/herochart.py` + `ui/components/herochart/chart.js`) — drugi,
  obok globu, wyjątek od „każda figura przez `ui/theme.py`”: Plotly nie umie
  postawić tekstu na marginesie i poprowadzić z niego linii do punktu danych
  bez znajomości szerokości w pikselach (sprawdzone: `axref="x domain"` nie
  działa dla końca strzałki). Spec z Pythona: panele `trend` / `bars` /
  `lines` (+ `format`: `time`, `clock`, `pace`; `invert`: szybciej = wyżej),
  satelity `{side, group, head, text, anchor:{t, v}, go}`. Pasy połączeń
  (`strip: True`) to sąsiednie etapy pętli na tej samej osi czasu, z
  jednozdaniowym „Połączenie:”; jeden kursor przez wszystkie panele. Wykres
  bierze wysokość, którą zostawia okno (`reserve` px na „Szczegóły” i „Dalej”),
  w granicach 240–560 px.
- **Szczegóły**: dotychczasowe kafle strony są pod linkiem „Szczegóły”
  (`story.details`) w warstwie `st.dialog` na całe okno, bez ramek. Kafel, który
  powtarzałby wykres główny, z nich wylatuje.
- Strony z wykresem głównym: Regeneracja (HRV + norma Garmina, poranki po
  mocnym treningu; km/tydz., sen), Przegląd biegania (rok w tygodniach z
  przerwami ≥ 3 tyg. i powrotem; CTL), Obciążenie (CTL/ATL wszystkich sportów;
  TSB, HRV; oba stare widoki w szczegółach), Rytm i sen (długość z normą
  10.–90. percentyl 60 nocy; pora zasypiania, HRV), Prognoza (czas na dystans
  najbliższego startu z 80%, oś odwrócona; km, VDOT), Fizjologia (EF bieg po
  biegu; km, HRV). Strony z nagłówkiem nad dotychczasową treścią: Dziś
  (decyzja dnia), Plan i zawody, Sport (gotowość), Segmenty, Historia.
  Laboratorium — tylko wspólne chrome.
- Pod nagłówkiem strony `bento.header` widoku rysuje mały tytuł sekcji
  (`bento.HEADED`, ustawiane przez `story.head`, zerowane w `story.topbar`).
- **Przyciski „C”, bez prostokątów**: akcja główna — gruba niebieska kreska pod
  słowem (`type="primary"`), reszta — kropkowana; wybór (zakres, język,
  przełącznik widoków) to słowa z niebieską kreską pod wybranym
  (`aria-checked="true"`). `primaryColor` = niebieski wykresów (config.toml
  i `serve.py`), nie czerwień Streamlita.
- **Kafle bez ramek**: tło przezroczyste, cienka linia nad kaflem, bez cienia i
  bez podnoszenia przy najechaniu. Klucze `wgt_`/`kpi_`/`pnl_` zostają.

Zasady układu, które trzymają spójność:

- **Siatka bento (`ui/bento.py`) pod wykresem głównym i w szczegółach — pływające widgety.** Kanwa
  (czarne tło, kafle bez ramek — patrz wyżej) to mozaika na siatce 4 kolumn. Kafel
  zajmuje 1–4 kolumny (`bento.row(2, 2)`, `row(2, 1, 1)` — suma zawsze 4)
  i 1–3 rzędy (`bento.tile(..., rows=2)`). **Kafle nie mają stałej wysokości**
  (stała wysokość = ucięta treść albo przewijanie w środku); rzędy wyrównuje
  CSS w `shell.page_style`: kolumny rzędu rozciągają się do najwyższej, kafle
  rosną (`flex: 1 0 auto` — nigdy nie kurczą się poniżej treści). `rows` ustala
  wysokość wykresu (`bento.chart_height`), dobraną tak, że wykres 2-rzędowy
  z chrome = dwa kafle 1-rzędowe. Szkielet strony: `bento.header` → pasek KPI
  → mozaika → panele. Klucze kontenerów: `wgt_` kafel, `wgthd_` jego nagłówek,
  `kpi_` liczba, `pnl_` panel — CSS wybiera po tych prefiksach.
- **Tabela w kaflu nigdy się nie przewija**: `t.table(df)` pokazuje tyle
  wierszy, ile mieści się w miejscu wykresu (`table_rows`), dokładnie na ich
  wysokość; reszta jest pod ikoną tabeli w nagłówku.
- **Ruch** (CSS, `page_style`): kafle wjeżdżają rząd po rzędzie i kolumna po
  kolumnie (zmienne `--row-delay`/`--col-delay`), wykres odsłania się od lewej
  (kierunek czasu) w chwili, gdy Plotly go narysuje, liczby KPI osiadają na
  końcu; najechanie podnosi kartę i pokazuje ikony nagłówka. Streamlit trzyma
  DOM między rerunami, więc animacja gra tylko przy wejściu na stronę.
  `prefers-reduced-motion` wyłącza wszystko.
- Pułapki CSS: Streamlit daje blokom markdown `margin-bottom: -1rem` — tekst
  w `<div>` (podpis, lista) wylewa się wtedy z kafla, dlatego `page_style`
  zeruje ten margines dla `.tile-caption/.tile-list/.tile-title`; podpis
  podciąga się ujemnym marginesem na **kontenerze elementu**, nigdy na tekście.
  Grupa śladów Plotly to `.cartesianlayer .overplot` (nie `.plot`).
- **KPI zawsze po 4**: `bento.kpis(row, previous, specs)` dla kolumn `daily`
  (podpowiedź z `glossary.FIELDS`), `bento.stat(...)` dla innych liczb,
  `bento.empty_stat` na brakujący slot.
- **Oś czasu dostaje co najmniej 2 kolumny.** Kafel 1-kolumnowy to liczba,
  krótka lista (`bento.bullets`), `theme.spark` albo wykres bez osi czasu.
  Kafel 1-rzędowy mieści jeden wykres — dwa panele `stacked_panels` wymagają
  `rows=2`.
- **Kafel ma własne chrome**: tytuł, jednozdaniowy `caption` (dzisiejsza liczba
  i jej status albo *po co* jest kafel), a w nagłówku ikony „?” (`terms` +
  `how=` — opis znaczników wykresu idzie tu, nie do podpisu) i tabeli danych
  (`t.chart(fig, table=...)`). Kontrolki sterujące jednym kaflem (wybór nocy,
  metryki) idą do `with t.header:` z `label_visibility="collapsed"`, żeby nie
  zjadały wysokości wykresu; przejście na inną stronę to ikona strzałki tamże.
  `t.chart` nadpisuje wysokość figury (`bento.chart_height`).
- **Formularze, edytory, długie tabele i proza → `bento.panel`**: ten sam
  wygląd, wysokość według treści (Plan, Zawody, SQL, Insights, Słownik).
- Nowy wskaźnik = nowe hasło w `ui/glossary.py` (co / po co / jak czytać);
  `tests/test_glossary.py` pilnuje, że każdy klucz z `terms=[...]` istnieje.
  Wszystko widać też na stronie *Słownik*. Tytuł nigdy nie idzie do figury.
- *Dzień* (`views/day.py`) jest stroną startową — patrz „Strona Dzień” niżej.
  *Dziś* (`views/today.py`) to **jedyna odpowiedź na „co
  dziś”**: decyzja dnia to `coach.next_session`, przyciski kafla wołają
  `plan.soften` / `plan.postpone` (pojedyncza sesja, z regułą „mocne dni nie
  sąsiadują”); kafel „Poza bieganiem” bierze ranking z `sport/` — w dzień z
  biegiem tylko dodatek, w dzień bez biegu dwie propozycje.
- Glob na *Historii* zostaje poza kaflem (hero na pełną szerokość w `globe_stage`,
  na płaskim tle — bez poświaty), reszta strony to zwykła mozaika i Dziennik.
- **Chrome w górnej linii** (`story.topbar`): strony codzienne, Laboratorium,
  jeden globalny zakres czasu (`shell.range_picker`), język i pobieranie
  (`shell.pull_inline`); status hurtowni w menu Laboratorium.
- **Dane tylko przez `shell.table/query/daily/clip`** — cache jest kluczowany
  znacznikiem builda, więc przebudowa tabel sama unieważnia widok.

### Telefon: ten sam dashboard, krótsza strona (2026-11-05)

Dashboard da się zainstalować na ekranie telefonu jako osobna aplikacja
(`ui/webapp.py`, `docs/DOSTEP.md`) — i wtedy jest to **cała** strona, nie
widżet spod `/api/app/`. Żeby to miało sens na 360 px, działają dwa osobne
mechanizmy. Rozdzielenie jest celowe:

| | co decyduje | gdzie | czego dotyczy |
|---|---|---|---|
| **układ** | szerokość okna (`@media (max-width: 760px)`) | `shell.page_style` | jak rzeczy **stoją** |
| **treść** | nagłówek żądania (`shell.phone()`) | `story.second` w widokach | co się w ogóle **rysuje** |

**Dlaczego nie jeden.** Streamlitowe kolumny **nie zawijają się same** — rząd
bento z czterech kafli zostaje czterema i przy 360 px daje 68 px na kafel. To
właśnie było „rozjeżdża się”. Naprawia to CSS i tylko CSS, bo przeglądarka zna
szerokość, a serwer nie. Ale CSS umie wyłącznie przestawiać: kafel schowany
`display: none` jest nadal policzony i wysłany, a na telefonie chodzi o to, żeby
**mniej rysować**, nie żeby więcej ukrywać. Decyzję „czego nie licz” może podjąć
tylko Python, a jedyne, co serwer wie o ekranie, jest w żądaniu —
`st.context.headers` (bez komponentu, bez reruna, bez drugiego malowania).
Szerokość zmierzona w przeglądarce przyszłaby o jeden rerun za późno, a pierwsze
malowanie byłoby i tak stroną na biurko.

Reguły układu (blok `@media` w `page_style`):

- Zawijają się **tylko rzędy kolumn** — selektor ma
  `:has(> [data-testid="stColumn"])`. Kontener poziomy (nagłówek kafla,
  górna linia) to ten sam `stHorizontalBlock`, a on musi zostać w jednej linii.
  Test tego pilnuje (`tests/test_phone.py`).
- Kolumna bierze całą szerokość, **z jednym wyjątkiem: pasek KPI idzie po dwa**
  (`flex: 1 1 38%`). Zasada „KPI zawsze po 4” mówi o czterech kaflach w pasku,
  nie o czterech w jednej linii — cztery liczby jedna pod drugą to ekran
  przewijania na cztery liczby.
- Stagger kolumn jest zerowany (`--col-delay: 0ms`): po spłaszczeniu obie osie
  opóźnienia biegną w dół strony i ostatni kafel czekałby ponad pół sekundy.
- Glob wychodzi poza tekst o padding strony, nie o 3,5rem; „Szczegóły” to pełny
  ekran (dialog z marginesem na telefonie to listwa).

Reguły treści:

- `story.second(label, render, key=...)` to **jedyna dźwignia**, jakiej strona
  używa, żeby być stroną na telefon. Nad zgięciem zostaje to, co odpowiada na
  pytanie strony — nagłówek, cztery liczby, jeden wykres; wszystko inne idzie do
  `second`. Na biurku nic się nie zmienia (`render()` w miejscu), na telefonie
  ląduje za „Szczegóły” i **nie jest liczone, dopóki nikt nie naciśnie** —
  dlatego bierze funkcję, a nie blok `with`.
- **Nawigacja schodzi do szuflady** (`ui/drawer.py`, 2026-11-05): hamburger
  w lewym górnym rogu otwiera szynę Streamlita z **wszystkimi** stronami,
  a z samej strony znika to, co ją obramowywało — linki górnej linii, menu
  *Laboratorium*, pętla pod nagłówkiem i pasek „Dalej”. Razem były ekranem
  chrome'u nad i pod tym, po co się wchodzi: pętla stacknięta pod nagłówkiem to
  dwanaście słów nad wykresem, a linki i ustawienia w jednej linii na 360 px
  zawijały się na dwa–trzy rzędy. W górnej linii zostaje tytuł strony.
- **Kolejność w szufladzie to model aplikacji**, nie alfabet: *Na co dzień* →
  cztery etapy pętli, każdy ze swoją liczbą dnia → *Laboratorium* → *Widok*
  (zakres, język) → *Twoje dane* (Konto, pobranie, wylogowanie). Każda strona
  raz — ta z dwóch grup (Sport, Fizjologia) zostaje w pierwszej. Test pilnuje,
  że żadna strona z menu nie wypadła z listy (`tests/test_phone.py`), bo na
  telefonie nie ma drugiej drogi.
- **Szuflada to Python, nie `@media`** (`shell.phone()`), jak reszta treści: tak
  samo działa `?layout=phone` na biurku, czyli da się ją obejrzeć bez telefonu.
  Szyna i hamburger to chrome Streamlita, do którego sięga tylko CSS — dlatego
  reguły, które je odsłaniają, siedzą w osobnym bloku (`shell.drawer_style()`:
  `_DRAWER` + `_DRAWER_PHONE` albo `_DRAWER_WIDE`), który `drawer.render`
  wysyła **tylko** wtedy, gdy szuflada faktycznie się rysuje (nie na ekranie
  logowania ani w onboardingu). Idzie przez `st.html` z samym `<style>`:
  Streamlit kładzie go do kontenera zdarzeń, poza rzędy strony i **za**
  `page_style` w DOM — `<style>` w samej szynie przegrałby z ogólnym
  `display: none`, bo szyna stoi w DOM przed stroną. Hamburgera robi ligatura
  `menu` w `::after` (natywny przełącznik to podwójny szewron).
- **Na biurku szuflada jest dodatkowo** (2026-11-06): ta sama lista stron
  i pętla z liczbami dnia, obok górnej linii, która zostaje bez zmian. Bez
  widżetów — zakres, język, pobranie i wylogowanie są w górnej linii (patrz
  niżej). Hamburger stoi na stałe w lewym marginesie, szyna (260 px) odsuwa
  stronę zamiast ją przykrywać i **nie zamyka się** po kliknięciu linku — na
  szerokim ekranie jest na nią miejsce; zamyka ją kliknięcie **poza** nią
  (`drawer._CLOSE_OUTSIDE`, liczy się tylko przy otwartej szynie, więc klik
  w hamburgera jej nie zamyka). Kliki wewnątrz ramek komponentów (wykres
  główny, glob) nie dochodzą do dokumentu i jej nie zamykają. Menu „⋮” Streamlita zostaje.
- **Widżet stoi w jednym miejscu, nie w dwóch**: zakres, język, pobieranie
  i wylogowanie na telefonie rysuje szuflada, a na biurku górna linia — nigdy
  oba w jednym przebiegu, dlatego wystarcza jeden klucz (dwa widżety na jednym
  kluczu to wyjątek Streamlita, a kopia z własnym rozjeżdża się ze stanem).
- Link w szynie **nie zamyka jej sam** (robi to tylko wbudowane menu stron
  Streamlita, którego tu nie ma): jeden delegowany `click` na dokumencie klika
  „Collapse sidebar”, gdy dotknięto linku w szufladzie. Zakres i język są z tego
  wyjęte — ustawienie zmienia się czasem dwa razy pod rząd.
- Stron z `story.frame_page` (*Regeneracja*, *Sen*, *Prognoza*, *Fizjologia*,
  *Bieganie*, *Plan*) **nie trzeba ruszać**: nagłówek + hero + „Szczegóły” jest
  już krótką stroną. `second` dostały te, które sypały kafle wprost na stronę:
  *Dziś*, *Sport*, *Obciążenie biegowe*, *Statystyka*, *Historia*.
- *Dzień* (strona startowa, czyli `start_url` ikony) ma własny tryb wąski
  w komponencie od początku: mapa na górze, fakty listą pod nią.

`?layout=phone` i `?layout=wide` wymuszają wybór i zostają zapamiętane na
zakładkę — tak się ten układ przegląda bez telefonu w ręku i tak telefon może
poprosić o całość. Tablety (Android bez „Mobile”, iPad) dostają całość.

**Wykres główny czyta się palcem.** `herochart` miał tylko `onmousemove`, więc
na telefonie był obrazkiem, z którego nie dało się odczytać ani jednej wartości.
Teraz zdarzenia wskaźnika: dotknięcie czyta dzień pod palcem, przeciągnięcie
przesuwa kursor, mysz nadal czyta na hover. Nic nie woła `preventDefault` —
palec, który zaczął na wykresie, musi dalej przewijać stronę. Odczyt zostaje na
ekranie po podniesieniu palca (palec nie ma „leave”); czyści go dotknięcie poza
wykresami. Prostokąt scenki jest mierzony w chwili odczytu, nie przy renderze —
między jednym a drugim strona się przewija, a dymek postawiony według starego
prostokąta ląduje poza wykresem.

## Zespół: karteczki trenera (`views/team.py`, 2026-11-08)

Strona tylko dla trenera (ktoś jest wpisany przy innych jako `coach`). Jedna
karteczka na zawodnika, posortowane „kto potrzebuje uwagi” (`analysis/team.py`).
Kolor papieru to stan (skala porządkowa, jednolite kolory, bez gradientów): koral —
uwaga (2+ sygnały regeneracji albo 2+ opuszczone sesje w 7 dni), żółty — do
obserwacji (jedno z tych albo bieg ponad regułę 30 dni), szary — bez danych od 2+
dni (dzień bez zegarka to nie zła noc), miętowy — w normie; przerywana ramka — brak
zgody (tylko imię). Na karteczce: dzisiejsza sesja (✎ = ustawiona przez trenera),
regeneracja wobec **własnej** normy (Δ HRV i tętna spocz. od średniej 7 dni, sen wobec
mediany 28 dni — nigdy wartości dwóch osób obok siebie), tydzień zrobione/plan,
ostatni bieg, najbliższy start, powody stanu, ✉ nieprzeczytane notatki.
„Otwórz” = cały dashboard zawodnika w zakresie jego zgody, z paskiem „Patrzysz na …”
(`ui/coaching.bar`); „Notatka” = wątek widoczny też u zawodnika na *Dziś*.
Na telefonie po jednej, prosto (obrót tylko na biurku). Karta liczy się z tabel
zawodnika w `tenant.use(id)`, cache kluczowany jego `build_id` i plikami planu.

## System wykresów (`ui/theme.py`)

Każda figura w dashboardzie powstaje przez buildery z `ui/theme.py`. Nie dodawaj
`px.*` ani `go.Figure` bezpośrednio w `app.py` — paleta, marginesy i hover
rozjadą się w ciągu jednego PR-a.

**Żadnych gradientów. Nigdy.** Ani w tle strony, ani w kaflach (także
„refleks” czy „połysk”), ani za globem, ani na canvasie globu, ani w
wykresach. Wszystko to jednolite kolory: czarna strona, grafitowe kafle
(`#1a1c20`), płaski ocean. Głębię dają krawędź, cień i odstęp — nie przejście
tonalne. Użytkownik odrzucał to trzy razy; nie proponuj gradientu jako
„ciekawego tła”.

Trzy reguły wymuszone strukturalnie:

1. **Żadnych tytułów wewnątrz figury.** Tytuł to nagłówek kafla (`bento.tile`) nad
   wykresem (`heading()`); tytuł plotly i legenda u góry walczą o ten sam pas
   i nachodzą na siebie.
2. **Żadnych podwójnych osi.** `timeseries` przyjmuje jedną oś wartości; dwie
   wielkości o różnej skali idą do `stacked_panels` (małe wielokrotności na
   wspólnej osi X). Dopasowanie dwóch skal Y jest arbitralne i zmyśla korelacje.
3. **Kolor według zadania**: tożsamość → paleta kategorialna (max 3 serie),
   wielkość → jedna rampa niebieska jasno→ciemno, biegunowość → niebiesko-czerwona
   z szarym środkiem, kategorie uporządkowane (fazy snu, strefy HR) → rampa
   porządkowa.

Buildery: `trend`, `range_bars`, `trail`, `hbars`, `timeseries`, `bars`,
`stacked`, `scatter`, `heatmap`, `stacked_panels`, `route_map`, `profile`;
dekoratory `band`, `threshold`, `zero_lines`; wspólna legenda nad grupą wykresów
`key(...)`; render w kaflu przez `t.chart(fig, table=...)` (poza siatką:
`show(fig, table=..., note=...)`), który dokłada
bliźniaczy widok tabelaryczny.

**Domyślny idiom dla dziennej metryki to `trend`**, nie `timeseries`: dni jako
blade kropki, średnia krocząca jako jedyna wyraźna linia, osobista norma jako
szary pas, ostatnia wartość podpisana na końcu linii. Surowa seria narysowana
pełną linią (piła 90 odcinków + pomarańczowa średnia na wierzchu) to dokładnie
to, co sprawiało, że dashboard wyglądał jak arkusz z 2005 roku. Kolejne zasady:

- Zakres dnia (Body Battery min–max, okno snu) → `range_bars`; `clock=True`
  daje oś godzin z wieczorem u góry.
- Ranking kategorii (miejsca) → `hbars`, nie pionowe słupki z ukośnymi etykietami.
- Udział części w czasie przy > 30 okresach → `stacked` sam przechodzi w warstwy
  (`area`), bo 90 słupków ze szczelinami to kod kreskowy.
- Fazy snu → `sleep_stage_colors()`, intensywność → `intensity_colors()`
  (łatwo / środek / mocno). Pięć sąsiednich odcieni niebieskiego jest nie do
  odróżnienia — nie wracaj do `ordinal_colors` dla tych dwóch zbiorów.
- Daty na osiach są w języku interfejsu (`local_dates`, wołane przez buildery samo);
  wykres zbudowany ręcznie przez `go.Figure` trzeba przepuścić przez nie jawnie.
- Kafelki KPI (`bento.kpis`) porównują z `shell.week_before(frame)` i mają
  czwarte pole `delta_color`: `"inverse"` dla tętna spoczynkowego / stresu,
  `"off"` dla zmęczenia i ilorazów obciążenia.

Zachowania, które wyglądają jak magia, ale są celowe:

- `scatter` **porzuca kanał koloru**, gdy kolumna ma pokrycie < 60% — inaczej
  wykres robi się szary (NaN), a skala rozciąga się na kilku punktach.
- `threshold` **nie rysuje linii**, jeśli próg leży daleko poza zakresem danych —
  rozciągałby oś i spłaszczał wszystkie realne wartości.
- Rampy sekwencyjne są przycinane do kwantyli 5–95%, żeby pojedynczy odstający
  pomiar (postój na światłach w tempie 20 min/km) nie zjadł całej skali.
- Osie mają `automargin`; nie ustawiaj marginesów ręcznie.
- **Aplikacja jest zawsze ciemna, na czarnym tle**: `serve.py` (flagi
  `--theme.*`) i `.streamlit/config.toml` przypinają `theme.base = "dark"`.
  `theme.mode()` najpierw czyta przypięty motyw, dopiero potem
  `st.context.theme.type` — ten drugi zgłasza preferencję przeglądarki, co przy
  jasnym systemie dawało jasny CSS kafli pod białym tekstem ciemnego motywu.
  `theme.backgroundColor` to kolor *wnętrza* widżetów (tabele, popovery) =
  kolor kafla; czarną stronę maluje `shell.page_style`.

## Strona Dzień (hero, `views/day.py`)

Strona startowa: **fakty, nie sugestie**, ułożone wokół jednego biegu — bez
siatki bento. Co zrobić, mówi *Dziś* (wpis niżej); tu jest tylko to, co się
wydarzyło, zawsze na tle własnej normy.

- **Który bieg**: dzisiejszy, jeśli już był (`hero.pick_run`); inaczej ostatni
  sprzed dziś, wyblakły, a nagłówek mówi o sesji z planu (albo o ostatnim biegu,
  gdy planu nie ma). Stan w `payload["state"]`: `done` / `planned` / `rest`.
- **Fakty** (`analysis/hero.py`, czyste pandas, testy w `tests/test_hero.py`): bieg
  (podsumowanie, najważniejszy fragment — powtórzenia z `workouts.reps`, inaczej
  dryf tętna ≥ 6 uderzeń przy tym samym tempie ±3%, postoje, najszybszy pełny km,
  porównanie z poprzednim biegiem ±15% dystansu), przerwa od ostatniego biegu,
  sesja z planu, najbliższy start, noc wobec 7 poprzednich nocy (sen, pora snu
  z `circadian`, fazy), HRV w % wobec 7 nocy (**nie** `hrv_deviation` — to ms),
  Body Battery/readiness, ciekawostki (rotowane kliknięciem). Każdy ma
  `priority`; fakt z miejscem na trasie ma `anchor` (`km` albo `lat`/`lon`).
- **Układ liczy przeglądarka** (`ui/components/hero/hero.js`): ślad na siatce
  zajętości 8 px z otoczką, transformata odległości, a każdy fakt (po
  priorytecie) bierze wolny prostokąt, który najciaśniej przylega do śladu —
  kilka bliskich krawędzi wygrywa, więc tekst wchodzi we wcięcia i do środka
  pętli. Fakt z kotwicą chce być blisko swojego miejsca, a jego linia nie może
  przecinać cudzego tekstu. Wszystkie szerokości bloku (250…140 px) konkurują
  naraz. Tekst wyrównuje się do strony, po której jest ślad.
- **Mniej faktów na mniejszym ekranie** (`capacity`): ≥ 1400 px szerokości
  komponentu 12, ≥ 1200 — 10, ≥ 1000 — 8, mniej — 6 (ciekawostka liczy się jako
  jeden); czego nie da się zmieścić, wypada od końca. Poniżej 720 px mapa na
  górze, fakty listą pod nią.
- Kolor śladu = strefy tętna biegu (`hero.zone_edges`: `zone_lthr`/`zone_vt1` z `zone_time`),
  Z1–Z3 niebieskie, Z4–Z5 kolory statusu. Klik w fakt otwiera stronę (`go`:
  bieg, sen, regeneracja, plan/zawody, atlas); licznik `clicks` jak w globie.
- Ładunek jest cache'owany po buildzie, dniu, języku i stemplu plików trenera;
  zmiana `token` (build/dzień/język) rysuje ślad od nowa, zwykły rerun nie.

## Odtwarzacz aktywności (opcja „▶ Odtwórz” w kaflu Mapa)

`ui/replay.py` + `ui/components/replay/index.html`: kropka biegnie trasą, ślad za nią ma
kolor wybranej miary (tempo / tętno / wysokość — przełącznik jest w komponencie, więc
zmiana koloru nie restartuje przebiegu Streamlita), obok liczą się dystans, czas,
tempo z ostatnich 30 s, tętno, wysokość, podejście i kadencja z tej chwili, a pod mapą
jest suwak do przewijania.

**Trzy wykresy w drugiej kolumnie** (`replay.charts`, `ui/components/replaycharts/`):
tempo, tętno i wysokość naraz, jeden kursor przez wszystkie. W trybie „Odtwórz” stoją
obok mapy w miejscu dawnego samotnego profilu wysokości (`routes.streams_tile`, na stronie
biegu i w Trasach), poza nim to zwykły wykres Plotly wzdłuż dystansu. Mapa i wykresy
rozmawiają w przeglądarce przez `BroadcastChannel("garmin-replay-<id aktywności>")`:
mapa trzyma zegar i publikuje `pos`, wykresy odsyłają `seek` (dotknięcie lub przeciągnięcie
przewija film) — żaden z tych ruchów nie przeładowuje Streamlita. Tryb poznaje się po
stanie przełącznika koloru (`<key>_colour` == `"replay"`).

- **Prędkość to całe wielokrotności zegara**: `replay.SPEEDS` = ×10 (domyślnie: 10 s
  aktywności na 1 s filmu), ×30, ×60, ×120, ×300. Przeglądarka liczy pozycję z zegara
  (`requestAnimationFrame`), więc szybciej = większy skok na klatkę, nie rzadsze klatki.
- Python wysyła tylko równoległe tablice (`payload`): jeden zegar rosnący monotonicznie,
  luki w strumieniach wypełnione, strumienia, którego zegarek nie zapisał, nie ma wcale.
  Bez zegara przy śladzie opcji „Odtwórz” nie ma.
- Kafelki OSM i ciemny filtr jak na płaskiej mapie globu; mapa jest stała (bez zoomu
  i przesuwania), więc palec przewija stronę. Kolory kroków rampy jak w `route_map`
  (7 kroków, bez gradientu), postój to stojąca kropka.
- Pierwsza wersja grała w klatkach Plotly: każda klatka niosła cały ślad, więc szybki
  film z długiego biegu ważył megabajty, a kolor śladu i liczby na żywo się nie mieściły.

## Glob na stronie Historia (`atlas`)

Hero Atlasu nie jest figurą plotly — to własny komponent Streamlita
(`ui/globe.py` + `ui/components/globe/`). Powód jest wydajnościowy: obracający się
glob w plotly trzeba przerysowywać po stronie serwera, a `st.fragment(run_every=…)`
to pełny rerun, przebudowa figury i round-trip po websockecie **na każdą
klatkę**. Tutaj animacja jest w przeglądarce i serwer nie robi nic, dopóki
nikt nie kliknie.

Jak to jest poskładane:

- **Rzutowanie i klipowanie robi `d3-geo`**, zwendorowane w `ui/components/globe/vendor/`
  (nigdy CDN — glob ma działać offline). To świadome cofnięcie własnej
  implementacji: przycięcie wielokąta do widocznej półkuli nie jest małym
  problemem. Kiedy kontur wychodzi poza tarczę, musi wrócić wokół horyzontu
  właściwą stroną, a ani „krótszym łukiem", ani „zgodnie ze zwrotem w miejscu
  przecięcia" nie jest poprawną regułą — Afryka i Eurazja to **jeden**
  wielokąt owijający ponad połowę horyzontu, więc pierwsza reguła wycina
  w kuli kliny (widoczne, gdy patrzysz od bieguna), a druga zalewa ją lądem.
- `ui/components/globe/globe.js` trzyma tylko to, o czym d3 nie ma zdania:
  klastrowanie, animację (`requestAnimationFrame`, pętla zatrzymuje się, gdy
  nie ma czego animować) i obsługę myszy.
- `ui/components/globe/world.json` — Natural Earth 110 m jako GeoJSON
  (MultiPolygon + MultiLineString), współrzędne do 0,01°, oczka < 1,2° wycięte
  (112 KB). Przeglądarka pobiera go raz i trzyma we własnym cache.
- **Mapa ciepła** (od ×14 w górę): glob zamienia starty na ślady GPS, każdy
  odcinek w jednej z 5 klas „ile różnych treningów tędy przeszło” (siatka 20 m,
  sąsiedztwo 3×3, żeby kilka metrów rozrzutu GPS nie rozbijało korytarza na
  równoległe nitki), z obwódką w kolorze tła. **Liczenie jest w przeglądarce**
  (`computeHeat` w `globe.js`): Python wysyła tylko listę wybranych
  `activity_id`, więc filtr sportu nie kosztuje serwera nic. Same ślady
  `globe.tracks_url` zapisuje raz na build do `ui/components/globe/cache/`
  (gitignorowane — to te same ślady GPS co `data/`) jako statyczny plik
  (~400 KB, delta-kodowane inty 1e-5°), który przeglądarka trzyma w cache.
  Od ×4 (płaska mapa) glob przestaje się kręcić; siatka południków jest tylko na kuli.
- **Glob jest domyślnie widoczny**; przełącznik „Pokaż glob” w Atlasie zostaje,
  żeby dało się go schować.
- **Filtry nad globem**: *Kadr* (okolica / świat / miasta — `globe.place`
  dobiera zoom do kwantyli 4–96% śladów) i *Sport*. Strona *Trasy* nie ma już
  osobnej mapy gęstości — to jest ta mapa.
- **Strona *Trasy* nie ma wpisu w menu** (`st.Page(..., visibility="hidden")`):
  to szczegół jednej aktywności (mapa kolorowana metryką, profil, strumienie),
  otwierany klikiem w wiersz Dziennika (pod globem na *Historii*), w trening na globie
  i przyciskiem „Mapa trasy” w *Treningu*; dla biegu ma powrót „Analiza
  treningu”. Jedyny widok szczegółów dla sportów innych niż bieg.
- **Zoom**: kółko myszy, pinch na touchpadzie (Chrome/Firefox: ctrl+wheel,
  Safari: `gesture*`), pinch dwoma palcami na ekranie dotykowym, dwuklik
  i przyciski + − ○; 1×–40000×. **Punkt pod kursorem zostaje pod kursorem**:
  `setZoom` po zmianie skali dociąga obrót, aż ten sam punkt wróci pod wskaźnik.
  (Wcześniej każde zdarzenie przenosiło środek na punkt pod kursorem — touchpad
  wysyła ich dziesiątki na sekundę, więc obraz skakał.) Klastry markerów mają
  **poziomy**: siatka (26 px w stopniach) zmienia się tylko przy podwojeniu
  zoomu, a każdy poziom dzieli komórki poprzedniego na pół — grupa rozpada się
  na swoje części, zamiast tasować się przy każdym zdarzeniu. W trakcie zoomu
  markery bledną (`markerAlpha`) i wracają ~0,2 s po ostatnim zdarzeniu, więc
  przejście między poziomami dzieje się pod przygaszeniem. Na płaskiej mapie
  start to adnotacja: kropka dla jednego treningu, małe kółko z liczbą dla grupy.
- **Od ×4 (`FLAT_ZOOM`) glob staje się płaską mapą**: Mercator w ramce
  z zaokrąglonymi rogami, skala w środku dopasowana do kuli (`s = R·cos φ`),
  więc przejście nie skacze. Pod spodem kafelki **OpenStreetMap**
  (`tile.openstreetmap.org`, bez klucza, z atrybucją w `index.html`) — przygaszone
  filtrem canvas w jasnym motywie, odwrócone w ciemnym. Rastrowe kafelki CARTO
  (`light_all`/`dark_all`) odpowiadają dziś obrazkiem „API KEY REQUIRED”, stąd
  OSM. Bez internetu płaska mapa pokazuje zwendorowany kontur lądu.
  Brakujący kafelek zastępuje najbliższy wczytany przodek (rozmyty na chwilę,
  zamiast błysku oceanu). Przeciąganie na płaskiej mapie idzie dokładnie za ręką.
- **Klik**: pojedynczy trening to link — Atlas od razu przechodzi na *Trasy*
  z tym `activity_id`. Skupisko to pytanie — dialog z listą treningów.
  Licznik `clicks` w wartości komponentu odróżnia nowe kliknięcie od tej samej
  wartości po rerunie; bez niego dialog otwierałby się w kółko.
- `globe.starts(frame, build)` — ładunek (jeden wiersz na aktywność, ~34 KB)
  jest `@st.cache_data` kluczowany **id builda hurtowni**, więc liczy się po
  nowych aktywnościach, a nie przy każdym rerunie.
- Nawigacja idzie przez `ui/routing.py`, nie przez link do `/trasy`: link to
  przeładowanie przeglądarki i utrata globalnego zakresu czasu.

Podgląd renderera bez Streamlita (tak sprawdzasz artefakty — zrzut ekranu
z headless Chrome na konkretnym ujęciu):

```bash
.venv/bin/python -m http.server 8777 --directory ui/components/globe
# http://127.0.0.1:8777/test.html?lat=85            (bieguny — tu wychodzą kliny)
# http://127.0.0.1:8777/test.html?lat=-85
# http://127.0.0.1:8777/test.html?lat=52&lon=21&zoom=12&theme=dark
# ?zoom=250&tracks=cache/tracks-<build>.json  (płaska mapa + mapa ciepła; tiles=off bez kafelków)
# ?pinch=1                                    (tytuł strony = dryf punktu pod kursorem)
# ?from=&to= zawęża ląd do wycinka wielokątów (bisekcja po wadliwym)
```

## Trasy GPS

`etl/fetch.py` pobiera `get_activity_details` na aktywność (jeden request,
payload się nie zmienia, więc pobrany raz zostaje na zawsze) do
`data/raw/details/<activity_id>.json`. `etl/load.py` rozpakowuje je do tabel
`routes` (punkt trasy: `lat`, `lon`, `elevation_m`, `hr`, `speed_ms`,
`pace_min_km`, `distance_km`, `cadence`, `power`, `duration_s` — stoper, `moving_s` — czas w ruchu) i `route_summary`
(bounding box, przewyższenie liczone na wygładzonym profilu).

Mapy wymagają internetu — kafelki idą z CARTO/OpenStreetMap. Zoom liczy się
z bounding boxu po wzorze Web Mercatora dla kafli 512 px (MapLibre); stała
„na oko" zostawia trasę jako kropkę na środku mapy.

`route_map` rysuje **linie, nie punkty** — i to jest wymóg, nie styl:

- `route_map` koloruje sam ślad: każdy odcinek dostaje odcień wartości
  z jego początku (7 traców, bo plotly koloruje linię per trace). Markerów
  nie ma, bo ciąg kropek rozjeżdża się przy przybliżaniu na oddzielne
  koraliki; pod spodem leży szeroka, blada linia spinająca kształt, a hover
  siedzi na **niewidocznej** warstwie markerów (`opacity=0`), żeby wartości
  dało się odczytać punkt po punkcie bez stawiania kropek z powrotem.
- Mapa wszystkich śladów naraz żyje na globie w Atlasie (patrz wyżej). Wcześniej
  była tu mapa plotly z półprzezroczystymi liniami — po przybliżeniu rozpadała
  się na blade nitki zlewające się z ulicami podkładu, stąd liczenie przebiegów.
- Podkład map plotly idzie za motywem: `carto-darkmatter` w ciemnym (jasny raster
  w ciemnym kaflu wyglądał na wklejony zrzut), `carto-positron` w jasnym.
  `route_map` dobiera paletę do podkładu; na ciemnym rampa zaczyna się od 3.
  stopnia, bo dwa najciemniejsze toną w kafelkach mapy.

## Fragmenty i stan mapy

Bloki z własnymi kontrolkami (eksplorator tras, mapa doby, heatmapa korelacji,
ACF, dzień tygodnia) są oznaczone `@st.fragment`: zmiana ich widżetu przelicza
tylko ten blok, nie całą stronę.

Mapy dostają `uirevision`:

- ślad trasy — `f"route-{activity_id}"`, więc **zmiana kolorowanej metryki
  zachowuje zoom i przesunięcie**, a zmiana aktywności świadomie je resetuje;

Glob nie ma `uirevision`, bo nie jest figurą plotly — jego kąt żyje w JS
(patrz wyżej).

Jeśli dodajesz mapę, ustaw `uirevision` na coś, co zmienia się dokładnie wtedy,
gdy reset widoku jest pożądany. Bez tego każdy rerun wyrzuca użytkownika z powrotem.
