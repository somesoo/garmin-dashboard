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

SEGMENT_ORDER = ["INTERVAL_WARMUP", "INTERVAL_ACTIVE", "INTERVAL_RECOVERY", "INTERVAL_REST", "INTERVAL_COOLDOWN"]


def _segment_labels() -> dict[str, str]:
    tr = i18n.tr
    return {"INTERVAL_WARMUP": tr(pl="rozgrzewka", en="warm-up"), "INTERVAL_ACTIVE": tr(pl="praca", en="work"),
            "INTERVAL_RECOVERY": tr(pl="przerwa (trucht)", en="recovery (jog)"),
            "INTERVAL_REST": tr(pl="przerwa", en="rest"), "INTERVAL_COOLDOWN": tr(pl="schłodzenie", en="cool-down")}


def _runs_noun(count: int) -> str:
    return i18n.plural(count, pl=("bieg", "biegi", "biegów"), en=("run", "runs"))


def render() -> None:
    bento.header(i18n.page("bieg"), i18n.tr(
        pl="Jeden bieg w szczegółach: splity, przebieg, strefy, struktura i porównanie z podobnymi.",
        en="One run in detail: splits, streams, zones, structure and a comparison with similar runs."))
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
    chosen = picker.selectbox(i18n.tr(pl="Bieg", en="Run"), options, format_func=describe, key="run_activity",
                              label_visibility="collapsed")
    run = catalogue[catalogue["activity_id"] == chosen].iloc[0]
    routes = shell.table("routes")
    track = routes[pd.to_numeric(routes["activity_id"], errors="coerce") == chosen].sort_values("seq") \
        if not routes.empty else pd.DataFrame()
    if not track.empty and action.button(i18n.tr(pl="Mapa trasy", en="Route map"), icon=":material/map:",
                                         key="run_to_map", width="stretch"):
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
    tr = i18n.tr
    bento.stat(columns[0], tr(pl="Dystans", en="Distance"), f"{run['distance_km']:.2f} km", key="s_km")
    bento.stat(columns[1], tr(pl="Czas", en="Time"), units.fmt_time(run["duration_min"] * 60), key="s_time")
    bento.stat(columns[2], tr(pl="Tempo", en="Pace"), units.fmt_pace(run["pace_min_km"]), key="s_pace")
    bento.stat(columns[3], tr(pl="Tętno śr. / maks.", en="Avg / max HR"),
               f"{hr:.0f} / {run.get('max_hr'):.0f}" if pd.notna(hr) else "—",
               key="s_hr", note=f"{hr / hr_max:.0%} HRmax ({hr_max:.0f})" if pd.notna(hr) and pd.notna(hr_max) else None)


def _character(run: pd.Series) -> None:
    tr = i18n.tr
    kind, sure = rc.kind_label(run["kind"]), rc.confidence_label(run["kind_confidence"])
    with bento.tile(
        tr(pl=f"Charakter: {kind}", en=f"Character: {kind}"), key="character", terms=["run_kind", "te", "cadence"],
        caption=tr(pl=f"pewność {sure} — {run['kind_reason']}", en=f"confidence {sure} — {run['kind_reason']}"),
        how=tr(pl="Etykieta to opis sesji z danych, nie ocena — przy niskiej pewności traktuj ją jako przypuszczenie.",
               en="The label describes the session from the data, it is not a grade — at low confidence treat it as "
                  "a guess."),
    ):
        columns = st.columns(4)
        gain, cadence, load, te = (run.get(c) for c in ("elevation_gain_m", "cadence", "training_load", "te_aerobic"))
        columns[0].metric(tr(pl="Przewyższenie", en="Elevation gain"), f"{gain:.0f} m" if pd.notna(gain) else "—")
        columns[1].metric(tr(pl="Kadencja", en="Cadence"), f"{cadence:.0f}" if pd.notna(cadence) else "—",
                          help=tr(pl="kroki/min, obie nogi", en="steps/min, both feet"))
        columns[2].metric("Load", f"{load:.0f}" if pd.notna(load) else "—",
                          help=tr(pl="Load Garmina", en="Garmin's load"))
        columns[3].metric("TE", f"{te:.1f} / {run.get('te_anaerobic', 0) or 0:.1f}" if pd.notna(te) else "—",
                          help=tr(pl="Training Effect tlenowy / beztlenowy", en="Aerobic / anaerobic Training Effect"))


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
        tr = i18n.tr
        row = hit.iloc[0]
        verdict = {"done": tr(pl="zrealizowany", en="done"), "modified": tr(pl="zmodyfikowany", en="modified"),
                   "skipped": tr(pl="pominięty", en="skipped")}.get(row["effective"], row["effective"])
        name, title = item.get("name"), row["title"]
        text = tr(pl=f"plan „{name}”: <b>{title}</b> → {verdict}", en=f"plan “{name}”: <b>{title}</b> → {verdict}")
        if "reps_done" in row.index and pd.notna(row["reps_done"]):
            reps = f"{row['reps_done']:.0f}/{row['reps_planned']:.0f}"
            text += tr(pl=f" · odcinki {reps}", en=f" · reps {reps}")
            if pd.notna(row["reps_on_pace"]):
                text += tr(pl=f", w tempie {row['reps_on_pace']:.0f}", en=f", on pace {row['reps_on_pace']:.0f}")
        return text
    return None


