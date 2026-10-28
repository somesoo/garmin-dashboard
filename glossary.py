"""What each number on the dashboard is, why it is there, and how to read it.

One entry per concept, written for a runner rather than a physiologist. Pages
point at entries by key (``shell.lead(..., terms=[...])``, ``shell.metrics``),
and the Słownik page lists them all — so an explanation is written once and
reads the same everywhere.

``TERMS`` is the Polish text; the English one is ``glossary_en`` under the same
keys. Read entries through ``term()``, which picks the interface language.
"""

from __future__ import annotations

from dataclasses import dataclass

import glossary_en
import i18n


@dataclass(frozen=True)
class Term:
    name: str
    what: str
    why: str
    read: str = ""
    group: str = ""


def _group(name: str, items: dict[str, tuple[str, ...]]) -> dict[str, Term]:
    return {key: Term(*parts, group=name) for key, parts in items.items()}


TERMS: dict[str, Term] = {
    **_group("Regeneracja", {
        "readiness": (
            "Readiness (gotowość treningowa)",
            "Ocena Garmina 0–100 złożona z HRV, snu, tętna spoczynkowego, obciążenia z ostatnich dni "
            "i czasu od ostatniego mocnego treningu.",
            "Podpowiada, czy dziś organizm przyjmie mocny trening, czy lepiej zrobić spokojny.",
            "Powyżej ~75 — zielone światło na jakość. 50–75 — normalny dzień. Poniżej ~40 — dzień na luz "
            "albo odpoczynek. Ważniejszy jest ciąg kilku dni niż jeden odczyt.",
        ),
        "hrv": (
            "HRV (zmienność rytmu serca)",
            "Jak bardzo różnią się odstępy między kolejnymi uderzeniami serca, mierzone w nocy (ms). "
            "Wysoka zmienność = układ nerwowy w trybie odpoczynku.",
            "Najczulszy wskaźnik regeneracji: spada po ciężkim treningu, chorobie, alkoholu, stresie.",
            "Liczy się tylko względem własnej normy (szary pas) — wartości różnią się między ludźmi "
            "kilkukrotnie. Kilka dni pod pasem = organizm nie nadąża.",
        ),
        "rhr": (
            "RHR (tętno spoczynkowe)",
            "Najniższe utrzymujące się tętno w ciągu doby, zwykle w nocy.",
            "Rośnie przy zmęczeniu, chorobie, odwodnieniu i upale; spada powoli, gdy rośnie wydolność.",
            "Wzrost o 5+ uderzeń ponad własną średnią to sygnał ostrzegawczy. Tu spadek jest dobry.",
        ),
        "sleep_score": (
            "Ocena snu",
            "Ocena Garmina 0–100: długość, fazy (głęboki, REM), wybudzenia i stres w nocy.",
            "Sen to główne źródło regeneracji — gorsza noc obniża readiness następnego dnia.",
            "80+ dobrze, 60–80 przeciętnie, poniżej 60 słabo.",
        ),
        "body_battery": (
            "Body Battery",
            "Szacunek Garmina 0–100 „ile energii zostało”: ładuje się w czasie snu i odpoczynku, "
            "rozładowuje przy wysiłku i stresie.",
            "Pokazuje, czy noc naprawdę odbudowała zapasy po dniu.",
            "Liczy się szczyt rano (jak dobrze naładowała noc) i dół wieczorem (ile kosztował dzień).",
        ),
        "stress": (
            "Stres",
            "Ocena Garmina 0–100 z HRV w ciągu dnia: wysoka, gdy dominuje układ współczulny "
            "(wysiłek, nerwy, trawienie, kawa).",
            "Dużo stresu w dzień i w nocy spowalnia regenerację niezależnie od treningu.",
            "Średnia dobowa poniżej ~25 jest spokojna. Stres w czasie snu powinien być niski — jeśli nie, "
            "noc nie regeneruje.",
        ),
        "quadrants": (
            "Kwadranty regeneracji",
            "Dzień umieszczony według dwóch odchyleń od własnej bazy 60 dni: HRV (oś pozioma) i tętna "
            "spoczynkowego (oś pionowa).",
            "Razem mówią więcej niż osobno: wysokie HRV przy niskim tętnie to dobra regeneracja, "
            "odwrotnie — obciążenie.",
            "Zregenerowany: HRV ↑ RHR ↓. Obciążony: HRV ↓ RHR ↑ (odpuść). Pobudzony: oba ↑ "
            "(stres, kawa, upał). Stłumiony: oba ↓ (bywa po bardzo dużym zmęczeniu).",
        ),
        "deviation": (
            "Odchylenie od normy",
            "Różnica między dzisiejszą wartością a własną średnią z ostatnich dni.",
            "Porównuje cię z tobą, nie z tabelką — tylko tak HRV i tętno mają sens.",
            "Zero = typowy dzień. Wartości w σ (odchyleniach standardowych): ±1 zdarza się często, ±2 rzadko.",
        ),
    }),
    **_group("Obciążenie i forma", {
        "training_load": (
            "Load (obciążenie treningu)",
            "Liczba Garmina (EPOC) mówiąca, ile treningu „kosztował” organizm — rośnie z czasem i intensywnością.",
            "Wspólna waluta dla różnych treningów: 10 km spokojnie i 5 km interwałów da się porównać.",
            "Spokojny bieg to zwykle 50–100, mocny 150–250+.",
        ),
        "ctl": (
            "CTL — sprawność",
            "Średnia obciążenia z ostatnich ~6 tygodni (wykładnicza, 42 dni).",
            "Pokazuje, ile treningu twój organizm jest przyzwyczajony znosić — to „kondycja” w liczbie.",
            "Rośnie powoli, gdy trenujesz regularnie; spada w przerwie. Wyższa = więcej zbudowanej bazy.",
        ),
        "atl": (
            "ATL — zmęczenie",
            "Średnia obciążenia z ostatniego tygodnia (wykładnicza, 7 dni).",
            "Pokazuje świeże zmęczenie — reaguje na każdy mocny tydzień.",
            "Wyższa niż CTL = ostatnio trenujesz więcej, niż jesteś przyzwyczajony.",
        ),
        "tsb": (
            "TSB — forma (świeżość)",
            "CTL minus ATL: sprawność pomniejszona o zmęczenie.",
            "Przed startem chcesz mieć dodatnie TSB — wypoczęty przy zachowanej sprawności.",
            "Poniżej −30 przeciążenie, −30…−10 budowanie formy (normalne w treningu), −10…+5 neutralnie, "
            "+5…+25 świeżość (dobry moment na start), powyżej +25 roztrenowanie. To model, nie pomiar.",
        ),
        "ramp": (
            "Przyrost CTL / 7 dni",
            "O ile wzrosła sprawność (CTL) w ostatnim tygodniu.",
            "Za szybkie budowanie formy to klasyczna droga do kontuzji.",
            "Do ~5 punktów tygodniowo bezpiecznie; więcej przez kilka tygodni z rzędu — ryzykownie.",
        ),
        "acwr": (
            "ACWR (iloraz obciążenia ostrego do przewlekłego)",
            "Obciążenie ostatniego tygodnia podzielone przez średnie z ostatnich 4 tygodni.",
            "Wykrywa nagłe skoki treningu, które ciało nie zdążyło przyjąć.",
            "0,8–1,3 — przyrost stopniowy. Powyżej 1,5 — skok. Poniżej 0,8 — roztrenowywanie się.",
        ),
        "run_ratio": (
            "Kilometry 7 d / średnia 28 d",
            "Ten sam pomysł co ACWR, ale liczony tylko z kilometrów biegowych.",
            "Ścięgna i kości reagują na kilometry biegu, nie na rower czy siłownię.",
            "0,8–1,3 — spokojny przyrost; powyżej 1,5 — gwałtownie więcej niż zwykle.",
        ),
        "monotony": (
            "Monotonia (Foster)",
            "Średnie dzienne obciążenie w tygodniu podzielone przez jego zmienność.",
            "Tydzień, w którym każdy dzień jest podobny (bez dni lekkich), męczy bardziej, niż wynika z sumy.",
            "Poniżej 1,5 — dobrze przeplatane dni mocne i lekkie. Powyżej 2 — za mało różnicy między dniami.",
        ),
        "strain": (
            "Strain (Foster)",
            "Suma obciążenia tygodnia × monotonia.",
            "Łączy ilość i brak zróżnicowania w jedną liczbę ryzyka przemęczenia.",
            "Porównuj z własnymi tygodniami — skok wyraźnie ponad zwykły poziom jest sygnałem.",
        ),
        "banister": (
            "Model Banistera",
            "Model, w którym każdy trening jednocześnie buduje sprawność (wolno zanika) i zmęczenie "
            "(szybko zanika); dopasowany do twoich danych.",
            "Daje stałe czasowe twojego organizmu i szacunek, ile dni przed startem odpuścić.",
            "Patrz najpierw na R²: poniżej ~0,3 model słabo opisuje twoje dane i liczby pod nim są orientacyjne.",
        ),
        "intensity": (
            "Rozkład intensywności",
            "Jaka część czasu tygodnia minęła w strefach łatwych (1–2), średnich (3) i mocnych (4–5).",
            "Większość postępu u amatorów daje dużo spokojnego biegania i niewiele naprawdę mocnego.",
            "Około 75–80% łatwo to zdrowy model. Dużo strefy 3 to „szare tempo” — za mocno na regenerację, "
            "za słabo na bodziec.",
        ),
        "hr_zones": (
            "Strefy tętna",
            "Pięć przedziałów tętna z ustawień zegarka, od 1 (bardzo lekko) do 5 (maksymalnie).",
            "Pozwalają sprawdzić, czy trening miał zamierzoną intensywność.",
            "Spokojny bieg: głównie 1–2. Próg: 4. Interwały: 4–5.",
        ),
        "te": (
            "Training Effect (TE)",
            "Ocena Garmina 0–5, jak mocno trening pobudził wydolność tlenową i beztlenową.",
            "Mówi, czy trening był bodźcem, czy tylko podtrzymaniem.",
            "Poniżej 2 — regeneracja, 2–3 podtrzymanie, 3–4 poprawa, 4–5 duża poprawa, 5 — przeciążenie.",
        ),
    }),
    **_group("Wydolność", {
        "vo2max": (
            "VO₂max",
            "Szacunek Garmina, ile tlenu organizm potrafi zużyć na minutę na kg masy — sufit wydolności tlenowej.",
            "Najprostsza miara „silnika”; wyższa zwykle oznacza szybsze czasy na każdym dystansie.",
            "Zmienia się w skali tygodni. Skok o 1–2 w kilka dni to zwykle upał, teren albo błąd pomiaru.",
        ),
        "cs": (
            "CS — prędkość krytyczna",
            "Najszybsze tempo, które w teorii da się długo utrzymać bez narastającego zakwaszenia; "
            "liczone z twoich najlepszych odcinków.",
            "Bliskie tempu progowemu — dobra kotwica dla treningów tempowych.",
            "Wiarygodne, gdy R² jest wysokie i dopasowanie stoi na kilku różnych dystansach.",
        ),
        "d_prime": (
            "D′ — rezerwa beztlenowa",
            "Ile metrów można przebiec szybciej niż CS, zanim trzeba zwolnić.",
            "Mówi o finiszu i odcinkach krótszych niż ~10 minut.",
            "Typowo 100–300 m. Rośnie od interwałów, spada, gdy biegasz tylko spokojnie.",
        ),
        "riegel": (
            "Wykładnik Riegla",
            "Jak bardzo zwalniasz, gdy dystans rośnie (czas ∝ dystans^b).",
            "Pokazuje, czy jesteś bardziej „szybki”, czy bardziej „wytrzymały”.",
            "Około 1,06 — dobra wytrzymałość. Powyżej ~1,12 — tempo wyraźnie siada na długich dystansach, "
            "czyli brakuje długich biegów.",
        ),
        "ef": (
            "EF — ekonomia biegu",
            "Metry przebiegnięte na jedno uderzenie serca (prędkość skorygowana o podbiegi ÷ tętno).",
            "Gdy rośnie przy tym samym tętnie, ten sam wysiłek daje więcej prędkości — to postęp.",
            "Patrz na średnią z wielu biegów; pojedynczy bieg zależy od pogody, terenu i snu.",
        ),
        "cadence": (
            "Kadencja",
            "Kroki na minutę (obu nóg).",
            "Bardzo niska kadencja często oznacza długi, „hamujący” krok.",
            "Typowo 160–185 kr/min; rośnie z tempem. Nie ma jednej idealnej liczby.",
        ),
    }),
    **_group("Prognoza i bieganie", {
        "vdot": (
            "VDOT",
            "Jedna liczba wydolności biegowej z tablic Danielsa, wyliczona z czasu na danym dystansie. "
            "Działa jak „VO₂max z wyniku”.",
            "Pozwala przełożyć wynik z jednego dystansu na inny i wyznaczyć tempa treningowe.",
            "+1 VDOT to ok. 1,5–2% szybciej na każdym dystansie. Realnie da się zyskać ok. 1 VDOT na 4–6 tygodni treningu.",
        ),
        "realistic": (
            "Wynik realistyczny",
            "Prognoza czasu przy twojej dzisiejszej wydolności i dzisiejszym przygotowaniu do tego dystansu.",
            "Na ten czas warto planować start, jeśli byłby dziś.",
            "To środek przedziału — tak samo możliwe, że wyjdzie szybciej, jak wolniej.",
        ),
        "potential": (
            "Potencjał",
            "Ten sam czas, ale przy założeniu, że wytrzymałość do dystansu jest w pełni zbudowana.",
            "Pokazuje, ile kosztuje dziś brak długich biegów i kilometrów.",
            "Różnica potencjał − realistyczny to zysk możliwy bez poprawy szybkości, samym treningiem pod dystans.",
        ),
        "after_plan": (
            "Na dzień startu (po planie / jak teraz)",
            "Prognoza na dzień zawodów. Gdy plan obejmuje start: +1 VDOT na ~5 tygodni i przygotowanie, które "
            "plan buduje przed tym startem. Bez planu: dzisiejsze przygotowanie i przyrost formy razy regularność, "
            "wygasający po ~6 tygodniach.",
            "Pokazuje, czy cel jest osiągalny do daty startu — i ile daje plan wobec trenowania jak dotąd.",
            "W nawiasie wariant ostrożny i optymistyczny. Pojawia się tylko dla dystansu z wpisanym startem.",
        ),
        "interval80": (
            "Przedział 80%",
            "Zakres, w którym wynik powinien się zmieścić w 8 startach na 10.",
            "Uczciwie mówi, ile model wie — wąski przedział = dużo dobrych danych.",
            "Co piąty start wypadnie poza nim. Gdy dolna granica jest wyraźnie dalej niż górna, ostatni "
            "wysiłek nie był maksymalny i możesz być szybszy, niż mówi środek.",
        ),
        "confidence": (
            "Pewność prognozy",
            "Skrót szerokości przedziału i jakości kotwicy: ●●● wysoka, ●●○ średnia, ●○○ niska.",
            "Mówi, na ile wierzyć liczbie, zanim ustawisz pod nią tempo startowe.",
            "Wysoka: świeży (≤ 6 tyg.) wysiłek bliski maksymalnego i metody zgodne (przedział ok. ±5%). "
            "Średnia: jest udokumentowany wysiłek, przedział do ok. ±10%. Niska: szerzej — zwykle daleka "
            "ekstrapolacja (np. z 4 km na maraton), słabe przygotowanie albo rozjazd metod. Żeby podnieść: "
            "pobiegnij mocno (start, test) na dystansie bliskim docelowemu.",
        ),
        "preparation": (
            "Przygotowanie do dystansu",
            "0–100%: najdłuższy bieg i kilometry tygodniowo z ostatnich 6 tygodni oraz regularność "
            "względem minimum przyjętego dla dystansu.",
            "Szybkość z 5 km nie przenosi się na półmaraton bez długich biegów — ta liczba to wycenia.",
            "100% = spełnione minimum. Im niżej, tym bardziej realistyczny czas odstaje od potencjału.",
        ),
        "near_max": (
            "Wysiłek bliski maksymalnego",
            "Start albo odcinek, na którym tętno było ≥ 91% maksymalnego przez co najmniej 6 minut.",
            "Tylko taki wynik mówi, na co cię naprawdę stać; spokojny trening to tylko dolna granica.",
            "Pełny punkt na wykresie prognozy = kotwica maksymalna, pusty = dolna granica.",
        ),
        "methods": (
            "Metody prognozy",
            "Trzy niezależne szacunki: z udokumentowanych wysiłków (kotwica), z relacji tętno–tempo "
            "na spokojnych biegach i z prognozy Garmina.",
            "Gdy się zgadzają, przedział jest wąski; gdy rozjeżdżają — szerszy.",
            "Kotwica decyduje o liczbie, pozostałe dwie tylko o niepewności.",
        ),
        "backtest": (
            "Sprawdzenie wstecz",
            "Każdy twój mocny bieg porównany z tym, co model przewidywał tydzień wcześniej.",
            "Jedyny sposób, żeby wiedzieć, ile prognoza jest warta na twoich danych.",
            "Mediana błędu ~5% to dobrze, ~10% — przeciętnie. Dodatni błąd = model był zbyt ostrożny.",
        ),
        "run_kind": (
            "Typ treningu",
            "Etykieta nadana regułami z tętna, tempa i dystansu: regeneracja, spokojny, długi, tempo, "
            "próg, interwały, start.",
            "Pozwala policzyć balans spokojnych i mocnych kilometrów bez ręcznego tagowania.",
            "Powód i pewność etykiety są w szczegółach treningu.",
        ),
        "today_decision": (
            "Decyzja na dziś",
            "Najbliższa sesja z planu (albo propozycja z danych, gdy planu nie ma) zestawiona z sygnałami "
            "regeneracji z ostatniej nocy i z obciążeniem z 7 dni.",
            "Plan układa się tygodniami naprzód, a forma zmienia się z dnia na dzień. Decyzja godzi jedno "
            "z drugim: nigdy nie dokłada więcej, niż plan przewidział, najwyżej odpuszcza.",
            "„Jak w planie” — biegnij. Jeden sygnał przeciw — zacznij i oceń po rozgrzewce. Dwa lub więcej "
            "przy mocnej sesji — zamień na spokojny albo przesuń o dzień. Sygnały starsze niż doba są pomijane. "
            "Gdy dziś nie ma sesji, kafel tylko zapowiada następną — decyzja zapada rano w jej dniu.",
        ),
        "quality_sessions": (
            "Mocne sesje",
            "Treningi typu tempo, próg, interwały i starty.",
            "To one dają bodziec; reszta to baza i regeneracja.",
            "Amatorom zwykle wystarczają 1–2 w tygodniu przy ~75–80% spokojnych kilometrów.",
        ),
        "rep_fade": (
            "Rozjazd odcinków",
            "O ile wolniej był ostatni odcinek workoutu niż pierwszy (s/km) i o ile wyżej szło na nim tętno.",
            "Pokazuje, czy tempo było dobrane do formy: równe odcinki przy lekko rosnącym tętnie to dobrze "
            "rozłożony wysiłek.",
            "Do ~5 s/km i kilku uderzeń — równo. Ostatni wyraźnie wolniejszy przy tętnie pod sufitem — tempo "
            "za ambitne albo za krótkie przerwy. Ujemny rozjazd (przyspieszanie) — był zapas.",
        ),
        "same_route": (
            "Ta sama trasa",
            "Biegi, których ślady GPS pokrywają się w co najmniej 80% (w obie strony, siatka ~50 m) "
            "przy dystansie różnym o najwyżej 15%. Kierunek nie ma znaczenia.",
            "Na tej samej trasie tempo nie zależy od podbiegów ani nawierzchni — porównanie jest uczciwe "
            "także dla długich i spokojnych biegów, które nie mają odcinków z zegarka.",
            "Patrz na tempo razem z tętnem i typem treningu: szybciej przy tym samym tętnie to postęp, "
            "szybciej przy wyższym — po prostu mocniej.",
        ),
        "shared_stretch": (
            "Wspólny odcinek",
            "Najdłuższy kawałek trasy, który ten bieg dzieli z innym (ślady ≤ 35 m od siebie, ten sam kierunek, "
            "co najmniej 400 m) — segment o takiej długości, jaka akurat wyszła, bez rysowania.",
            "Porównuje dowolne dwa biegi na dokładnie tym samym terenie, także gdy całe trasy się różnią.",
            "Czas ze strumienia próbek (kilka sekund dokładności). Postój na światłach liczy się do czasu, "
            "więc pojedynczy duży rozjazd sprawdź na mapie.",
        ),
        "efficiency_delta": (
            "Δ efektywność",
            "Zmiana metrów przebiegniętych na jedno uderzenie serca wobec tamtego biegu, na tym samym odcinku.",
            "Oddziela formę od wysiłku: szybciej przy wyższym tętnie to mocniejszy bieg, szybciej przy tym "
            "samym tętnie — lepsza forma.",
            "Dodatnia = więcej metrów na uderzenie niż wtedy. Porównuj z biegami podobnego typu; upał, wiatr "
            "i zmęczenie przesuwają ją o kilka procent.",
        ),
        "best_effort": (
            "Najlepsze odcinki",
            "Najszybszy ciągły fragment biegu na standardowych dystansach (1 km, mila, 3 km, 5 km, 10 km, "
            "półmaraton, maraton) — wycięty z dowolnego miejsca biegu.",
            "Rekordy powstają też na treningu, nie tylko na zawodach; miejsce w historii pokazuje, jak dobry "
            "był ten bieg.",
            "🏆 = rekord życiowy, 🏅 = najlepszy w ostatnich 365 dniach. Źródło: Garmin albo strumień próbek.",
        ),
        "segment": (
            "Segment",
            "Twój prywatny odcinek trasy, wycięty z jednego biegu (jak segmenty na Stravie, ale nigdzie "
            "nie wysyłany). Bieg go przechodzi, gdy mija start i metę w promieniu 35 m, a cały ślad "
            "między nimi trzyma się trasy segmentu (40 m).",
            "Ten sam podbieg czy prosta w parku pojawia się w wielu biegach różnego typu — segment "
            "pozwala porównać właśnie ten kawałek.",
            "Czas jest ze strumienia próbek (dokładność kilku sekund), tempo liczone na długości segmentu. "
            "Kierunek ma znaczenie: od startu do mety. „auto” = znaleziony sam na trasie przebiegniętej "
            "co najmniej 4 razy; zapisz go jako swój, żeby nadać mu nazwę.",
        ),
        "pace_at_hr": (
            "Tempo przy tym samym tętnie",
            "Prosta tempo ~ tętno poprowadzona przez odcinki wcześniejszych workoutów (2 lata) i odległość "
            "odcinków tego treningu od niej, w s/km.",
            "Porównuje workouty o różnej długości odcinków: 5×800 m biega się szybciej niż 3×2 km, ale przy "
            "tym samym tętnie szybsze tempo to postęp.",
            "Ujemnie = szybciej niż wcześniej przy tym samym tętnie. Średnie tętno odcinka spóźnia się za "
            "wysiłkiem, więc długie odcinki wypadają tu trochę gorzej niż krótkie — porównuj głównie "
            "z podobnymi (kolor w legendzie).",
        ),
    }),
    **_group("Sen i rytm dobowy", {
        "sri": (
            "SRI — regularność snu",
            "Szansa, że o tej samej minucie doby jesteś w tym samym stanie (sen/czuwanie) dwie noce z rzędu.",
            "Regularne pory snu poprawiają jego jakość niezależnie od długości.",
            "100 = identyczne noce. Powyżej ~80 regularnie, poniżej ~60 rozjechany rytm.",
        ),
        "midpoint": (
            "Środek snu i jego rozrzut",
            "Godzina w połowie między zaśnięciem a wybudzeniem; rozrzut to typowe odchylenie z 30 nocy.",
            "Środek snu dobrze opisuje twój chronotyp; duży rozrzut = rozregulowany zegar biologiczny.",
            "Rozrzut poniżej ±0,5 h jest bardzo regularny, powyżej ±1 h — nieregularny.",
        ),
        "social_jetlag": (
            "Social jetlag",
            "O ile później wypada środek snu w weekend niż w tygodniu.",
            "Każdy weekend z przesunięciem działa na organizm jak mała zmiana strefy czasowej.",
            "Do ~1 h jest typowe; powyżej 2 h poniedziałki zaczynają się od „jetlagu”.",
        ),
        "night_profile": (
            "Profil nocy (nadir tętna)",
            "Najniższe tętno nocy i moment, w którym wypadło (procent nocy).",
            "Wczesny nadir = organizm szybko się wyciszył. Późny = długo trawił dzień (późny trening, "
            "posiłek, alkohol).",
            "Nadir w pierwszej połowie nocy to dobry znak.",
        ),
        "hrv_slope": (
            "Nachylenie HRV w nocy",
            "Jak zmienia się HRV od początku do końca nocy (ms na godzinę).",
            "Dodatnie = noc „nadrabiała” i regeneracja postępowała.",
            "Ujemne kilka nocy z rzędu — sen przestaje regenerować.",
        ),
        "sleep_stages": (
            "Fazy snu",
            "Głęboki (regeneracja ciała), REM (regeneracja układu nerwowego, pamięć), lekki, czuwanie.",
            "Proporcje mówią więcej niż sama długość snu.",
            "Głęboki zwykle 13–23% nocy, REM 20–25%. Garmin szacuje fazy z ruchu i tętna, więc pojedyncza noc bywa niedokładna.",
        ),
    }),
    **_group("Statystyka", {
        "r2": (
            "R² (dopasowanie modelu)",
            "Jaką część zmienności danych model wyjaśnia: od 0 (wcale) do 1 (idealnie).",
            "Mówi, czy liczbom wyliczonym z modelu można ufać.",
            "Powyżej ~0,9 dla CS — solidnie. Dla modelu Banistera już 0,3–0,5 bywa dobrym wynikiem; "
            "poniżej ~0,3 traktuj wynik jako orientacyjny.",
        ),
        "correlation": (
            "Korelacja z opóźnieniem",
            "Czy czynnik z jednego dnia (np. sen) wiąże się z odpowiedzią kilka dni później (np. HRV). "
            "ρ od −1 do 1.",
            "Pomaga znaleźć, co naprawdę wpływa na twoją regenerację.",
            "Czytaj q, nie p: q < 0,05 przetrwało korektę na liczbę testów. Brak takich par to też wynik — "
            "korelacja to nie przyczyna.",
        ),
        "acf": (
            "Autokorelacja",
            "Jak bardzo wartość dziś przypomina wartość sprzed n dni.",
            "Mówi, jak długo stan się „utrzymuje” i czy jest rytm tygodniowy.",
            "Słupki poza szarym pasem są istotne. Pik przy 7 dniach = rytm tygodnia (praca, długi bieg w niedzielę).",
        ),
        "changepoint": (
            "Punkt zmiany bazy",
            "Dzień, od którego średnia metryki trwale przesunęła się w górę lub w dół.",
            "Odróżnia prawdziwą zmianę (nowy plan, przeprowadzka, choroba) od codziennego szumu.",
            "Sprawdź, co działo się w życiu w okolicy tej daty.",
        ),
        "weekday": (
            "Efekt dnia tygodnia",
            "O ile dany dzień tygodnia odbiega od średniej, z testem, czy różnice są realne.",
            "Pokazuje nawyki: gorszy sen w niedzielę, wyższy stres w poniedziałek.",
            "p < 0,05 w teście Kruskala-Wallisa = dni tygodnia faktycznie się różnią.",
        ),
    }),
}


