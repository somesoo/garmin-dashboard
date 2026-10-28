"""One run in detail: splits, streams, zones, structure, its label and its peers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import i18n
import routing
import shell
import theme as tz
from running import plan as planning, segments, sessions, store, units, workouts
from views import run_common as rc

ZONE_LABELS = {f"hr_z{i}_s": f"strefa {i}" for i in range(1, 6)}
SEGMENT_LABELS = {
    "INTERVAL_WARMUP": "rozgrzewka",
    "INTERVAL_ACTIVE": "praca",
    "INTERVAL_RECOVERY": "przerwa (trucht)",
    "INTERVAL_REST": "przerwa",
    "INTERVAL_COOLDOWN": "schłodzenie",
}


def render() -> None:
    bento.header(i18n.page("bieg"), "Jeden bieg w szczegółach: splity, przebieg, strefy, struktura i porównanie z podobnymi.")
    frame = rc.guard()
    if frame is None:
        return
    catalogue = frame.sort_values("start_local", ascending=False)
    options = catalogue["activity_id"].astype(int).tolist()
    wanted = st.session_state.pop("run_activity_request", None)
    if wanted is not None and int(wanted) in options:
        st.session_state["run_activity"] = int(wanted)

    def describe(activity_id: int) -> str:
        row = catalogue[catalogue["activity_id"] == activity_id].iloc[0]
        return (f"{row['start_local']:%d.%m.%Y} · {rc.kind_label(row['kind'])} · "
                f"{row['distance_km']:.1f} km · {row['name']}")

    picker, action = st.columns([5, 1], vertical_alignment="bottom")
    chosen = picker.selectbox("Bieg", options, format_func=describe, key="run_activity",
                              label_visibility="collapsed")
    run = catalogue[catalogue["activity_id"] == chosen].iloc[0]
    routes = shell.table("routes")
    track = routes[pd.to_numeric(routes["activity_id"], errors="coerce") == chosen].sort_values("seq") \
        if not routes.empty else pd.DataFrame()
    if not track.empty and action.button("Mapa trasy", icon=":material/map:", key="run_to_map", width="stretch"):
        routing.open_activity(int(chosen))

    _summary(run)
    _workout(frame, run)
    left, right = bento.row(2, 2)
    with left:
        _splits(run)
        _character(run)
    with right:
        _streams(track)

    left, right = bento.row(2, 2)
    with left:
        _structure(run)
        _zones(run)
    with right:
        _similar(frame, run)

    if not track.empty:
        _same_route(run)
        _shared(run, track)
    left, right = bento.row(2, 2)
    with left:
        if not track.empty:
            _faster_or_harder(run)
    with right:
        _best_efforts(run)
    if not track.empty:
        _segments(run)
        _new_segment(run, track)


def _summary(run: pd.Series) -> None:
    columns = bento.row(1, 1, 1, 1)
    hr = run.get("avg_hr")
    hr_max = run.get("hr_max_used")
    bento.stat(columns[0], "Dystans", f"{run['distance_km']:.2f} km", key="s_km")
    bento.stat(columns[1], "Czas", units.fmt_time(run["duration_min"] * 60), key="s_time")
    bento.stat(columns[2], "Tempo", units.fmt_pace(run["pace_min_km"]), key="s_pace")
    bento.stat(columns[3], "Tętno śr. / maks.", f"{hr:.0f} / {run.get('max_hr'):.0f}" if pd.notna(hr) else "—",
               key="s_hr", note=f"{hr / hr_max:.0%} HRmax ({hr_max:.0f})" if pd.notna(hr) and pd.notna(hr_max) else None)


def _character(run: pd.Series) -> None:
    with bento.tile(
        f"Charakter: {rc.kind_label(run['kind'])}", key="character", terms=["run_kind", "te", "cadence"],
        caption=f"pewność {run['kind_confidence']} — {run['kind_reason']}",
        how="Etykieta to opis sesji z danych, nie ocena — przy niskiej pewności traktuj ją jako przypuszczenie.",
    ):
        columns = st.columns(4)
        gain, cadence, load, te = (run.get(c) for c in ("elevation_gain_m", "cadence", "training_load", "te_aerobic"))
        columns[0].metric("Przewyższenie", f"{gain:.0f} m" if pd.notna(gain) else "—")
        columns[1].metric("Kadencja", f"{cadence:.0f}" if pd.notna(cadence) else "—", help="kroki/min, obie nogi")
        columns[2].metric("Load", f"{load:.0f}" if pd.notna(load) else "—", help="Load Garmina")
        columns[3].metric("TE", f"{te:.1f} / {run.get('te_anaerobic', 0) or 0:.1f}" if pd.notna(te) else "—",
                          help="Training Effect tlenowy / beztlenowy")


def _plan_line(run: pd.Series) -> str | None:
    """If a plan session matched this run: what was planned and the verdict."""
    laps = shell.table("run_laps")
    for item in store.plans():
        matched = planning.match(item, rc.runs(), laps=laps)
        if matched.empty:
            continue
        hit = matched[matched["activity_id"] == int(run["activity_id"])]
        if hit.empty:
            continue
        row = hit.iloc[0]
        verdict = {"done": "zrealizowany", "modified": "zmodyfikowany", "skipped": "pominięty"}.get(
            row["effective"], row["effective"])
        text = f"plan „{item.get('name')}”: <b>{row['title']}</b> → {verdict}"
        if "reps_done" in row.index and pd.notna(row["reps_done"]):
            text += f" · odcinki {row['reps_done']:.0f}/{row['reps_planned']:.0f}"
            if pd.notna(row["reps_on_pace"]):
                text += f", w tempie {row['reps_on_pace']:.0f}"
        return text
    return None


def _structure(run: pd.Series) -> None:
    """Work reps from the watch's laps; the split summary when there are no laps."""
    laps = shell.table("run_laps")
    mine = laps[laps["activity_id"] == int(run["activity_id"])] if not laps.empty else laps
    reps = planning.rep_blocks(mine) if not mine.empty else []
    with bento.tile("Odcinki workoutu", key="structure", caption=_plan_line(run) or
                    "Z okrążeń zegarka; auto-lap jednego odcinka jest sklejony.") as t:
        if reps:
            table = pd.DataFrame({
                "#": range(1, len(reps) + 1),
                "km": [r["km"] for r in reps],
                "tempo": [units.fmt_pace(r["pace"], False) for r in reps],
                "tętno": [r["hr"] for r in reps],
            })
            # Points, not bars: same reason as the splits (reversed pace axis).
            figure = tz.timeseries(table.assign(pace=[r["pace"] for r in reps]), "#", {"tempo": "pace"},
                                   markers=True)
            if figure is not None:
                tz.pace_axis(figure, pd.Series([r["pace"] for r in reps]))
                figure.update_xaxes(title_text="odcinek", dtick=1)
                # Pace is stored as decimal minutes (4.36); the hover must say 4:22, like the splits.
                figure.update_traces(customdata=[[units.fmt_pace(r["pace"]), r["km"], r["hr"] or "—"] for r in reps],
                                     hovertemplate="odcinek %{x}: %{customdata[0]} · %{customdata[1]} km"
                                                   " · tętno %{customdata[2]}<extra></extra>")
            t.chart(figure, table=table)
            return
        segments = shell.table("activity_segments")
        phases = segments[(segments["activity_id"] == run["activity_id"])
                          & segments["split_type"].astype(str).str.startswith("INTERVAL")] if not segments.empty else segments
        if phases.empty:
            st.caption("Bieg ciągły — bez struktury workoutu.")
            return
        order = list(SEGMENT_LABELS)
        phases = phases.assign(order=phases["split_type"].map({k: i for i, k in enumerate(order)})).sort_values("order")
        t.table(pd.DataFrame({
            "faza": phases["split_type"].map(SEGMENT_LABELS).fillna(phases["split_type"]),
            "powt.": phases["splits"].fillna(1).astype(int),
            "km": (phases["distance_m"] / 1000).round(2),
            "tempo": phases["avg_speed_ms"].map(lambda v: units.fmt_pace(units.pace_from_speed(v), False)),
        }))


