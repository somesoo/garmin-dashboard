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
from ui import replay
from ui import routing
from ui import shell
from ui import tables
from ui import theme as tz

def _sport_label(code: object) -> str:
    """The discipline's name where the catalogue knows the Garmin sport, the code otherwise."""
    from sport import catalog

    key = catalog.discipline_of(code if isinstance(code, str) else None)
    return catalog.label(key) if key else str(code or "").replace("_", " ")


def render() -> None:
    from ui import elevation

    elevation.selector()
    tr = i18n.tr
    routes = shell.table("routes")
    activities = shell.table("activities")

    bento.header(i18n.page("trasy"), tr(
        pl="Ślady aktywności innych niż bieg — biegi mają mapę w Treningu. Wszystkie ślady naraz są na globie w Atlasie.",
        en="Tracks of activities other than runs — a run has its map on the Run page. All tracks at once are on "
           "the Atlas globe."))
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
        st.caption(tr(pl="Poza biegami nie ma tu aktywności ze śladem GPS. Mapa biegu jest w Treningu, w zakładce "
                         "„Przegląd”.",
                      en="Apart from runs there are no activities with a GPS track. A run's map is on the Run page, "
                         "in the “Overview” tab."))
        if st.button(i18n.page("bieg"), icon=":material/directions_run:", key="routes_to_runs", type="tertiary"):
            routing.goto("bieg")
        return

    _explorer(routes, catalogue)


def _catalogue(routes: pd.DataFrame, activities: pd.DataFrame) -> pd.DataFrame:
    ids = set(pd.to_numeric(routes["activity_id"], errors="coerce").dropna().astype("int64"))
    frame = activities.copy()
    frame["activity_id"] = pd.to_numeric(frame["activity_id"], errors="coerce")
    frame = frame[frame["activity_id"].isin(ids)].copy()
    # A run lives on its own page, map included (routing.open_activity sends it there).
    runs = shell.table("run_sessions")
    if not runs.empty:
        frame = frame[~frame["activity_id"].isin(pd.to_numeric(runs["activity_id"], errors="coerce"))]
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
    with st.container(key="routes_picker"):
        chosen = tables.chooser(
            tables.activity_items(catalogue, catalogue["sport"].map(_sport_label)), options[0],
            key="routes_activity_pick", state="routes_activity")

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
        map_tile(track, chosen)
        sport = str((summary.get("sport") if summary is not None else "") or "")
        # Splits per kilometre mean something on foot; a ride would list 60 rows of 2-minute kilometres.
        if any(word in sport for word in ("walk", "hik", "trail")):
            splits_tile(track)
    with right:
        streams_tile(track, int(chosen), key="route_ov_streams")
    _gpx(chosen)


