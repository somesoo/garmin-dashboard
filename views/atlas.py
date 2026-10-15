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

    st.title("Atlas")
    st.caption(
        f"{info.get('activities', 0)} aktywności · {info.get('days', 0)} dni pomiarów · "
        f"ostatni dzień z danymi: {row['day']:%d.%m.%Y}"
        if row is not None
        else "Brak danych dziennych."
    )

    _hero(activities)
    _now(frame, row)
    _places(activities)
    _recent(activities)


def _hero(activities: pd.DataFrame) -> None:
    """The globe, its two controls, and what a click on it does."""
    if "start_lat" not in activities.columns:
        shell.missing("activities.start_lat", "Odśwież tabele: `etl/load.py`.")
        return
    with_gps = activities.dropna(subset=["start_lat", "start_lon"]).copy()
    if with_gps.empty:
        shell.missing("activities.start_lat", "Odśwież tabele: `etl/load.py`.")
        return

    # One row per activity, built once per warehouse build. Grouping them into
    # markers is the browser's job, because it depends on the zoom.
    starts = globe.starts(with_gps, shell.build_id())

    columns = st.columns(4)
    columns[0].metric("Miejsca", f"{with_gps['location'].nunique()}")
    columns[1].metric("Z GPS", f"{len(with_gps)}")
    columns[2].metric("Dystans", f"{with_gps['distance_km'].sum():,.0f} km".replace(",", " "))
    columns[3].metric("Czas", f"{with_gps['duration_min'].sum() / 60:,.0f} h".replace(",", " "))

    frame_control, spin_control = st.columns([3, 1], vertical_alignment="bottom")
    with frame_control:
        focus = st.segmented_control(
            "Kadr",
            list(FRAMES),
            default="home",
            format_func=FRAMES.get,
            key="globe_frame",
            label_visibility="collapsed",
        ) or "home"
    with spin_control:
        turning = st.toggle("Obrót", value=True, key="globe_spin")

    target = globe.home(starts) if focus == "home" else globe.world(starts)
    with st.container(key="globe_stage"):
        clicked = globe.show(
            starts,
            spin=bool(turning),
            target=target,
            frame=focus,
            key="atlas_globe",
        )

    st.caption(
        "Każdy punkt to start treningu; kółko myszy przybliża, a przy "
        "przybliżaniu skupiska rozpadają się na pojedyncze treningi. "
        "**Kliknięcie pojedynczego treningu otwiera jego ślad na stronie "
        "*Trasy***; kliknięcie skupiska pyta, który z nich otworzyć. Glob kręci "
        "się w przeglądarce — przeciągnięcie obraca go ręcznie, „Obrót” "
        "zatrzymuje, „okolica” i „świat” przelatują do wybranego kadru."
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
    if frame.empty or row is None:
        return
    shell.lead(
        "Stan na dziś",
        "Cztery liczby, które zmieniają decyzję o dzisiejszym treningu, i ich "
        "przebieg w wybranym zakresie.",
    )
    previous = frame.iloc[-2] if len(frame) > 1 else None
    shell.metrics(
        row,
        previous,
        [
            ("readiness", "Readiness", ""),
            ("hrv_last_night", "HRV noc", "ms"),
            ("rhr", "RHR", "bpm", "inverse"),
            ("sleep_h", "Sen", "h"),
        ],
    )

    view = shell.clip(frame)
    pmc = shell.clip(shell.table("pmc"))
    panels = [
        {
            "title": "Readiness",
            "series": {"readiness": "readiness", "średnia 7 d": "readiness_roll7"},
            "kind": "line",
        },
        {
            "title": "HRV w nocy (ms)",
            "series": {"HRV": "hrv_last_night", "średnia 7 d": "hrv_last_night_roll7"},
            "kind": "line",
        },
    ]
    tz.show(tz.stacked_panels(view, "day", panels, height=320))

    if not pmc.empty:
        shell.sub(
            "Obciążenie i forma",
            "Sprawność rośnie wolno, zmęczenie szybko; forma to ich różnica. "
            "Pełny model jest na stronie **Forma**.",
        )
        tz.show(
            tz.stacked_panels(
                pmc,
                "day",
                [
                    {
                        "title": "CTL / ATL",
                        "series": {"sprawność": "ctl", "zmęczenie": "atl"},
                        "kind": "line",
                        "height": 1.4,
                    },
                    {"title": "Load dzienny", "series": {"load": "load_day"}, "kind": "bar", "height": 0.8},
                ],
                height=340,
            )
        )


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
    shell.lead(
        "Gdzie najwięcej",
        "Miejsca uszeregowane liczbą aktywności. Treningi w podróży zwykle wyglądają "
        "inaczej niż domowe — warto o tym pamiętać, patrząc na średnie.",
    )
    for column in ("km", "godziny"):
        places[column] = places[column].round(1)
    places["ostatnia"] = pd.to_datetime(places["ostatnia"]).dt.date
    top = places.head(12).copy()
    tz.show(
        tz.bars(top.sort_values("aktywności"), "miejsce", "aktywności", height=360),
        table=places,
    )


def _recent(activities: pd.DataFrame) -> None:
    if activities.empty:
        return
    shell.lead("Ostatnie aktywności")
    recent = activities.sort_values("start_local", ascending=False).head(10).copy()
    recent["start_local"] = pd.to_datetime(recent["start_local"]).dt.strftime("%d.%m %H:%M")
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
    st.dataframe(shown, width="stretch", hide_index=True)


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