# Tiles name the daily column; this maps them onto the entries above.
FIELDS = {
    "readiness": "readiness",
    "hrv_last_night": "hrv",
    "rhr": "rhr",
    "sleep_score": "sleep_score",
    "bb_high": "body_battery",
    "ctl": "ctl",
    "atl": "atl",
    "tsb": "tsb",
    "ramp_7d": "ramp",
    "acwr_ewma": "acwr",
}

# Shared reading of the trend idiom, so section notes do not repeat it.
_TREND_HOW = (
    "Blade kropki to pojedyncze dni, wyraźna linia to średnia krocząca — to ona niesie sygnał. "
    "Szary pas to twoja norma, liczba na końcu linii to ostatnia wartość."
)


def trend_how() -> str:
    return i18n.tr(pl=_TREND_HOW, en=glossary_en.TREND_HOW)


def term(key: str) -> Term:
    """The entry in the interface language."""
    item = TERMS[key]
    if i18n.lang() == "en":
        return Term(*glossary_en.TERMS[key], group=glossary_en.GROUPS[item.group])
    return item


def short(key: str) -> str:
    """One-paragraph tooltip text for a tile or a table column."""
    item = term(key)
    text = f"{item.what} {item.why}"
    return f"{text}\n\n{item.read}" if item.read else text


def why_label() -> str:
    return i18n.tr(pl="Po co", en="Why")


def read_label() -> str:
    return i18n.tr(pl="Jak czytać", en="How to read")


def markdown(key: str) -> str:
    item = term(key)
    lines = [f"**{item.name}** — {item.what}", f"*{why_label()}:* {item.why}"]
    if item.read:
        lines.append(f"*{read_label()}:* {item.read}")
    return "\n\n".join(lines)


def groups() -> dict[str, list[str]]:
    """Keys by group, the group named in the interface language."""
    out: dict[str, list[str]] = {}
    for key in TERMS:
        out.setdefault(term(key).group, []).append(key)
    return out