def _workout(frame: pd.DataFrame, run: pd.Series) -> None:
    """A watch workout rep by rep, then against the earlier workouts."""
    laps = shell.table("run_laps")
    activity_id = int(run["activity_id"])
    table = workouts.reps(laps[laps["activity_id"] == activity_id]) if not laps.empty else pd.DataFrame()
    if len(table) < 2:
        return
    ranked = rc.rep_efforts()
    _reps(table, workouts.summary(table), ranked[ranked["activity_id"] == activity_id] if not ranked.empty else ranked)
    history, every = workouts.history(frame, laps)
    peers = workouts.peers(history, activity_id)
    if peers.empty:
        return
    left, right = bento.row(2, 2)
    with left:
        _pace_at_hr(peers, every, run)
    with right:
        _workout_peers(peers, run)


def _same_route(run: pd.Series) -> None:
    """Earlier and later runs on this route (GPS overlap), whatever their kind."""
    twins = rc.same_route(int(run["activity_id"]))
    if twins.empty:
        return
    every = pd.concat([twins, run.to_frame().T], ignore_index=True)
    every["start_local"] = pd.to_datetime(every["start_local"])
    earlier = twins[twins["start_local"] < run["start_local"]].sort_values("start_local")
    caption = f"{len(twins)} {'bieg' if len(twins) == 1 else 'biegi' if len(twins) < 5 else 'biegów'} tą trasą"
    if not earlier.empty:
        last = earlier.iloc[-1]
        caption += (f" · wobec {last['start_local']:%d.%m.%Y} ({rc.kind_label(last['kind'])}): tempo "
                    f"<b>{(run['pace_min_km'] - last['pace_min_km']) * 60:+.0f} s/km</b>"
                    + (f", tętno <b>{run['avg_hr'] - last['avg_hr']:+.0f}</b> bpm"
                       if pd.notna(run["avg_hr"]) and pd.notna(last["avg_hr"]) else ""))
    left, right = bento.row(2, 2)
    with left, bento.tile(
        "Ta sama trasa w czasie", rows=2, key="route_time", caption=caption, terms=["same_route"],
        how="Biegi, których ślady GPS pokrywają się w ≥80% (w obie strony) przy dystansie ±15% — niezależnie "
            "od typu treningu. Szybciej przy tym samym tętnie na tej samej trasie to czysty postęp.",
    ) as t:
        points = every.assign(
            grupa=lambda f: f["activity_id"].map(lambda a: "ten bieg" if a == run["activity_id"] else "ta trasa"),
            kiedy=lambda f: f["start_local"].dt.strftime("%d.%m.%Y"),
            typ=lambda f: f["kind"].map(rc.kind_label),
            tętno=lambda f: pd.to_numeric(f["avg_hr"], errors="coerce").round(),
        ).sort_values("grupa", key=lambda g: g.map({"ten bieg": 0, "ta trasa": 1}))
        points["pace_min_km"] = pd.to_numeric(points["pace_min_km"], errors="coerce")
        figure = tz.scatter(points, "start_local", "pace_min_km", color="grupa", color_kind="categorical",
                            hover=("typ", "tętno"), x_title="", y_title="", pace_y=True, reverse_y=True)
        t.chart(figure, table=points[["kiedy", "typ", "distance_km", "pace_min_km", "tętno"]].rename(
            columns={"distance_km": "km", "pace_min_km": "tempo"}), key=f"route_time_{int(run['activity_id'])}")
    with right, bento.tile("Biegi tą trasą", rows=2, key="route_runs", terms=["same_route"],
                           how="Kliknij wiersz, żeby otworzyć bieg."):
        shown = twins.sort_values("start_local", ascending=False).head(bento.table_rows(2))
        rc.pickable_runs(shown, key=f"route_runs_{int(run['activity_id'])}",
                         height=bento.table_height(len(shown)), hint=False)


