"""Race-time forecast: numbers, how they were reached, how they moved, what moves them."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bento
import glossary
import routing
import shell
import theme as tz
from running import forecast, physio, sessions, units
from views import run_common as rc


def render() -> None:
    frame = rc.guard()
    result = rc.current_forecast() if frame is not None else {}
    vdot = f" Wydolność dziś: VDOT {result['vdot']:.1f}." if result.get("status") == "ok" else ""
    bento.header("Prognoza wyników",
                 "Na jaki czas możesz dziś liczyć na każdym dystansie i jak bardzo tej liczbie ufać." + vdot)
    if frame is None:
        return
    if result.get("status") != "ok":
        st.warning(result.get("reason", "Za mało danych na prognozę."))
        return

    history = rc.history()
    _kpis(result, history)
    for note in result.get("notes", []):
        st.caption(f"⚠ {note}")

    key = st.segmented_control(
        "Dystans", list(units.RACES), default="10k", format_func=units.RACE_LABELS.get, key="forecast_distance",
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
    with bento.panel("Przygotowanie i założenia modelu", key="assumptions",
                     caption="Jak brak przygotowania zamienia potencjał w wynik realistyczny i na czym model stoi."):
        _preparation(result, item)
        _assumptions()


def _kpis(result: dict, history: pd.DataFrame) -> None:
    for column, (key, item) in zip(bento.row(1, 1, 1, 1), result["distances"].items()):
        four = forecast.trend(history, key, 4)
        bento.stat(column, units.RACE_LABELS[key], units.fmt_time(item.realistic_s), key=f"fc_{key}",
                   delta=units.fmt_delta(four) if four is not None else None, delta_color="inverse",
                   note=f"{units.fmt_time(item.low_s)}–{units.fmt_time(item.high_s)} · pewność {item.confidence}",
                   help=f"Zmiana względem prognozy sprzed 4 tygodni (ujemna = szybciej). "
                        f"{units.fmt_pace(item.pace)}, potencjał {units.fmt_time(item.potential_s)}.")


def _table(result: dict, history: pd.DataFrame) -> None:
    rows = []
    for key, item in result["distances"].items():
        four = forecast.trend(history, key, 4)
        twelve = forecast.trend(history, key, 12)
        rows.append(
            {
                "dystans": units.RACE_LABELS[key],
                "realistyczny": units.fmt_time(item.realistic_s),
                "przedział 80%": f"{units.fmt_time(item.low_s)} – {units.fmt_time(item.high_s)}",
                "tempo": units.fmt_pace(item.pace),
                "potencjał": units.fmt_time(item.potential_s),
                "po planie": (f"{units.fmt_time(item.target_s)} ({units.fmt_time(item.target_low_s)}–"
                              f"{units.fmt_time(item.target_high_s)})") if item.target_s else "—",
                "pewność": f"{item.confidence} {rc.CONFIDENCE_ICON[item.confidence]}",
                "przygotowanie": f"{item.prep['score']:.0%}",
                "zmiana 4 tyg.": units.fmt_delta(four) if four is not None else "—",
                "zmiana 12 tyg.": units.fmt_delta(twelve) if twelve is not None else "—",
            }
        )
    with bento.panel(
        "Wszystkie liczby", key="forecast_table",
        caption="Nagłówki kolumn mają podpowiedzi po najechaniu.",
        terms=["realistic", "interval80", "confidence", "potential", "preparation", "vdot", "after_plan"],
        how="Zmiana 4/12 tyg.: ujemna = prognoza szybsza niż wtedy. „Po planie” pojawia się tylko dla "
            "dystansu z wpisanym startem (strona Zawody).",
    ):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=_COLUMNS)


def _help(key: str) -> str:
    return glossary.short(key)


_COLUMNS = {
    "realistyczny": st.column_config.TextColumn(help=_help("realistic")),
    "przedział 80%": st.column_config.TextColumn(help=_help("interval80")),
    "potencjał": st.column_config.TextColumn(help=_help("potential")),
    "po planie": st.column_config.TextColumn(help=_help("after_plan")),
    "pewność": st.column_config.TextColumn(help=_help("confidence")),
    "przygotowanie": st.column_config.TextColumn(help=_help("preparation")),
    "zmiana 4 tyg.": st.column_config.TextColumn(help="Zmiana prognozy względem 4 tygodni temu; ujemna = szybciej."),
    "zmiana 12 tyg.": st.column_config.TextColumn(help="Zmiana prognozy względem 12 tygodni temu; ujemna = szybciej."),
}


def _confidence(result: dict, item: forecast.DistanceForecast) -> None:
    """The confidence label, what it means in seconds, and what holds it back."""
    label = units.RACE_LABELS[item.key]
    spread = (item.high_s - item.low_s) / 2
    reasons = forecast.confidence_reasons(item, result.get("perf"))
    with bento.tile(
        f"Pewność — {label}", key="confidence", terms=["confidence", "interval80"],
        caption=f"<b>{item.confidence} {rc.CONFIDENCE_ICON[item.confidence]}</b> · 8 na 10 startów między "
                f"{units.fmt_time(item.low_s)} a {units.fmt_time(item.high_s)} (±{units.fmt_time(spread)})",
        how="Najszybciej podnosi pewność mocny bieg (start, test) na dystansie bliskim docelowemu, powiązany ze "
            "startem na stronie Zawody.",
    ):
        if reasons:
            st.markdown("<div class='tile-caption'>Co poszerza przedział, od największego:</div>",
                        unsafe_allow_html=True)
            bento.bullets(reasons[:3])
        else:
            st.caption("Świeży wysiłek maksymalny i zgodne metody — prognoza jest tak pewna, jak ten model potrafi.")


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
    with bento.tile(
        "Jak zmieniała się prognoza", rows=2, key="forecast_history", terms=["near_max", "interval80"],
        caption="Liczona co tydzień tylko z danych sprzed tego dnia. Wyżej = szybciej.",
        how="Pas to przedział 80%, linia kropkowana — Garmin. Pełne punkty: prognoza oparta na wysiłku bliskim "
            "maksymalnego; puste: tylko na odcinkach treningowych (dolna granica).",
    ) as tile:
        _history_body(tile, history, key)


def _history_body(tile, history: pd.DataFrame, key: str) -> None:
    if history.empty:
        st.caption("Brak historii prognoz — uruchom `analytics.py`.")
        return
    view = shell.clip(history[history["distance"] == key].sort_values("day"))
    if view.empty:
        st.caption("Brak prognoz w wybranym zakresie.")
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
    fig.add_scatter(x=minutes["day"], y=minutes["real"], mode="lines", name="realistyczny",
                    line=dict(width=2.4, color=accent), customdata=minutes[["text"]],
                    hovertemplate="%{customdata[0]}<extra>prognoza</extra>")
    for near, symbol in ((True, "circle"), (False, "circle-open")):
        part = minutes[minutes["near_max"] == near]
        fig.add_scatter(x=part["day"], y=part["real"], mode="markers", showlegend=False, hoverinfo="skip",
                        marker=dict(size=6, symbol=symbol, color=accent, line=dict(width=1.4, color=accent)))
    if minutes["garmin"].notna().sum() >= 3:
        fig.add_scatter(x=minutes["day"], y=minutes["garmin"], mode="lines", name="Garmin",
                        line=dict(width=1.6, color=t["muted"], dash="dot"),
                        hovertemplate="%{y:.1f} min<extra>Garmin</extra>")
    fig.update_layout(**tz.base_layout(legend=True, height=340))
    _minutes_axis(fig, pd.concat([minutes["low"], minutes["high"], minutes["garmin"]]))
    tile.chart(
        tz.polish_dates(tz.style_axes(fig), minutes["day"]),
        table=view.assign(
            realistyczny=view["realistic_s"].map(units.fmt_time),
            od=view["low_s"].map(units.fmt_time), do=view["high_s"].map(units.fmt_time),
            Garmin=view["garmin_s"].map(units.fmt_time),
        )[["day", "realistyczny", "od", "do", "Garmin", "vdot", "prep", "confidence"]]
        .sort_values("day", ascending=False).head(30),
        key=f"forecast_history_{key}",
    )


def _advice(result: dict, frame: pd.DataFrame, key: str) -> None:
    tips = forecast.advice(result, frame, key)
    with bento.tile("Co może poprawić wynik", key="advice", terms=["preparation", "potential"],
                    caption="Gdzie prognoza jest dziś ograniczana, od największego — luki, nie diagnoza."):
        if not tips:
            st.caption("Przygotowanie spełnia przyjęte wymagania dla tego dystansu — dalszy postęp to głównie "
                       "regularność i stopniowe podnoszenie jakości.")
            return
        bento.bullets(tips[:3])


def _methods(result: dict, item: forecast.DistanceForecast) -> None:
    weights = ", ".join(f"{name} {weight:.0%}" for name, weight in result["weights"].items())
    with bento.tile(
        "Metody i ich zgodność", key="methods", terms=["methods", "vdot"], caption=f"wagi w VDOT: {weights}",
        how=f"Rozbieżność metod i odległość od dystansu kotwicy składają się na σ = {item.sigma:.3f} (log-czas), "
            f"co daje przedział ±{(pow(2.718, 1.28 * item.sigma) - 1):.0%}.",
    ):
        columns = st.columns(3)
        for column, (label, name, role) in zip(columns, (
            ("wysiłki (Daniels)", "wyniki", "Kotwica prognozy: udokumentowane wysiłki."),
            ("tętno ↔ tempo", "tętno", "Trend i niezależna kontrola (skalibrowane)."),
            ("Garmin", "Garmin", "Odniesienie zewnętrzne (Firstbeat) — tylko poszerza przedział."),
        )):
            column.metric(label, units.fmt_time(item.methods.get(name)), help=role)


def _anchor(result: dict) -> None:
    perf = result.get("perf")
    with bento.tile("Wysiłek, na którym stoi prognoza", key="anchor", terms=["near_max"],
                    caption=(f"{perf['day']:%d.%m.%Y} · {perf['age_days']} dni temu · {perf['source']}"
                             if perf else None)) as t:
        if not perf:
            st.caption("Brak udokumentowanego wysiłku — prognoza stoi na tętnie.")
            return
        with t.header:
            if st.button("", icon=":material/open_in_new:", type="tertiary", key="forecast_open_anchor",
                         help="Otwórz ten trening"):
                routing.open_run(perf["activity_id"])
        label = sessions.EFFORT_LABELS.get(perf["effort"], perf["effort"])
        columns = st.columns(3)
        columns[0].metric(label, units.fmt_time(perf["seconds"]),
                          help=f"{perf['distance_m'] / 1000:.2f} km")
        columns[1].metric("tempo", units.fmt_pace(units.pace_from(perf["seconds"], perf["distance_m"] / 1000), False))
        columns[2].metric("VDOT", f"{perf['vdot']:.1f}",
                          help=f"surowy {perf['vdot_raw']:.1f}; wysiłków w oknie 120 dni: {perf['n_efforts']}")
        hr = f"{perf['hr_frac']:.0%} HRmax" if perf.get("hr_frac") else "bez tętna"
        st.markdown(f"<div class='tile-caption'>{hr} — "
                    + ("bliski maksymalnego" if perf["near_max"] else "nie maksymalny: dolna granica") + "</div>",
                    unsafe_allow_html=True)


def _preparation(result: dict, item: forecast.DistanceForecast) -> None:
    perf = result.get("perf")
    hr = result.get("hr")
    calibration = result.get("calibration")
    if hr:
        st.caption(
            f"Tętno: {hr['n']} spokojnych biegów z 42 dni, surowy VDOT z tętna {hr['raw']:.1f} "
            + (f"× kalibracja {calibration['factor']:.2f} (z {calibration['n']} wysiłków bliskich maksimum) "
               f"= {hr['vdot']:.1f}." if calibration else "— bez kalibracji, więc poza prognozą.")
            + f" HRmax {result['hr_max']:.0f} (trzecie najwyższe maksimum z biegów)."
        )
    with st.expander(f"Przygotowanie do dystansu — {units.RACE_LABELS[item.key]}"):
        prep = item.prep
        st.dataframe(
            pd.DataFrame(
                [
                    {"składnik": "najdłuższy bieg (6 tyg.)", "jest": f"{prep['long_km']:.1f} km",
                     "przyjęte minimum": f"{prep['long_need']:.0f} km", "waga": "40%"},
                    {"składnik": "średnio tygodniowo (6 tyg.)", "jest": f"{prep['weekly_km']:.1f} km",
                     "przyjęte minimum": f"{prep['weekly_need']:.0f} km", "waga": "40%"},
                    {"składnik": f"tygodnie z ≥ {max(2, prep['runs_need'] - 1)} biegami (8 tyg.)",
                     "jest": f"{prep['consistency']:.0%}", "przyjęte minimum": "100%", "waga": "20%"},
                ]
            ),
            hide_index=True, width="stretch",
        )
        anchor_km = (perf or {}).get("distance_m", 5000) / 1000
        extra = forecast.MAX_EXTRA_EXPONENT * (1 - prep["score"])
        st.caption(
            f"Wynik {prep['score']:.0%}. Krzywa Danielsa zakłada trening pod dystans; brak przygotowania "
            f"podnosi wykładnik Riegla o {extra:.3f} ponad dystans kotwicy ({anchor_km:.1f} km): "
            f"potencjał {units.fmt_time(item.potential_s)} → realistycznie {units.fmt_time(item.realistic_s)}."
        )


def _backtest(history: pd.DataFrame) -> None:
    efforts = rc.efforts()
    if efforts.empty or "near_max" not in efforts.columns:
        return
    table = forecast.backtest(history, efforts)
    error = table["error_pct"].abs() if not table.empty else pd.Series(dtype=float)
    slower = int((table["error_pct"] > 0).sum()) if not table.empty else 0
    with bento.tile(
        "Sprawdzenie wstecz", rows=2, key="backtest", terms=["backtest"],
        caption=(f"{len(table)} porównań · mediana błędu <b>{error.median():.1f}%</b> · za wolno {slower}, "
                 f"za szybko {len(table) - slower}") if not table.empty else None,
        how="Mocne biegi (≥ 3 km) wobec tego, co model przewidywał tydzień wcześniej. Dodatni błąd = prognoza "
            "zbyt ostrożna (zwykle po okresie szybkiego postępu).",
    ) as t:
        if table.empty:
            st.caption("Brak wysiłków bliskich maksymalnego ≥ 3 km z prognozą tydzień wcześniej.")
            return
        _backtest_table(t, table)


def _backtest_table(t, table: pd.DataFrame) -> None:
    table = table.sort_values("day", ascending=False)
    t.table(
        pd.DataFrame(
            {
                "dzień": pd.to_datetime(table["day"]).dt.strftime("%d.%m.%Y"),
                "dystans": (table["distance_m"] / 1000).round(2),
                "wynik": table["actual_s"].map(units.fmt_time),
                "prognoza": table["predicted_s"].map(units.fmt_time),
                "błąd %": table["error_pct"],
            }
        ),
    )


def _assumptions() -> None:
    with st.expander("Założenia modelu"):
        req = pd.DataFrame(forecast.REQUIREMENTS).T.rename(
            index=units.RACE_LABELS, columns={"long_km": "długi bieg km", "weekly_km": "km/tydz.", "runs": "biegi/tydz."}
        )
        st.dataframe(req, width="stretch")
        st.markdown(
            "- Wydolność to VDOT z krzywych Danielsa i Gilberta (koszt tlenowy biegu × ułamek VO₂max możliwy "
            "do utrzymania przez dany czas). Na tych samych krzywych liczone są tempa treningowe w planie.\n"
            "- Wymagania dystansu powyżej to heurystyki dla biegaczy rekreacyjnych, nie normy. Niedobór "
            f"podnosi wykładnik Riegla maksymalnie o {forecast.MAX_EXTRA_EXPONENT}.\n"
            "- Starszy wysiłek maksymalny traci 0,3% na tydzień po 4 tygodniach (maks. 12%) — łagodnie, bo "
            "zwykle trening trwa dalej.\n"
            "- Tętno → VO₂max przez %HRR ≈ %VO₂R (Swain), kalibrowane osobistym współczynnikiem.\n"
            "- „Po planie”: +1 VDOT na ~5 tygodni regularnego treningu (Daniels: podnoś VDOT o 1 co 4–6 tygodni), "
            "maks. 16 tygodni, i przygotowanie, które osiąga plan.\n"
            "- Model nie widzi trasy zawodów, pogody, taktyki ani dnia startu. Upał i przewyższenia potrafią "
            "kosztować więcej niż szerokość przedziału."
        )
        paces = physio.training_paces(rc.current_forecast().get("vdot"))
        if paces:
            st.caption("Tempa treningowe przy obecnym VDOT: " + " · ".join(
                f"{name} {units.fmt_pace(a, False)}–{units.fmt_pace(b, False)}" for name, (a, b) in paces.items()))