def map_tile(track: pd.DataFrame, activity_id: int, *, key: str = "route") -> None:
    """The activity's map (also the run page's): one component that shows, reads, moves and plays.

    Everything happens inside it (ui/replay.py) -- the colour switch, the zoom, the play button --
    so nothing on it reruns Streamlit, and the phone gets the same map, only narrower.
    """
    tr = i18n.tr
    with bento.tile(
        tr(pl="Mapa", en="Map"), rows=3, key=f"{key}_map",
        how=tr(pl="Kolor śladu niesie miarę z przełącznika w rogu (tempo: jaśniej = szybciej); skala przycięta do "
                  "5–95%, więc postój na światłach nie zjada zakresu. Kółka z liczbą to kilometry. Najedź na ślad "
                  "(na telefonie: dotknij), a pod mapą pojawią się liczby z tego miejsca; kliknięcie przenosi tam "
                  "kropkę. Mapę przeciągasz myszą, przybliżasz przyciskami, dwuklikiem albo Ctrl + kółkiem; na "
                  "telefonie dwoma palcami (jeden przewija stronę) albo wygodniej na pełnym ekranie. ▶ puszcza "
                  "aktywność jak film: przycisk ×10 zmienia prędkość (10 s aktywności na 1 s filmu, do ×300), "
                  "pasek obok to profil wybranej miary i zarazem suwak.",
               en="The track's colour carries the measure from the switch in the corner (pace: lighter = faster); "
                  "the scale is clipped to 5–95%, so a stop at the lights does not eat the range. Numbered circles "
                  "are kilometres. Point at the track (on a phone: tap it) and the numbers of that spot appear "
                  "under the map; a click moves the dot there. Drag the map with the mouse, zoom with the buttons, "
                  "a double click or Ctrl + scroll; on a phone with two fingers (one scrolls the page) or, easier, "
                  "in full screen. ▶ plays the activity like a film: the ×10 button changes the speed (10 s of "
                  "the activity per 1 s of film, up to ×300); the bar beside it is the profile of the chosen "
                  "measure and the seek bar at once."),
    ):
        # Under the map stand the numbers and the bar (about 110 px); on a phone the map is about square.
        height = 360 if shell.phone() else max(340, bento.chart_height(3) - 110)
        if not replay.show(track, key=f"{key}_map_{int(activity_id)}", channel=int(activity_id), map_height=height):
            st.caption(tr(pl="Ta aktywność nie ma śladu GPS.", en="This activity has no GPS track."))


