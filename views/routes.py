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
        _side(track)
    _gpx(chosen)


def map_tile(track: pd.DataFrame, activity_id: int, *, key: str = "route") -> None:
    """The GPS track coloured by a measure picked in the tile's header (also the run page's map)."""
    tr = i18n.tr
    choices, units = _colour_choices(), _colour_units()
    with bento.tile(
        tr(pl="Mapa", en="Map"), rows=3, key=f"{key}_map",
        how=tr(pl="Linia pod spodem trzyma kształt trasy, kolor niesie wartość — ślad zostaje czytelny też tam, "
                  "gdzie zawraca po sobie. Skala przycięta do 5–95%: postój na światłach nie zjada zakresu. "
                  "Tempo ma odwróconą rampę: ciemniej = szybciej. „Odtwórz” puszcza aktywność jak film: kropka "
                  "biegnie trasą (domyślnie 10 s aktywności na 1 s filmu, do ×300), ślad ma kolor wybranej miary, "
                  "a obok liczą się dystans, czas, tempo, tętno i wysokość z tej chwili; wykres pod mapą przewija.",
               en="The line underneath holds the route's shape, the colour carries the value — the track stays "
                  "readable even where it doubles back. Scale clipped to 5–95%: a stop at the lights does not eat "
                  "the range. Pace has a reversed ramp: darker = faster. “Replay” plays the activity like a film: a "
                  "dot runs the route (10 s of the activity per 1 s of film by default, up to ×300), the trail takes "
                  "the colour of the chosen measure, and distance, time, pace, heart rate and elevation of that "
                  "moment run beside it; the chart under the map scrubs."),
    ) as t:
        with t.header:
            options = [*choices, *(["replay"] if replay.ready(track) else [])]
            names = {**choices, "replay": tr(pl="▶ Odtwórz", en="▶ Replay")}
            colour_by = st.segmented_control(
                tr(pl="Kolor śladu", en="Track colour"), options, default="pace_min_km",
                format_func=lambda v: names[v], label_visibility="collapsed", key=f"{key}_colour")
        colour_by = colour_by or "pace_min_km"
        chosen = activity_id
        # The zoom is fitted to the drawn size, so the size is decided here, once.
        phone = shell.phone()
        height, width = (340, 330) if phone else (bento.chart_height(3), 620)
        if colour_by == "replay":
            # The film has its own colour switch and live numbers (ui/replay.py).
            replay.show(track, key=f"{key}_replay_{int(chosen)}", map_height=height if phone else max(340, height - 230))
            return
        t.chart(
            tz.route_map(
                track, color=colour_by, color_title=units[colour_by],
                reverse_scale=(colour_by == "pace_min_km"), pace=(colour_by == "pace_min_km"),
                height=height, width=width,
                # Tied to the activity, not the metric: recolouring keeps the view.
                uirevision=f"route-{int(chosen)}",
            ),
            empty=tr(pl="Ta aktywność nie ma śladu GPS.", en="This activity has no GPS track."),
            key=f"{key}_map_{int(chosen)}",
            height=height,
        )


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
