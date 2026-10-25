"""Landing page: where the training happened, then how it is going.

The globe is the hero because this athlete trains across countries -- the one
fact a table of averages cannot show. It is a custom component (see
``globe.py``): it spins in the browser, costs the server nothing while it
turns, and every marker is a control -- clicking a place asks which training to
open. Everything below it answers "and what state am I in right now", in one
column, newest first.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import globe
import bento
import glossary
import routing
import shell
import theme as tz

FRAMES = {"home": "okolica", "world": "świat"}


def render() -> None:
    # A dialog button cannot navigate (its callback runs before the page body),
    # so it parks the request here and the page performs the switch.
    wanted = st.session_state.pop("atlas_open_activity", None)
    if wanted is not None:
        routing.open_activity(int(wanted))

    activities = shell.table("activities")
    frame = shell.daily()
    row = shell.latest_day()
    info = shell.state()

    bento.header(
        "Atlas",
        f"{info.get('activities', 0)} aktywności · {info.get('days', 0)} dni pomiarów · "
        f"ostatni dzień z danymi: {row['day']:%d.%m.%Y}" if row is not None else "Brak danych dziennych.",
    )

    _hero(activities)
    left, right = bento.row(2, 2)
    with left:
        _now(frame, row)
    with right:
        _load()
    left, right = bento.row(2, 2)
    with left:
        _places(activities)
    with right:
        _recent(activities)


def _hero(activities: pd.DataFrame) -> None:
    """The globe, its filters, and what a click on it does.

    Zoomed out it is the map of places; zoomed in to a city it becomes the heat
    map of every track, each stretch coloured by how many times it was run.
    The place picker flies there, the sport picker filters both layers.
    """
    if "start_lat" not in activities.columns:
        shell.missing("activities.start_lat", "Odśwież tabele: `etl/load.py`.")
        return
    with_gps = activities.dropna(subset=["start_lat", "start_lon"]).copy()
    if with_gps.empty:
        shell.missing("activities.start_lat", "Odśwież tabele: `etl/load.py`.")
        return

    # Shown by default; the switch stays for a lighter page (the globe is the
    # heaviest element on it).
    if not st.toggle("Pokaż glob", value=True, key="globe_visible"):
        return

    # One row per activity, built once per warehouse build. Grouping them into
    # markers is the browser's job, because it depends on the zoom.
    starts = globe.starts(with_gps, shell.build_id())
    routes = shell.table("routes")
    tracks = globe.tracks_url(routes, shell.build_id())

    places = with_gps["location"].dropna().value_counts().index.tolist()[:15]
    where_options = list(FRAMES) + places
    where_control, sport_control, spin_control = st.columns([2, 3, 1], vertical_alignment="bottom")
    with where_control:
        where = st.selectbox(
            "Kadr",
            where_options,
            index=0,
            format_func=lambda v: FRAMES.get(v, v),
            key="globe_where",
        )
    with sport_control:
        sports = sorted(with_gps["sport"].dropna().unique())
        picked = st.multiselect("Sport", sports, default=sports, key="globe_sports",
                                placeholder="wszystkie sporty")
    with spin_control:
        turning = st.toggle("Obrót", value=True, key="globe_spin")

    chosen = with_gps[with_gps["sport"].isin(picked)] if picked else with_gps
    selected = None if len(chosen) == len(with_gps) else [int(i) for i in chosen["activity_id"]]

    columns = bento.row(1, 1, 1, 1)
    bento.stat(columns[0], "Miejsca", f"{chosen['location'].nunique()}", key="atlas_places")
    bento.stat(columns[1], "Aktywności z GPS", f"{len(chosen)}", key="atlas_gps")
    bento.stat(columns[2], "Dystans", f"{chosen['distance_km'].sum():,.0f} km".replace(",", " "), key="atlas_km")
    bento.stat(columns[3], "Czas", f"{chosen['duration_min'].sum() / 60:,.0f} h".replace(",", " "), key="atlas_h")

    if where == "home":
        target = globe.home(starts)
    elif where == "world":
        target = globe.world(starts)
    else:
        ids = set(chosen.loc[chosen["location"] == where, "activity_id"].astype("int64"))
        if not ids:
            ids = set(with_gps.loc[with_gps["location"] == where, "activity_id"].astype("int64"))
        here = routes[pd.to_numeric(routes["activity_id"], errors="coerce").isin(ids)]
        target = globe.place(here) or globe.home(starts)
    with st.container(key="globe_stage"):
        clicked = globe.show(
            starts,
            spin=bool(turning),
            target=target,
            frame=where,
            tracks=tracks,
            selected=selected,
            key="atlas_globe",
        )

    st.caption(
        "Punkt to start treningu; przybliż albo wybierz **Kadr**, a na poziomie ulic glob staje się mapą ciepła "
        "(ile treningów przeszło odcinkiem). Klik w start otwiera ślad na stronie *Trasy*."
    )

    pick = _fresh_pick(clicked)
    if pick is None:
        return
    if pick.get("activity"):
        routing.open_activity(int(pick["activity"]))
        return
    _pick_dialog(pick, with_gps)


def _fresh_pick(clicked: dict | None) -> dict | None:
    """One action per click.

    The component keeps its value across reruns, so the click counter is what
    separates "the viewer just clicked" from "this is the same value again
    after a rerun" -- without it the dialog would reopen on every rerun and
    could never be dismissed.
    """
    if not clicked or "clicks" not in clicked:
        return None
    seen = st.session_state.get("globe_clicks_seen", 0)
    clicks = int(clicked.get("clicks", 0))
    if clicks <= seen:
        return None
    st.session_state["globe_clicks_seen"] = clicks
    return clicked


def _describe(row: pd.Series) -> str:
    when = pd.to_datetime(row["start_local"])
    parts = [f"{when:%d.%m.%Y}", str(row.get("sport") or "")]
    if pd.notna(row.get("distance_km")):
        parts.append(f"{row['distance_km']:.1f} km")
    if pd.notna(row.get("duration_min")):
        parts.append(f"{row['duration_min']:.0f} min")
    return " · ".join(p for p in parts if p)


def _request(activity_id: int) -> None:
    st.session_state["atlas_open_activity"] = int(activity_id)


def _now(frame: pd.DataFrame, row: pd.Series | None) -> None:
    view = shell.clip(frame)
    with bento.tile("Readiness", key="atlas_readiness", terms=["readiness"], how=glossary.TREND_HOW,
                    caption=f"ostatnio <b>{row['readiness']:.0f}</b>" if row is not None and pd.notna(row.get("readiness"))
                    else None) as t:
        t.chart(tz.trend(view, "day", {"readiness": ("readiness", "readiness_roll7")}),
                table=view[["day", "readiness"]].tail(40))
    with bento.tile("HRV w nocy", key="atlas_hrv", terms=["hrv"], how=glossary.TREND_HOW,
                    caption=f"ostatnio <b>{row['hrv_last_night']:.0f} ms</b>"
                    if row is not None and pd.notna(row.get("hrv_last_night")) else None) as t:
        t.chart(tz.trend(view, "day", {"HRV": ("hrv_last_night", "hrv_last_night_roll7")},
                         band=("hrv_baseline_low", "hrv_baseline_high"), unit="ms"),
                table=view[["day", "hrv_last_night"]].tail(40))


def _load() -> None:
    pmc = shell.clip(shell.table("pmc"))
    with bento.tile("Obciążenie i forma", rows=2, key="atlas_pmc", terms=["ctl", "atl", "tsb"],
                    caption="Sprawność rośnie wolno, zmęczenie szybko. Pełny model: strona Forma.") as t:
        if pmc.empty:
            shell.missing("pmc", "Uruchom `analytics.py`.")
            return
        t.chart(tz.stacked_panels(pmc, "day", [
            {"title": "CTL / ATL", "series": {"sprawność": "ctl", "zmęczenie": "atl"}, "kind": "line", "height": 1.4},
            {"title": "Load dzienny", "series": {"load": "load_day"}, "kind": "bar", "height": 0.8},
        ], height=400), table=pmc[["day", "ctl", "atl", "tsb", "load_day"]].tail(40))


def _places(activities: pd.DataFrame) -> None:
    if "location" not in activities.columns:
        return
    places = (
        activities.dropna(subset=["location"])
        .groupby("location")
        .agg(
            aktywności=("activity_id", "count"),
            km=("distance_km", "sum"),
            godziny=("duration_min", lambda s: s.sum() / 60),
            ostatnia=("start_local", "max"),
        )
        .sort_values("aktywności", ascending=False)
        .reset_index()
        .rename(columns={"location": "miejsce"})
    )
    if places.empty:
        return
    for column in ("km", "godziny"):
        places[column] = places[column].round(1)
    places["ostatnia"] = pd.to_datetime(places["ostatnia"]).dt.date
    top = places.head(10).copy()
    with bento.tile("Gdzie najwięcej", rows=2, key="atlas_where",
                    caption="Treningi w podróży zwykle wyglądają inaczej niż domowe.") as t:
        t.chart(tz.hbars(top, "miejsce", "aktywności"), table=places)


def _recent(activities: pd.DataFrame) -> None:
    if activities.empty:
        return
    recent = activities.sort_values("start_local", ascending=False).head(10).copy()
    recent["start_local"] = pd.to_datetime(recent["start_local"]).dt.strftime("%d.%m %H:%M")
    if "pace_min_km" in recent.columns:
        recent["pace_min_km"] = shell.pace_column(recent["pace_min_km"])
    columns = {
        "start_local": "kiedy",
        "sport": "sport",
        "name": "nazwa",
        "distance_km": "km",
        "duration_min": "min",
        "pace_min_km": "min/km",
        "avg_hr": "tętno",
        "training_load": "load",
        "location": "miejsce",
    }
    shown = recent[[c for c in columns if c in recent.columns]].rename(columns=columns)
    with bento.tile("Ostatnie aktywności", rows=2, key="atlas_recent", caption="Wszystkie sporty, najnowsze na górze."):
        st.dataframe(shown, width="stretch", hide_index=True, column_config=shell.ACTIVITY_COLUMNS,
                     height=bento.chart_height(2, caption=True))


@st.dialog("Który trening otworzyć?")
def _pick_dialog(pick: dict, activities: pd.DataFrame) -> None:
    ids = [int(i) for i in pick.get("ids", [])]
    here = activities[activities["activity_id"].astype("int64").isin(ids)]
    here = here.sort_values("start_local", ascending=False)
    if here.empty:
        st.caption("W tym punkcie nie ma aktywności — odśwież tabele.")
        return

    st.caption(
        f"**{pick.get('name', '—')}** · {len(here)} "
        + ("aktywność" if len(here) == 1 else "aktywności")
        + " · otwieram na stronie *Trasy* ze śladem GPS. Przybliż glob, żeby "
        "klikać pojedyncze treningi bez tego pytania."
    )
    for _, row in here.head(12).iterrows():
        st.button(
            f"{_describe(row)} — {row.get('name') or 'trening'}",
            key=f"globe_pick_{int(row['activity_id'])}",
            width="stretch",
            on_click=_request,
            args=(int(row["activity_id"]),),
        )
    if len(here) > 12:
        st.caption(
            f"…i {len(here) - 12} starszych w tym miejscu — przybliż glob albo "
            "zajrzyj na stronę *Aktywności*."
        )