def split_table(splits: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Kilometre splits as one readable table, and the sentence under it.

    km, pace, Δ from the average (minus = faster), heart rate, climb, and
    cadence and stops when there are any.
    """
    from running import units as ru

    tr = i18n.tr
    pace = pd.to_numeric(splits["pace_min_km"], errors="coerce")
    full = splits["length_km"] >= 0.9
    mean = pace[full].mean() if full.any() else pace.mean()
    table = pd.DataFrame({
        "km": [f"{k}" if length >= 0.9 else f"{k} ({length:.2f})" for k, length in zip(splits["km"], splits["length_km"])],
        tr(pl="tempo", en="pace"): pace.map(lambda v: ru.fmt_pace(v, False)),
        "Δ s/km": ((pace - mean) * 60).round().astype("Int64").map(lambda v: "—" if pd.isna(v) else f"{v:+d}"),
        tr(pl="tętno", en="HR"): pd.to_numeric(splits["hr"], errors="coerce").round().astype("Int64"),
        "↑ / ↓ m": [f"+{u:.0f} / −{d:.0f}" if pd.notna(u) and pd.notna(d) else "—"
                    for u, d in zip(splits["elev_gain_m"], splits["elev_loss_m"])],
    })
    cadence = pd.to_numeric(splits["cadence"], errors="coerce")
    if cadence.notna().any():
        table[tr(pl="kadencja", en="cadence")] = cadence.round().astype("Int64")
    stops = pd.to_numeric(splits["stop_s"], errors="coerce") if "stop_s" in splits.columns else pd.Series(dtype=float)
    if (stops >= 5).any():
        table[tr(pl="postój", en="stop")] = stops.map(lambda v: ru.fmt_time(v) if pd.notna(v) and v >= 5 else "")
    fastest = pace[full].idxmin() if full.any() and pace[full].notna().any() else None
    caption = tr(pl=f"średnio {ru.fmt_pace(mean, False)} /km; Δ = różnica od średniej, minus = szybciej",
                 en=f"average {ru.fmt_pace(mean, False)} /km; Δ = off the average, minus = faster")
    if fastest is not None:
        caption += tr(pl=f" · najszybszy km {splits.at[fastest, 'km']}", en=f" · fastest km {splits.at[fastest, 'km']}")
    return table, caption


def split_how() -> str:
    return i18n.tr(
        pl="Czas stopera, bez autopauzy — postój na światłach jest w tempie (kolumna „postój”). Ze strumienia "
           "~400 próbek, dokładność kilku sekund. Ostatni odcinek może być niepełny (długość w nawiasie).",
        en="Stopwatch time, without auto-pause — a stop at the lights is in the pace (the “stop” column). From "
           "a stream of ~400 samples, accurate to a few seconds. The last split may be partial (length in brackets).")


def splits_tile(track: pd.DataFrame) -> None:
    """Kilometre splits right under the map (a walk, a hike)."""
    from running import sessions

    splits = sessions.km_splits(track)
    if splits.empty:
        return
    table, caption = split_table(splits)
    with bento.tile(i18n.tr(pl="Splity kilometrowe", en="Kilometre splits"), key="route_splits", caption=caption,
                    how=split_how()) as t:
        t.chart(tz.split_bars(splits), table=table, key="split_bars_route",
                height=len(splits) * 26 + 24, empty=i18n.tr(pl="Brak splitów.", en="No splits."))


def streams_tile(track: pd.DataFrame, activity_id: int, *, key: str) -> None:
    """Pace, heart rate and elevation, all three at once (what used to be a lone elevation profile).

    With a clock in the track these are the map's own charts: the same clock, one playhead, a mouse
    over them moves the dot on the map and a press or a drag moves the film. A track nobody timed
    gets a plain figure along the distance, with hover.
    """
    tr = i18n.tr
    caption = tr(pl="Wyżej na panelu tempa = szybciej.", en="Higher on the pace panel = faster.")
    if "elevation_source" in track and track["elevation_source"].astype(str).str.startswith("mapzen").any():
        caption += tr(pl=" Wysokość: Mapzen · Copernicus / EU-DEM (finansowanie UE) · USGS (SRTM, GMTED2010).",
                      en=" Elevation: Mapzen · Copernicus / EU-DEM (EU funding) · USGS (SRTM, GMTED2010).")
    if replay.ready(track):
        with bento.tile(tr(pl="Przebieg w czasie", en="Over time"), rows=2, key=f"{key}_replay", caption=caption,
                        how=tr(pl="Wykresy i mapa mają jeden zegar: najedź na wykres, a kropka na mapie pokaże to "
                                  "miejsce; dotknięcie albo przeciągnięcie przenosi tam film, a przy odtwarzaniu "
                                  "kursor biegnie razem z kropką.",
                               en="The charts and the map share one clock: point at a chart and the dot on the map "
                                  "shows that spot; a tap or a drag moves the film there, and during a replay "
                                  "the cursor runs with the dot.")):
            replay.charts(track, key=f"{key}_replaycharts_{int(activity_id)}", channel=int(activity_id),
                          height=bento.chart_height(2))
        return
    panels = []
    if "pace_min_km" in track.columns and track["pace_min_km"].notna().any():
        panels.append({"title": tr(pl="Tempo (/km)", en="Pace (/km)"),
                       "series": {tr(pl="tempo", en="pace"): "pace_min_km"}, "kind": "line", "pace": True})
    if "hr" in track.columns and track["hr"].notna().any():
        panels.append({"title": tr(pl="Tętno (bpm)", en="Heart rate (bpm)"),
                       "series": {tr(pl="tętno", en="heart rate"): "hr"}, "kind": "line"})
    if "elevation_m" in track.columns and track["elevation_m"].notna().any():
        panels.append({"title": tr(pl="Wysokość (m n.p.m.)", en="Elevation (m a.s.l.)"),
                       "series": {tr(pl="wysokość", en="elevation"): "elevation_m"}, "kind": "line"})
    with bento.tile(tr(pl="Przebieg wzdłuż dystansu", en="Along the distance"), rows=2, key=key,
                    caption=caption) as t:
        figure = tz.stacked_panels(track, "distance_km", panels, height=bento.chart_height(2)) if panels else None
        if figure is not None:
            figure.update_xaxes(title_text=tr(pl="dystans (km)", en="distance (km)"), row=len(panels), col=1)
        t.chart(figure, table=track.head(200), empty=tr(pl="Brak strumienia próbek.", en="No sample stream."),
                key=f"{key}_chart_{int(activity_id)}")


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
