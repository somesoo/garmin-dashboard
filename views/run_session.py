"""One run in detail: splits, streams, zones, structure, its label and its peers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import routing
import shell
import theme as tz
from running import plan as planning, sessions, store, units
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
    st.title("Trening")
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

    chosen = st.selectbox("Bieg", options, format_func=describe, key="run_activity")
    run = catalogue[catalogue["activity_id"] == chosen].iloc[0]
    routes = shell.table("routes")
    track = routes[pd.to_numeric(routes["activity_id"], errors="coerce") == chosen].sort_values("seq") \
        if not routes.empty else pd.DataFrame()

    _summary(run)
    _plan_link(run)
    _structure(run)
    _splits(run)
    _streams(track)
    _zones(run)
    _similar(frame, run)
    if not track.empty and st.button("Mapa trasy →", key="run_to_map"):
        routing.open_activity(int(chosen))


def _summary(run: pd.Series) -> None:
    columns = st.columns(4)
    columns[0].metric("Dystans", f"{run['distance_km']:.2f} km")
    columns[1].metric("Czas", units.fmt_time(run["duration_min"] * 60))
    columns[2].metric("Tempo", units.fmt_pace(run["pace_min_km"]))
    hr = run.get("avg_hr")
    columns[3].metric("Tętno śr. / maks.", f"{hr:.0f} / {run.get('max_hr'):.0f}" if pd.notna(hr) else "—")
    columns = st.columns(4)
    gain = run.get("elevation_gain_m")
    columns[0].metric("Przewyższenie", f"{gain:.0f} m" if pd.notna(gain) else "—")
    cadence = run.get("cadence")
    columns[1].metric("Kadencja", f"{cadence:.0f} kr/min" if pd.notna(cadence) else "—")
    load = run.get("training_load")
    columns[2].metric("Load Garmina", f"{load:.0f}" if pd.notna(load) else "—")
    te = run.get("te_aerobic")
    columns[3].metric("TE tlen. / beztlen.",
                      f"{te:.1f} / {run.get('te_anaerobic', 0) or 0:.1f}" if pd.notna(te) else "—")
    st.markdown(
        f"**Charakter: {rc.kind_label(run['kind'])}** · pewność {run['kind_confidence']} — {run['kind_reason']}."
    )
    hr_max = run.get("hr_max_used")
    if pd.notna(hr) and pd.notna(hr_max):
        st.caption(f"Średnie tętno to {hr / hr_max:.0%} HRmax ({hr_max:.0f}). Etykieta to opis sesji z danych, "
                   "nie ocena — przy niskiej pewności traktuj ją jako przypuszczenie.")


def _plan_link(run: pd.Series) -> None:
    """If a plan session matched this run, how it compares."""
    for item in store.plans():
        matched = planning.match(item, rc.runs())
        if matched.empty:
            continue
        hit = matched[matched["activity_id"] == int(run["activity_id"])]
        if hit.empty:
            continue
        row = hit.iloc[0]
        session = next(s for s in item["sessions"] if s["id"] == row["id"])
        shell.lead("W planie", f"Plan „{item.get('name')}”, tydzień {row['week']}.")
        verdict = {"done": "zrealizowany", "modified": "zmodyfikowany", "skipped": "pominięty"}.get(
            row["effective"], row["effective"])
        st.markdown(
            f"Zaplanowano: **{session.get('title')}** — {session.get('main')}  \n"
            f"Wykonano: {row['actual_km']:.1f} km"
            + (f" ({row['distance_ratio']:.0%} planu)" if pd.notna(row["distance_ratio"]) else "")
            + ", typ "
            f"„{rc.kind_label(row['actual_kind'])}” → **{verdict}**."
        )
        if session.get("pace_lo") and row["type"] in ("threshold", "intervals", "tempo"):
            st.caption(
                f"Tempo docelowe części głównej: {units.fmt_pace(session['pace_lo'], False)}–"
                f"{units.fmt_pace(session['pace_hi'])}. Porównaj z blokiem pracy niżej — średnie tempo całego "
                "biegu zawiera rozgrzewkę i przerwy."
            )
        return


def _structure(run: pd.Series) -> None:
    segments = shell.table("activity_segments")
    if segments.empty:
        return
    mine = segments[(segments["activity_id"] == run["activity_id"])
                    & segments["split_type"].astype(str).str.startswith("INTERVAL")]
    if mine.empty:
        return
    shell.lead("Struktura workoutu",
               "Fazy zapisane przez zegarek. Kilka powtórzeń tej samej fazy to jeden wiersz z sumą.")
    order = list(SEGMENT_LABELS)
    mine = mine.assign(order=mine["split_type"].map({k: i for i, k in enumerate(order)})).sort_values("order")
    st.dataframe(
        pd.DataFrame(
            {
                "faza": mine["split_type"].map(SEGMENT_LABELS).fillna(mine["split_type"]),
                "powtórzeń": mine["splits"].fillna(1).astype(int),
                "km": (mine["distance_m"] / 1000).round(2),
                "czas": mine["duration_s"].map(units.fmt_time),
                "tempo": mine["avg_speed_ms"].map(lambda v: units.fmt_pace(units.pace_from_speed(v), False)),
            }
        ),
        hide_index=True, width="stretch",
    )


def _splits(run: pd.Series) -> None:
    splits = shell.table("run_splits")
    shell.lead(
        "Splity kilometrowe",
        "Liczone ze strumienia ~400 próbek na trening (czas stopera, bez autopauzy): dokładność kilku sekund, "
        "nie dziesiątych jak na zegarku. Ostatni odcinek może być niepełny.",
    )
    mine = splits[splits["activity_id"] == run["activity_id"]] if not splits.empty else splits
    if mine.empty:
        st.caption("Ten bieg nie ma strumienia próbek (np. bieżnia albo brak GPS) — splitów nie da się policzyć, "
                   "więc ich nie ma.")
        return
    # Points and a line, not bars: on a reversed pace axis a bar hangs from the
    # top and the slowest kilometre would get the longest bar.
    figure = tz.timeseries(mine, "km", {"tempo": "pace_min_km"}, markers=True, height=240)
    if figure is not None:
        tz.pace_axis(figure, mine["pace_min_km"], robust=True)
        figure.update_xaxes(title_text="kilometr", dtick=1)
        figure.update_traces(customdata=mine["pace_min_km"].map(lambda v: units.fmt_pace(v)),
                             hovertemplate="km %{x}: %{customdata}<extra></extra>")
    tz.show(
        figure,
        table=pd.DataFrame(
            {
                "km": mine["km"],
                "długość": mine["length_km"],
                "czas": mine["seconds"].map(units.fmt_time),
                "tempo": mine["pace_min_km"].map(lambda v: units.fmt_pace(v, False)),
                "tętno": mine["hr"],
                "w górę m": mine["elev_gain_m"],
                "w dół m": mine["elev_loss_m"],
                "kadencja": mine["cadence"],
            }
        ),
        key=f"splits_{int(run['activity_id'])}",
    )
    paces = mine[mine["length_km"] >= 0.9]["pace_min_km"]
    # Halves only mean something for a continuous run: a workout with a
    # warm-up always "negative splits".
    if len(paces) >= 4 and run["kind"] in ("easy", "long", "recovery", "race"):
        half = len(paces) // 2
        first, second = paces.iloc[:half].mean(), paces.iloc[half:].mean()
        st.caption(
            f"Pierwsza połowa {units.fmt_pace(first)}, druga {units.fmt_pace(second)} — "
            + ("negative split." if second < first - 0.03 else "równo." if abs(second - first) <= 0.03
               else "druga połowa wolniejsza.")
        )


def _streams(track: pd.DataFrame) -> None:
    if track.empty:
        return
    panels = []
    if "pace_min_km" in track.columns and track["pace_min_km"].notna().any():
        panels.append({"title": "Tempo (/km, wyżej = szybciej)", "series": {"tempo": "pace_min_km"},
                       "kind": "line", "pace": True})
    if "hr" in track.columns and track["hr"].notna().any():
        panels.append({"title": "Tętno (bpm)", "series": {"tętno": "hr"}, "kind": "line"})
    if "elevation_m" in track.columns and track["elevation_m"].notna().any():
        panels.append({"title": "Wysokość (m)", "series": {"wysokość": "elevation_m"}, "kind": "line",
                       "height": 0.7})
    if not panels:
        return
    shell.lead("Przebieg wzdłuż dystansu", "Te same próbki co splity, bez uśredniania do kilometra.")
    figure = tz.stacked_panels(track, "distance_km", panels, height=130 * len(panels) + 60)
    if figure is not None:
        figure.update_xaxes(title_text="dystans (km)", row=len(panels), col=1)
    tz.show(figure, key="run_streams")


def _zones(run: pd.Series) -> None:
    zones = {label: run.get(column) for column, label in ZONE_LABELS.items()}
    if all(pd.isna(v) for v in zones.values()):
        return
    shell.lead("Strefy tętna", "Minuty w strefach Garmina (granice z ustawień zegarka).", terms=["hr_zones"])
    frame = pd.DataFrame({"strefa": list(zones), "min": [(v or 0) / 60 for v in zones.values()]})
    # Zones are ordered categories: vertical bars in zone order, not a ranking.
    tz.show(tz.bars(frame, "strefa", "min", height=220, y_title="min"), key="run_zones",
            table=frame.round(1))


def _similar(frame: pd.DataFrame, run: pd.Series) -> None:
    peers = sessions.similar(frame, int(run["activity_id"]))
    shell.lead(
        "Na tle podobnych",
        f"Wcześniejsze biegi typu „{rc.kind_label(run['kind'])}” o dystansie ±25%. Szybciej przy tym samym "
        "tętnie to postęp; szybciej przy wyższym — mocniejszy trening.",
    )
    if peers.empty:
        st.caption("Brak podobnych biegów do porównania.")
        return
    pace_diff = (run["pace_min_km"] - peers["pace_min_km"].median()) * 60
    hr_diff = run["avg_hr"] - peers["avg_hr"].median() if pd.notna(run["avg_hr"]) else None
    st.caption(
        f"Wobec mediany {len(peers)} podobnych: tempo {'-' if pace_diff < 0 else '+'}"
        f"{units.fmt_time(abs(pace_diff))} /km"
        + (f", tętno {hr_diff:+.0f} bpm." if hr_diff is not None and pd.notna(hr_diff) else ".")
    )
    rc.pickable_runs(peers, key=f"similar_{int(run['activity_id'])}")
