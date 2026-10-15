# Garmin Dashboard (lokalnie)

Pobiera dane z Garmin Connect, buduje hurtownię na dysku i hostuje dashboard
na `http://localhost:8501`. Nic nie wychodzi na zewnątrz.

## Uruchomienie

Dwuklik na **`Dashboard.cmd`** — aktualizuje dane od ostatniego pobrania,
przebudowuje tabele, podnosi serwer (jeśli nie działa) i otwiera przeglądarkę.
Skrót do tego pliku możesz wrzucić gdziekolwiek (`Prawy → Utwórz skrót`).

Ręcznie:

```powershell
.venv\Scripts\python.exe etl\run.py              # aktualizacja (14 dni wstecz)
.venv\Scripts\python.exe etl\run.py --backfill    # cała historia
.venv\Scripts\python.exe etl\load.py              # tylko przebudowa tabel
.venv\Scripts\python.exe analytics.py           # tylko modele i statystyka
.venv\Scripts\python.exe -m streamlit run app.py  # tylko serwer
```

## Jak to działa

| warstwa | plik | wynik |
|---|---|---|
| pobieranie | `etl/fetch.py` | `data/raw/<metryka>/<data>.json` |
| transformacja | `etl/load.py` | `daily`, `activities`, `sleep_stages`, `night_series`, `intraday` |
| modele i statystyka | `analytics.py` | `pmc`, `load_weekly`, `critical_speed`, `riegel`, `efficiency`, `correlations`, `acf`, `changepoints`, `weekday_effects`, `circadian`, `sleep_regularity`, `intensity_distribution`, `quadrants`, `models.json` |
| zapytania | `db.py` | DuckDB in-memory z widokami na parquet |
| system wykresów | `theme.py` | paleta, buildery, mapy, glob — jedno miejsce na wygląd |
| widoki | `app.py` + `views/` | router `st.navigation` i 11 stron |

### Co liczy warstwa analityczna

- **Forma**: Performance Management Chart (CTL 42 d / ATL 7 d / TSB), tempo
  narastania CTL, ACWR w dwóch wariantach (kroczący Gabbetta vs wykładniczy
  Williamsa), monotonia i strain Fostera, dopasowanie modelu Banistera
  z własnymi stałymi czasowymi i szacowaną długością taperu.
- **Fizjologia**: prędkość krytyczna i zapas D′ z rekordów odcinków
  (`d = CS·t + D′`), hiperbola prędkość–czas, wykładnik Riegela, ekonomia biegu
  (metry na uderzenie serca), rozkład intensywności z etykietą modelu treningu.
- **Statystyka**: korelacje Spearmana dla lagów 0–7 dni z kontrolą FDR
  (Benjamini-Hochberg), autokorelacja z 95% CI, detekcja punktów zmiany bazy
  (segmentacja binarna z karą BIC), efekt dnia tygodnia z testem
  Kruskala-Wallisa, kwadranty HRV/RHR względem bazy 60-dniowej.
- **Sen i rytm**: hipnogram pojedynczej nocy, nocne przebiegi tętna/HRV/Body
  Battery/stresu, Sleep Regularity Index z minutowego hipnogramu, środek snu
  i social jetlag, mapa doby (godzina × dzień) ze stresu i Body Battery.
- **Trasy**: ślad GPS na mapie kolorowany tempem / tętnem / wysokością, profil
  wysokości, tętno i tempo wzdłuż dystansu, oraz mapa gęstości wszystkich tras.
  Zmiana kolorowanej metryki nie resetuje widoku mapy.
- **Atlas** (strona startowa): obrotowy glob ze skupiskami wszystkich aktywności,
  stan na dziś, ranking miejsc i ostatnie treningi.

Surowy JSON jest źródłem prawdy — mapowanie można przepisać i odtworzyć tabele
bez odpytywania API. Dzień raz pobrany nie jest pobierany ponownie, poza oknem
`RECHECK_DAYS` (Garmin dopisuje dane wstecz).

Hurtownia to pliki parquet, nie plik bazy: ETL może nadpisywać tabele, gdy
dashboard jest otwarty — żadnych blokad.

## Insights

Zakładka **Insights** renderuje pliki z `insights/`: markdown z blokami SQL,
które liczą się na świeżych danych przy każdym odświeżeniu strony.

Nowy wniosek dodaje Claude Code:

```
/garmin-insight hrv vs obciążenie treningowe
```

Format opisuje `insights/_template.md`, schemat danych — `CLAUDE.md`.

## Tokeny

Logowanie idzie z `~/.garminconnect/garmin_tokens.json`. Gdy token wygaśnie
(ETL kończy się kodem 2):

```powershell
.venv\Scripts\python.exe etl\login.py
```

Plik z tokenami ma wartość hasła — trzymaj go poza repo i backupami.

## Automatyczna aktualizacja (opcjonalnie)

```powershell
schtasks /create /tn GarminETL /sc daily /st 07:00 /tr "\"$PWD\.venv\Scripts\python.exe\" \"$PWD\etl\run.py\""
```

## Co nie jest pobierane

Szczegóły pojedynczych treningów (`get_activity`: splity, GPS, strumienie
sekundowe), SpO2 minuta po minucie, golf, żywienie, sprzęt. Hipnogramy, nocne
HRV i 3-minutowe próbki stresu/Body Battery **są** pobierane. Dodanie kolejnej
metryki: wpis w `config.DAILY_METRICS` (lub `MONTHLY_METRICS`) + mapowanie
w `etl/load.py`.
