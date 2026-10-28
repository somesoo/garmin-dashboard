"""One run in detail: splits, streams, zones, structure, its label and its peers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import bento
import routing
import shell
import theme as tz
from running import plan as planning, sessions, store, units, workouts
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
    bento.header("Trening", "Jeden bieg w szczegółach: splity, przebieg, strefy, struktura i porównanie z podobnymi.")
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
    _reps(table, workouts.summary(table))
    history, every = workouts.history(frame, laps)
    peers = workouts.peers(history, activity_id)
    if peers.empty:
        return
    left, right = bento.row(2, 2)
    with left:
        _pace_at_hr(peers, every, run)
    with right:
        _workout_peers(peers, run)


def _lap_text(laps: list[tuple[float, float]]) -> str:
    return " · ".join(units.fmt_pace(pace, False) + ("" if abs(km - 1) < 0.05 else f" ({km * 1000:.0f} m)")
                      for km, pace in laps)


def _reps(table: pd.DataFrame, shape: dict) -> None:
    caption = (f"{shape['reps']} × {shape['rep_km']:.1f} km · śr. <b>{units.fmt_pace(shape['pace'])}</b>"
               + (f" przy {shape['hr']:.0f} bpm" if pd.notna(shape["hr"]) else "")
               + f" · ostatni <b>{shape['fade_s']:+.0f} s/km</b> wobec pierwszego"
               + (f", tętno {shape['hr_drift']:+.0f}" if pd.notna(shape["hr_drift"]) else "")
               + (f" · przerwy {units.fmt_time(shape['rest_s'])}" if pd.notna(shape["rest_s"]) else ""))
    with bento.tile(
        "Odcinki i splity", key="reps", caption=caption, terms=["rep_fade", "cadence"],
        how="Z okrążeń zegarka (dokładny czas stopera). Splity to kolejne okrążenia wewnątrz odcinka — "
            "auto-lap co kilometr, niepełne z długością w nawiasie. Przerwa to trucht po odcinku.",
    ) as t:
        t.table(pd.DataFrame({
            "#": table["rep"],
            "km": table["km"],
            "czas": table["seconds"].map(units.fmt_time),
            "tempo": table["pace"].map(lambda v: units.fmt_pace(v, False)),
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
