"""Segmenty: private segments -- every pass, the ranking and the trend."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import theme as tz
from running import sessions, store, units, workouts
from views import run_common as rc


def render() -> None:
    bento.header(i18n.page("segmenty"), "Rekordy na dystansach i na odcinkach interwałów, a pod nimi segmenty — "
                             "Twoje i znalezione na trasach, które biegasz najczęściej.")
    frame = rc.guard()
    if frame is None:
        return
    reps = rc.rep_efforts()
    rep_list = workouts.rep_segments(reps)
    _distance_records()
    _rep_records(rep_list, reps)
    _segment_list(rc.all_segments() + rep_list,
                  pd.concat([rc.segment_efforts(), reps.drop(columns="km")], ignore_index=True)
                  if not reps.empty else rc.segment_efforts())


def open_key(segment_id: str) -> str:
    """Session key of a segment's expander -- set it to open the segment from another page."""
    return f"seg_open_{segment_id}"


def _segment_list(every: list[dict], efforts: pd.DataFrame) -> None:
    """Every segment as one collapsed line; its details are drawn only when opened."""
    with bento.panel(
        "Segmenty", key="segment_list", terms=["segment"],
        caption="Twoje, „auto” (trasy przebiegnięte ≥ 4 razy) i odcinki z interwałów. Rozwiń, żeby zobaczyć "
                "trend, ranking i mapę.",
    ):
        if not every:
            st.caption("Brak segmentów: żadna trasa nie powtórzyła się jeszcze 4 razy. Własny zapiszesz na "
                       "stronie *Trening* (panel „Nowy segment z tego biegu”).")
            return
        counts = efforts.groupby("segment_id").size() if not efforts.empty else pd.Series(dtype=int)
        order = {"saved": 0, "auto": 1, "reps": 2}
        every = sorted(every, key=lambda item: (order[_origin(item)], -counts.get(item["id"], 0)))
        for item in every:
            passes = efforts[efforts["segment_id"] == item["id"]].sort_values("start_local") \
                if not efforts.empty else efforts
            expander = st.expander(_label(item, passes), key=open_key(item["id"]), on_change="rerun",
                                   icon={"saved": ":material/bookmark:", "auto": ":material/route:",
                                         "reps": ":material/timer:"}[_origin(item)])
            with expander:
                if expander.open:
                    _details(item, passes)


