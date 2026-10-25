"""Physiology from the training data alone: critical speed, Riegel, economy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bento
import glossary
import shell
import theme as tz


def render() -> None:
    bento.header("Fizjologia", "Wszystko tutaj liczy się z samych treningów — bez testu na bieżni i bez laboratorium.")
    table = shell.table("critical_speed")
    fitted = table.dropna(subset=["cs_ms"]) if not table.empty else table
    _cs_kpis(fitted)

    left, right = bento.row(2, 2)
    with left:
        _critical_speed(table, fitted)
    with right:
        _hyperbola(fitted)
        _riegel()

    left, right = bento.row(2, 2)
    with left:
        _economy()
        _zones()
    with right:
        _predictions()


def _cs_kpis(fitted: pd.DataFrame) -> None:
    columns = bento.row(1, 1, 1, 1)
    if fitted.empty:
        for index, column in enumerate(columns):
            bento.empty_stat(column, f"cs_{index}")
        return
    last, first = fitted.tail(1).iloc[0], fitted.head(1).iloc[0]
    bento.stat(columns[0], "CS — prędkość krytyczna", f"{last['cs_ms']:.2f} m/s", key="cs",
               delta=f"{last['cs_ms'] - first['cs_ms']:+.2f}", help=glossary.short("cs"))
    bento.stat(columns[1], "CS jako tempo", shell.pace(last["cs_pace_min_km"]), key="cs_pace")
    bento.stat(columns[2], "D′ — zapas beztlenowy", f"{last['d_prime_m']:.0f} m", key="d_prime",
               help=glossary.short("d_prime"))
    bento.stat(columns[3], "Prognoza 5 km (model CS)", shell.clock(last.get("pred_5k_s")), key="cs_5k",
               note="potencjał z odcinków — zwykle optymistyczny")


def _critical_speed(table: pd.DataFrame, fitted: pd.DataFrame) -> None:
    caption = (f"R² ostatniego dopasowania <b>{fitted['r2'].iloc[-1]}</b> · okno 90 dni"
               if not fitted.empty else None)
    with bento.tile(
        "Prędkość krytyczna i D′", rows=2, key="cs", terms=["cs", "d_prime", "r2"], caption=caption,
        how="Model `d = CS·t + D′` dopasowany do najlepszych odcinków 1 km / 1 mila / 5 km z 90 dni. "
            "CS i D′ zwykle idą w przeciwnych kierunkach: blok tlenowy podnosi CS i obniża D′. Jeśli rosną "
            "oba, sprawdź kolumnę `distances` w danych — okno z dwoma dystansami to prosta przez dwa punkty.",
    ) as t:
        if table.empty:
            shell.missing("critical_speed", "Potrzebne biegi z co najmniej dwoma różnymi odcinkami.")
            return
        t.chart(
            tz.stacked_panels(table, "day", [
                {"title": "CS (m/s)", "series": {"CS": "cs_ms"}, "kind": "line"},
                {"title": "D′ (m)", "series": {"D′": "d_prime_m"}, "kind": "line"},
            ], height=400),
            table=table[["day", "cs_ms", "cs_pace_min_km", "d_prime_m", "r2", "distances"]].tail(25),
        )


def _hyperbola(fitted: pd.DataFrame) -> None:
    activities = shell.table("activities")
    with bento.tile("Hiperbola wydolności", key="hyperbola", terms=["cs"],
                    caption="Im dłuższy wysiłek, tym bliżej CS da się go utrzymać.",
                    how="Punkty to twoje rekordy odcinków, linia to model dopasowany do nich.") as t:
        if fitted.empty:
            shell.missing("critical_speed")
            return
        last = fitted.tail(1).iloc[0]
        _hyperbola_chart(t, last, activities)


def _hyperbola_chart(t, last, activities) -> None:
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
    figure.update_layout(**tz.base_layout(legend=False, height=200, hover="closest"))
    # Log time: 1 km (~4 min) and 1 mile (~7 min) sit apart instead of on top of each other.
    figure.update_xaxes(title_text="czas trwania (min)", type="log", tickvals=[1, 2, 5, 10, 20, 30, 60])
    figure.update_yaxes(title_text="m/s")
    t.chart(tz.style_axes(figure),
            table=pd.DataFrame([{"dystans": p[2], "czas": p[3], "prędkość m/s": round(p[1], 2)} for p in points]))


def _riegel() -> None:
    riegel = shell.table("riegel")
    with bento.tile("Wykładnik Riegela", key="riegel", terms=["riegel"],
                    caption="Jak bardzo zwalniasz na dłuższych dystansach.") as t:
        if riegel.empty:
            shell.missing("riegel")
            return
        figure = tz.timeseries(riegel, "day", {"b": "riegel_b"}, y_title="b")
        if figure is not None:
            tz.threshold(figure, 1.06, label="1.06", status="good")
        t.chart(figure, table=riegel[["day", "riegel_b", "distances"]].tail(20))


def _economy() -> None:
    efficiency = shell.table("efficiency")
    with bento.tile(
        "Ekonomia biegu", key="economy", terms=["ef"],
        caption="Ten sam wysiłek, coraz więcej prędkości? Liczy się mediana z 10 sesji.",
        how="Rosnąca mediana przy tym samym tętnie to realny postęp tlenowy. Jeśli rośnie tylko dlatego, że "
            "biegasz szybciej na wyższym tętnie — to nie postęp, tylko mocniejszy trening.",
    ) as t:
        if efficiency.empty:
            shell.missing("efficiency")
            return
        _economy_chart(t, efficiency)


def _economy_chart(t, efficiency) -> None:
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
    figure.update_layout(**tz.base_layout(legend=False, height=200, hover="closest"))
    figure.update_yaxes(title_text="m / uderzenie")
    t.chart(tz.polish_dates(tz.style_axes(figure), view["day"]),
            table=view[["day", "distance_km", "avg_hr", "ef", "ef_roll10"]].tail(30))


def _zones() -> None:
    zones = shell.table("intensity_distribution")
    view = zones.copy()
    if not view.empty:
        view["week"] = pd.to_datetime(view["iso_week"] + "-1", format="%G-W%V-%u", errors="coerce")
        view = shell.clip(view.dropna(subset=["week"]), "week")
    caption = (" · ".join(f"{name} ×{count}" for name, count in view["model"].value_counts().items())
               if not view.empty else None)
    with bento.tile(
        "Rozkład intensywności", key="zones", terms=["intensity", "hr_zones"], caption=caption,
        how="Udział czasu tygodniowo: łatwo (strefy 1–2), środek (3), mocno (4–5). Model spolaryzowany to dużo "
            "niebieskiego, trochę pomarańczowego i mało szarego pośrodku. Etykieta modelu to reguła opisowa "
            "(≥70% łatwo, ≥10% mocno, <15% w środku), nie opublikowany indeks.",
    ) as t:
        if view.empty:
            st.caption("Brak treningów z tętnem w tym zakresie.")
            return
        colors = tz.intensity_colors()
        t.chart(
            tz.stacked(view, "week", ["easy_pct", "middle_pct", "hard_pct"],
                       {"easy_pct": "łatwo", "middle_pct": "środek", "hard_pct": "mocno"}, y_title="% czasu",
                       colors={"easy_pct": colors["easy"], "middle_pct": colors["middle"], "hard_pct": colors["hard"]}),
            table=view[["iso_week", "total_min", "easy_pct", "middle_pct", "hard_pct", "model"]]
            .sort_values("iso_week", ascending=False).head(25),
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
    with bento.tile("Prognozy Garmina", rows=2, key="garmin_predictions",
                    caption="Dla porównania z naszą prognozą; zmiana względem początku zakresu.",
                    how="W dół znaczy szybciej.") as t:
        _predictions_body(t, view, present, labels, frame)


def _predictions_body(t, view, present, labels, frame) -> None:
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
    garmin = pd.to_numeric(frame.get("race_5k_s"), errors="coerce").dropna()
    cs_table = shell.table("critical_speed")
    model = cs_table.dropna(subset=["pred_5k_s"]).tail(1) if not cs_table.empty else pd.DataFrame()
    if not garmin.empty and not model.empty:
        st.caption(f"5 km — model CS: **{shell.clock(float(model['pred_5k_s'].iloc[0]))}** · "
                   f"Garmin: **{shell.clock(float(garmin.iloc[-1]))}** (model nie liczy zmęczenia na dystansie).")
    if "race_5k_s" in view.columns:
        minutes = view[["day", "race_5k_s"]].copy()
        minutes["5 km"] = pd.to_numeric(minutes["race_5k_s"], errors="coerce") / 60
        figure = tz.timeseries(minutes, "day", {"5 km (min)": "5 km"}, end_labels=True, decimals=1)
        if figure is not None:
            figure.update_layout(height=bento.chart_height(2, caption=True) - 150)
            st.plotly_chart(figure, width="stretch", key="pred_5k", config={"displayModeBar": False})


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else shell.clock(seconds)