HARD = ("tempo", "threshold", "intervals", "race")


def _effort_group(kind: str) -> str:
    return "mocny" if kind in HARD else "długi" if kind == "long" else "spokojny"


def _shared(run: pd.Series, track: pd.DataFrame) -> None:
    """The longest stretch shared with each other run -- an ad-hoc segment of
    whatever length the two tracks have in common."""
    found = rc.shared(int(run["activity_id"]))
    if found.empty:
        return
    activity_id = int(run["activity_id"])
    with bento.tile(
        "Wspólne odcinki z innymi biegami", key="shared", terms=["shared_stretch", "efficiency_delta"],
        caption=f"{len(found)} {'bieg dzieli' if len(found) == 1 else 'biegi dzielą' if len(found) < 5 else 'biegów dzieli'}"
                f" z tym biegiem co najmniej 400 m trasy, w tym samym kierunku. Zaznacz wiersz, żeby zapisać "
                "odcinek jako segment albo otworzyć tamten bieg.",
        how="Dla każdego innego biegu najdłuższy wspólny kawałek (ślady ≤ 35 m od siebie), zmierzony na obu. "
            "Δ < 0: tutaj szybciej / niższe tętno. Efektywność to metry na uderzenie serca — rośnie, gdy "
            "biegniesz szybciej przy tym samym tętnie.",
    ) as t:
        shown = found.head(bento.table_rows(2)).reset_index(drop=True)
        event = st.dataframe(pd.DataFrame({
            "kiedy": shown["start_local"].dt.strftime("%d.%m.%Y"),
            "typ": shown["kind"].map(rc.kind_label),
            "km tutaj": [f"{a:.2f}–{b:.2f}" for a, b in zip(shown["km_from"], shown["km_to"])],
            "długość": (shown["length_m"] / 1000).round(2),
            "czas tu": shown["seconds"].map(units.fmt_time),
            "czas wtedy": shown["seconds_other"].map(units.fmt_time),
            "tempo tu": shown["pace"].map(lambda v: units.fmt_pace(v, False)),
            "Δ s/km": shown["d_pace_s"].round().astype("Int64"),
            "Δ tętno": shown["d_hr"].round().astype("Int64"),
            "Δ efektywność %": shown["d_eff_pct"].round(1),
        }), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key=f"shared_{activity_id}", height=bento.table_height(len(shown)))
        if len(found) > len(shown):
            st.markdown(f"<div class='tile-caption'>{len(shown)} najdłuższych z {len(found)}</div>",
                        unsafe_allow_html=True)
        rows = getattr(getattr(event, "selection", None), "rows", None) or []
        chosen = shown.iloc[rows[0]] if rows else None
        # Where it was: every shared stretch on this run's track, or just the picked one.
        km = pd.to_numeric(track["distance_km"], errors="coerce")
        km = km - km.min()
        marked = pd.Series(False, index=track.index)
        for item in ([chosen] if chosen is not None else shown.to_dict("records")):
            marked |= km.between(item["km_from"], item["km_to"])
        st.markdown("<div class='tile-caption'>" + (
            f"Na mapie: km {chosen['km_from']:.2f}–{chosen['km_to']:.2f}, wspólne z biegiem z "
            f"{chosen['start_local']:%d.%m.%Y}." if chosen is not None
            else "Na mapie: wszystkie wspólne odcinki z tabeli. Zaznacz wiersz, żeby pokazać jeden.")
            + "</div>", unsafe_allow_html=True)
        tz.show(tz.route_map(track.assign(shared=marked), highlight="shared", height=380,
                             uirevision=f"shared-{activity_id}"), key=f"shared_map_{activity_id}")
        if chosen is None:
            return
        name, save, open_ = st.columns([3, 1, 1], vertical_alignment="bottom")
        title = name.text_input("Nazwa segmentu", key=f"shared_name_{activity_id}",
                                placeholder=f"np. km {chosen['km_from']:.1f}–{chosen['km_to']:.1f}")
        if save.button("Zapisz segment", icon=":material/add_location_alt:", key=f"shared_save_{activity_id}",
                       width="stretch", type="primary"):
            try:
                store.save_segment({"name": title, **chosen["segment"], "activity_id": activity_id,
                                    "km_from": float(chosen["km_from"]), "km_to": float(chosen["km_to"])})
            except ValueError as error:
                st.warning(str(error))
            else:
                st.rerun()
        if open_.button("Tamten bieg", icon=":material/arrow_forward:", key=f"shared_open_{activity_id}",
                        width="stretch"):
            routing.open_run(int(chosen["other_id"]))


