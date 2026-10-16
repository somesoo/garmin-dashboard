"""Race-time forecast: numbers, how they were reached, how they moved, what moves them."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import glossary
import routing
import shell
import theme as tz
from running import forecast, physio, sessions, units
from views import run_common as rc


def render() -> None:
    st.title("Prognoza wyników")
    st.caption(
        "Na jaki czas możesz dziś liczyć na każdym dystansie i jak bardzo tej liczbie ufać. Każda sekcja ma "
        "„Co to jest?” z objaśnieniem pojęć; nagłówki kolumn tabeli mają podpowiedzi po najechaniu."
    )
    frame = rc.guard()
    if frame is None:
        return
    result = rc.current_forecast()
    if result.get("status") != "ok":
        st.warning(result.get("reason", "Za mało danych na prognozę."))
        return

    history = rc.history()
    _table(result, history)
    for note in result.get("notes", []):
        st.caption(f"⚠ {note}")

    key = st.segmented_control(
        "Dystans", list(units.RACES), default="10k", format_func=units.RACE_LABELS.get, key="forecast_distance"
    ) or "10k"
    item = result["distances"][key]
    for warning in item.warnings:
        st.warning(warning)
    _confidence(result, item)
    _history_chart(history, key)
    _advice(result, frame, key)
    _method(result, item)
    _backtest(history)
    _assumptions()


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
    shell.lead(
        "Prognoza na dziś",
        f"Twoja wydolność to dziś VDOT {result['vdot']:.1f}; tabela przekłada ją na czasy startowe.",
        terms=["realistic", "interval80", "confidence", "potential", "preparation", "vdot", "after_plan"],
        how="Zmiana 4/12 tyg.: ujemna = prognoza szybsza niż wtedy. „Po planie” pojawia się tylko dla "
            "dystansu z wpisanym startem (strona Zawody).",
    )
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
    st.markdown(
        f"**Pewność: {item.confidence} {rc.CONFIDENCE_ICON[item.confidence]}** — w 8 startach na 10 wynik na "
        f"{label} powinien wypaść między **{units.fmt_time(item.low_s)}** a **{units.fmt_time(item.high_s)}** "
        f"(ok. ±{units.fmt_time(spread)} od {units.fmt_time(item.realistic_s)})."
    )
    reasons = forecast.confidence_reasons(item, result.get("perf"))
    if reasons:
        st.caption("Co poszerza przedział, od największego: " + "; ".join(reasons) + ".")
        st.caption("Najszybciej podnosi pewność mocny bieg (start, test) na dystansie bliskim docelowemu, "
                   "powiązany ze startem na stronie Zawody.")
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
    shell.lead(
        "Jak zmieniała się prognoza",
        "Czy idziesz do przodu: prognoza liczona co tydzień tylko z danych sprzed tego dnia.",
        terms=["near_max", "interval80"],
        how="Wyżej = szybciej. Pas to przedział 80%, linia przerywana — Garmin. Pełne punkty: prognoza oparta "
            "na wysiłku bliskim maksymalnego; puste: tylko na odcinkach treningowych (dolna granica).",
    )
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
    tz.show(
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
    shell.lead(
        f"Co może poprawić wynik — {units.RACE_LABELS[key]}",
        "Miejsca, w których prognoza jest dziś ograniczana, od największego. To luki w danych, nie diagnoza.",
        terms=["preparation", "potential"],
    )
    if not tips:
        st.caption("Przygotowanie spełnia przyjęte wymagania dla tego dystansu — dalszy postęp to głównie "
                   "regularność i stopniowe podnoszenie jakości.")
        return
    st.markdown("\n".join(f"- {tip}" for tip in tips))


def _method(result: dict, item: forecast.DistanceForecast) -> None:
    shell.lead("Z czego to wynika", "Wszystkie wejścia tej prognozy — do sprawdzenia, nie do wiary na słowo.",
               terms=["methods", "near_max", "vdot"])
    perf = result.get("perf")
    with st.expander("Metody i ich zgodność", expanded=True):
        methods = pd.DataFrame(
            [
                {"metoda": "Udokumentowane wysiłki (Daniels)", "czas": units.fmt_time(item.methods.get("wyniki")),
                 "rola": "kotwica prognozy"},
                {"metoda": "Tętno ↔ tempo (skalibrowane)", "czas": units.fmt_time(item.methods.get("tętno")),
                 "rola": "trend i niezależna kontrola"},
                {"metoda": "Garmin (Firstbeat)", "czas": units.fmt_time(item.methods.get("Garmin")),
                 "rola": "odniesienie zewnętrzne — poszerza przedział"},
            ]
        )
        st.dataframe(methods, hide_index=True, width="stretch")
        weights = ", ".join(f"{name} {weight:.0%}" for name, weight in result["weights"].items())
        st.caption(
            f"Wagi w VDOT: {weights}. Rozbieżność metod i odległość od dystansu kotwicy składają się "
            f"na σ = {item.sigma:.3f} (log-czas), co daje przedział ±{(pow(2.718, 1.28 * item.sigma) - 1):.0%}."
        )
    with st.expander("Wysiłek, na którym stoi prognoza"):
        if not perf:
            st.caption("Brak udokumentowanego wysiłku — prognoza stoi na tętnie.")
        else:
            label = sessions.EFFORT_LABELS.get(perf["effort"], perf["effort"])
            st.markdown(
                f"**{label}** ({perf['distance_m'] / 1000:.2f} km) w **{units.fmt_time(perf['seconds'])}** "
                f"({units.fmt_pace(units.pace_from(perf['seconds'], perf['distance_m'] / 1000))}), "
                f"{perf['day']:%d.%m.%Y}, {perf['age_days']} dni temu · źródło: {perf['source']}"
            )
            hr = f"{perf['hr_frac']:.0%} HRmax" if perf.get("hr_frac") else "bez tętna"
            st.caption(
                f"Tętno na tym odcinku: {hr} → "
                + ("wysiłek bliski maksymalnego (≥ 91% HRmax przez ≥ 6 min albo start)."
                   if perf["near_max"] else "nie był maksymalny: wynik z niego to dolna granica.")
                + f" VDOT {perf['vdot_raw']:.1f}"
                + (f", po korekcie na wiek wyniku {perf['vdot']:.1f}" if abs(perf["vdot"] - perf["vdot_raw"]) > 0.05 else "")
                + f". Wysiłków w oknie 120 dni: {perf['n_efforts']}."
            )
            if st.button("Otwórz ten trening", key="forecast_open_anchor"):
                routing.open_run(perf["activity_id"])
        hr = result.get("hr")
        calibration = result.get("calibration")
        if hr:
            st.caption(
                f"Tętno: {hr['n']} spokojnych biegów z 42 dni, surowy VDOT z tętna {hr['raw']:.1f} "
                + (f"× kalibracja {calibration['factor']:.2f} (z {calibration['n']} wysiłków bliskich maksimum) "
                   f"= {hr['vdot']:.1f}." if calibration else "— bez kalibracji, więc poza prognozą.")
                + f" HRmax {result['hr_max']:.0f} (trzecie najwyższe maksimum z biegów — pojedyncze skoki czujnika "
                "się nie liczą)."
            )
    with st.expander("Przygotowanie do dystansu"):
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
    shell.lead(
        "Sprawdzenie wstecz",
        "Ile ta prognoza była warta na twoich danych: mocne biegi (≥ 3 km) wobec tego, co model "
        "przewidywał tydzień wcześniej.",
        terms=["backtest"],
    )
    if table.empty:
        st.caption("Brak wysiłków bliskich maksymalnego ≥ 3 km z prognozą tydzień wcześniej — nie ma czego sprawdzać.")
        return
    error = table["error_pct"].abs()
    slower = int((table["error_pct"] > 0).sum())
    st.caption(
        f"{len(table)} porównań · mediana błędu bezwzględnego {error.median():.1f}% · model przewidział "
        f"wolniej niż wyszło w {slower}, szybciej w {len(table) - slower} przypadkach. Dodatni błąd = "
        "prognoza zbyt ostrożna (zwykle po okresie szybkiego postępu)."
    )
    table = table.sort_values("day", ascending=False)
    st.dataframe(
        pd.DataFrame(
            {
                "dzień": pd.to_datetime(table["day"]).dt.strftime("%d.%m.%Y"),
                "dystans": (table["distance_m"] / 1000).round(2),
                "wynik": table["actual_s"].map(units.fmt_time),
                "prognoza": table["predicted_s"].map(units.fmt_time),
                "błąd %": table["error_pct"],
            }
        ),
        hide_index=True, width="stretch",
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
