"""Route explorer: one GPS track at a time, plus every track at once.

The map lives inside a fragment so that switching the coloured metric reruns
only this block, and ``uirevision`` keyed on the activity keeps the viewer's
pan and zoom across that rerun. Changing the activity is the one case where
resetting the view is the right behaviour, so the key changes with it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import shell
import theme as tz

COLOUR_CHOICES = {
    "pace_min_km": "tempo",
    "hr": "tętno",
    "elevation_m": "wysokość",
    "speed_ms": "prędkość",
}
COLOUR_UNITS = {
    "pace_min_km": "min/km",
    "hr": "bpm",
    "elevation_m": "m n.p.m.",
    "speed_ms": "m/s",
}


def render() -> None:
    routes = shell.table("routes")
    activities = shell.table("activities")

    st.title("Trasy")
    if routes.empty:
        st.caption(
            "Brak śladów GPS. `etl/run.py` pobiera je automatycznie — jeden request "
            "na aktywność, payload się nie zmienia, więc pobrany raz zostaje na zawsze."
        )
        return

    catalogue = _catalogue(routes, activities)
    if catalogue.empty:
        st.caption("Aktywności ze śladem nie mają metadanych — odśwież tabele.")
        return

    _explorer(routes, catalogue)
    _everything(routes, catalogue)


def _catalogue(routes: pd.DataFrame, activities: pd.DataFrame) -> pd.DataFrame:
    ids = set(pd.to_numeric(routes["activity_id"], errors="coerce").dropna().astype("int64"))
    frame = activities.copy()
    frame["activity_id"] = pd.to_numeric(frame["activity_id"], errors="coerce")
    frame = frame[frame["activity_id"].isin(ids)].copy()
    if frame.empty:
        return frame
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    return frame.sort_values("start_local", ascending=False)


@st.fragment
def _explorer(routes: pd.DataFrame, catalogue: pd.DataFrame) -> None:
    """Self-contained block: its widgets rerun only this function."""

    def describe(activity_id: float) -> str:
        row = catalogue[catalogue["activity_id"] == activity_id]
        if row.empty:
            return str(int(activity_id))
        row = row.iloc[0]
        distance = row.get("distance_km")
        return (
            f"{row['start_local']:%d.%m.%Y %H:%M} · {row.get('sport', '')}"
            + (f" · {distance:.1f} km" if pd.notna(distance) else "")
            + (f" · {row['location']}" if pd.notna(row.get("location")) else "")
        )

    options = catalogue["activity_id"].tolist()
    # Another page (the Atlas globe) can ask for one activity by id; the picker
    # keeps its own state afterwards, so the request is consumed once.
    wanted = st.session_state.pop("routes_activity_request", None)
    if wanted is not None:
        match = next((o for o in options if int(o) == int(wanted)), None)
        if match is not None:
            st.session_state["routes_activity"] = match

    picker, colour = st.columns([3, 2], vertical_alignment="bottom")
    with picker:
        chosen = st.selectbox(
            "Aktywność", options, format_func=describe, key="routes_activity"
        )
    with colour:
        colour_by = st.segmented_control(
            "Kolor śladu",
            list(COLOUR_CHOICES),
            default="pace_min_km",
            format_func=lambda v: COLOUR_CHOICES[v],
        )
    colour_by = colour_by or "pace_min_km"

    track = routes[pd.to_numeric(routes["activity_id"], errors="coerce") == chosen].sort_values("seq")
    summary = catalogue[catalogue["activity_id"] == chosen]
    summary = summary.iloc[0] if not summary.empty else None

    if summary is not None:
        columns = st.columns(5)
        columns[0].metric("Dystans", f"{summary.get('distance_km', float('nan')):.2f} km")
        columns[1].metric("Czas", f"{summary.get('duration_min', float('nan')):.0f} min")
        pace = summary.get("pace_min_km")
        columns[2].metric("Tempo", f"{pace:.2f} min/km" if pd.notna(pace) else "—")
        columns[3].metric("Tętno śr.", f"{summary.get('avg_hr', float('nan')):.0f}")
        columns[4].metric("Load", f"{summary.get('training_load', float('nan')):.0f}")

    tz.show(
        tz.route_map(
            track,
            color=colour_by,
            color_title=COLOUR_UNITS[colour_by],
            reverse_scale=(colour_by == "pace_min_km"),
            height=560,
            # Tied to the activity, not the metric: recolouring keeps the view.
            uirevision=f"route-{int(chosen)}",
        ),
        empty="Ta aktywność nie ma śladu GPS.",
        key=f"route_map_{int(chosen)}",
    )
    st.caption(
        "Linia pod spodem trzyma kształt trasy, kolorowe punkty niosą wartość — "
        "ślad zostaje czytelny też tam, gdzie zawraca po sobie. Skala jest "
        "przycięta do kwantyli 5–95%, żeby postój na światłach nie zjadł całego "
        "zakresu. Tempo ma odwróconą rampę: ciemniej = szybciej."
    )

    shell.sub("Profil wysokości")
    tz.show(tz.profile(track), empty="Brak danych wysokości.")

    panels = []
    if "hr" in track.columns and track["hr"].notna().any():
        panels.append({"title": "Tętno (bpm)", "series": {"tętno": "hr"}, "kind": "line"})
    if "pace_min_km" in track.columns and track["pace_min_km"].notna().any():
        panels.append({"title": "Tempo (min/km)", "series": {"tempo": "pace_min_km"}, "kind": "line"})
    if "cadence" in track.columns and track["cadence"].notna().any():
        panels.append({"title": "Kadencja", "series": {"kadencja": "cadence"}, "kind": "line"})
    if panels:
        shell.sub("Przebieg wzdłuż dystansu")
        figure = tz.stacked_panels(track, "distance_km", panels, height=120 * len(panels) + 60)
        if figure is not None:
            figure.update_xaxes(title_text="dystans (km)", row=len(panels), col=1)
        tz.show(figure, table=track.head(200))

    with st.expander("Plik GPX"):
        st.caption("Ślad jest już w tabeli `routes`; oryginalny GPX pobierzesz z API:")
        st.code(
            "from garminconnect import Garmin\n"
            "g = Garmin(); g.login('~/.garminconnect')\n"
            f"data = g.download_activity({int(chosen)}, "
            "dl_fmt=Garmin.ActivityDownloadFormat.GPX)\n"
            f"open('{int(chosen)}.gpx', 'wb').write(data)",
            language="python",
        )


@st.fragment
def _everything(routes: pd.DataFrame, catalogue: pd.DataFrame) -> None:
    shell.lead(
        "Wszystkie ślady naraz",
        "Gęstość punktów GPS. Nakładanie setek półprzezroczystych linii zamienia "
        "się w kleks; gęstość utrzymuje czytelność powtarzanych korytarzy i od razu "
        "pokazuje, które pętle są naprawdę domyślne.",
    )
    # A place filter, not just a sport filter: the tracks span several countries,
    # and a density map framed on all of them at once is a blank regional view
    # with the tracks too thin to see.
    places = (
        catalogue.dropna(subset=["location"])["location"].value_counts().index.tolist()
    )
    options = places[:12] + ["wszystko"]
    left, right = st.columns([2, 3], vertical_alignment="bottom")
    with left:
        place = st.selectbox("Miejsce", options, index=0, key="density_place")
    with right:
        sports = sorted(catalogue["sport"].dropna().unique())
        picked = st.multiselect("Sport", sports, default=sports, key="density_sport")

    chosen = catalogue
    if place != "wszystko":
        chosen = chosen[chosen["location"] == place]
    if picked:
        chosen = chosen[chosen["sport"].isin(picked)]

    ids = set(chosen["activity_id"].dropna().astype("int64"))
    points = routes[pd.to_numeric(routes["activity_id"], errors="coerce").isin(ids)]
    tz.show(
        tz.route_density(points, height=600, uirevision=f"density-{place}"),
        note=f"{len(ids)} tras · {len(points):,} punktów".replace(",", " "),
        empty="Brak śladów dla tego filtra.",
        key="density_all",
    )