def _faster_or_harder(run: pd.Series) -> None:
    """Each shared stretch as a point: was this run faster, and what did it cost?"""
    found = rc.shared(int(run["activity_id"])).dropna(subset=["d_hr", "d_pace_s"])
    if found.empty:
        with bento.tile("Szybciej czy mocniej?", rows=2, key="faster_harder", terms=["efficiency_delta"]):
            st.caption("Brak wspólnych odcinków z tętnem po obu stronach.")
        return
    better = int(((found["d_pace_s"] < 0) & (found["d_hr"] <= 0)).sum())
    gained = found["d_eff_pct"].median()
    with bento.tile(
        "Szybciej czy mocniej?", rows=2, key="faster_harder", terms=["efficiency_delta"],
        caption=f"wobec {len(found)} wspólnych odcinków: szybciej przy niższym tętnie {better}×, "
                f"mediana efektywności <b>{gained:+.1f}%</b>",
        how="Kropka = wspólny odcinek z innym biegiem, wielkość = jego długość. Lewa górna ćwiartka: szybciej "
            "przy niższym tętnie (forma). Prawa górna: szybciej, ale mocniej. Kolor to typ tamtego biegu — "
            "porównanie ze spokojnym biegiem mówi więcej niż z interwałami.",
    ) as t:
        points = found.assign(
            typ=found["kind"].map(_effort_group),
            kiedy=found["start_local"].dt.strftime("%d.%m.%Y"),
            km=(found["length_m"] / 1000).round(2),
            d_hr=found["d_hr"].round(),
            d_pace_s=found["d_pace_s"].round(),
            d_eff_pct=found["d_eff_pct"].round(1),
        ).rename(columns={"d_hr": "Δ tętno", "d_pace_s": "Δ s/km"})
        figure = tz.scatter(points, "Δ tętno", "Δ s/km", color="typ", color_kind="categorical", size="km",
                            hover=("kiedy", "km"), x_title="Δ tętno (bpm)", y_title="Δ tempa (s/km, w górę = szybciej)",
                            reverse_y=True)
        if figure is not None:
            tz.zero_lines(figure)
        t.chart(figure, table=points[["kiedy", "typ", "km", "Δ s/km", "Δ tętno", "d_eff_pct"]].rename(
            columns={"d_eff_pct": "Δ efektywność %"}), key=f"faster_harder_{int(run['activity_id'])}")


