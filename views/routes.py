"""Route explorer: one GPS track at a time, plus every track at once.

The map lives inside a fragment so that switching the coloured metric reruns
only this block, and ``uirevision`` keyed on the activity keeps the viewer's
pan and zoom across that rerun. Changing the activity is the one case where
resetting the view is the right behaviour, so the key changes with it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import bento
from core import i18n
from ui import routing
from ui import shell
from ui import tables
from ui import theme as tz

def _colour_choices() -> dict[str, str]:
    tr = i18n.tr
    return {"pace_min_km": tr(pl="tempo", en="pace"), "hr": tr(pl="tętno", en="heart rate"),
            "elevation_m": tr(pl="wysokość", en="elevation"), "speed_ms": tr(pl="prędkość", en="speed")}


def _colour_units() -> dict[str, str]:
    tr = i18n.tr
    return {"pace_min_km": tr(pl="tempo /km", en="pace /km"), "hr": "bpm",
            "elevation_m": tr(pl="m n.p.m.", en="m a.s.l."), "speed_ms": "m/s"}


def _sport_label(code: object) -> str:
    """The discipline's name where the catalogue knows the Garmin sport, the code otherwise."""
    from sport import catalog

    key = catalog.discipline_of(code if isinstance(code, str) else None)
    return catalog.label(key) if key else str(code or "").replace("_", " ")


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

    options = [int(a) for a in catalogue["activity_id"]]
    # Another page (the Atlas globe) can ask for one activity by id; the picker
    # keeps its own state afterwards, so the request is consumed once.
    wanted = st.session_state.pop("routes_activity_request", None)
    if wanted is not None:
        if int(wanted) in options:
            st.session_state["routes_activity"] = int(wanted)

    tr = i18n.tr
    choices, units = _colour_choices(), _colour_units()
    with st.container(key="routes_picker"):
        chosen = tables.chooser(
            tables.activity_items(catalogue, catalogue["sport"].map(_sport_label)), options[0],
            key="routes_activity_pick", state="routes_activity")
    colour, analysis = st.columns([3, 1], vertical_alignment="center")
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
    with left:
        _map(track, chosen, colour_by, units)
        _splits(track, summary)
    with right:
        _side(track)
    _gpx(chosen)


def _map(track: pd.DataFrame, chosen: int, colour_by: str, units: dict[str, str]) -> None:
    tr = i18n.tr
    with bento.tile(
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
                reverse_scale=(colour_by == "pace_min_km"), pace=(colour_by == "pace_min_km"),
                # Tied to the activity, not the metric: recolouring keeps the view.
                uirevision=f"route-{int(chosen)}",
            ),
            empty=tr(pl="Ta aktywność nie ma śladu GPS.", en="This activity has no GPS track."),
            key=f"route_map_{int(chosen)}",
            # A phone sees the splits under the map without scrolling past a full-screen map.
            height=380 if shell.phone() else None,
        )


def _splits(track: pd.DataFrame, summary: pd.Series | None) -> None:
    """Kilometre splits right under the map: km, pace, heart rate, climb, cadence."""
    from running import sessions, units as ru

    tr = i18n.tr
    sport = str((summary.get("sport") if summary is not None else "") or "")
    # Splits per kilometre mean something on foot; a ride would list 60 rows of 2-minute kilometres.
    if not any(word in sport for word in ("run", "walk", "hik", "trail")):
        return
    splits = sessions.km_splits(track)
    if splits.empty:
        return
    pace = pd.to_numeric(splits["pace_min_km"], errors="coerce")
    full = splits["length_km"] >= 0.9
    mean = pace[full].mean() if full.any() else pace.mean()
    table = pd.DataFrame({
        "km": [f"{k}" if length >= 0.9 else f"{k} ({length:.2f})" for k, length in zip(splits["km"], splits["length_km"])],
        tr(pl="tempo", en="pace"): pace.map(lambda v: ru.fmt_pace(v, False)),
        "Δ s/km": ((pace - mean) * 60).round().astype("Int64").map(lambda v: "—" if pd.isna(v) else f"{v:+d}"),
        tr(pl="tętno", en="HR"): pd.to_numeric(splits["hr"], errors="coerce").round().astype("Int64"),
        tr(pl="↑ / ↓ m", en="↑ / ↓ m"): [f"+{u:.0f} / −{d:.0f}" if pd.notna(u) and pd.notna(d) else "—"
                                       for u, d in zip(splits["elev_gain_m"], splits["elev_loss_m"])],
    })
    cadence = pd.to_numeric(splits["cadence"], errors="coerce")
    if cadence.notna().any():
        table[tr(pl="kadencja", en="cadence")] = cadence.round().astype("Int64")
    stops = pd.to_numeric(splits["stop_s"], errors="coerce")
    if (stops >= 5).any():
        table[tr(pl="postój", en="stop")] = stops.map(lambda v: ru.fmt_time(v) if pd.notna(v) and v >= 5 else "")
    fastest = pace[full].idxmin() if full.any() else None
    caption = tr(pl=f"średnio {ru.fmt_pace(mean, False)} /km; Δ = różnica od średniej, minus = szybciej",
                 en=f"average {ru.fmt_pace(mean, False)} /km; Δ = off the average, minus = faster")
    if fastest is not None:
        caption += tr(pl=f" · najszybszy km {splits.at[fastest, 'km']}", en=f" · fastest km {splits.at[fastest, 'km']}")
    with bento.tile(tr(pl="Splity kilometrowe", en="Kilometre splits"), key="route_splits", caption=caption,
                    how=tr(pl="Czas stopera, bez autopauzy — postój na światłach jest w tempie (kolumna „postój”). "
                              "Ze strumienia ~400 próbek, dokładność kilku sekund. Ostatni odcinek może być niepełny "
                              "(długość w nawiasie).",
                           en="Stopwatch time, without auto-pause — a stop at the lights is in the pace (the “stop” "
                              "column). From a stream of ~400 samples, accurate to a few seconds. The last split "
                              "may be partial (length in brackets).")):
        tables.show(table)


def _side(track: pd.DataFrame) -> None:
    tr = i18n.tr
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


def _gpx(chosen: int) -> None:
    tr = i18n.tr
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
