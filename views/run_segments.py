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
    bento.header(i18n.page("segmenty"), i18n.tr(
        pl="Rekordy na dystansach i na odcinkach interwałów, a pod nimi segmenty — Twoje i znalezione na trasach, "
           "które biegasz najczęściej.",
        en="Records at distances and on interval reps, and segments below them — yours and those found on the "
           "routes you run most."))
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
    tr = i18n.tr
    with bento.panel(
        i18n.page("segmenty"), key="segment_list", terms=["segment"],
        caption=tr(pl="Twoje, „auto” (trasy przebiegnięte ≥ 4 razy) i odcinki z interwałów. Rozwiń, żeby zobaczyć "
                      "trend, ranking i mapę.",
                   en="Yours, “auto” (routes run ≥ 4 times) and interval reps. Expand to see the trend, the ranking "
                      "and the map."),
    ):
        if not every:
            st.caption(tr(pl="Brak segmentów: żadna trasa nie powtórzyła się jeszcze 4 razy. Własny zapiszesz na "
                             "stronie *Trening* (panel „Nowy segment z tego biegu”).",
                          en="No segments: no route has repeated 4 times yet. Save your own on the *Workout* page "
                             "(the “New segment from this run” panel)."))
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


def _label(item: dict, passes: pd.DataFrame) -> str:
    # An auto segment's name already carries its length.
    tr = i18n.tr
    origin = _origin(item)
    text = item["name"] + {"saved": f" · {item['length_m'] / 1000:.2f} km", "auto": " · auto", "reps": ""}[origin]
    if passes.empty:
        return text + tr(pl=" · brak przebiegów", en=" · no passes")
    best = passes.loc[passes["seconds"].idxmin()]
    count = len(passes)
    noun = i18n.plural(count, pl=("powtórzenie", "powtórzenia", "powtórzeń"), en=("rep", "reps")) if item.get("reps") \
        else i18n.plural(count, pl=("przebieg", "przebiegi", "przebiegów"), en=("pass", "passes"))
    record = f"{units.fmt_time(best['seconds'])} ({best['start_local']:%d.%m.%Y})"
    return f"{text} · {count} {noun} · " + tr(pl=f"rekord {record}", en=f"record {record}")


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
    with left, bento.tile(i18n.tr(pl="Przebieg segmentu", en="Segment course"), rows=2,
                          key=f"segment_map_{segment['id']}") as t:
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
    tr = i18n.tr
    with bento.panel(
        tr(pl="Rekordy odcinków z interwałów", en="Interval rep records"), key="rep_records", terms=["rep_fade"],
        caption=tr(pl="Każde powtórzenie workoutu z zegarka, pogrupowane po długości (±7%) — niezależnie od miejsca, "
                      "także na bieżni. Czas przeliczony na pełną długość w tempie odcinka. Kliknij wiersz, żeby "
                      "otworzyć trening.",
                   en="Every rep of a watch workout, grouped by length (±7%) — wherever it was run, the track "
                      "included. Time scaled to the full length at the rep's pace. Click a row to open the "
                      "session."),
    ):
        heart = tr(pl="tętno", en="HR")
        record = tr(pl="rekord", en="record")
        rows = []
        for item in rep_list:
            pool = reps[reps["segment_id"] == item["id"]].sort_values("start_local")
            best, last = pool.loc[pool["pace_min_km"].idxmin()], pool.iloc[-1]
            slower = f"+{(last['pace_min_km'] - best['pace_min_km']) * 60:.0f} s/km ({last['start_local']:%d.%m.%y})"
            rows.append({
                "activity_id": best["activity_id"],
                tr(pl="odcinek", en="rep"): workouts.rep_label(item["length_m"]),
                tr(pl="powtórzenia", en="reps"): len(pool),
                tr(pl="w treningach", en="in sessions"): pool["activity_id"].nunique(),
                record: units.fmt_time(best["seconds"]),
                tr(pl="tempo", en="pace"): units.fmt_pace(best["pace_min_km"], False),
                heart: best["hr"],
                tr(pl="kiedy", en="when"): f"{best['start_local']:%d.%m.%Y}",
                tr(pl="który", en="which"): tr(pl=f"{best['pass']:.0f}. odcinek", en=f"rep {best['pass']:.0f}"),
                tr(pl="ostatnio", en="latest"): record if last["pace_min_km"] == best["pace_min_km"] else slower,
            })
        shown = pd.DataFrame(rows).reset_index(drop=True)
        event = st.dataframe(
            shown.drop(columns="activity_id").assign(**{heart: shown[heart].round().astype("Int64")}),
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
    tr = i18n.tr
    with bento.panel(
        tr(pl="Rekordy na dystansach", en="Distance records"), key="distance_records", terms=["best_effort"],
        caption=tr(pl="Najszybszy odcinek na każdym dystansie — z zawodów albo z treningu. Kliknij wiersz, żeby "
                      "otworzyć trening.",
                   en="The fastest stretch at every distance — from a race or from training. Click a row to open "
                      "the session."),
    ):
        shown = best.reset_index(drop=True)
        second = efforts.sort_values("seconds").groupby("effort")["seconds"].nth(1)
        second = efforts.loc[second.index].set_index("effort")["seconds"] if len(second) else pd.Series(dtype=float)
        event = st.dataframe(pd.DataFrame({
            tr(pl="dystans", en="distance"): shown["effort"].map(rc.effort_label),
            tr(pl="rekord", en="record"): shown["seconds"].map(units.fmt_time),
            tr(pl="tempo", en="pace"): shown["pace_min_km"].map(lambda v: units.fmt_pace(v, False)),
            tr(pl="tętno", en="HR"): shown["avg_hr"].round().astype("Int64"),
            tr(pl="kiedy", en="when"): pd.to_datetime(shown["day"]).dt.strftime("%d.%m.%Y"),
            tr(pl="trening", en="session"): shown["activity_id"].map(lambda a: rc.kind_label(frame.at[a, "kind"])
                                                                     if a in frame.index else "—"),
            tr(pl="źródło", en="source"): shown["source"],
            tr(pl="przewaga nad 2.", en="lead over 2nd"): [
                ("<1 s" if second[e] - s < 0.5 else f"{second[e] - s:.0f} s") if e in second.index else "—"
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
    tr = i18n.tr
    best = passes.loc[passes["seconds"].idxmin()]
    last = passes.iloc[-1]
    runs = passes["activity_id"].nunique()
    bento.stat(columns[0], tr(pl="Przebiegi", en="Passes"), f"{len(passes)}", key=f"seg_n_{suffix}",
               note=tr(pl=f"w {runs} biegach", en=f"in {runs} runs"))
    bento.stat(columns[1], tr(pl="Najlepszy", en="Best"), units.fmt_time(best["seconds"]), key=f"seg_best_{suffix}",
               note=f"{units.fmt_pace(best['pace_min_km'])} · {best['start_local']:%d.%m.%Y}")
    bento.stat(columns[2], tr(pl="Ostatni", en="Latest"), units.fmt_time(last["seconds"]), key=f"seg_last_{suffix}",
               note=f"{last['start_local']:%d.%m.%Y} · " + (tr(pl="najlepszy", en="the best")
                                                            if last["seconds"] == best["seconds"]
                                                            else f"+{last['seconds'] - best['seconds']:.0f} s"))
    bento.stat(columns[3], tr(pl="Mediana", en="Median"), units.fmt_time(passes["seconds"].median()),
               key=f"seg_median_{suffix}",
               note=units.fmt_pace(passes["pace_min_km"].median()))


def _trend(passes: pd.DataFrame, segment: dict) -> None:
    tr = i18n.tr
    with bento.tile(
        tr(pl="Segment w czasie", en="The segment over time"), rows=2, key=f"segment_trend_{segment['id']}",
        terms=["segment"],
        caption=tr(pl="Każda kropka to jeden przebieg; kolor to typ treningu — tempo spokojnego i mocnego biegu "
                      "na tym samym odcinku to dwie różne rzeczy.",
                   en="Each dot is one pass; colour is the session type — the pace of an easy and a hard run "
                      "over the same stretch are two different things."),
    ) as t:
        kind, time, heart, when = (tr(pl="typ", en="type"), tr(pl="czas", en="time"), tr(pl="tętno", en="HR"),
                                   tr(pl="kiedy", en="when"))
        hard, long_, easy = tr(pl="mocny", en="hard"), tr(pl="długi", en="long"), tr(pl="spokojny", en="easy")
        points = passes.assign(**{
            kind: passes["kind"].map(lambda k: hard if k in ("tempo", "threshold", "intervals", "race")
                                     else long_ if k == "long" else easy),
            time: passes["seconds"].map(units.fmt_time),
            heart: passes["hr"],
        })
        figure = tz.scatter(points, "start_local", "pace_min_km", color=kind, color_kind="categorical",
                            hover=(time, heart), x_title="", y_title="", pace_y=True, reverse_y=True)
        t.chart(figure, table=points.assign(**{when: points["start_local"].dt.strftime("%d.%m.%Y")})[
            [when, kind, time, "pace_min_km", heart]].rename(columns={"pace_min_km": tr(pl="tempo", en="pace")}),
            key=f"segment_trend_{segment['id']}")


def _ranking(passes: pd.DataFrame, suffix: str) -> None:
    tr = i18n.tr
    with bento.tile("Ranking", rows=2, key=f"segment_ranking_{suffix}",
                    how=tr(pl="Kliknij wiersz, żeby otworzyć bieg.", en="Click a row to open the run.")):
        shown = passes.sort_values("seconds").head(bento.table_rows(2)).reset_index(drop=True)
        event = st.dataframe(pd.DataFrame({
            "#": shown["rank"],
            tr(pl="kiedy", en="when"): shown["start_local"].dt.strftime("%d.%m.%Y"),
            tr(pl="typ", en="type"): shown["kind"].map(rc.kind_label),
            tr(pl="czas", en="time"): shown["seconds"].map(units.fmt_time),
            tr(pl="tempo", en="pace"): shown["pace_min_km"].map(lambda v: units.fmt_pace(v, False)),
            tr(pl="tętno", en="HR"): shown["hr"].round().astype("Int64"),
            tr(pl="od km", en="from km"): shown["at_km"],
        }), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key=f"segment_ranking_table_{suffix}", height=bento.table_height(len(shown)))
        rows = getattr(getattr(event, "selection", None), "rows", None) or []
        if rows:
            routing.open_run(int(shown.iloc[rows[0]]["activity_id"]))


def _manage(segment: dict) -> None:
    tr = i18n.tr
    frame = rc.runs()
    source = frame[frame["activity_id"] == segment.get("activity_id")]
    span = f"km {segment.get('km_from', 0):.2f}–{segment.get('km_to', 0):.2f}"
    if not source.empty:
        day = f"{source.iloc[0]['start_local']:%d.%m.%Y}"
        where = tr(pl=f"z biegu z {day} ({span})", en=f"from the run of {day} ({span})")
    else:
        where = tr(pl=f"z usuniętego biegu ({span})", en=f"from a deleted run ({span})")
    if segment.get("auto"):
        runs = segment.get("runs", 0)
        with bento.panel(tr(pl="Segment znaleziony automatycznie", en="Segment found automatically"),
                         key=f"segment_manage_{segment['id']}",
                         caption=tr(pl=f"Ten odcinek przebiegłeś w {runs} biegach; wycięty {where}. Zapisany jako "
                                       "Twój zostaje na stałe i dostaje własną nazwę.",
                                    en=f"You ran this stretch in {runs} runs; cut {where}. Saved as yours it stays "
                                       "for good and gets its own name.")):
            name = st.text_input(tr(pl="Nazwa", en="Name"), segment["name"], key=f"segment_keep_name_{segment['id']}")
            if st.button(tr(pl="Zapisz jako mój segment", en="Save as my segment"), icon=":material/bookmark_add:",
                         width="stretch",
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
    with bento.panel("Segment", key=f"segment_manage_{segment['id']}",
                     caption=tr(pl=f"Wycięty {where}.", en=f"Cut {where}.")):
        name = st.text_input(tr(pl="Nazwa", en="Name"), segment["name"], key=f"segment_rename_{segment['id']}")
        columns = st.columns(2)
        if columns[0].button(tr(pl="Zapisz nazwę", en="Save the name"), key=f"segment_rename_save_{segment['id']}",
                             width="stretch",
                             disabled=name.strip() == segment["name"]):
            try:
                store.save_segment({**segment, "name": name})
            except ValueError as error:
                st.warning(str(error))
            else:
                st.rerun()
        if columns[1].button(tr(pl="Usuń segment", en="Delete the segment"), icon=":material/delete:",
                             key=f"segment_delete_{segment['id']}",
                             width="stretch"):
            store.delete_segment(segment["id"])
            st.rerun()