def _origin(item: dict) -> str:
    return "reps" if item.get("reps") else "auto" if item.get("auto") else "saved"


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Polish: 1 przebieg, 2-4 przebiegi (not 12-14), 5+ przebiegów."""
    if count == 1:
        return one
    return few if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14) else many


def _label(item: dict, passes: pd.DataFrame) -> str:
    # An auto segment's name already carries its length.
    origin = _origin(item)
    text = item["name"] + {"saved": f" · {item['length_m'] / 1000:.2f} km", "auto": " · auto", "reps": ""}[origin]
    if passes.empty:
        return f"{text} · brak przebiegów"
    best = passes.loc[passes["seconds"].idxmin()]
    count = len(passes)
    noun = _plural(count, "powtórzenie", "powtórzenia", "powtórzeń") if item.get("reps") \
        else _plural(count, "przebieg", "przebiegi", "przebiegów")
    return f"{text} · {count} {noun} · rekord {units.fmt_time(best['seconds'])} ({best['start_local']:%d.%m.%Y})"


def _details(segment: dict, passes: pd.DataFrame) -> None:
    _kpis(passes, segment["id"])
    if not passes.empty:
        left, right = bento.row(2, 2)
        with left:
            _trend(passes, segment)
        with right:
            _ranking(passes, segment["id"])
    if segment.get("reps"):
        return
    left, right = bento.row(2, 2)
    with left, bento.tile("Przebieg segmentu", rows=2, key=f"segment_map_{segment['id']}") as t:
        points = pd.DataFrame(segment["points"], columns=["lat", "lon"])
        points["distance_km"] = range(len(points))
        points["distance_km"] = points["distance_km"] / max(len(points) - 1, 1) * segment["length_m"] / 1000
        t.chart(tz.route_map(points, uirevision=f"segment-{segment['id']}"), key=f"segment_map_{segment['id']}")
    with right:
        _manage(segment)


def _open_selected(event, shown: pd.DataFrame) -> None:
    rows = getattr(getattr(event, "selection", None), "rows", None) or []
    if rows:
        routing.open_run(int(shown.iloc[rows[0]]["activity_id"]))


def _rep_records(rep_list: list[dict], reps: pd.DataFrame) -> None:
    """Workout reps by standard length: the fastest one of each, wherever run."""
    if not rep_list:
        return
    with bento.panel(
        "Rekordy odcinków z interwałów", key="rep_records", terms=["rep_fade"],
        caption="Każde powtórzenie workoutu z zegarka, pogrupowane po długości (±7%) — niezależnie od miejsca, "
                "także na bieżni. Czas przeliczony na pełną długość w tempie odcinka. Kliknij wiersz, żeby "
                "otworzyć trening.",
    ):
        rows = []
        for item in rep_list:
            pool = reps[reps["segment_id"] == item["id"]].sort_values("start_local")
            best, last = pool.loc[pool["pace_min_km"].idxmin()], pool.iloc[-1]
            rows.append({
                "activity_id": best["activity_id"],
                "odcinek": workouts.rep_label(item["length_m"]),
                "powtórzenia": len(pool),
                "w treningach": pool["activity_id"].nunique(),
                "rekord": units.fmt_time(best["seconds"]),
                "tempo": units.fmt_pace(best["pace_min_km"], False),
                "tętno": best["hr"],
                "kiedy": f"{best['start_local']:%d.%m.%Y}",
                "który": f"{best['pass']:.0f}. odcinek",
                "ostatnio": "rekord" if last["pace_min_km"] == best["pace_min_km"]
                else f"+{(last['pace_min_km'] - best['pace_min_km']) * 60:.0f} s/km ({last['start_local']:%d.%m.%y})",
            })
        shown = pd.DataFrame(rows).reset_index(drop=True)
        event = st.dataframe(
            shown.drop(columns="activity_id").assign(tętno=shown["tętno"].round().astype("Int64")),
            hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key="rep_records_table", height=bento.table_height(len(shown)),
        )
        _open_selected(event, shown)


def _distance_records() -> None:
    """Strava's best efforts: the fastest 1 km ... marathon ever, and where."""
    efforts = rc.all_efforts()
    if efforts.empty:
        return
    best = efforts.loc[efforts.groupby("effort")["seconds"].idxmin()].sort_values("distance_m")
    frame = rc.runs().set_index("activity_id")
    with bento.panel(
        "Rekordy na dystansach", key="distance_records", terms=["best_effort"],
        caption="Najszybszy odcinek na każdym dystansie — z zawodów albo z treningu. Kliknij wiersz, żeby "
                "otworzyć trening.",
    ):
        shown = best.reset_index(drop=True)
        second = efforts.sort_values("seconds").groupby("effort")["seconds"].nth(1)
        second = efforts.loc[second.index].set_index("effort")["seconds"] if len(second) else pd.Series(dtype=float)
        event = st.dataframe(pd.DataFrame({
            "dystans": shown["effort"].map(sessions.EFFORT_LABELS),
            "rekord": shown["seconds"].map(units.fmt_time),
            "tempo": shown["pace_min_km"].map(lambda v: units.fmt_pace(v, False)),
            "tętno": shown["avg_hr"].round().astype("Int64"),
            "kiedy": pd.to_datetime(shown["day"]).dt.strftime("%d.%m.%Y"),
            "trening": shown["activity_id"].map(lambda a: rc.kind_label(frame.at[a, "kind"])
                                                if a in frame.index else "—"),
            "źródło": shown["source"],
            "przewaga nad 2.": [("<1 s" if second[e] - s < 0.5 else f"{second[e] - s:.0f} s") if e in second.index else "—"
                                for e, s in zip(shown["effort"], shown["seconds"])],
        }), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key="distance_records_table", height=bento.table_height(len(shown)))
        _open_selected(event, shown)