def _best_efforts(run: pd.Series) -> None:
    """Strava's best efforts: this run's fastest 1 km ... marathon, ranked."""
    efforts = rc.all_efforts()
    if efforts.empty:
        return
    mine = efforts[efforts["activity_id"] == run["activity_id"]]
    year = efforts[efforts["day"] > pd.Timestamp(run["day"]) - pd.Timedelta(days=365)]
    rows = []
    for item in mine.sort_values("distance_m").itertuples():
        pool = efforts[efforts["effort"] == item.effort]
        pool_year = year[year["effort"] == item.effort]
        rank = int((pool["seconds"] < item.seconds).sum()) + 1
        rank_year = int((pool_year["seconds"] < item.seconds).sum()) + 1
        best = pool["seconds"].min()
        badge = "🏆 rekord" if rank == 1 else f"{rank}. w historii" if rank <= 3 else \
            "🏅 najlepszy w roku" if rank_year == 1 else f"{rank_year}. w roku" if rank_year <= 3 else ""
        rows.append({
            "dystans": sessions.EFFORT_LABELS.get(item.effort, item.effort),
            "czas": units.fmt_time(item.seconds),
            "tempo": units.fmt_pace(item.pace_min_km, False),
            "tętno": round(item.avg_hr) if pd.notna(item.avg_hr) else None,
            "miejsce": f"{rank}/{len(pool)}",
            "": badge,
            "do rekordu": "—" if item.seconds <= best else f"+{units.fmt_time(item.seconds - best)}",
        })
    records = sum(1 for r in rows if r[""].startswith("🏆"))
    with bento.tile(
        "Najlepsze odcinki", rows=2, key="best_efforts", terms=["best_effort"],
        caption=(f"<b>{records} {'rekord' if records == 1 else 'rekordy' if records < 5 else 'rekordów'}"
                 "</b> życiowe w tym biegu" if records else "Najszybsze odcinki tego biegu na tle wszystkich biegów.")
        if rows else "Za krótki bieg na najlepsze odcinki.",
        how="Najszybszy ciągły kawałek biegu na każdym dystansie (jak „best efforts” na Stravie), z miejscem "
            "wśród wszystkich biegów i w ostatnich 365 dniach. Odcinek treningowy to nie start — rekord z "
            "biegu ciągłego jest zwykle zaniżony.",
    ) as t:
        if rows:
            t.table(pd.DataFrame(rows))


def _segments(run: pd.Series) -> None:
    """Every segment this run matched -- saved, auto and workout reps --
    each against all its other passes. A row opens the segment."""
    from views.run_segments import open_key

    activity_id = int(run["activity_id"])
    reps = rc.rep_efforts()
    known = {s["id"]: s for s in [*rc.all_segments(), *workouts.rep_segments(reps)]}
    efforts = pd.concat([rc.segment_efforts(), reps.drop(columns="km")], ignore_index=True) \
        if not reps.empty else rc.segment_efforts()
    mine = efforts[(efforts["activity_id"] == activity_id) & efforts["segment_id"].isin(known)] \
        if not efforts.empty else efforts
    loop = rc.is_loop(activity_id)
    notes = []
    if loop:
        notes.append("Bieżnia albo krótka pętla — segmenty GPS są tu pominięte (owal to jeden kłąb śladu); "
                     "odcinki z okrążeń zegarka i najlepsze odcinki na dystansach liczą się normalnie.")
    if mine.empty:
        notes.append("Ten bieg nie pasuje do żadnego segmentu.")
    elif not loop:
        notes.append(f"{len(mine)} {'dopasowanie' if len(mine) == 1 else 'dopasowania' if len(mine) < 5 else 'dopasowań'}. "
                     "Kliknij wiersz, żeby otworzyć segment.")
    with bento.tile(
        "Dopasowane segmenty", key="run_segments", terms=["segment"], caption=" ".join(notes),
        how="Twoje segmenty, „auto” (trasy przebiegnięte co najmniej 4 razy) i odcinki z interwałów "
            "(każde powtórzenie w rankingu swojej długości). Miejsce liczy wszystkie przebiegi segmentu; "
            "„poprzednio” to ostatni wcześniejszy przebieg z innego biegu.",
    ) as t:
        with t.header:
            if st.button("", icon=":material/arrow_forward:", key="to_segments", type="tertiary",
                         help="Strona Segmenty"):
                routing.goto("segmenty")
        if mine.empty:
            return
        rows = []
        for item in mine.sort_values(["at_km", "pass"]).rename(columns={"pass": "number"}).itertuples():
            segment = known[item.segment_id]
            pool = efforts[efforts["segment_id"] == item.segment_id]
            before = pool[pool["start_local"] < item.start_local]
            best = pool["seconds"].min()
            label = segment["name"] + (" · auto" if segment.get("auto") else "")
            if segment.get("reps"):
                label += f" · {int(item.number)}. powt."
            rows.append({
                "segment_id": item.segment_id,
                "segment": label,
                "od km": item.at_km,
                "czas": units.fmt_time(item.seconds),
                "tempo": units.fmt_pace(item.pace_min_km, False),
                "tętno": item.hr,
                "miejsce": f"{item.rank}/{item.of}" + (" 🏆" if item.rank == 1 and item.of > 1 else ""),
                "do najlepszego": "—" if item.seconds == best else f"+{item.seconds - best:.0f} s",
                "poprzednio": "—" if before.empty
                else f"{item.seconds - before.iloc[-1]['seconds']:+.0f} s ({before.iloc[-1]['start_local']:%d.%m.%y})",
            })
        shown = pd.DataFrame(rows)
        event = st.dataframe(
            tz.readable_paces(shown.drop(columns="segment_id").assign(
                tętno=pd.to_numeric(shown["tętno"], errors="coerce").round().astype("Int64"))),
            hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key=f"run_segments_{activity_id}", height=bento.table_height(len(shown)))
        picked = getattr(getattr(event, "selection", None), "rows", None) or []
        if picked:
            routing.goto("segmenty", **{open_key(shown.iloc[picked[0]]["segment_id"]): True})


