"""Route explorer: one GPS track at a time, plus every track at once.

The map lives inside a fragment so that switching the coloured metric reruns
only this block, and ``uirevision`` keyed on the activity keeps the viewer's
pan and zoom across that rerun. Changing the activity is the one case where
resetting the view is the right behaviour, so the key changes with it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import shell
import theme as tz

def _colour_choices() -> dict[str, str]:
    tr = i18n.tr
    return {"pace_min_km": tr(pl="tempo", en="pace"), "hr": tr(pl="tętno", en="heart rate"),
            "elevation_m": tr(pl="wysokość", en="elevation"), "speed_ms": tr(pl="prędkość", en="speed")}


def _colour_units() -> dict[str, str]:
    tr = i18n.tr
    return {"pace_min_km": tr(pl="tempo /km", en="pace /km"), "hr": "bpm",
            "elevation_m": tr(pl="m n.p.m.", en="m a.s.l."), "speed_ms": "m/s"}


def render() -> None:
    tr = i18n.tr
    routes = shell.table("routes")
    activities = shell.table("activities")

    bento.header(i18n.page("trasy"), tr(pl="Jeden ślad GPS naraz. Wszystkie ślady (mapa ciepła) są na globie w Atlasie.",
                                        en="One GPS track at a time. All tracks (the heat map) are on the Atlas globe."))
    if routes.empty:
        st.caption(tr(
            pl="Brak śladów GPS. `etl/run.py` pobiera je automatycznie — jeden request na aktywność, payload się nie "
               "zmienia, więc pobrany raz zostaje na zawsze.",
            en="No GPS tracks. `etl/run.py` fetches them automatically — one request per activity; the payload never "
               "changes, so once fetched it stays for good.",
        ))
        return

    catalogue = _catalogue(routes, activities)
    if catalogue.empty:
        st.caption(tr(pl="Aktywności ze śladem nie mają metadanych — odśwież tabele.",
                      en="The activities with a track have no metadata — rebuild the tables."))
        return

    _explorer(routes, catalogue)


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

    tr = i18n.tr
    choices, units = _colour_choices(), _colour_units()
    picker, colour, analysis = st.columns([3, 2, 1], vertical_alignment="bottom")
    with picker:
        chosen = st.selectbox(
            tr(pl="Aktywność", en="Activity"), options, format_func=describe, key="routes_activity",
            label_visibility="collapsed",
        )
    with colour:
        colour_by = st.segmented_control(
            tr(pl="Kolor śladu", en="Track colour"),
            list(choices),
            default="pace_min_km",
            format_func=lambda v: choices[v],
            label_visibility="collapsed",
        )
    colour_by = colour_by or "pace_min_km"
    runs = shell.table("run_sessions")
    # Runs have a richer page (splits, reps, segments); the button leads there.
    if not runs.empty and (runs["activity_id"] == chosen).any() and analysis.button(
            tr(pl="Analiza treningu", en="Workout analysis"), icon=":material/insights:", key="routes_to_run",
            width="stretch"):
        routing.open_run(int(chosen))

    track = routes[pd.to_numeric(routes["activity_id"], errors="coerce") == chosen].sort_values("seq")
    summary = catalogue[catalogue["activity_id"] == chosen]
    summary = summary.iloc[0] if not summary.empty else None

    if summary is not None:
        columns = bento.row(1, 1, 1, 1)
        bento.stat(columns[0], tr(pl="Dystans", en="Distance"), f"{summary.get('distance_km', float('nan')):.2f} km",
                   key="r_km")
        bento.stat(columns[1], tr(pl="Czas", en="Time"), f"{summary.get('duration_min', float('nan')):.0f} min",
                   key="r_time")
        bento.stat(columns[2], tr(pl="Tempo", en="Pace"), shell.pace(summary.get("pace_min_km")), key="r_pace")
        bento.stat(columns[3], tr(pl="Tętno śr.", en="Avg HR"), f"{summary.get('avg_hr', float('nan')):.0f}",
                   key="r_hr", note=f"load {summary.get('training_load', float('nan')):.0f}")

    left, right = bento.row(2, 2)
    with left, bento.tile(
        tr(pl="Ślad", en="Track"), rows=3, key="route_map",
        caption=tr(pl=f"kolor: {units[colour_by]} · skala przycięta do 5–95%",
                   en=f"colour: {units[colour_by]} · scale clipped to 5–95%"),
        how=tr(pl="Linia pod spodem trzyma kształt trasy, kolor niesie wartość — ślad zostaje czytelny też tam, "
                  "gdzie zawraca po sobie. Postój na światłach nie zjada zakresu. Tempo ma odwróconą rampę: "
                  "ciemniej = szybciej.",
               en="The line underneath holds the route's shape, the colour carries the value — the track stays "
                  "readable even where it doubles back. A stop at the lights does not eat the range. Pace has a "
                  "reversed ramp: darker = faster."),
    ) as t:
        t.chart(
            tz.route_map(
                track, color=colour_by, color_title=units[colour_by],
                reverse_scale=(colour_by == "pace_min_km"), pace=(colour_by == "pace_min_km"), height=560,
                # Tied to the activity, not the metric: recolouring keeps the view.
                uirevision=f"route-{int(chosen)}",
            ),
            empty=tr(pl="Ta aktywność nie ma śladu GPS.", en="This activity has no GPS track."),
            key=f"route_map_{int(chosen)}",
        )
    with right:
        with bento.tile(tr(pl="Profil wysokości", en="Elevation profile"), key="route_profile") as t:
            t.chart(tz.profile(track), empty=tr(pl="Brak danych wysokości.", en="No elevation data."))
        panels = []
        if "hr" in track.columns and track["hr"].notna().any():
            panels.append({"title": tr(pl="Tętno (bpm)", en="Heart rate (bpm)"),
                           "series": {tr(pl="tętno", en="heart rate"): "hr"}, "kind": "line"})
        if "pace_min_km" in track.columns and track["pace_min_km"].notna().any():
            panels.append({"title": tr(pl="Tempo (/km)", en="Pace (/km)"),
                           "series": {tr(pl="tempo", en="pace"): "pace_min_km"}, "kind": "line", "pace": True})
        if "cadence" in track.columns and track["cadence"].notna().any():
            panels.append({"title": tr(pl="Kadencja", en="Cadence"),
                           "series": {tr(pl="kadencja", en="cadence"): "cadence"}, "kind": "line"})
        with bento.tile(tr(pl="Przebieg wzdłuż dystansu", en="Along the distance"), rows=2, key="route_streams",
                        caption=tr(pl="Wyżej na panelu tempa = szybciej.", en="Higher on the pace panel = faster.")) as t:
            figure = tz.stacked_panels(track, "distance_km", panels, height=400) if panels else None
            if figure is not None:
                figure.update_xaxes(title_text=tr(pl="dystans (km)", en="distance (km)"), row=len(panels), col=1)
            t.chart(figure, table=track.head(200), empty=tr(pl="Brak strumienia próbek.", en="No sample stream."))

    with st.expander(tr(pl="Plik GPX", en="GPX file")):
        st.caption(tr(pl="Ślad jest już w tabeli `routes`; oryginalny GPX pobierzesz z API:",
                      en="The track is already in the `routes` table; the original GPX comes from the API:"))
        st.code(
            "from garminconnect import Garmin\n"
            "g = Garmin(); g.login('~/.garminconnect')\n"
            f"data = g.download_activity({int(chosen)}, "
            "dl_fmt=Garmin.ActivityDownloadFormat.GPX)\n"
            f"open('{int(chosen)}.gpx', 'wb').write(data)",
            language="python",
        )