def _structure(run: pd.Series) -> None:
    """Work reps from the watch's laps; the split summary when there are no laps."""
    laps = shell.table("run_laps")
    mine = laps[laps["activity_id"] == int(run["activity_id"])] if not laps.empty else laps
    reps = planning.rep_blocks(mine) if not mine.empty else []
    tr = i18n.tr
    pace, heart, rep = tr(pl="tempo", en="pace"), tr(pl="tętno", en="HR"), tr(pl="odcinek", en="rep")
    with bento.tile(tr(pl="Odcinki workoutu", en="Workout reps"), key="structure", caption=_plan_line(run) or
                    tr(pl="Z okrążeń zegarka; auto-lap jednego odcinka jest sklejony.",
                       en="From the watch laps; the auto-laps of one rep are joined.")) as t:
        if reps:
            table = pd.DataFrame({
                "#": range(1, len(reps) + 1),
                "km": [r["km"] for r in reps],
                pace: [units.fmt_pace(r["pace"], False) for r in reps],
                heart: [r["hr"] for r in reps],
            })
            # Points, not bars: same reason as the splits (reversed pace axis).
            figure = tz.timeseries(table.assign(pace_value=[r["pace"] for r in reps]), "#", {pace: "pace_value"},
                                   markers=True)
            if figure is not None:
                tz.pace_axis(figure, pd.Series([r["pace"] for r in reps]))
                figure.update_xaxes(title_text=rep, dtick=1)
                # Pace is stored as decimal minutes (4.36); the hover must say 4:22, like the splits.
                figure.update_traces(customdata=[[units.fmt_pace(r["pace"]), r["km"], r["hr"] or "—"] for r in reps],
                                     hovertemplate=f"{rep} %{{x}}: %{{customdata[0]}} · %{{customdata[1]}} km"
                                                   f" · {heart} %{{customdata[2]}}<extra></extra>")
            t.chart(figure, table=table)
            return
        segments = shell.table("activity_segments")
        phases = segments[(segments["activity_id"] == run["activity_id"])
                          & segments["split_type"].astype(str).str.startswith("INTERVAL")] if not segments.empty else segments
        if phases.empty:
            st.caption(tr(pl="Bieg ciągły — bez struktury workoutu.", en="A continuous run — no workout structure."))
            return
        labels = _segment_labels()
        phases = phases.assign(order=phases["split_type"].map({k: i for i, k in enumerate(SEGMENT_ORDER)})) \
            .sort_values("order")
        t.table(pd.DataFrame({
            tr(pl="faza", en="phase"): phases["split_type"].map(labels).fillna(phases["split_type"]),
            tr(pl="powt.", en="reps"): phases["splits"].fillna(1).astype(int),
            "km": (phases["distance_m"] / 1000).round(2),
            pace: phases["avg_speed_ms"].map(lambda v: units.fmt_pace(units.pace_from_speed(v), False)),
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
    tr = i18n.tr
    every = pd.concat([twins, run.to_frame().T], ignore_index=True)
    every["start_local"] = pd.to_datetime(every["start_local"])
    earlier = twins[twins["start_local"] < run["start_local"]].sort_values("start_local")
    caption = tr(pl=f"{len(twins)} {_runs_noun(len(twins))} tą trasą", en=f"{len(twins)} {_runs_noun(len(twins))} "
                                                                           "on this route")
    if not earlier.empty:
        last = earlier.iloc[-1]
        then = f"{last['start_local']:%d.%m.%Y} ({rc.kind_label(last['kind'])})"
        pace = f"<b>{(run['pace_min_km'] - last['pace_min_km']) * 60:+.0f} s/km</b>"
        caption += tr(pl=f" · wobec {then}: tempo {pace}", en=f" · against {then}: pace {pace}")
        if pd.notna(run["avg_hr"]) and pd.notna(last["avg_hr"]):
            heart = f"<b>{run['avg_hr'] - last['avg_hr']:+.0f}</b> bpm"
            caption += tr(pl=f", tętno {heart}", en=f", HR {heart}")
    left, right = bento.row(2, 2)
    with left, bento.tile(
        tr(pl="Ta sama trasa w czasie", en="The same route over time"), rows=2, key="route_time", caption=caption,
        terms=["same_route"],
        how=tr(pl="Biegi, których ślady GPS pokrywają się w ≥80% (w obie strony) przy dystansie ±15% — niezależnie "
                  "od typu treningu. Szybciej przy tym samym tętnie na tej samej trasie to czysty postęp.",
               en="Runs whose GPS tracks overlap by ≥80% (both ways) at a distance within ±15% — whatever the "
                  "session type. Faster at the same heart rate on the same route is pure progress."),
    ) as t:
        group, when, kind, heart = (tr(pl="grupa", en="group"), tr(pl="kiedy", en="when"), tr(pl="typ", en="type"),
                                    tr(pl="tętno", en="HR"))
        this, route = tr(pl="ten bieg", en="this run"), tr(pl="ta trasa", en="this route")
        points = every.assign(**{
            group: every["activity_id"].map(lambda a: this if a == run["activity_id"] else route),
            when: every["start_local"].dt.strftime("%d.%m.%Y"),
            kind: every["kind"].map(rc.kind_label),
            heart: pd.to_numeric(every["avg_hr"], errors="coerce").round(),
        }).sort_values(group, key=lambda g: g.map({this: 0, route: 1}))
        points["pace_min_km"] = pd.to_numeric(points["pace_min_km"], errors="coerce")
        figure = tz.scatter(points, "start_local", "pace_min_km", color=group, color_kind="categorical",
                            hover=(kind, heart), x_title="", y_title="", pace_y=True, reverse_y=True)
        t.chart(figure, table=points[[when, kind, "distance_km", "pace_min_km", heart]].rename(
            columns={"distance_km": "km", "pace_min_km": tr(pl="tempo", en="pace")}),
            key=f"route_time_{int(run['activity_id'])}")
    with right, bento.tile(tr(pl="Biegi tą trasą", en="Runs on this route"), rows=2, key="route_runs",
                           terms=["same_route"],
                           how=tr(pl="Kliknij wiersz, żeby otworzyć bieg.", en="Click a row to open the run.")):
        shown = twins.sort_values("start_local", ascending=False).head(bento.table_rows(2))
        rc.pickable_runs(shown, key=f"route_runs_{int(run['activity_id'])}",
                         height=bento.table_height(len(shown)), hint=False)


HARD = ("tempo", "threshold", "intervals", "race")


def _effort_group(kind: str) -> str:
    tr = i18n.tr
    return tr(pl="mocny", en="hard") if kind in HARD else tr(pl="długi", en="long") if kind == "long" \
        else tr(pl="spokojny", en="easy")


def _shared(run: pd.Series, track: pd.DataFrame) -> None:
    """The longest stretch shared with each other run -- an ad-hoc segment of
    whatever length the two tracks have in common."""
    found = rc.shared(int(run["activity_id"]))
    if found.empty:
        return
    tr = i18n.tr
    activity_id = int(run["activity_id"])
    count = len(found)
    shares = i18n.plural(count, pl=("bieg dzieli", "biegi dzielą", "biegów dzieli"),
                         en=("run shares", "runs share"))
    with bento.tile(
        tr(pl="Wspólne odcinki z innymi biegami", en="Stretches shared with other runs"), key="shared",
        terms=["shared_stretch", "efficiency_delta"],
        caption=tr(pl=f"{count} {shares} z tym biegiem co najmniej 400 m trasy, w tym samym kierunku. Zaznacz "
                      "wiersz, żeby zapisać odcinek jako segment albo otworzyć tamten bieg.",
                   en=f"{count} {shares} at least 400 m of route with this run, in the same direction. Select a row "
                      "to save the stretch as a segment or open that run."),
        how=tr(pl="Dla każdego innego biegu najdłuższy wspólny kawałek (ślady ≤ 35 m od siebie), zmierzony na obu. "
                  "Δ < 0: tutaj szybciej / niższe tętno. Efektywność to metry na uderzenie serca — rośnie, gdy "
                  "biegniesz szybciej przy tym samym tętnie.",
               en="For every other run the longest shared piece (tracks ≤ 35 m apart), measured on both. Δ < 0: "
                  "faster / lower heart rate here. Efficiency is metres per heartbeat — it rises when you run "
                  "faster at the same heart rate."),
    ) as t:
        shown = found.head(bento.table_rows(2)).reset_index(drop=True)
        event = st.dataframe(pd.DataFrame({
            tr(pl="kiedy", en="when"): shown["start_local"].dt.strftime("%d.%m.%Y"),
            tr(pl="typ", en="type"): shown["kind"].map(rc.kind_label),
            tr(pl="km tutaj", en="km here"): [f"{a:.2f}–{b:.2f}" for a, b in zip(shown["km_from"], shown["km_to"])],
            tr(pl="długość", en="length"): (shown["length_m"] / 1000).round(2),
            tr(pl="czas tu", en="time here"): shown["seconds"].map(units.fmt_time),
            tr(pl="czas wtedy", en="time then"): shown["seconds_other"].map(units.fmt_time),
            tr(pl="tempo tu", en="pace here"): shown["pace"].map(lambda v: units.fmt_pace(v, False)),
            "Δ s/km": shown["d_pace_s"].round().astype("Int64"),
            tr(pl="Δ tętno", en="Δ HR"): shown["d_hr"].round().astype("Int64"),
            tr(pl="Δ efektywność %", en="Δ efficiency %"): shown["d_eff_pct"].round(1),
        }), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key=f"shared_{activity_id}", height=bento.table_height(len(shown)))
        if len(found) > len(shown):
            note = tr(pl=f"{len(shown)} najdłuższych z {len(found)}", en=f"the {len(shown)} longest of {len(found)}")
            st.markdown(f"<div class='tile-caption'>{note}</div>", unsafe_allow_html=True)
        rows = getattr(getattr(event, "selection", None), "rows", None) or []
        chosen = shown.iloc[rows[0]] if rows else None
        # Where it was: every shared stretch on this run's track, or just the picked one.
        km = pd.to_numeric(track["distance_km"], errors="coerce")
        km = km - km.min()
        marked = pd.Series(False, index=track.index)
        for item in ([chosen] if chosen is not None else shown.to_dict("records")):
            marked |= km.between(item["km_from"], item["km_to"])
        if chosen is not None:
            span, day = f"km {chosen['km_from']:.2f}–{chosen['km_to']:.2f}", f"{chosen['start_local']:%d.%m.%Y}"
            note = tr(pl=f"Na mapie: {span}, wspólne z biegiem z {day}.",
                      en=f"On the map: {span}, shared with the run of {day}.")
        else:
            note = tr(pl="Na mapie: wszystkie wspólne odcinki z tabeli. Zaznacz wiersz, żeby pokazać jeden.",
                      en="On the map: every shared stretch in the table. Select a row to show one.")
        st.markdown(f"<div class='tile-caption'>{note}</div>", unsafe_allow_html=True)
        tz.show(tz.route_map(track.assign(shared=marked), highlight="shared", height=380,
                             uirevision=f"shared-{activity_id}"), key=f"shared_map_{activity_id}")
        if chosen is None:
            return
        name, save, open_ = st.columns([3, 1, 1], vertical_alignment="bottom")
        example = f"km {chosen['km_from']:.1f}–{chosen['km_to']:.1f}"
        title = name.text_input(tr(pl="Nazwa segmentu", en="Segment name"), key=f"shared_name_{activity_id}",
                                placeholder=tr(pl=f"np. {example}", en=f"e.g. {example}"))
        if save.button(tr(pl="Zapisz segment", en="Save the segment"), icon=":material/add_location_alt:",
                       key=f"shared_save_{activity_id}",
                       width="stretch", type="primary"):
            try:
                store.save_segment({"name": title, **chosen["segment"], "activity_id": activity_id,
                                    "km_from": float(chosen["km_from"]), "km_to": float(chosen["km_to"])})
            except ValueError as error:
                st.warning(str(error))
            else:
                st.rerun()
        if open_.button(tr(pl="Tamten bieg", en="That run"), icon=":material/arrow_forward:",
                        key=f"shared_open_{activity_id}",
                        width="stretch"):
            routing.open_run(int(chosen["other_id"]))


def _faster_or_harder(run: pd.Series) -> None:
    """Each shared stretch as a point: was this run faster, and what did it cost?"""
    tr = i18n.tr
    title = tr(pl="Szybciej czy mocniej?", en="Faster or harder?")
    found = rc.shared(int(run["activity_id"])).dropna(subset=["d_hr", "d_pace_s"])
    if found.empty:
        with bento.tile(title, rows=2, key="faster_harder", terms=["efficiency_delta"]):
            st.caption(tr(pl="Brak wspólnych odcinków z tętnem po obu stronach.",
                          en="No shared stretches with heart rate on both sides."))
        return
    better = int(((found["d_pace_s"] < 0) & (found["d_hr"] <= 0)).sum())
    gained = f"<b>{found['d_eff_pct'].median():+.1f}%</b>"
    with bento.tile(
        title, rows=2, key="faster_harder", terms=["efficiency_delta"],
        caption=tr(pl=f"wobec {len(found)} wspólnych odcinków: szybciej przy niższym tętnie {better}×, "
                      f"mediana efektywności {gained}",
                   en=f"against {len(found)} shared stretches: faster at a lower heart rate {better}×, "
                      f"median efficiency {gained}"),
        how=tr(pl="Kropka = wspólny odcinek z innym biegiem, wielkość = jego długość. Lewa górna ćwiartka: szybciej "
                  "przy niższym tętnie (forma). Prawa górna: szybciej, ale mocniej. Kolor to typ tamtego biegu — "
                  "porównanie ze spokojnym biegiem mówi więcej niż z interwałami.",
               en="A dot = a stretch shared with another run, size = its length. Top-left quadrant: faster at a "
                  "lower heart rate (form). Top-right: faster, but harder. Colour is that run's type — a comparison "
                  "with an easy run says more than with intervals."),
    ) as t:
        kind, when, d_hr = tr(pl="typ", en="type"), tr(pl="kiedy", en="when"), tr(pl="Δ tętno", en="Δ HR")
        points = found.assign(**{
            kind: found["kind"].map(_effort_group),
            when: found["start_local"].dt.strftime("%d.%m.%Y"),
            "km": (found["length_m"] / 1000).round(2),
            "d_hr": found["d_hr"].round(),
            "d_pace_s": found["d_pace_s"].round(),
            "d_eff_pct": found["d_eff_pct"].round(1),
        }).rename(columns={"d_hr": d_hr, "d_pace_s": "Δ s/km"})
        figure = tz.scatter(points, d_hr, "Δ s/km", color=kind, color_kind="categorical", size="km",
                            hover=(when, "km"), x_title=tr(pl="Δ tętno (bpm)", en="Δ HR (bpm)"),
                            y_title=tr(pl="Δ tempa (s/km, w górę = szybciej)", en="Δ pace (s/km, up = faster)"),
                            reverse_y=True)
        if figure is not None:
            tz.zero_lines(figure)
        t.chart(figure, table=points[[when, kind, "km", "Δ s/km", d_hr, "d_eff_pct"]].rename(
            columns={"d_eff_pct": tr(pl="Δ efektywność %", en="Δ efficiency %")}),
            key=f"faster_harder_{int(run['activity_id'])}")


def _best_efforts(run: pd.Series) -> None:
    """Strava's best efforts: this run's fastest 1 km ... marathon, ranked."""
    efforts = rc.all_efforts()
    if efforts.empty:
        return
    mine = efforts[efforts["activity_id"] == run["activity_id"]]
    year = efforts[efforts["day"] > pd.Timestamp(run["day"]) - pd.Timedelta(days=365)]
    tr = i18n.tr
    rows = []
    for item in mine.sort_values("distance_m").itertuples():
        pool = efforts[efforts["effort"] == item.effort]
        pool_year = year[year["effort"] == item.effort]
        rank = int((pool["seconds"] < item.seconds).sum()) + 1
        rank_year = int((pool_year["seconds"] < item.seconds).sum()) + 1
        best = pool["seconds"].min()
        badge = tr(pl="🏆 rekord", en="🏆 record") if rank == 1 else \
            tr(pl=f"{rank}. w historii", en=f"#{rank} all-time") if rank <= 3 else \
            tr(pl="🏅 najlepszy w roku", en="🏅 best of the year") if rank_year == 1 else \
            tr(pl=f"{rank_year}. w roku", en=f"#{rank_year} of the year") if rank_year <= 3 else ""
        rows.append({
            tr(pl="dystans", en="distance"): rc.effort_label(item.effort),
            tr(pl="czas", en="time"): units.fmt_time(item.seconds),
            tr(pl="tempo", en="pace"): units.fmt_pace(item.pace_min_km, False),
            tr(pl="tętno", en="HR"): round(item.avg_hr) if pd.notna(item.avg_hr) else None,
            tr(pl="miejsce", en="rank"): f"{rank}/{len(pool)}",
            "": badge,
            tr(pl="do rekordu", en="to the record"): "—" if item.seconds <= best
            else f"+{units.fmt_time(item.seconds - best)}",
        })
    records = sum(1 for r in rows if r[""].startswith("🏆"))
    noun = i18n.plural(records, pl=("rekord życiowy", "rekordy życiowe", "rekordów życiowych"),
                       en=("personal best", "personal bests"))
    if not rows:
        caption = tr(pl="Za krótki bieg na najlepsze odcinki.", en="Too short a run for best efforts.")
    elif records:
        caption = tr(pl=f"<b>{records} {noun}</b> w tym biegu", en=f"<b>{records} {noun}</b> in this run")
    else:
        caption = tr(pl="Najszybsze odcinki tego biegu na tle wszystkich biegów.",
                     en="This run's fastest stretches against all runs.")
    with bento.tile(
        tr(pl="Najlepsze odcinki", en="Best efforts"), rows=2, key="best_efforts", terms=["best_effort"],
        caption=caption,
        how=tr(pl="Najszybszy ciągły kawałek biegu na każdym dystansie (jak „best efforts” na Stravie), z miejscem "
                  "wśród wszystkich biegów i w ostatnich 365 dniach. Odcinek treningowy to nie start — rekord z "
                  "biegu ciągłego jest zwykle zaniżony.",
               en="The fastest continuous piece of the run at each distance (like Strava's “best efforts”), ranked "
                  "among all runs and over the last 365 days. A training stretch is not a race — a record from a "
                  "continuous run is usually an underestimate."),
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
    tr = i18n.tr
    loop = rc.is_loop(activity_id)
    notes = []
    if loop:
        notes.append(tr(pl="Bieżnia albo krótka pętla — segmenty GPS są tu pominięte (owal to jeden kłąb śladu); "
                           "odcinki z okrążeń zegarka i najlepsze odcinki na dystansach liczą się normalnie.",
                        en="A track or a short loop — GPS segments are skipped here (an oval is one tangle of track); "
                           "reps from the watch laps and best efforts at distances count as usual."))
    if mine.empty:
        notes.append(tr(pl="Ten bieg nie pasuje do żadnego segmentu.", en="This run matches no segment."))
    elif not loop:
        noun = i18n.plural(len(mine), pl=("dopasowanie", "dopasowania", "dopasowań"), en=("match", "matches"))
        notes.append(tr(pl=f"{len(mine)} {noun}. Kliknij wiersz, żeby otworzyć segment.",
                        en=f"{len(mine)} {noun}. Click a row to open the segment."))
    with bento.tile(
        tr(pl="Dopasowane segmenty", en="Matched segments"), key="run_segments", terms=["segment"],
        caption=" ".join(notes),
        how=tr(pl="Twoje segmenty, „auto” (trasy przebiegnięte co najmniej 4 razy) i odcinki z interwałów "
                  "(każde powtórzenie w rankingu swojej długości). Miejsce liczy wszystkie przebiegi segmentu; "
                  "„poprzednio” to ostatni wcześniejszy przebieg z innego biegu.",
               en="Your segments, “auto” (routes run at least 4 times) and interval reps (each rep ranked at its "
                  "length). The rank counts every pass of the segment; “previous” is the last earlier pass from "
                  "another run."),
    ) as t:
        with t.header:
            if st.button("", icon=":material/arrow_forward:", key="to_segments", type="tertiary",
                         help=i18n.page("segmenty")):
                routing.goto("segmenty")
        if mine.empty:
            return
        heart = tr(pl="tętno", en="HR")
        rows = []
        for item in mine.sort_values(["at_km", "pass"]).rename(columns={"pass": "number"}).itertuples():
            segment = known[item.segment_id]
            pool = efforts[efforts["segment_id"] == item.segment_id]
            before = pool[pool["start_local"] < item.start_local]
            best = pool["seconds"].min()
            label = segment["name"] + (" · auto" if segment.get("auto") else "")
            if segment.get("reps"):
                label += tr(pl=f" · {int(item.number)}. powt.", en=f" · rep {int(item.number)}")
            previous = "—" if before.empty else \
                f"{item.seconds - before.iloc[-1]['seconds']:+.0f} s ({before.iloc[-1]['start_local']:%d.%m.%y})"
            rows.append({
                "segment_id": item.segment_id,
                "segment": label,
                tr(pl="od km", en="from km"): item.at_km,
                tr(pl="czas", en="time"): units.fmt_time(item.seconds),
                tr(pl="tempo", en="pace"): units.fmt_pace(item.pace_min_km, False),
                heart: item.hr,
                tr(pl="miejsce", en="rank"): f"{item.rank}/{item.of}" + (" 🏆" if item.rank == 1 and item.of > 1 else ""),
                tr(pl="do najlepszego", en="to the best"): "—" if item.seconds == best
                else f"+{item.seconds - best:.0f} s",
                tr(pl="poprzednio", en="previous"): previous,
            })
        shown = pd.DataFrame(rows)
        event = st.dataframe(
            tz.readable_paces(shown.drop(columns="segment_id").assign(
                **{heart: pd.to_numeric(shown[heart], errors="coerce").round().astype("Int64")})),
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
    tr = i18n.tr
    with bento.panel(tr(pl="Nowy segment z tego biegu", en="New segment from this run"), key="new_segment",
                     terms=["segment"],
                     caption=tr(pl="Wybierz odcinek po kilometrach — każdy bieg, który przejdzie go od początku do "
                                   "końca, trafi do rankingu.",
                                en="Pick a stretch by kilometres — every run that covers it from start to finish "
                                   "enters the ranking.")):
        activity_id = int(run["activity_id"])
        low, high = st.slider(tr(pl="Kilometry", en="Kilometres"), 0.0, round(total, 2),
                              (0.0, round(min(total, 1.0), 2)), step=0.05,
                              key=f"segment_range_{activity_id}", format="%.2f km")
        marked = track.assign(segment=pd.to_numeric(track["distance_km"], errors="coerce").between(low, high))
        tz.show(tz.route_map(marked, highlight="segment", height=360, uirevision=f"segment-{activity_id}"),
                key=f"segment_map_{activity_id}")
        name, save = st.columns([4, 1], vertical_alignment="bottom")
        title = name.text_input(tr(pl="Nazwa", en="Name"), key=f"segment_name_{activity_id}",
                                placeholder=tr(pl="np. podbieg na Wzgórzu", en="e.g. the hill climb"))
        if save.button(tr(pl="Zapisz segment", en="Save the segment"), icon=":material/add_location_alt:",
                       key=f"segment_save_{activity_id}", width="stretch", type="primary"):
            cut = segments.cut(track, low, high)
            try:
                if cut is None:
                    raise ValueError(tr(pl="Za krótki odcinek śladu.", en="Too short a stretch of track."))
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
    tr = i18n.tr
    pace, fade = f"<b>{units.fmt_pace(shape['pace'])}</b>", f"<b>{shape['fade_s']:+.0f} s/km</b>"
    caption = (f"{shape['reps']} × {shape['rep_km']:.1f} km · " + tr(pl=f"śr. {pace}", en=f"avg {pace}")
               + (tr(pl=f" przy {shape['hr']:.0f} bpm", en=f" at {shape['hr']:.0f} bpm") if pd.notna(shape["hr"])
                  else "")
               + tr(pl=f" · ostatni {fade} wobec pierwszego", en=f" · last {fade} against the first")
               + (tr(pl=f", tętno {shape['hr_drift']:+.0f}", en=f", HR {shape['hr_drift']:+.0f}")
                  if pd.notna(shape["hr_drift"]) else "")
               + (tr(pl=" · przerwy ", en=" · rests ") + units.fmt_time(shape["rest_s"])
                  if pd.notna(shape["rest_s"]) else ""))
    with bento.tile(
        tr(pl="Odcinki i splity", en="Reps and splits"), key="reps", caption=caption, terms=["rep_fade", "cadence"],
        how=tr(pl="Z okrążeń zegarka (dokładny czas stopera). Splity to kolejne okrążenia wewnątrz odcinka — "
                  "auto-lap co kilometr, niepełne z długością w nawiasie. Przerwa to trucht po odcinku. Miejsce: "
                  "wśród wszystkich Twoich odcinków tej długości (±7%), gdziekolwiek biegniętych — także na bieżni.",
               en="From the watch laps (exact stopwatch time). Splits are the laps inside a rep — an auto-lap every "
                  "kilometre, partial ones with their length in brackets. Rest is the jog after the rep. Rank: "
                  "among all your reps of that length (±7%), wherever run — the track included."),
    ) as t:
        places = {int(r.pass_): f"{r.rank}/{r.of}" + (" 🏆" if r.rank == 1 and r.of > 1 else "")
                  for r in ranked.rename(columns={"pass": "pass_"}).itertuples()}
        t.table(pd.DataFrame({
            "#": table["rep"],
            "km": table["km"],
            tr(pl="czas", en="time"): table["seconds"].map(units.fmt_time),
            tr(pl="tempo", en="pace"): table["pace"].map(lambda v: units.fmt_pace(v, False)),
            tr(pl="miejsce", en="rank"): table["rep"].map(lambda r: places.get(int(r), "—")),
            tr(pl="splity", en="splits"): table["laps"].map(_lap_text),
            tr(pl="tętno", en="HR"): table["hr"].round().astype("Int64"),
            tr(pl="maks.", en="max"): table["hr_max"].round().astype("Int64"),
            tr(pl="kadencja", en="cadence"): table["cadence"].round().astype("Int64"),
            tr(pl="przerwa", en="rest"): table["rest_s"].map(lambda v: units.fmt_time(v) if pd.notna(v) else "—"),
            tr(pl="trucht", en="jog"): table["rest_pace"].map(lambda v: units.fmt_pace(v, False)),
            tr(pl="tętno w przerwie", en="HR in rest"): table["rest_hr"].round().astype("Int64"),
        }))


def _pace_at_hr(peers: pd.DataFrame, every: pd.DataFrame, run: pd.Series) -> None:
    activity_id = int(run["activity_id"])
    current = peers[peers["current"]].iloc[0]
    tr = i18n.tr
    offset = current["vs_hr_s"]
    if pd.notna(offset):
        gap = f"{abs(offset):.0f} s/km"
        caption = (tr(pl=f"przy tym samym tętnie <b>szybciej o {gap}</b> niż odcinki wcześniejszych workoutów",
                      en=f"at the same heart rate <b>{gap} faster</b> than the reps of earlier workouts") if offset < 0
                   else tr(pl=f"przy tym samym tętnie <b>wolniej o {gap}</b> niż odcinki wcześniejszych workoutów",
                           en=f"at the same heart rate <b>{gap} slower</b> than the reps of earlier workouts"))
    else:
        caption = tr(pl="Za mało wcześniejszych workoutów, żeby poprowadzić linię tempo ~ tętno.",
                     en="Too few earlier workouts to fit a pace ~ heart rate line.")
    with bento.tile(
        tr(pl="Tempo a tętno na odcinkach", en="Pace against heart rate on reps"), rows=2, key="pace_hr",
        caption=caption, terms=["pace_at_hr"],
        how=tr(pl="Każda kropka to jeden odcinek. Szara linia to dopasowanie do odcinków sprzed tego treningu — "
                  "kropki nad nią to szybciej przy tym samym tętnie. Podobne = odcinki o długości ±35%.",
               en="Each dot is one rep. The grey line is the fit to reps before this session — dots above it are "
                  "faster at the same heart rate. Similar = reps of a length within ±35%."),
    ) as t:
        this, similar_, other = (tr(pl="ten trening", en="this session"), tr(pl="podobne odcinki", en="similar reps"),
                                 tr(pl="inne workouty", en="other workouts"))
        group, when, rep = tr(pl="grupa", en="group"), tr(pl="kiedy", en="when"), tr(pl="odcinek", en="rep")
        heart, pace = tr(pl="tętno", en="HR"), tr(pl="tempo", en="pace")
        groups = {aid: this if is_current else similar_ if similar else other
                  for aid, is_current, similar in peers[["activity_id", "current", "similar"]].itertuples(index=False)}
        shown = every[every["start_local"] <= current["start_local"]]
        points = shown.assign(**{
            group: shown["activity_id"].map(groups),
            when: shown["start_local"].dt.strftime("%d.%m.%Y"),
            rep: shown["km"].map(lambda v: f"{v:.1f} km"),
        }).rename(columns={"hr": heart, "pace": pace})
        order = {this: 0, similar_: 1, other: 2}
        points = points.sort_values(group, key=lambda g: g.map(order))
        figure = tz.scatter(points, heart, pace, color=group, color_kind="categorical",
                            hover=(when, rep), x_title=tr(pl="średnie tętno odcinka (bpm)", en="rep average HR (bpm)"),
                            y_title="", pace_y=True, reverse_y=True)
        fit = workouts.hr_fit(every, activity_id, current["start_local"])
        if figure is not None and fit is not None:
            span = pd.Series([points[heart].min(), points[heart].max()])
            figure.add_scatter(x=span, y=fit[0] + fit[1] * span, mode="lines", hoverinfo="skip", showlegend=False,
                               line=dict(color=tz.tokens()["muted"], width=1.4, dash="dot"))
        t.chart(figure, table=points[[when, group, rep, pace, heart]],
                key=f"pace_hr_{activity_id}")


def _workout_peers(peers: pd.DataFrame, run: pd.Series) -> None:
    others = peers[~peers["current"]]
    current = peers[peers["current"]].iloc[0]
    earlier = others[others["similar"] & (others["start_local"] < current["start_local"])]
    tr = i18n.tr
    caption = None
    if not earlier.empty:
        last = earlier.iloc[-1]
        then = f"{last['start_local']:%d.%m.%Y} ({last['reps']:.0f} × {last['rep_km']:.1f} km)"
        pace = f"<b>{(current['pace'] - last['pace']) * 60:+.0f} s/km</b>"
        heart = f"<b>{current['hr'] - last['hr']:+.0f}</b> bpm"
        caption = tr(pl=f"wobec {then}: tempo {pace}, tętno {heart}", en=f"against {then}: pace {pace}, HR {heart}")
    with bento.tile(
        tr(pl="Podobne workouty", en="Similar workouts"), rows=2, key="workout_peers", caption=caption,
        terms=["rep_fade", "pace_at_hr"],
        how=tr(pl="Najpierw workouty o podobnej długości odcinków (±35%, znak ≈), potem pozostałe; w grupie od "
                  "najnowszych. Kliknij wiersz, żeby otworzyć trening.",
               en="First the workouts with similar rep lengths (±35%, sign ≈), then the rest; newest first within "
                  "a group. Click a row to open the session."),
    ):
        if others.empty:
            st.caption(tr(pl="To pierwszy workout z okrążeniami — nie ma z czym porównać.",
                          en="This is the first workout with laps — nothing to compare it with."))
            return
        shown = others.sort_values(["similar", "start_local"], ascending=[False, False]) \
            .head(bento.table_rows(2)).reset_index(drop=True)
        event = st.dataframe(pd.DataFrame({
            tr(pl="kiedy", en="when"): shown["start_local"].dt.strftime("%d.%m.%Y"),
            tr(pl="odcinki", en="reps"): [f"{r.reps:.0f} × {r.rep_km:.1f} km" + (" ≈" if r.similar else "")
                                          for r in shown.itertuples()],
            tr(pl="tempo", en="pace"): shown["pace"].map(lambda v: units.fmt_pace(v, False)),
            tr(pl="tętno", en="HR"): shown["hr"].round().astype("Int64"),
            tr(pl="rozjazd s/km", en="fade s/km"): shown["fade_s"].round().astype("Int64"),
            tr(pl="tętno ↑", en="HR ↑"): shown["hr_drift"].round().astype("Int64"),
            tr(pl="przerwa", en="rest"): shown["rest_s"].map(lambda v: units.fmt_time(v) if pd.notna(v) else "—"),
            tr(pl="vs tętno s/km", en="vs HR s/km"): shown["vs_hr_s"].round().astype("Int64"),
        }), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
            key=f"workout_peers_{int(run['activity_id'])}", height=bento.table_height(len(shown)))
        rows = getattr(getattr(event, "selection", None), "rows", None) or []
        if rows:
            routing.open_run(int(shown.iloc[rows[0]]["activity_id"]))


def _splits(run: pd.Series) -> None:
    splits = shell.table("run_splits")
    mine = splits[splits["activity_id"] == run["activity_id"]] if not splits.empty else splits
    tr = i18n.tr
    caption = tr(pl="Ze strumienia ~400 próbek — dokładność kilku sekund.",
                 en="From a stream of ~400 samples — accurate to a few seconds.")
    paces = mine[mine["length_km"] >= 0.9]["pace_min_km"] if not mine.empty else pd.Series(dtype=float)
    # Halves only mean something for a continuous run: a workout with a
    # warm-up always "negative splits".
    if len(paces) >= 4 and run["kind"] in ("easy", "long", "recovery", "race"):
        half = len(paces) // 2
        first, second = paces.iloc[:half].mean(), paces.iloc[half:].mean()
        halves = f"{units.fmt_pace(first, False)}, 2. {units.fmt_pace(second, False)}"
        verdict = "negative split" if second < first - 0.03 else \
            tr(pl="równo", en="even") if abs(second - first) <= 0.03 else tr(pl="druga wolniejsza",
                                                                             en="second half slower")
        caption = tr(pl=f"1. połowa {halves} — {verdict}", en=f"1st half {halves} — {verdict}")
    with bento.tile(tr(pl="Splity kilometrowe", en="Kilometre splits"), key="splits", caption=caption,
                    how=tr(pl="Czas stopera, bez autopauzy. Ostatni odcinek może być niepełny. Wyżej = szybciej.",
                           en="Stopwatch time, without auto-pause. The last split may be partial. Higher = "
                              "faster.")) as t:
        if mine.empty:
            st.caption(tr(pl="Ten bieg nie ma strumienia próbek (np. bieżnia albo brak GPS).",
                          en="This run has no sample stream (e.g. a treadmill or no GPS)."))
            return
        pace = tr(pl="tempo", en="pace")
        # Points and a line, not bars: on a reversed pace axis a bar hangs from the
        # top and the slowest kilometre would get the longest bar.
        figure = tz.timeseries(mine, "km", {pace: "pace_min_km"}, markers=True)
        if figure is not None:
            tz.pace_axis(figure, mine["pace_min_km"], robust=True)
            figure.update_xaxes(title_text=tr(pl="kilometr", en="kilometre"), dtick=1)
            figure.update_traces(customdata=mine["pace_min_km"].map(lambda v: units.fmt_pace(v)),
                                 hovertemplate="km %{x}: %{customdata}<extra></extra>")
        t.chart(figure, table=pd.DataFrame({
            "km": mine["km"], tr(pl="długość", en="length"): mine["length_km"],
            tr(pl="czas", en="time"): mine["seconds"].map(units.fmt_time),
            pace: mine["pace_min_km"].map(lambda v: units.fmt_pace(v, False)), tr(pl="tętno", en="HR"): mine["hr"],
            tr(pl="w górę m", en="up m"): mine["elev_gain_m"], tr(pl="w dół m", en="down m"): mine["elev_loss_m"],
            tr(pl="kadencja", en="cadence"): mine["cadence"],
        }), key=f"splits_{int(run['activity_id'])}")


def _streams(track: pd.DataFrame) -> None:
    tr = i18n.tr
    with bento.tile(tr(pl="Przebieg wzdłuż dystansu", en="Along the distance"), rows=2, key="streams",
                    caption=tr(pl="Te same próbki co splity, bez uśredniania do kilometra.",
                               en="The same samples as the splits, without averaging to the kilometre.")) as t:
        panels = []
        if not track.empty and "pace_min_km" in track.columns and track["pace_min_km"].notna().any():
            panels.append({"title": tr(pl="Tempo (/km)", en="Pace (/km)"),
                           "series": {tr(pl="tempo", en="pace"): "pace_min_km"}, "kind": "line", "pace": True})
        if not track.empty and "hr" in track.columns and track["hr"].notna().any():
            panels.append({"title": tr(pl="Tętno (bpm)", en="Heart rate (bpm)"),
                           "series": {tr(pl="tętno", en="heart rate"): "hr"}, "kind": "line"})
        if not track.empty and "elevation_m" in track.columns and track["elevation_m"].notna().any():
            panels.append({"title": tr(pl="Wysokość (m)", en="Elevation (m)"),
                           "series": {tr(pl="wysokość", en="elevation"): "elevation_m"}, "kind": "line",
                           "height": 0.7})
        if not panels:
            st.caption(tr(pl="Brak strumienia próbek dla tego biegu.", en="No sample stream for this run."))
            return
        figure = tz.stacked_panels(track, "distance_km", panels, height=400)
        if figure is not None:
            figure.update_xaxes(title_text=tr(pl="dystans (km)", en="distance (km)"), row=len(panels), col=1)
        t.chart(figure, key="run_streams")


def _zones(run: pd.Series) -> None:
    tr = i18n.tr
    zones = {tr(pl=f"strefa {i}", en=f"zone {i}"): run.get(f"hr_z{i}_s") for i in range(1, 6)}
    with bento.tile(tr(pl="Strefy tętna", en="Heart rate zones"), key="zones", terms=["hr_zones"],
                    caption=tr(pl="Minuty w strefach Garmina (granice z ustawień zegarka).",
                               en="Minutes in Garmin's zones (limits from the watch settings).")) as t:
        if all(pd.isna(v) for v in zones.values()):
            st.caption(tr(pl="Brak tętna.", en="No heart rate."))
            return
        zone = tr(pl="strefa", en="zone")
        frame = pd.DataFrame({zone: list(zones), "min": [(v or 0) / 60 for v in zones.values()]})
        # Zones are ordered categories: vertical bars in zone order, not a ranking.
        t.chart(tz.bars(frame, zone, "min", y_title="min"), table=frame.round(1), key="run_zones")


def _similar(frame: pd.DataFrame, run: pd.Series) -> None:
    peers = sessions.similar(frame, int(run["activity_id"]))
    tr = i18n.tr
    caption = None
    if not peers.empty:
        pace_diff = (run["pace_min_km"] - peers["pace_min_km"].median()) * 60
        hr_diff = run["avg_hr"] - peers["avg_hr"].median() if pd.notna(run["avg_hr"]) else None
        pace = f"<b>{'-' if pace_diff < 0 else '+'}{units.fmt_time(abs(pace_diff))}</b> /km"
        caption = tr(pl=f"wobec mediany {len(peers)}: tempo {pace}", en=f"against the median of {len(peers)}: pace {pace}")
        if hr_diff is not None and pd.notna(hr_diff):
            caption += tr(pl=f", tętno <b>{hr_diff:+.0f}</b> bpm", en=f", HR <b>{hr_diff:+.0f}</b> bpm")
    kind = rc.kind_label(run["kind"])
    with bento.tile(
        tr(pl="Na tle podobnych", en="Against similar runs"), rows=2, key="similar", caption=caption,
        how=tr(pl=f"Wcześniejsze biegi typu „{kind}” o dystansie ±25%. Szybciej przy tym samym tętnie to postęp; "
                  "szybciej przy wyższym — mocniejszy trening. Kliknij wiersz, żeby otworzyć bieg.",
               en=f"Earlier “{kind}” runs at a distance within ±25%. Faster at the same heart rate is progress; "
                  "faster at a higher one — harder training. Click a row to open the run."),
    ):
        if peers.empty:
            st.caption(tr(pl="Brak podobnych biegów do porównania.", en="No similar runs to compare with."))
            return
        count = bento.table_rows(2)
        shown = peers.sort_values("start_local", ascending=False).head(count)
        rc.pickable_runs(shown, key=f"similar_{int(run['activity_id'])}", height=bento.table_height(len(shown)),
                         hint=False)