@st.fragment
def _new_segment(run: pd.Series, track: pd.DataFrame) -> None:
    """Cut a segment out of this run: a km range, a name, a look at the map."""
    total = float(pd.to_numeric(track["distance_km"], errors="coerce").max() or 0)
    if total < 0.2 or rc.is_loop(int(run["activity_id"])):
        return
    with bento.panel("Nowy segment z tego biegu", key="new_segment", terms=["segment"],
                     caption="Wybierz odcinek po kilometrach — każdy bieg, który przejdzie go od początku do "
                             "końca, trafi do rankingu."):
        activity_id = int(run["activity_id"])
        low, high = st.slider("Kilometry", 0.0, round(total, 2), (0.0, round(min(total, 1.0), 2)), step=0.05,
                              key=f"segment_range_{activity_id}", format="%.2f km")
        marked = track.assign(segment=pd.to_numeric(track["distance_km"], errors="coerce").between(low, high))
        tz.show(tz.route_map(marked, highlight="segment", height=360, uirevision=f"segment-{activity_id}"),
                key=f"segment_map_{activity_id}")
        name, save = st.columns([4, 1], vertical_alignment="bottom")
        title = name.text_input("Nazwa", key=f"segment_name_{activity_id}", placeholder="np. podbieg na Wzgórzu")
        if save.button("Zapisz segment", icon=":material/add_location_alt:", key=f"segment_save_{activity_id}",
                       width="stretch", type="primary"):
            cut = segments.cut(track, low, high)
            try:
                if cut is None:
                    raise ValueError("Za krótki odcinek śladu.")
                store.save_segment({"name": title, **cut, "activity_id": activity_id,
                                    "km_from": low, "km_to": high})
            except ValueError as error:
                st.warning(str(error))
            else:
                st.rerun(scope="app")


def _lap_text(laps: list[tuple[float, float]]) -> str:
    return " · ".join(units.fmt_pace(pace, False) + ("" if abs(km - 1) < 0.05 else f" ({km * 1000:.0f} m)")
                      for km, pace in laps)


def _reps(table: pd.DataFrame, shape: dict, ranked: pd.DataFrame) -> None:
    caption = (f"{shape['reps']} × {shape['rep_km']:.1f} km · śr. <b>{units.fmt_pace(shape['pace'])}</b>"
               + (f" przy {shape['hr']:.0f} bpm" if pd.notna(shape["hr"]) else "")
               + f" · ostatni <b>{shape['fade_s']:+.0f} s/km</b> wobec pierwszego"
               + (f", tętno {shape['hr_drift']:+.0f}" if pd.notna(shape["hr_drift"]) else "")
               + (f" · przerwy {units.fmt_time(shape['rest_s'])}" if pd.notna(shape["rest_s"]) else ""))
    with bento.tile(
        "Odcinki i splity", key="reps", caption=caption, terms=["rep_fade", "cadence"],
        how="Z okrążeń zegarka (dokładny czas stopera). Splity to kolejne okrążenia wewnątrz odcinka — "
            "auto-lap co kilometr, niepełne z długością w nawiasie. Przerwa to trucht po odcinku. Miejsce: "
            "wśród wszystkich Twoich odcinków tej długości (±7%), gdziekolwiek biegniętych — także na bieżni.",
    ) as t:
        places = {int(r.pass_): f"{r.rank}/{r.of}" + (" 🏆" if r.rank == 1 and r.of > 1 else "")
                  for r in ranked.rename(columns={"pass": "pass_"}).itertuples()}
        t.table(pd.DataFrame({
            "#": table["rep"],
            "km": table["km"],
            "czas": table["seconds"].map(units.fmt_time),
            "tempo": table["pace"].map(lambda v: units.fmt_pace(v, False)),
            "miejsce": table["rep"].map(lambda r: places.get(int(r), "—")),
            "splity": table["laps"].map(_lap_text),
            "tętno": table["hr"].round().astype("Int64"),
            "maks.": table["hr_max"].round().astype("Int64"),
            "kadencja": table["cadence"].round().astype("Int64"),
            "przerwa": table["rest_s"].map(lambda v: units.fmt_time(v) if pd.notna(v) else "—"),
            "trucht": table["rest_pace"].map(lambda v: units.fmt_pace(v, False)),
            "tętno w przerwie": table["rest_hr"].round().astype("Int64"),
        }))


