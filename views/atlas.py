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
import i18n
import routing
import shell
import theme as tz

def _frames() -> dict[str, str]:
    return {"home": i18n.tr(pl="okolica", en="around home"), "world": i18n.tr(pl="świat", en="world")}


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

    count, days = int(info.get("activities", 0) or 0), int(info.get("days", 0) or 0)
    acts = i18n.plural(count, pl=("aktywność", "aktywności", "aktywności"), en=("activity", "activities"))
    noun = i18n.plural(days, pl=("dzień", "dni", "dni"), en=("day", "days"))
    if row is not None:
        note = i18n.tr(pl=f"{count} {acts} · {days} {noun} pomiarów · ostatni dzień z danymi: {row['day']:%d.%m.%Y}",
                       en=f"{count} {acts} · {days} {noun} measured · latest day with data: {row['day']:%d.%m.%Y}")
    else:
        note = i18n.tr(pl="Brak danych dziennych.", en="No daily data.")
    bento.header(i18n.page("atlas"), note)

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
    tr = i18n.tr
    rebuild = tr(pl="Odśwież tabele: `etl/load.py`.", en="Rebuild the tables: `etl/load.py`.")
    if "start_lat" not in activities.columns:
        shell.missing("activities.start_lat", rebuild)
        return
    with_gps = activities.dropna(subset=["start_lat", "start_lon"]).copy()
    if with_gps.empty:
        shell.missing("activities.start_lat", rebuild)
        return

    # Shown by default; the switch stays for a lighter page (the globe is the
    # heaviest element on it).
    if not st.toggle(tr(pl="Pokaż glob", en="Show the globe"), value=True, key="globe_visible"):
        return

    # One row per activity, built once per warehouse build. Grouping them into
    # markers is the browser's job, because it depends on the zoom.
    starts = globe.starts(with_gps, shell.build_id())
    routes = shell.table("routes")
    tracks = globe.tracks_url(routes, shell.build_id())

    places = with_gps["location"].dropna().value_counts().index.tolist()[:15]
    frames = _frames()
    where_options = list(frames) + places
    where_control, sport_control, spin_control = st.columns([2, 3, 1], vertical_alignment="bottom")
    with where_control:
        where = st.selectbox(
            tr(pl="Kadr", en="View"),
            where_options,
            index=0,
            format_func=lambda v: frames.get(v, v),
            key="globe_where",
        )
    with sport_control:
        sports = sorted(with_gps["sport"].dropna().unique())
        picked = st.multiselect("Sport", sports, default=sports, key="globe_sports",
                                placeholder=tr(pl="wszystkie sporty", en="all sports"))
    with spin_control:
        turning = st.toggle(tr(pl="Obrót", en="Spin"), value=True, key="globe_spin")

    chosen = with_gps[with_gps["sport"].isin(picked)] if picked else with_gps
    selected = None if len(chosen) == len(with_gps) else [int(i) for i in chosen["activity_id"]]

    columns = bento.row(1, 1, 1, 1)
    bento.stat(columns[0], tr(pl="Miejsca", en="Places"), f"{chosen['location'].nunique()}", key="atlas_places")
    bento.stat(columns[1], tr(pl="Aktywności z GPS", en="Activities with GPS"), f"{len(chosen)}", key="atlas_gps")
    bento.stat(columns[2], tr(pl="Dystans", en="Distance"),
               f"{chosen['distance_km'].sum():,.0f} km".replace(",", " "), key="atlas_km")
    bento.stat(columns[3], tr(pl="Czas", en="Time"),
               f"{chosen['duration_min'].sum() / 60:,.0f} h".replace(",", " "), key="atlas_h")

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

    st.caption(tr(
        pl="Punkt to start treningu; przybliż albo wybierz **Kadr**, a na poziomie ulic glob staje się mapą ciepła "
           "(ile treningów przeszło odcinkiem). Klik w start otwiera ślad na stronie *Trasy*.",
        en="A point is the start of a session; zoom in or pick a **View**, and at street level the globe becomes a "
           "heat map (how many sessions ran along each stretch). Clicking a start opens its track on *Routes*.",
    ))

    pick = _fresh_pick(clicked)
    if pick is None:
        return
    if pick.get("activity"):
        routing.open_activity(int(pick["activity"]))
        return
    st.dialog(tr(pl="Który trening otworzyć?", en="Which session to open?"))(_pick_dialog)(pick, with_gps)


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
    latest = i18n.tr(pl="ostatnio", en="latest")
    with bento.tile("Readiness", key="atlas_readiness", terms=["readiness"], how=glossary.trend_how(),
                    caption=f"{latest} <b>{row['readiness']:.0f}</b>"
                    if row is not None and pd.notna(row.get("readiness")) else None) as t:
        t.chart(tz.trend(view, "day", {"readiness": ("readiness", "readiness_roll7")}),
                table=view[["day", "readiness"]].tail(40))
    with bento.tile(i18n.tr(pl="HRV w nocy", en="Overnight HRV"), key="atlas_hrv", terms=["hrv"],
                    how=glossary.trend_how(),
                    caption=f"{latest} <b>{row['hrv_last_night']:.0f} ms</b>"
                    if row is not None and pd.notna(row.get("hrv_last_night")) else None) as t:
        t.chart(tz.trend(view, "day", {"HRV": ("hrv_last_night", "hrv_last_night_roll7")},
                         band=("hrv_baseline_low", "hrv_baseline_high"), unit="ms"),
                table=view[["day", "hrv_last_night"]].tail(40))


