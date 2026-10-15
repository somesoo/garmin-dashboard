"""Physiology from the training data alone: critical speed, Riegel, economy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import shell
import theme as tz


def render() -> None:
    st.title("Fizjologia")
    st.caption(
        "Wszystko tutaj liczy się z samych treningów — bez testu na bieżni "
        "i bez laboratorium."
    )
    _critical_speed()
    _riegel()
    _economy()
    _zones()
    _predictions()


def _critical_speed() -> None:
    table = shell.table("critical_speed")
    activities = shell.table("activities")
    shell.lead(
        "Prędkość krytyczna",
        "Model dwuparametrowy `d = CS·t + D′` dopasowany na najlepszych odcinkach "
        "1 km / 1 mila / 5 km w oknie 90 dni. CS to tempo utrzymywane tlenowo, D′ to "
        "skończony zapas dystansu powyżej niej — ta sama matematyka, którą "
        "w kolarstwie zna się jako FTP i W′.",
    )
    if table.empty:
        shell.missing("critical_speed", "Potrzebne biegi z co najmniej dwoma różnymi odcinkami.")
        return

    fitted = table.dropna(subset=["cs_ms"])
    last, first = fitted.tail(1).iloc[0], fitted.head(1).iloc[0]
    columns = st.columns(5)
    columns[0].metric("CS", f"{last['cs_ms']:.2f} m/s", f"{last['cs_ms'] - first['cs_ms']:+.2f}")
    columns[1].metric("CS jako tempo", f"{last['cs_pace_min_km']:.2f} min/km")
    columns[2].metric("D′", f"{last['d_prime_m']:.0f} m")
    columns[3].metric("R² dopasowania", f"{last['r2']}")
    columns[4].metric("Prognoza 5 km", shell.clock(last.get("pred_5k_s")))

    tz.show(
        tz.stacked_panels(
            table,
            "day",
            [
                {"title": "CS — prędkość krytyczna (m/s)", "series": {"CS": "cs_ms"}, "kind": "line"},
                {"title": "D′ — zapas beztlenowy (m)", "series": {"D′": "d_prime_m"}, "kind": "line"},
            ],
            height=400,
        ),
        table=table[["day", "cs_ms", "cs_pace_min_km", "d_prime_m", "r2", "distances"]].tail(25),
        note="CS i D′ zwykle idą w przeciwnych kierunkach: blok tlenowy podnosi CS "
        "i obniża D′, blok szybkościowy odwrotnie. Jeśli rosną oba, sprawdź kolumnę "
        "`distances` — okno z dwoma dystansami to prosta przez dwa punkty.",
    )

    shell.sub(
        "Hiperbola wydolności",
        "Im dłużej trwa wysiłek, tym bliżej CS można go utrzymać. Punkty to twoje "
        "rekordy odcinków, linia to model dopasowany do nich.",
    )
    cs_value, d_prime = float(last["cs_ms"]), float(last["d_prime_m"])
    times = np.linspace(60, 3600, 240)
    tokens = tz.tokens()
    figure = go.Figure()
    figure.add_scatter(
        x=times / 60,
        y=cs_value + d_prime / times,
        mode="lines",
        line=dict(width=2, color=tokens["series"][0]),
        name="model CS + D′/t",
        hovertemplate="%{x:.1f} min: %{y:.2f} m/s<extra>model</extra>",
    )
    points = []
    if not activities.empty:
        runs = activities[activities["sport"].astype(str).str.contains("running", na=False)]
        for column, metres, label in (
            ("best_1k_s", 1000, "1 km"),
            ("best_mile_s", 1609, "1 mila"),
            ("best_5k_s", 5000, "5 km"),
        ):
            if column in runs.columns:
                best = pd.to_numeric(runs[column], errors="coerce").min()
                if pd.notna(best) and best > 0:
                    points.append((best / 60, metres / best, label, shell.clock(best)))
    if points:
        figure.add_scatter(
            x=[p[0] for p in points],
            y=[p[1] for p in points],
            mode="markers+text",
            text=[f"{p[2]} · {p[3]}" for p in points],
            textposition="top center",
            textfont=dict(size=11, color=tokens["ink_secondary"]),
            marker=dict(size=11, color=tokens["series"][1], line=dict(width=2, color=tokens["surface"])),
            name="rekordy odcinków",
            hoverinfo="skip",
        )
    figure.add_hline(
        y=cs_value,
        line_width=1,
        line_color=tokens["axis"],
        annotation_text="CS",
        annotation_position="bottom right",
        annotation_font=dict(size=10, color=tokens["muted"]),
    )
    figure.update_layout(**tz.base_layout(legend=True, height=400, hover="closest"))
    figure.update_xaxes(title_text="czas trwania (min)")
    figure.update_yaxes(title_text="prędkość (m/s)")
    tz.show(
        tz.style_axes(figure),
        table=pd.DataFrame(
            [{"dystans": p[2], "czas": p[3], "prędkość m/s": round(p[1], 2)} for p in points]
        ),
    )


def _riegel() -> None:
    riegel = shell.table("riegel")
    shell.lead(
        "Wykładnik Riegela",
        "`t = a·d^b`: `b` to osobista sygnatura wytrzymałości. Około 1.06 to poziom "
        "dobrze rozbieganego zawodnika, powyżej ~1.12 prędkość szybko siada "
        "z dystansem.",
    )
    if riegel.empty:
        shell.missing("riegel")
        return
    figure = tz.timeseries(riegel, "day", {"b": "riegel_b"}, y_title="wykładnik b")
    if figure is not None:
        tz.threshold(figure, 1.06, label="1.06", status="good")
    tz.show(figure, table=riegel[["day", "riegel_b", "distances"]].tail(20))


def _economy() -> None:
    efficiency = shell.table("efficiency")
    shell.lead(
        "Ekonomia biegu",
        "Metry na uderzenie serca: prędkość skorygowana o nachylenie dzielona przez "
        "tętno. Pojedyncza sesja nic nie znaczy (upał, teren, sen) — mediana z 10 "
        "sesji jest zaskakująco stabilna.",
    )
    if efficiency.empty:
        shell.missing("efficiency")
        return
    view = shell.clip(efficiency)
    tokens = tz.tokens()
    figure = go.Figure()
    figure.add_scatter(
        x=view["day"],
        y=view["ef"],
        mode="markers",
        name="sesja",
        marker=dict(size=8, color=tz._alpha(tokens["series"][0], 0.45),
                    line=dict(width=2, color=tokens["surface"])),
        hovertemplate="%{x|%Y-%m-%d}: %{y:.3f}<extra>sesja</extra>",
    )
    if "ef_roll10" in view.columns:
        figure.add_scatter(
            x=view["day"],
            y=view["ef_roll10"],
            mode="lines",
            name="mediana 10 sesji",
            line=dict(width=2.4, color=tokens["series"][0]),
            hovertemplate="%{y:.3f}<extra>mediana 10</extra>",
        )
    figure.update_layout(**tz.base_layout(legend=True, height=340, hover="closest"))
    figure.update_yaxes(title_text="m / uderzenie")
    tz.show(
        tz.polish_dates(tz.style_axes(figure), view["day"]),
        table=view[["day", "distance_km", "avg_hr", "ef", "ef_roll10"]].tail(30),
        note="Rosnąca mediana przy tym samym tętnie to realny postęp tlenowy. Jeśli "
        "rośnie tylko dlatego, że biegasz szybciej na wyższym tętnie — to nie postęp, "
        "tylko mocniejszy trening.",
    )


def _zones() -> None:
    zones = shell.table("intensity_distribution")
    shell.lead(
        "Rozkład intensywności",
        "Udział czasu tygodniowo w trzech pasmach: łatwo (strefy 1–2), środek "
        "(strefa 3) i mocno (strefy 4–5). Model spolaryzowany to dużo niebieskiego, "
        "trochę pomarańczowego i mało szarego pośrodku. Etykieta modelu to reguła "
        "opisowa (≥70% łatwo, ≥10% mocno, <15% w środku), nie opublikowany indeks.",
    )
    if zones.empty:
        shell.missing("intensity_distribution")
        return
    view = zones.copy()
    view["week"] = pd.to_datetime(view["iso_week"] + "-1", format="%G-W%V-%u", errors="coerce")
    view = shell.clip(view.dropna(subset=["week"]), "week")
    if view.empty:
        st.caption("Brak treningów z tętnem w tym zakresie.")
        return
    columns = ["easy_pct", "middle_pct", "hard_pct"]
    colors = tz.intensity_colors()
    tz.show(
        tz.stacked(
            view, "week", columns,
            {"easy_pct": "łatwo", "middle_pct": "środek", "hard_pct": "mocno"},
            y_title="% czasu", height=300,
            colors={"easy_pct": colors["easy"], "middle_pct": colors["middle"], "hard_pct": colors["hard"]},
        ),
        table=view[["iso_week", "total_min", "easy_pct", "middle_pct", "hard_pct", "model"]]
        .sort_values("iso_week", ascending=False)
        .head(25),
        note="Tygodnie w zakresie: "
        + " · ".join(f"{name} ×{count}" for name, count in view["model"].value_counts().items()),
        key="zones",
    )


def _predictions() -> None:
    frame = shell.daily()
    columns = [c for c in ("race_5k_s", "race_10k_s", "race_hm_s", "race_marathon_s") if c in frame.columns]
    if not columns:
        return
    view = shell.clip(frame)
    labels = {
        "race_5k_s": "5 km",
        "race_10k_s": "10 km",
        "race_hm_s": "półmaraton",
        "race_marathon_s": "maraton",
    }
    present = [c for c in columns if pd.to_numeric(view[c], errors="coerce").notna().any()]
    if not present:
        return
    shell.lead(
        "Prognozy Garmina",
        "Przewidywane czasy na podstawie ostatnich treningów. Zmiana: względem "
        "początku wybranego zakresu — w dół znaczy szybciej.",
    )
    tiles = st.columns(len(present))
    for tile, column in zip(tiles, present):
        values = pd.to_numeric(view[column], errors="coerce").dropna()
        now, then = float(values.iloc[-1]), float(values.iloc[0])
        change = now - then
        # ASCII minus: Streamlit reads the arrow direction from the string, and a
        # typographic "−" made a faster prediction show as a red rise.
        sign = "-" if change < 0 else "+"
        tile.metric(
            labels[column],
            _duration(now),
            f"{sign}{shell.clock(abs(change))}" if abs(change) >= 1 else None,
            delta_color="inverse",
        )
    minutes = view[["day", "race_5k_s"]].copy() if "race_5k_s" in view.columns else None
    if minutes is not None:
        minutes["5 km"] = pd.to_numeric(minutes["race_5k_s"], errors="coerce") / 60
        shell.sub("Prognoza na 5 km (minuty)")
        tz.show(tz.timeseries(minutes, "day", {"5 km": "5 km"}, height=220,
                              end_labels=True, decimals=1), key="pred_5k")

    garmin = pd.to_numeric(frame.get("race_5k_s"), errors="coerce").dropna()
    cs_table = shell.table("critical_speed")
    model = cs_table.dropna(subset=["pred_5k_s"]).tail(1) if not cs_table.empty else pd.DataFrame()
    if not garmin.empty and not model.empty:
        st.caption(
            f"Model CS na 5 km: **{shell.clock(float(model['pred_5k_s'].iloc[0]))}** · "
            f"Garmin: **{shell.clock(float(garmin.iloc[-1]))}**. Model CS liczy czysty "
            "potencjał z rekordów odcinków i jest zwykle optymistyczny — nie uwzględnia "
            "zmęczenia narastającego na pełnym dystansie."
        )


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else shell.clock(seconds)
