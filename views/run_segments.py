"""Segmenty: private segments -- every pass, the ranking and the trend."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import routing
import theme as tz
from running import store, units
from views import run_common as rc


def render() -> None:
    bento.header("Segmenty", "Twoje odcinki tras: każdy przebieg z każdego biegu z GPS, ranking i trend.")
    frame = rc.guard()
    if frame is None:
        return
    saved = store.segments()
    if not saved:
        st.info("Nie masz jeszcze segmentów. Otwórz bieg na stronie *Trening* i na dole wybierz kilometry "
                "w panelu „Nowy segment z tego biegu”.")
        return
    efforts = rc.segment_efforts()
    counts = efforts.groupby("segment_id").size().to_dict() if not efforts.empty else {}
    by_id = {s["id"]: s for s in saved}

    def describe(segment_id: str) -> str:
        item = by_id[segment_id]
        return f"{item['name']} · {item['length_m'] / 1000:.2f} km · przebiegi: {counts.get(segment_id, 0)}"

    chosen = st.selectbox("Segment", list(by_id), format_func=describe, key="segment_pick",
                          label_visibility="collapsed")
    segment = by_id[chosen]
    passes = efforts[efforts["segment_id"] == chosen].sort_values("start_local") if not efforts.empty else efforts

    _kpis(passes)
    if passes.empty:
        st.caption("Żaden bieg nie przechodzi tego segmentu od początku do końca.")
    else:
        left, right = bento.row(2, 2)
        with left:
            _trend(passes, segment)
        with right:
            _ranking(passes)
    left, right = bento.row(2, 2)
    with left, bento.tile("Przebieg segmentu", rows=2, key="segment_map") as t:
        points = pd.DataFrame(segment["points"], columns=["lat", "lon"])
        points["distance_km"] = range(len(points))
        points["distance_km"] = points["distance_km"] / max(len(points) - 1, 1) * segment["length_m"] / 1000
        t.chart(tz.route_map(points, uirevision=f"segment-{chosen}"), key=f"segment_map_{chosen}")
    with right:
        _manage(segment)


def _kpis(passes: pd.DataFrame) -> None:
    columns = bento.row(1, 1, 1, 1)
    if passes.empty:
        for index, key in enumerate(("seg_n", "seg_best", "seg_last", "seg_median")):
            bento.empty_stat(columns[index], key)
        return
    best = passes.loc[passes["seconds"].idxmin()]
    last = passes.iloc[-1]
    bento.stat(columns[0], "Przebiegi", f"{len(passes)}", key="seg_n",
               note=f"w {passes['activity_id'].nunique()} biegach")
    bento.stat(columns[1], "Najlepszy", units.fmt_time(best["seconds"]), key="seg_best",
               note=f"{units.fmt_pace(best['pace_min_km'])} · {best['start_local']:%d.%m.%Y}")
    bento.stat(columns[2], "Ostatni", units.fmt_time(last["seconds"]), key="seg_last",
               note=f"{last['start_local']:%d.%m.%Y} · " + ("najlepszy" if last["seconds"] == best["seconds"]
                                                            else f"+{last['seconds'] - best['seconds']:.0f} s"))
    bento.stat(columns[3], "Mediana", units.fmt_time(passes["seconds"].median()), key="seg_median",
               note=units.fmt_pace(passes["pace_min_km"].median()))


def _trend(passes: pd.DataFrame, segment: dict) -> None:
    with bento.tile(
        "Segment w czasie", rows=2, key="segment_trend", terms=["segment"],
        caption="Każda kropka to jeden przebieg; kolor to typ treningu — tempo spokojnego i mocnego biegu "
                "na tym samym odcinku to dwie różne rzeczy.",
    ) as t:
        points = passes.assign(
            typ=passes["kind"].map(lambda k: "mocny" if k in ("tempo", "threshold", "intervals", "race")
                                   else "długi" if k == "long" else "spokojny"),
            czas=passes["seconds"].map(units.fmt_time),
            tętno=passes["hr"],
        )
        figure = tz.scatter(points, "start_local", "pace_min_km", color="typ", color_kind="categorical",
                            hover=("czas", "tętno"), x_title="", y_title="", pace_y=True, reverse_y=True)
        t.chart(figure, table=points.assign(kiedy=points["start_local"].dt.strftime("%d.%m.%Y"))[
            ["kiedy", "typ", "czas", "pace_min_km", "tętno"]].rename(columns={"pace_min_km": "tempo"}),
            key=f"segment_trend_{segment['id']}")


def _ranking(passes: pd.DataFrame) -> None:
    with bento.tile("Ranking", rows=2, key="segment_ranking", how="Kliknij wiersz, żeby otworzyć bieg."):
        shown = passes.sort_values("seconds").head(bento.table_rows(2)).reset_index(drop=True)
        event = st.dataframe(pd.DataFrame({
            "#": shown["rank"],
            "kiedy": shown["start_local"].dt.strftime("%d.%m.%Y"),
            "typ": shown["kind"].map(rc.kind_label),
            "czas": shown["seconds"].map(units.fmt_time),
            "tempo": shown["pace_min_km"].map(lambda v: units.fmt_pace(v, False)),
            "tętno": shown["hr"].round().astype("Int64"),
            "od km": shown["at_km"],
        }), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key="segment_ranking_table", height=bento.table_height(len(shown)))
        rows = getattr(getattr(event, "selection", None), "rows", None) or []
        if rows:
            routing.open_run(int(shown.iloc[rows[0]]["activity_id"]))


def _manage(segment: dict) -> None:
    frame = rc.runs()
    source = frame[frame["activity_id"] == segment.get("activity_id")]
    origin = f"{source.iloc[0]['start_local']:%d.%m.%Y}" if not source.empty else "usuniętego biegu"
    with bento.panel("Segment", key="segment_manage",
                     caption=f"Wycięty z biegu z {origin} "
                             f"(km {segment.get('km_from', 0):.2f}–{segment.get('km_to', 0):.2f})."):
        name = st.text_input("Nazwa", segment["name"], key=f"segment_rename_{segment['id']}")
        columns = st.columns(2)
        if columns[0].button("Zapisz nazwę", key=f"segment_rename_save_{segment['id']}", width="stretch",
                             disabled=name.strip() == segment["name"]):
            try:
                store.save_segment({**segment, "name": name})
            except ValueError as error:
                st.warning(str(error))
            else:
                st.rerun()
        if columns[1].button("Usuń segment", icon=":material/delete:", key=f"segment_delete_{segment['id']}",
                             width="stretch"):
            store.delete_segment(segment["id"])
            st.rerun()