def _load() -> None:
    tr = i18n.tr
    pmc = shell.clip(shell.table("pmc"))
    with bento.tile(tr(pl="Obciążenie i forma", en="Load and form"), rows=2, key="atlas_pmc",
                    terms=["ctl", "atl", "tsb"],
                    caption=tr(pl="Sprawność rośnie wolno, zmęczenie szybko. Pełny model: strona Forma.",
                               en="Fitness rises slowly, fatigue fast. The full model: the Form page.")) as t:
        if pmc.empty:
            shell.missing("pmc", tr(pl="Uruchom `analytics.py`.", en="Run `analytics.py`."))
            return
        t.chart(tz.stacked_panels(pmc, "day", [
            {"title": "CTL / ATL", "series": {tr(pl="sprawność", en="fitness"): "ctl",
                                              tr(pl="zmęczenie", en="fatigue"): "atl"},
             "kind": "line", "height": 1.4},
            {"title": tr(pl="Load dzienny", en="Daily load"), "series": {"load": "load_day"}, "kind": "bar",
             "height": 0.8},
        ], height=400), table=pmc[["day", "ctl", "atl", "tsb", "load_day"]].tail(40))


def _places(activities: pd.DataFrame) -> None:
    if "location" not in activities.columns:
        return
    tr = i18n.tr
    place, count = tr(pl="miejsce", en="place"), tr(pl="aktywności", en="activities")
    hours, last = tr(pl="godziny", en="hours"), tr(pl="ostatnia", en="latest")
    places = (
        activities.dropna(subset=["location"])
        .groupby("location")
        .agg(
            count=("activity_id", "count"),
            km=("distance_km", "sum"),
            hours=("duration_min", lambda s: s.sum() / 60),
            last=("start_local", "max"),
        )
        .sort_values("count", ascending=False)
        .reset_index()
    )
    if places.empty:
        return
    for column in ("km", "hours"):
        places[column] = places[column].round(1)
    places["last"] = pd.to_datetime(places["last"]).dt.date
    places = places.rename(columns={"location": place, "count": count, "hours": hours, "last": last})
    top = places.head(10).copy()
    with bento.tile(tr(pl="Gdzie najwięcej", en="Where most"), rows=2, key="atlas_where",
                    caption=tr(pl="Treningi w podróży zwykle wyglądają inaczej niż domowe.",
                               en="Sessions while travelling usually look different from those at home.")) as t:
        t.chart(tz.hbars(top, place, count), table=places)


def _recent(activities: pd.DataFrame) -> None:
    if activities.empty:
        return
    recent = activities.sort_values("start_local", ascending=False).head(10).copy()
    recent["start_local"] = pd.to_datetime(recent["start_local"]).dt.strftime("%d.%m %H:%M")
    if "pace_min_km" in recent.columns:
        recent["pace_min_km"] = shell.pace_column(recent["pace_min_km"])
    columns = ["start_local", "sport", "name", "distance_km", "duration_min", "pace_min_km", "avg_hr",
               "training_load", "location"]
    shown = recent[[c for c in columns if c in recent.columns]].rename(columns=shell.activity_labels())
    with bento.tile(i18n.tr(pl="Ostatnie aktywności", en="Recent activities"), rows=2, key="atlas_recent",
                    caption=i18n.tr(pl="Wszystkie sporty, najnowsze na górze.",
                                    en="All sports, newest on top.")) as t:
        t.table(shown, column_config=shell.activity_columns())


def _pick_dialog(pick: dict, activities: pd.DataFrame) -> None:
    """Body of the "which session" dialog; wrapped in st.dialog by the caller,
    so its title follows the interface language."""
    tr = i18n.tr
    ids = [int(i) for i in pick.get("ids", [])]
    here = activities[activities["activity_id"].astype("int64").isin(ids)]
    here = here.sort_values("start_local", ascending=False)
    if here.empty:
        st.caption(tr(pl="W tym punkcie nie ma aktywności — odśwież tabele.",
                      en="There are no activities at this point — rebuild the tables."))
        return

    noun = i18n.plural(len(here), pl=("aktywność", "aktywności", "aktywności"), en=("activity", "activities"))
    name = pick.get("name", "—")
    st.caption(tr(
        pl=f"**{name}** · {len(here)} {noun} · otwieram na stronie *Trasy* ze śladem GPS. Przybliż glob, żeby "
           "klikać pojedyncze treningi bez tego pytania.",
        en=f"**{name}** · {len(here)} {noun} · opens on *Routes* with the GPS track. Zoom the globe in to "
           "click single sessions without this question.",
    ))
    for _, row in here.head(12).iterrows():
        st.button(
            f"{_describe(row)} — {row.get('name') or tr(pl='trening', en='session')}",
            key=f"globe_pick_{int(row['activity_id'])}",
            width="stretch",
            on_click=_request,
            args=(int(row["activity_id"]),),
        )
    if len(here) > 12:
        st.caption(tr(
            pl=f"…i {len(here) - 12} starszych w tym miejscu — przybliż glob albo zajrzyj na stronę *Aktywności*.",
            en=f"…and {len(here) - 12} older ones here — zoom the globe in or look at the *Activities* page.",
        ))