def _pace_at_hr(peers: pd.DataFrame, every: pd.DataFrame, run: pd.Series) -> None:
    activity_id = int(run["activity_id"])
    current = peers[peers["current"]].iloc[0]
    offset = current["vs_hr_s"]
    caption = (f"przy tym samym tętnie <b>{'szybciej' if offset < 0 else 'wolniej'} o {abs(offset):.0f} s/km</b> "
               "niż odcinki wcześniejszych workoutów" if pd.notna(offset)
               else "Za mało wcześniejszych workoutów, żeby poprowadzić linię tempo ~ tętno.")
    with bento.tile(
        "Tempo a tętno na odcinkach", rows=2, key="pace_hr", caption=caption, terms=["pace_at_hr"],
        how="Każda kropka to jeden odcinek. Szara linia to dopasowanie do odcinków sprzed tego treningu — "
            "kropki nad nią to szybciej przy tym samym tętnie. Podobne = odcinki o długości ±35%.",
    ) as t:
        groups = {aid: "ten trening" if is_current else "podobne odcinki" if similar else "inne workouty"
                  for aid, is_current, similar in peers[["activity_id", "current", "similar"]].itertuples(index=False)}
        points = every[every["start_local"] <= current["start_local"]].assign(
            grupa=lambda f: f["activity_id"].map(groups),
            kiedy=lambda f: f["start_local"].dt.strftime("%d.%m.%Y"),
            odcinek=lambda f: f["km"].map(lambda v: f"{v:.1f} km"),
        ).rename(columns={"hr": "tętno", "pace": "tempo"})
        order = {"ten trening": 0, "podobne odcinki": 1, "inne workouty": 2}
        points = points.sort_values("grupa", key=lambda g: g.map(order))
        figure = tz.scatter(points, "tętno", "tempo", color="grupa", color_kind="categorical",
                            hover=("kiedy", "odcinek"), x_title="średnie tętno odcinka (bpm)", y_title="",
                            pace_y=True, reverse_y=True)
        fit = workouts.hr_fit(every, activity_id, current["start_local"])
        if figure is not None and fit is not None:
            span = pd.Series([points["tętno"].min(), points["tętno"].max()])
            figure.add_scatter(x=span, y=fit[0] + fit[1] * span, mode="lines", hoverinfo="skip", showlegend=False,
                               line=dict(color=tz.tokens()["muted"], width=1.4, dash="dot"))
        t.chart(figure, table=points[["kiedy", "grupa", "odcinek", "tempo", "tętno"]],
                key=f"pace_hr_{activity_id}")


def _workout_peers(peers: pd.DataFrame, run: pd.Series) -> None:
    others = peers[~peers["current"]]
    current = peers[peers["current"]].iloc[0]
    earlier = others[others["similar"] & (others["start_local"] < current["start_local"])]
    caption = None
    if not earlier.empty:
        last = earlier.iloc[-1]
        caption = (f"wobec {last['start_local']:%d.%m.%Y} ({last['reps']:.0f} × {last['rep_km']:.1f} km): tempo "
                   f"<b>{(current['pace'] - last['pace']) * 60:+.0f} s/km</b>, tętno "
                   f"<b>{current['hr'] - last['hr']:+.0f}</b> bpm")
    with bento.tile(
        "Podobne workouty", rows=2, key="workout_peers", caption=caption, terms=["rep_fade", "pace_at_hr"],
        how="Najpierw workouty o podobnej długości odcinków (±35%, znak ≈), potem pozostałe; w grupie od "
            "najnowszych. "
            "Kliknij wiersz, żeby otworzyć trening.",
    ):
        if others.empty:
            st.caption("To pierwszy workout z okrążeniami — nie ma z czym porównać.")
            return
        shown = others.sort_values(["similar", "start_local"], ascending=[False, False]) \
            .head(bento.table_rows(2)).reset_index(drop=True)
        event = st.dataframe(pd.DataFrame({
            "kiedy": shown["start_local"].dt.strftime("%d.%m.%Y"),
            "odcinki": [f"{r.reps:.0f} × {r.rep_km:.1f} km" + (" ≈" if r.similar else "") for r in shown.itertuples()],
            "tempo": shown["pace"].map(lambda v: units.fmt_pace(v, False)),
            "tętno": shown["hr"].round().astype("Int64"),
            "rozjazd s/km": shown["fade_s"].round().astype("Int64"),
            "tętno ↑": shown["hr_drift"].round().astype("Int64"),
            "przerwa": shown["rest_s"].map(lambda v: units.fmt_time(v) if pd.notna(v) else "—"),
            "vs tętno s/km": shown["vs_hr_s"].round().astype("Int64"),
        }), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key=f"workout_peers_{int(run['activity_id'])}", height=bento.table_height(len(shown)))
        rows = getattr(getattr(event, "selection", None), "rows", None) or []
        if rows:
            routing.open_run(int(shown.iloc[rows[0]]["activity_id"]))


