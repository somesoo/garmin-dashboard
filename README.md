# Garmin Dashboard (lokalnie)

Pobiera dane z Garmin Connect, buduje hurtownię na dysku i hostuje dashboard
na `http://localhost:8501`. Nic nie wychodzi na zewnątrz.

## Uruchomienie

**macOS:** dwuklik na **`Dashboard.command`** (otwiera się w Terminalu) albo
`./Dashboard.command` z terminala. **Windows:** dwuklik na **`Dashboard.cmd`**.
Oba aktualizują dane od ostatniego pobrania, przebudowują tabele, podnoszą
serwer (jeśli nie działa) i otwierają przeglądarkę. Na Macu serwer działa
w tle także po zamknięciu okna Terminala (log: `data/streamlit.log`);
zatrzymanie: `pkill -f "streamlit run"`.

Ręcznie (macOS/Linux; na Windowsie `.venv\Scripts\python.exe`):

```bash
.venv/bin/python etl/run.py              # aktualizacja (14 dni wstecz)
.venv/bin/python etl/run.py --backfill   # cała historia
.venv/bin/python etl/load.py             # tylko przebudowa tabel
.venv/bin/python analytics.py            # tylko modele i statystyka
.venv/bin/python -m streamlit run app.py # tylko serwer
```

### Pierwsza instalacja na Macu

```bash
brew install python@3.13
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Przeniesienie danych z Windowsa

`data/` i tokeny nie są w gicie. Na Windowsie (PowerShell, w katalogu repo):

```powershell
tar czf garmin-data.tar.gz data
tar czf garmin-tokens.tar.gz -C $env:USERPROFILE .garminconnect
```

Oba pliki przenieś na Maca (pendrive, AirDrop, `scp`) i w katalogu repo:

```bash
tar xzf ~/Downloads/garmin-data.tar.gz
tar xzf ~/Downloads/garmin-tokens.tar.gz -C ~
chmod 700 ~/.garminconnect && chmod 600 ~/.garminconnect/*
rm ~/Downloads/garmin-tokens.tar.gz   # archiwum ma wartość hasła
cat data/state.json                    # kontrola: ostatni pobrany dzień
.venv/bin/python etl/load.py           # odbudowa tabel lokalnie, bez API
```

Bez tokenów wystarczy raz `.venv/bin/python etl/login.py`.

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

```bash
.venv/bin/python etl/login.py              # macOS/Linux
.venv\Scripts\python.exe etl\login.py      # Windows
```

Plik z tokenami ma wartość hasła — trzymaj go poza repo i backupami.

## Automatyczna aktualizacja (opcjonalnie)

macOS — wpis w `crontab -e` (Mac musi wtedy nie spać):

```
0 7 * * * cd /Users/<ty>/repos/garmin-dashboard && .venv/bin/python etl/run.py >> data/etl.log 2>&1
```

Windows:

```powershell
schtasks /create /tn GarminETL /sc daily /st 07:00 /tr "\"$PWD\.venv\Scripts\python.exe\" \"$PWD\etl\run.py\""
```

## Co nie jest pobierane

Szczegóły pojedynczych treningów (`get_activity`: splity, GPS, strumienie
sekundowe), SpO2 minuta po minucie, golf, żywienie, sprzęt. Hipnogramy, nocne
HRV i 3-minutowe próbki stresu/Body Battery **są** pobierane. Dodanie kolejnej
metryki: wpis w `config.DAILY_METRICS` (lub `MONTHLY_METRICS`) + mapowanie
w `etl/load.py`.
