"""Race-time forecast: numbers, how they were reached, how they moved, what moves them."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bento
import glossary
import i18n
import routing
import shell
import theme as tz
from running import forecast, physio, units
from views import run_common as rc


def render() -> None:
    frame = rc.guard()
    result = rc.current_forecast() if frame is not None else {}
    tr = i18n.tr
    vdot = tr(pl=f" Wydolność dziś: VDOT {result['vdot']:.1f}.", en=f" Fitness today: VDOT {result['vdot']:.1f}.") \
        if result.get("status") == "ok" else ""
    bento.header(i18n.page("prognoza"),
                 tr(pl="Na jaki czas możesz dziś liczyć na każdym dystansie i jak bardzo tej liczbie ufać.",
                    en="What time you can count on today at each distance and how far to trust that number.") + vdot)
    if frame is None:
        return
    if result.get("status") != "ok":
        st.warning(result.get("reason") or tr(pl="Za mało danych na prognozę.", en="Too little data for a forecast."))
        return

    history = rc.history()
    _kpis(result, history)
    for note in result.get("notes", []):
        st.caption(f"⚠ {note}")

    key = st.segmented_control(
        tr(pl="Dystans", en="Distance"), list(units.RACES), default="10k", format_func=rc.race_label,
        key="forecast_distance",
        label_visibility="collapsed",
    ) or "10k"
    item = result["distances"][key]
    for warning in item.warnings:
        st.warning(warning)

    left, right = bento.row(2, 2)
    with left:
        _history_chart(history, key)
    with right:
        _confidence(result, item)
        _advice(result, frame, key)

    left, right = bento.row(2, 2)
    with left:
        _backtest(history)
    with right:
        _methods(result, item)
        _anchor(result)

    _table(result, history)
    with bento.panel(tr(pl="Przygotowanie i założenia modelu", en="Preparation and the model's assumptions"),
                     key="assumptions",
                     caption=tr(pl="Jak brak przygotowania zamienia potencjał w wynik realistyczny i na czym model stoi.",
                                en="How missing preparation turns potential into a realistic result, and what the "
                                   "model stands on.")):
        _preparation(result, item)
        _assumptions()


def _kpis(result: dict, history: pd.DataFrame) -> None:
    for column, (key, item) in zip(bento.row(1, 1, 1, 1), result["distances"].items()):
        four = forecast.trend(history, key, 4)
        band, sure = f"{units.fmt_time(item.low_s)}–{units.fmt_time(item.high_s)}", rc.confidence_label(item.confidence)
        pace, potential = units.fmt_pace(item.pace), units.fmt_time(item.potential_s)
        bento.stat(column, rc.race_label(key), units.fmt_time(item.realistic_s), key=f"fc_{key}",
                   delta=units.fmt_delta(four) if four is not None else None, delta_color="inverse",
                   note=i18n.tr(pl=f"{band} · pewność {sure}", en=f"{band} · confidence {sure}"),
                   help=i18n.tr(pl=f"Zmiana względem prognozy sprzed 4 tygodni (ujemna = szybciej). {pace}, "
                                   f"potencjał {potential}.",
                                en=f"Change against the forecast of 4 weeks ago (negative = faster). {pace}, "
                                   f"potential {potential}."))


def _headers() -> dict[str, str]:
    """Column key -> header of the "all numbers" table."""
    tr = i18n.tr
    return {
        "distance": tr(pl="dystans", en="distance"), "realistic": tr(pl="realistyczny", en="realistic"),
        "interval80": tr(pl="przedział 80%", en="80% range"), "pace": tr(pl="tempo", en="pace"),
        "potential": tr(pl="potencjał", en="potential"), "after_plan": tr(pl="po planie", en="after the plan"),
        "confidence": tr(pl="pewność", en="confidence"), "preparation": tr(pl="przygotowanie", en="preparation"),
        "change4": tr(pl="zmiana 4 tyg.", en="change 4 wk"), "change12": tr(pl="zmiana 12 tyg.", en="change 12 wk"),
    }


def _table(result: dict, history: pd.DataFrame) -> None:
    tr = i18n.tr
    header = _headers()
    rows = []
    for key, item in result["distances"].items():
        four = forecast.trend(history, key, 4)
        twelve = forecast.trend(history, key, 12)
        rows.append(
            {
                header["distance"]: rc.race_label(key),
                header["realistic"]: units.fmt_time(item.realistic_s),
                header["interval80"]: f"{units.fmt_time(item.low_s)} – {units.fmt_time(item.high_s)}",
                header["pace"]: units.fmt_pace(item.pace),
                header["potential"]: units.fmt_time(item.potential_s),
                header["after_plan"]: (f"{units.fmt_time(item.target_s)} ({units.fmt_time(item.target_low_s)}–"
                                       f"{units.fmt_time(item.target_high_s)})") if item.target_s else "—",
                header["confidence"]: rc.confidence(item.confidence),
                header["preparation"]: f"{item.prep['score']:.0%}",
                header["change4"]: units.fmt_delta(four) if four is not None else "—",
                header["change12"]: units.fmt_delta(twelve) if twelve is not None else "—",
            }
        )
    with bento.panel(
        tr(pl="Wszystkie liczby", en="All the numbers"), key="forecast_table",
        caption=tr(pl="Nagłówki kolumn mają podpowiedzi po najechaniu.", en="Column headers have tooltips on hover."),
        terms=["realistic", "interval80", "confidence", "potential", "preparation", "vdot", "after_plan"],
        how=tr(pl="Zmiana 4/12 tyg.: ujemna = prognoza szybsza niż wtedy. „Po planie” pojawia się tylko dla "
                  "dystansu z wpisanym startem (strona Zawody).",
               en="Change 4/12 wk: negative = the forecast is faster than then. “After the plan” appears only for a "
                  "distance with a race entered (the Races page)."),
    ):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=_columns())


def _columns() -> dict:
    tr = i18n.tr
    header = _headers()
    text = st.column_config.TextColumn
    columns = {header[key]: text(help=glossary.short(key))
               for key in ("realistic", "interval80", "potential", "after_plan", "confidence", "preparation")}
    for key, weeks in (("change4", 4), ("change12", 12)):
        columns[header[key]] = text(help=tr(pl=f"Zmiana prognozy względem {weeks} tygodni temu; ujemna = szybciej.",
                                            en=f"Change in the forecast against {weeks} weeks ago; negative = faster."))
    return columns


def _confidence(result: dict, item: forecast.DistanceForecast) -> None:
    """The confidence label, what it means in seconds, and what holds it back."""
    tr = i18n.tr
    label = rc.race_label(item.key)
    spread = (item.high_s - item.low_s) / 2
    reasons = forecast.confidence_reasons(item, result.get("perf"))
    low, high, pm = units.fmt_time(item.low_s), units.fmt_time(item.high_s), units.fmt_time(spread)
    sure = f"<b>{rc.confidence(item.confidence)}</b>"
    with bento.tile(
        tr(pl=f"Pewność — {label}", en=f"Confidence — {label}"), key="confidence", terms=["confidence", "interval80"],
        caption=tr(pl=f"{sure} · 8 na 10 startów między {low} a {high} (±{pm})",
                   en=f"{sure} · 8 races in 10 between {low} and {high} (±{pm})"),
        how=tr(pl="Najszybciej podnosi pewność mocny bieg (start, test) na dystansie bliskim docelowemu, powiązany "
                  "ze startem na stronie Zawody.",
               en="The fastest way to raise confidence is a hard run (a race, a test) at a distance close to the "
                  "target, linked to a race on the Races page."),
    ):
        if reasons:
            note = tr(pl="Co poszerza przedział, od największego:", en="What widens the range, largest first:")
            st.markdown(f"<div class='tile-caption'>{note}</div>", unsafe_allow_html=True)
            bento.bullets(reasons[:3])
        else:
            st.caption(tr(pl="Świeży wysiłek maksymalny i zgodne metody — prognoza jest tak pewna, jak ten model "
                             "potrafi.",
                          en="A fresh maximal effort and methods that agree — the forecast is as sure as this model "
                             "can be."))


def _minutes_axis(fig: go.Figure, values: pd.Series) -> None:
    data = pd.to_numeric(values, errors="coerce").dropna()
    if data.empty:
        return
    low, high = float(data.min()), float(data.max())
    span = max(high - low, 1.0)
    step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60) if span / s <= 6)
    first = (low // step) * step
    ticks = [first + i * step for i in range(int((high - first) / step) + 2)]
    fig.update_yaxes(tickmode="array", tickvals=ticks, ticktext=[units.fmt_time(t * 60) for t in ticks],
                     autorange="reversed")


def _history_chart(history: pd.DataFrame, key: str) -> None:
    tr = i18n.tr
    with bento.tile(
        tr(pl="Jak zmieniała się prognoza", en="How the forecast moved"), rows=2, key="forecast_history",
        terms=["near_max", "interval80"],
        caption=tr(pl="Liczona co tydzień tylko z danych sprzed tego dnia. Wyżej = szybciej.",
                   en="Computed weekly from data before that day only. Higher = faster."),
        how=tr(pl="Pas to przedział 80%, linia kropkowana — Garmin. Pełne punkty: prognoza oparta na wysiłku bliskim "
                  "maksymalnego; puste: tylko na odcinkach treningowych (dolna granica).",
               en="The band is the 80% range, the dotted line — Garmin. Filled points: a forecast resting on a "
                  "near-maximal effort; hollow: on training stretches only (a lower bound)."),
    ) as tile:
        _history_body(tile, history, key)


def _history_body(tile, history: pd.DataFrame, key: str) -> None:
    tr = i18n.tr
    if history.empty:
        st.caption(tr(pl="Brak historii prognoz — uruchom `analytics.py`.", en="No forecast history — run "
                                                                               "`analytics.py`."))
        return
    view = shell.clip(history[history["distance"] == key].sort_values("day"))
    if view.empty:
        st.caption(tr(pl="Brak prognoz w wybranym zakresie.", en="No forecasts in the selected range."))
        return
    t = tz.tokens()
    accent = t["series"][0]
    minutes = view.assign(
        real=view["realistic_s"] / 60, low=view["low_s"] / 60, high=view["high_s"] / 60,
        garmin=pd.to_numeric(view["garmin_s"], errors="coerce") / 60,
        text=view["realistic_s"].map(units.fmt_time),
    )
    fig = go.Figure()
    fig.add_scatter(x=minutes["day"], y=minutes["low"], mode="lines", line=dict(width=0),
                    hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=minutes["day"], y=minutes["high"], mode="lines", line=dict(width=0), fill="tonexty",
                    fillcolor=tz._alpha(accent, 0.14), hoverinfo="skip", showlegend=False)
    realistic = tr(pl="realistyczny", en="realistic")
    fig.add_scatter(x=minutes["day"], y=minutes["real"], mode="lines", name=realistic,
                    line=dict(width=2.4, color=accent), customdata=minutes[["text"]],
                    hovertemplate=f"%{{customdata[0]}}<extra>{tr(pl='prognoza', en='forecast')}</extra>")
    for near, symbol in ((True, "circle"), (False, "circle-open")):
        part = minutes[minutes["near_max"] == near]
        fig.add_scatter(x=part["day"], y=part["real"], mode="markers", showlegend=False, hoverinfo="skip",
                        marker=dict(size=6, symbol=symbol, color=accent, line=dict(width=1.4, color=accent)))
    if minutes["garmin"].notna().sum() >= 3:
        fig.add_scatter(x=minutes["day"], y=minutes["garmin"], mode="lines", name="Garmin",
                        line=dict(width=1.6, color=t["muted"], dash="dot"),
                        customdata=(minutes["garmin"] * 60).map(units.fmt_time),
                        hovertemplate="%{customdata}<extra>Garmin</extra>")
    fig.update_layout(**tz.base_layout(legend=True, height=340))
    _minutes_axis(fig, pd.concat([minutes["low"], minutes["high"], minutes["garmin"]]))
    tile.chart(
        tz.local_dates(tz.style_axes(fig), minutes["day"]),
        table=view.assign(**{
            realistic: view["realistic_s"].map(units.fmt_time),
            tr(pl="od", en="from"): view["low_s"].map(units.fmt_time),
            tr(pl="do", en="to"): view["high_s"].map(units.fmt_time),
            "Garmin": view["garmin_s"].map(units.fmt_time),
        })[["day", realistic, tr(pl="od", en="from"), tr(pl="do", en="to"), "Garmin", "vdot", "prep", "confidence"]]
        .sort_values("day", ascending=False).head(30),
        key=f"forecast_history_{key}",
    )


def _advice(result: dict, frame: pd.DataFrame, key: str) -> None:
    tips = forecast.advice(result, frame, key)
    tr = i18n.tr
    with bento.tile(tr(pl="Co może poprawić wynik", en="What could improve the result"), key="advice",
                    terms=["preparation", "potential"],
                    caption=tr(pl="Gdzie prognoza jest dziś ograniczana, od największego — luki, nie diagnoza.",
                               en="Where the forecast is held back today, largest first — gaps, not a diagnosis.")):
        if not tips:
            st.caption(tr(pl="Przygotowanie spełnia przyjęte wymagania dla tego dystansu — dalszy postęp to głównie "
                             "regularność i stopniowe podnoszenie jakości.",
                          en="Preparation meets the assumed requirements for this distance — further progress is "
                             "mostly consistency and gradually raising quality."))
            return
        bento.bullets(tips[:3])


def _methods(result: dict, item: forecast.DistanceForecast) -> None:
    tr = i18n.tr
    # forecast.py names its weights with these codes.
    names = {"wyniki": tr(pl="wyniki", en="results"),
             "trend tętna": tr(pl="trend tętna", en="heart rate trend"),  # i18n: key
             "tętno (poziom)": tr(pl="tętno (poziom)", en="heart rate (level)")}  # i18n: key
    weights = ", ".join(f"{names.get(name, name)} {weight:.0%}" for name, weight in result["weights"].items())
    sigma, width = f"{item.sigma:.3f}", f"{(pow(2.718, 1.28 * item.sigma) - 1):.0%}"
    with bento.tile(
        tr(pl="Metody i ich zgodność", en="Methods and their agreement"), key="methods", terms=["methods", "vdot"],
        caption=tr(pl=f"wagi w VDOT: {weights}", en=f"weights in VDOT: {weights}"),
        how=tr(pl=f"Rozbieżność metod i odległość od dystansu kotwicy składają się na σ = {sigma} (log-czas), "
                  f"co daje przedział ±{width}.",
               en=f"The methods' disagreement and the distance from the anchor's distance add up to σ = {sigma} "
                  f"(log-time), which gives a range of ±{width}."),
    ):
        columns = st.columns(3)
        for column, (label, name, role) in zip(columns, (
            (tr(pl="wysiłki (Daniels)", en="efforts (Daniels)"), "wyniki",
             tr(pl="Kotwica prognozy: udokumentowane wysiłki.", en="The forecast's anchor: documented efforts.")),
            (tr(pl="tętno ↔ tempo", en="heart rate ↔ pace"), "tętno",  # i18n: key
             tr(pl="Trend i niezależna kontrola (skalibrowane).", en="Trend and an independent check (calibrated).")),
            ("Garmin", "Garmin", tr(pl="Odniesienie zewnętrzne (Firstbeat) — tylko poszerza przedział.",
                                    en="An outside reference (Firstbeat) — it only widens the range.")),
        )):
            column.metric(label, units.fmt_time(item.methods.get(name)), help=role)


def _anchor(result: dict) -> None:
    tr = i18n.tr
    perf = result.get("perf")
    caption = None
    if perf:
        caption = tr(pl=f"{perf['day']:%d.%m.%Y} · {perf['age_days']} dni temu · {perf['source']}",
                     en=f"{perf['day']:%d.%m.%Y} · {perf['age_days']} days ago · {perf['source']}")
    with bento.tile(tr(pl="Wysiłek, na którym stoi prognoza", en="The effort the forecast stands on"), key="anchor",
                    terms=["near_max"], caption=caption) as t:
        if not perf:
            st.caption(tr(pl="Brak udokumentowanego wysiłku — prognoza stoi na tętnie.",
                          en="No documented effort — the forecast stands on heart rate."))
            return
        with t.header:
            if st.button("", icon=":material/open_in_new:", type="tertiary", key="forecast_open_anchor",
                         help=tr(pl="Otwórz ten trening", en="Open this session")):
                routing.open_run(perf["activity_id"])
        columns = st.columns(3)
        columns[0].metric(rc.effort_label(perf["effort"]), units.fmt_time(perf["seconds"]),
                          help=f"{perf['distance_m'] / 1000:.2f} km")
        columns[1].metric(tr(pl="tempo", en="pace"),
                          units.fmt_pace(units.pace_from(perf["seconds"], perf["distance_m"] / 1000), False))
        columns[2].metric("VDOT", f"{perf['vdot']:.1f}",
                          help=tr(pl=f"surowy {perf['vdot_raw']:.1f}; wysiłków w oknie 120 dni: {perf['n_efforts']}",
                                  en=f"raw {perf['vdot_raw']:.1f}; efforts in the 120-day window: {perf['n_efforts']}"))
        hr = f"{perf['hr_frac']:.0%} HRmax" if perf.get("hr_frac") else tr(pl="bez tętna", en="no heart rate")
        kind = tr(pl="bliski maksymalnego", en="near-maximal") if perf["near_max"] \
            else tr(pl="nie maksymalny: dolna granica", en="not maximal: a lower bound")
        st.markdown(f"<div class='tile-caption'>{hr} — {kind}</div>", unsafe_allow_html=True)


def _preparation(result: dict, item: forecast.DistanceForecast) -> None:
    perf = result.get("perf")
    hr = result.get("hr")
    calibration = result.get("calibration")
    tr = i18n.tr
    if hr:
        if calibration:
            rest = tr(pl=f"× kalibracja {calibration['factor']:.2f} (z {calibration['n']} wysiłków bliskich maksimum) "
                         f"= {hr['vdot']:.1f}.",
                      en=f"× calibration {calibration['factor']:.2f} (from {calibration['n']} near-maximal efforts) "
                         f"= {hr['vdot']:.1f}.")
        else:
            rest = tr(pl="— bez kalibracji, więc poza prognozą.", en="— not calibrated, so left out of the forecast.")
        st.caption(
            tr(pl=f"Tętno: {hr['n']} spokojnych biegów z 42 dni, surowy VDOT z tętna {hr['raw']:.1f} ",
               en=f"Heart rate: {hr['n']} easy runs from 42 days, raw VDOT from heart rate {hr['raw']:.1f} ")
            + rest
            + tr(pl=f" HRmax {result['hr_max']:.0f} (trzecie najwyższe maksimum z biegów).",
                 en=f" HRmax {result['hr_max']:.0f} (the third-highest maximum of the runs).")
        )
    label = rc.race_label(item.key)
    with st.expander(tr(pl=f"Przygotowanie do dystansu — {label}", en=f"Preparation for the distance — {label}")):
        prep = item.prep
        part, has = tr(pl="składnik", en="component"), tr(pl="jest", en="now")
        need, weight = tr(pl="przyjęte minimum", en="assumed minimum"), tr(pl="waga", en="weight")
        runs = max(2, prep["runs_need"] - 1)
        st.dataframe(
            pd.DataFrame(
                [
                    {part: tr(pl="najdłuższy bieg (6 tyg.)", en="longest run (6 wk)"), has: f"{prep['long_km']:.1f} km",
                     need: f"{prep['long_need']:.0f} km", weight: "40%"},
                    {part: tr(pl="średnio tygodniowo (6 tyg.)", en="weekly average (6 wk)"),
                     has: f"{prep['weekly_km']:.1f} km", need: f"{prep['weekly_need']:.0f} km", weight: "40%"},
                    {part: tr(pl=f"tygodnie z ≥ {runs} biegami (8 tyg.)", en=f"weeks with ≥ {runs} runs (8 wk)"),
                     has: f"{prep['consistency']:.0%}", need: "100%", weight: "20%"},
                ]
            ),
            hide_index=True, width="stretch",
        )
        anchor_km = (perf or {}).get("distance_m", 5000) / 1000
        extra = forecast.MAX_EXTRA_EXPONENT * (1 - prep["score"])
        potential, realistic = units.fmt_time(item.potential_s), units.fmt_time(item.realistic_s)
        st.caption(tr(
            pl=f"Wynik {prep['score']:.0%}. Krzywa Danielsa zakłada trening pod dystans; brak przygotowania "
               f"podnosi wykładnik Riegla o {extra:.3f} ponad dystans kotwicy ({anchor_km:.1f} km): "
               f"potencjał {potential} → realistycznie {realistic}.",
            en=f"Score {prep['score']:.0%}. Daniels' curve assumes training for the distance; missing preparation "
               f"raises the Riegel exponent by {extra:.3f} beyond the anchor's distance ({anchor_km:.1f} km): "
               f"potential {potential} → realistically {realistic}.",
        ))


def _backtest(history: pd.DataFrame) -> None:
    efforts = rc.efforts()
    if efforts.empty or "near_max" not in efforts.columns:
        return
    table = forecast.backtest(history, efforts)
    error = table["error_pct"].abs() if not table.empty else pd.Series(dtype=float)
    slower = int((table["error_pct"] > 0).sum()) if not table.empty else 0
    tr = i18n.tr
    caption = None
    if not table.empty:
        median, faster = f"<b>{error.median():.1f}%</b>", len(table) - slower
        caption = tr(pl=f"{len(table)} porównań · mediana błędu {median} · za wolno {slower}, za szybko {faster}",
                     en=f"{len(table)} comparisons · median error {median} · too slow {slower}, too fast {faster}")
    with bento.tile(
        tr(pl="Sprawdzenie wstecz", en="Backtest"), rows=2, key="backtest", terms=["backtest"],
        caption=caption,
        how=tr(pl="Mocne biegi (≥ 3 km) wobec tego, co model przewidywał tydzień wcześniej. Dodatni błąd = prognoza "
                  "zbyt ostrożna (zwykle po okresie szybkiego postępu).",
               en="Hard runs (≥ 3 km) against what the model predicted a week earlier. A positive error = the "
                  "forecast was too cautious (usually after a period of fast progress)."),
    ) as t:
        if table.empty:
            st.caption(tr(pl="Brak wysiłków bliskich maksymalnego ≥ 3 km z prognozą tydzień wcześniej.",
                          en="No near-maximal efforts ≥ 3 km with a forecast a week earlier."))
            return
        _backtest_table(t, table)


def _backtest_table(t, table: pd.DataFrame) -> None:
    tr = i18n.tr
    table = table.sort_values("day", ascending=False)
    t.table(
        pd.DataFrame(
            {
                tr(pl="dzień", en="day"): pd.to_datetime(table["day"]).dt.strftime("%d.%m.%Y"),
                tr(pl="dystans", en="distance"): (table["distance_m"] / 1000).round(2),
                tr(pl="wynik", en="result"): table["actual_s"].map(units.fmt_time),
                tr(pl="prognoza", en="forecast"): table["predicted_s"].map(units.fmt_time),
                tr(pl="błąd %", en="error %"): table["error_pct"],
            }
        ),
    )


def _assumptions() -> None:
    tr = i18n.tr
    with st.expander(tr(pl="Założenia modelu", en="Model assumptions")):
        req = pd.DataFrame(forecast.REQUIREMENTS).T
        req = req.rename(index={key: rc.race_label(key) for key in req.index},
                         columns={"long_km": tr(pl="długi bieg km", en="long run km"),
                                  "weekly_km": tr(pl="km/tydz.", en="km/week"),
                                  "runs": tr(pl="biegi/tydz.", en="runs/week")})
        st.dataframe(req, width="stretch")
        extra = forecast.MAX_EXTRA_EXPONENT
        st.markdown(tr(
            pl="- Wydolność to VDOT z krzywych Danielsa i Gilberta (koszt tlenowy biegu × ułamek VO₂max możliwy "
               "do utrzymania przez dany czas). Na tych samych krzywych liczone są tempa treningowe w planie.\n"
               "- Wymagania dystansu powyżej to heurystyki dla biegaczy rekreacyjnych, nie normy. Niedobór "
               f"podnosi wykładnik Riegla maksymalnie o {extra}.\n"
               "- Starszy wysiłek maksymalny traci 0,3% na tydzień po 4 tygodniach (maks. 12%) — łagodnie, bo "
               "zwykle trening trwa dalej.\n"
               "- Tętno → VO₂max przez %HRR ≈ %VO₂R (Swain), kalibrowane osobistym współczynnikiem.\n"
               "- „Po planie”: +1 VDOT na ~5 tygodni regularnego treningu (Daniels: podnoś VDOT o 1 co 4–6 "
               "tygodni), maks. 16 tygodni, i przygotowanie, które osiąga plan.\n"
               "- Model nie widzi trasy zawodów, pogody, taktyki ani dnia startu. Upał i przewyższenia potrafią "
               "kosztować więcej niż szerokość przedziału.",
            en="- Fitness is VDOT from the Daniels and Gilbert curves (the oxygen cost of running × the fraction of "
               "VO₂max sustainable for a given time). Training paces in the plan come from the same curves.\n"
               "- The distance requirements above are heuristics for recreational runners, not norms. A shortfall "
               f"raises the Riegel exponent by at most {extra}.\n"
               "- An older maximal effort loses 0.3% per week after 4 weeks (max. 12%) — gently, because training "
               "usually goes on.\n"
               "- Heart rate → VO₂max via %HRR ≈ %VO₂R (Swain), calibrated with a personal factor.\n"
               "- “After the plan”: +1 VDOT per ~5 weeks of regular training (Daniels: raise VDOT by 1 every 4–6 "
               "weeks), max. 16 weeks, and the preparation the plan reaches.\n"
               "- The model does not see the race course, the weather, tactics or race day. Heat and elevation "
               "can cost more than the width of the range.",
        ))
        paces = physio.training_paces(rc.current_forecast().get("vdot"))
        if paces:
            st.caption(tr(pl="Tempa treningowe przy obecnym VDOT: ", en="Training paces at the current VDOT: ")
                       + " · ".join(
                f"{name} {units.fmt_pace(a, False)}–{units.fmt_pace(b, False)}" for name, (a, b) in paces.items()))