def _splits(run: pd.Series) -> None:
    splits = shell.table("run_splits")
    mine = splits[splits["activity_id"] == run["activity_id"]] if not splits.empty else splits
    caption = "Ze strumienia ~400 próbek — dokładność kilku sekund."
    paces = mine[mine["length_km"] >= 0.9]["pace_min_km"] if not mine.empty else pd.Series(dtype=float)
    # Halves only mean something for a continuous run: a workout with a
    # warm-up always "negative splits".
    if len(paces) >= 4 and run["kind"] in ("easy", "long", "recovery", "race"):
        half = len(paces) // 2
        first, second = paces.iloc[:half].mean(), paces.iloc[half:].mean()
        caption = (f"1. połowa {units.fmt_pace(first, False)}, 2. {units.fmt_pace(second, False)} — "
                   + ("negative split" if second < first - 0.03 else "równo" if abs(second - first) <= 0.03
                      else "druga wolniejsza"))
    with bento.tile("Splity kilometrowe", key="splits", caption=caption,
                    how="Czas stopera, bez autopauzy. Ostatni odcinek może być niepełny. Wyżej = szybciej.") as t:
        if mine.empty:
            st.caption("Ten bieg nie ma strumienia próbek (np. bieżnia albo brak GPS).")
            return
        # Points and a line, not bars: on a reversed pace axis a bar hangs from the
        # top and the slowest kilometre would get the longest bar.
        figure = tz.timeseries(mine, "km", {"tempo": "pace_min_km"}, markers=True)
        if figure is not None:
            tz.pace_axis(figure, mine["pace_min_km"], robust=True)
            figure.update_xaxes(title_text="kilometr", dtick=1)
            figure.update_traces(customdata=mine["pace_min_km"].map(lambda v: units.fmt_pace(v)),
                                 hovertemplate="km %{x}: %{customdata}<extra></extra>")
        t.chart(figure, table=pd.DataFrame({
            "km": mine["km"], "długość": mine["length_km"], "czas": mine["seconds"].map(units.fmt_time),
            "tempo": mine["pace_min_km"].map(lambda v: units.fmt_pace(v, False)), "tętno": mine["hr"],
            "w górę m": mine["elev_gain_m"], "w dół m": mine["elev_loss_m"], "kadencja": mine["cadence"],
        }), key=f"splits_{int(run['activity_id'])}")


def _streams(track: pd.DataFrame) -> None:
    with bento.tile("Przebieg wzdłuż dystansu", rows=2, key="streams",
                    caption="Te same próbki co splity, bez uśredniania do kilometra.") as t:
        panels = []
        if not track.empty and "pace_min_km" in track.columns and track["pace_min_km"].notna().any():
            panels.append({"title": "Tempo (/km)", "series": {"tempo": "pace_min_km"}, "kind": "line", "pace": True})
        if not track.empty and "hr" in track.columns and track["hr"].notna().any():
            panels.append({"title": "Tętno (bpm)", "series": {"tętno": "hr"}, "kind": "line"})
        if not track.empty and "elevation_m" in track.columns and track["elevation_m"].notna().any():
            panels.append({"title": "Wysokość (m)", "series": {"wysokość": "elevation_m"}, "kind": "line",
                           "height": 0.7})
        if not panels:
            st.caption("Brak strumienia próbek dla tego biegu.")
            return
        figure = tz.stacked_panels(track, "distance_km", panels, height=400)
        if figure is not None:
            figure.update_xaxes(title_text="dystans (km)", row=len(panels), col=1)
        t.chart(figure, key="run_streams")


def _zones(run: pd.Series) -> None:
    zones = {label: run.get(column) for column, label in ZONE_LABELS.items()}
    with bento.tile("Strefy tętna", key="zones", terms=["hr_zones"],
                    caption="Minuty w strefach Garmina (granice z ustawień zegarka).") as t:
        if all(pd.isna(v) for v in zones.values()):
            st.caption("Brak tętna.")
            return
        frame = pd.DataFrame({"strefa": list(zones), "min": [(v or 0) / 60 for v in zones.values()]})
        # Zones are ordered categories: vertical bars in zone order, not a ranking.
        t.chart(tz.bars(frame, "strefa", "min", y_title="min"), table=frame.round(1), key="run_zones")


def _similar(frame: pd.DataFrame, run: pd.Series) -> None:
    peers = sessions.similar(frame, int(run["activity_id"]))
    caption = None
    if not peers.empty:
        pace_diff = (run["pace_min_km"] - peers["pace_min_km"].median()) * 60
        hr_diff = run["avg_hr"] - peers["avg_hr"].median() if pd.notna(run["avg_hr"]) else None
        caption = (f"wobec mediany {len(peers)}: tempo <b>{'-' if pace_diff < 0 else '+'}"
                   f"{units.fmt_time(abs(pace_diff))}</b> /km"
                   + (f", tętno <b>{hr_diff:+.0f}</b> bpm" if hr_diff is not None and pd.notna(hr_diff) else ""))
    with bento.tile(
        "Na tle podobnych", rows=2, key="similar", caption=caption,
        how=f"Wcześniejsze biegi typu „{rc.kind_label(run['kind'])}” o dystansie ±25%. Szybciej przy tym samym "
            "tętnie to postęp; szybciej przy wyższym — mocniejszy trening. Kliknij wiersz, żeby otworzyć bieg.",
    ):
        if peers.empty:
            st.caption("Brak podobnych biegów do porównania.")
            return
        count = bento.table_rows(2)
        shown = peers.sort_values("start_local", ascending=False).head(count)
        rc.pickable_runs(shown, key=f"similar_{int(run['activity_id'])}", height=bento.table_height(len(shown)),
                         hint=False)