def _kpis(passes: pd.DataFrame, suffix: str) -> None:
    columns = bento.row(1, 1, 1, 1)
    if passes.empty:
        for index, key in enumerate(("seg_n", "seg_best", "seg_last", "seg_median")):
            bento.empty_stat(columns[index], f"{key}_{suffix}")
        return
    best = passes.loc[passes["seconds"].idxmin()]
    last = passes.iloc[-1]
    bento.stat(columns[0], "Przebiegi", f"{len(passes)}", key=f"seg_n_{suffix}",
               note=f"w {passes['activity_id'].nunique()} biegach")
    bento.stat(columns[1], "Najlepszy", units.fmt_time(best["seconds"]), key=f"seg_best_{suffix}",
               note=f"{units.fmt_pace(best['pace_min_km'])} · {best['start_local']:%d.%m.%Y}")
    bento.stat(columns[2], "Ostatni", units.fmt_time(last["seconds"]), key=f"seg_last_{suffix}",
               note=f"{last['start_local']:%d.%m.%Y} · " + ("najlepszy" if last["seconds"] == best["seconds"]
                                                            else f"+{last['seconds'] - best['seconds']:.0f} s"))
    bento.stat(columns[3], "Mediana", units.fmt_time(passes["seconds"].median()), key=f"seg_median_{suffix}",
               note=units.fmt_pace(passes["pace_min_km"].median()))


def _trend(passes: pd.DataFrame, segment: dict) -> None:
    with bento.tile(
        "Segment w czasie", rows=2, key=f"segment_trend_{segment['id']}", terms=["segment"],
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


def _ranking(passes: pd.DataFrame, suffix: str) -> None:
    with bento.tile("Ranking", rows=2, key=f"segment_ranking_{suffix}", how="Kliknij wiersz, żeby otworzyć bieg."):
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
            key=f"segment_ranking_table_{suffix}", height=bento.table_height(len(shown)))
        rows = getattr(getattr(event, "selection", None), "rows", None) or []
        if rows:
            routing.open_run(int(shown.iloc[rows[0]]["activity_id"]))


def _manage(segment: dict) -> None:
    frame = rc.runs()
    source = frame[frame["activity_id"] == segment.get("activity_id")]
    origin = f"{source.iloc[0]['start_local']:%d.%m.%Y}" if not source.empty else "usuniętego biegu"
    where = f"z biegu z {origin} (km {segment.get('km_from', 0):.2f}–{segment.get('km_to', 0):.2f})"
    if segment.get("auto"):
        with bento.panel("Segment znaleziony automatycznie", key=f"segment_manage_{segment['id']}",
                         caption=f"Ten odcinek przebiegłeś w {segment.get('runs', 0)} biegach; wycięty {where}. "
                                 "Zapisany jako Twój zostaje na stałe i dostaje własną nazwę."):
            name = st.text_input("Nazwa", segment["name"], key=f"segment_keep_name_{segment['id']}")
            if st.button("Zapisz jako mój segment", icon=":material/bookmark_add:", width="stretch",
                         key=f"segment_keep_{segment['id']}", type="primary"):
                keep = {k: segment[k] for k in ("points", "length_m", "activity_id", "km_from", "km_to")}
                try:
                    saved = store.save_segment({**keep, "name": name})
                except ValueError as error:
                    st.warning(str(error))
                else:
                    st.session_state[open_key(saved["id"])] = True
                    st.rerun()
        return
    with bento.panel("Segment", key=f"segment_manage_{segment['id']}", caption=f"Wycięty {where}."):
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
