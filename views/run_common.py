"""Shared plumbing for the running pages (``views/run_*``).

Data comes through ``shell.table`` like everywhere else, so a warehouse
rebuild invalidates it. The forecast itself is cheap but depends on the races
and plans the runner entered, which live outside the warehouse -- their file
stamps are part of the cache key.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd
import streamlit as st

import i18n
import shell
from running import coach, forecast, plan as planning, segments, sessions, store, text, units, workouts

KIND_ORDER = ["recovery", "easy", "long", "tempo", "threshold", "intervals", "race"]
# Labels of stored codes live in running/text.py, next to the code that writes them.
CONFIDENCE_ICON = text.CONFIDENCE_ICON
confidence_label, confidence, race_label = text.confidence_label, text.confidence, text.race_label
effort_label, action_label, kind_label = text.effort_label, text.action_label, text.kind_label


def runs() -> pd.DataFrame:
    frame = shell.table("run_sessions")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    return frame


def efforts() -> pd.DataFrame:
    frame = shell.table("run_efforts")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


def history() -> pd.DataFrame:
    frame = shell.table("run_forecast")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


def hr_max(frame: pd.DataFrame) -> float | None:
    if frame.empty or "hr_max_used" not in frame.columns or frame["hr_max_used"].isna().all():
        return None
    return float(frame["hr_max_used"].dropna().iloc[0])


def store_stamp() -> str:
    """Changes whenever a race or plan file is written."""
    parts = []
    for path in [store.RACES, *sorted(store.PLANS.glob("*.json"))] if store.PLANS.is_dir() else [store.RACES]:
        if path.exists():
            parts.append(f"{path.name}:{path.stat().st_mtime_ns}")
    return "|".join(parts)


def upcoming_races(today: dt.date | None = None) -> list[dict[str, Any]]:
    today = today or dt.date.today()
    return sorted((r for r in store.races() if r.get("date", "") >= today.isoformat()), key=lambda r: r["date"])


def race_forecast(race: dict, result: dict[str, Any], today: dt.date) -> forecast.DistanceForecast | None:
    """The distance forecast with this race's own target: after the plan when
    the plan covers the race, otherwise if training goes on as now."""
    item = result["distances"].get(race["distance"]) if result.get("status") == "ok" else None
    if item is None:
        return None
    frame = runs()
    base = planning.baseline(frame, frame["day"].max(), result.get("vdot"))
    return planning.race_outlook(item, race, store.current_plan(), base, today)


# Cache keys are the build id (and the coach files' stamp): a rebuild or a
# saved race invalidates the result. The forecast also carries sentences, so
# the language is part of its key. (Streamlit does not hash parameters whose
# name starts with "_" -- a key must not.)
@st.cache_data(show_spinner=False)
def _forecast(build: str, stamp: str, today: str, lang: str) -> dict[str, Any]:
    frame = runs()
    result = forecast.forecast(frame, efforts(), shell.daily(), hr_max=hr_max(frame))
    if result.get("status") != "ok":
        return result
    # Per distance, the nearest race's target (the Forecast page's column).
    day = dt.date.fromisoformat(today)
    base = planning.baseline(frame, frame["day"].max(), result.get("vdot"))
    plan = store.current_plan()
    for race in reversed(upcoming_races(day)):
        item = result["distances"].get(race["distance"])
        if item is not None:
            result["distances"][race["distance"]] = planning.race_outlook(item, race, plan, base, day)
    return result


def current_forecast() -> dict[str, Any]:
    frame = runs()
    if frame.empty:
        return {"status": "insufficient", "reason": i18n.tr(pl="Brak tabeli biegów.", en="No runs table.")}
    return _forecast(shell.build_id(), store_stamp(), dt.date.today().isoformat(), i18n.lang())


@st.cache_data(show_spinner=False)
def _paths(build: str) -> dict[int, pd.DataFrame]:
    routes = shell.table("routes")
    frame = runs()
    if routes.empty or frame.empty:
        return {}
    return segments.paths(routes[routes["activity_id"].isin(frame["activity_id"])])


def paths() -> dict[int, pd.DataFrame]:
    """Every run's GPS track resampled to 10 m (``segments.path``)."""
    return _paths(shell.build_id())


@st.cache_data(show_spinner=False)
def _loops(build: str) -> frozenset[int]:
    return frozenset(a for a, p in paths().items() if segments.is_loop(p))


def is_loop(activity_id: int) -> bool:
    """A track session or tiny loop: no GPS segments, compare by distance."""
    return int(activity_id) in _loops(shell.build_id())


@st.cache_data(show_spinner=False)
def _rep_efforts(build: str) -> pd.DataFrame:
    frame = runs()
    _, every = workouts.history(frame, shell.table("run_laps"))
    return workouts.rep_efforts(every, frame)


def rep_efforts() -> pd.DataFrame:
    """Every workout rep as a pass of its standard length (``rep-1000``...)."""
    return _rep_efforts(shell.build_id())


@st.cache_data(show_spinner=False)
def _all_efforts(build: str) -> pd.DataFrame:
    standard = efforts()
    short = sessions.short_efforts(paths(), runs())
    if not short.empty:
        short = short.assign(day=pd.to_datetime(short["day"]))
    frame = pd.concat([standard, short], ignore_index=True) if not short.empty else standard
    return frame[frame["effort"].isin([*sessions.SHORT_EFFORTS, *sessions.EFFORT_DISTANCES])] \
        if not frame.empty else frame


def all_efforts() -> pd.DataFrame:
    """Best efforts per run: ``run_efforts`` plus 400 m / 800 m from the stream."""
    return _all_efforts(shell.build_id())


@st.cache_data(show_spinner=False)
def _signatures(build: str) -> dict[int, dict[str, Any]]:
    return segments.signatures(paths())


def same_route(activity_id: int) -> pd.DataFrame:
    """Other runs on this run's route (GPS overlap), with ``overlap``."""
    twins = segments.same_route(_signatures(shell.build_id()), int(activity_id))
    if not twins:
        return pd.DataFrame()
    frame = runs()
    overlap = dict(twins)
    return frame[frame["activity_id"].isin(overlap)].assign(overlap=lambda f: f["activity_id"].map(overlap))


@st.cache_data(show_spinner=False)
def _auto_segments(build: str, stamp: str, lang: str) -> list[dict[str, Any]]:
    return segments.frequent(paths(), runs(), store.segments())


def all_segments() -> list[dict[str, Any]]:
    """Saved segments first, then the ones found on frequent routes (``auto``)."""
    return store.segments() + _auto_segments(shell.build_id(), store.segments_stamp(), i18n.lang())


@st.cache_data(show_spinner=False)
def _segment_efforts(build: str, stamp: str) -> pd.DataFrame:
    return segments.efforts(all_segments(), paths(), runs())


def segment_efforts() -> pd.DataFrame:
    """Every pass of every segment, saved or found; recomputed after a rebuild or a save."""
    return _segment_efforts(shell.build_id(), store.segments_stamp())


@st.cache_data(show_spinner=False)
def _shared(build: str, activity_id: int) -> pd.DataFrame:
    return segments.shared(activity_id, paths(), runs())


def shared(activity_id: int) -> pd.DataFrame:
    """Longest stretch this run shares with every other run, timed on both."""
    return _shared(shell.build_id(), int(activity_id))


def guard() -> pd.DataFrame | None:
    """The running tables or a clear message; None means the page should stop."""
    frame = runs()
    if frame.empty:
        st.info(i18n.tr(
            pl="Brak tabel biegowych. Uruchom `analytics.py` (albo `etl/run.py`, który robi to po pobraniu) — tabele "
               "`run_*` powstają z istniejących danych, bez odpytywania Garmina.",
            en="No running tables. Run `analytics.py` (or `etl/run.py`, which does it after a pull) — the `run_*` "
               "tables are built from the existing data, without querying Garmin.",
        ))
        return None
    return frame


def fmt_time(seconds: Any) -> str:
    return units.fmt_time(seconds)


def runs_table(frame: pd.DataFrame) -> pd.DataFrame:
    """The compact run log used on several pages."""
    tr = i18n.tr
    out = pd.DataFrame(
        {
            tr(pl="kiedy", en="when"): frame["start_local"].dt.strftime("%d.%m.%Y"),
            tr(pl="typ", en="type"): frame["kind"].map(kind_label),
            "km": frame["distance_km"].round(2),
            tr(pl="czas", en="time"): (frame["duration_min"] * 60).map(units.fmt_time),
            tr(pl="tempo", en="pace"): frame["pace_min_km"].map(lambda v: units.fmt_pace(v, False)),
            tr(pl="tętno", en="HR"): frame["avg_hr"],
            "load": frame["training_load"],
            tr(pl="nazwa", en="name"): frame["name"],
        }
    )
    return out


def run_columns() -> dict[str, Any]:
    heart = i18n.tr(pl="tętno", en="HR")
    return {
        "km": st.column_config.NumberColumn("km", format="%.1f"),
        heart: st.column_config.NumberColumn(heart, format="%.0f"),
        "load": st.column_config.NumberColumn("load", format="%.0f"),
    }


def pickable_runs(frame: pd.DataFrame, key: str, height: int | None = None, hint: bool = True) -> None:
    """Run log where clicking a row opens the session page."""
    import routing

    shown = frame.sort_values("start_local", ascending=False).reset_index(drop=True)
    event = st.dataframe(
        runs_table(shown), hide_index=True, width="stretch", column_config=run_columns(),
        on_select="rerun", selection_mode="single-row", key=key, height=height or "auto",
    )
    rows = getattr(getattr(event, "selection", None), "rows", None) or []
    if rows:
        routing.open_run(int(shown.iloc[rows[0]]["activity_id"]))
    if hint:
        st.caption(i18n.tr(pl="Kliknij wiersz, żeby otworzyć szczegóły treningu.",
                           en="Click a row to open the session details."))


def download_brief(prefix: str) -> None:
    """Brief for the assistant as Markdown and JSON downloads."""
    frame = runs()
    if frame.empty:
        return
    data = coach.brief(frame, efforts(), shell.daily(), laps=shell.table("run_laps"))
    columns = st.columns(2)
    columns[0].download_button(
        "Brief (Markdown)", coach.markdown(data), file_name=f"brief-{dt.date.today()}.md",
        mime="text/markdown", key=f"{prefix}_brief_md", width="stretch",
    )
    columns[1].download_button(
        "Brief (JSON)", json.dumps(data, indent=2, ensure_ascii=False, default=str),
        file_name=f"brief-{dt.date.today()}.json", mime="application/json",
        key=f"{prefix}_brief_json", width="stretch",
    )


STATUS_ICONS = {"planned": "·", "done": "✓", "modified": "≈", "skipped": "✗", "missed": "✗"}


def strength_done() -> int:
    """Strength sessions the watch recorded recently (when heavy work may start)."""
    return planning.strength_done(shell.table("activities"))


def active_plan(today: dt.date | None = None) -> dict[str, Any] | None:
    """The plan, rebuilt from tomorrow when the races ahead are no longer its goals."""
    today = today or dt.date.today()
    plan = store.current_plan()
    if plan is None:
        return None
    races = upcoming_races(today)
    if races and planning.stale(plan, races, today):
        frame = runs()
        try:
            plan = store.save_only_plan(planning.replan(plan, frame, current_forecast(),
                                                        today=today + dt.timedelta(days=1),
                                                        goals=[planning.goal_of(r) for r in races],
                                                        strength_history=strength_done(),
                                                        laps=shell.table("run_laps"),
                                                        activities=shell.table("activities")))
        except ValueError as error:
            st.warning(i18n.tr(pl=f"Nie udało się dopasować planu do nowych celów: {error}",
                               en=f"Could not fit the plan to the new goals: {error}"))
    return plan if planning.next_goal(plan, today) else None


def forecast_tiles(result: dict[str, Any], keys: list[str] | None = None, compact: bool = False) -> None:
    """Realistic time per distance with the 80% interval underneath (``compact``:
    the interval only, for a 1-row bento tile; pace and confidence go to the tooltip)."""
    if result.get("status") != "ok":
        st.caption(result.get("reason") or i18n.tr(pl="Brak prognozy.", en="No forecast."))
        return
    sure = i18n.tr(pl="pewność", en="confidence")
    items = [(k, v) for k, v in result["distances"].items() if keys is None or k in keys]
    for column, (key, item) in zip(st.columns(len(items)), items):
        if compact:
            column.metric(race_label(key), units.fmt_time(item.realistic_s),
                          help=f"{units.fmt_pace(item.pace)} · {sure} {confidence_label(item.confidence)}")
            column.markdown(f"<div class='tile-caption'>{units.fmt_time(item.low_s)}–{units.fmt_time(item.high_s)}"
                            "</div>", unsafe_allow_html=True)
            continue
        column.metric(race_label(key), units.fmt_time(item.realistic_s))
        column.caption(
            f"{units.fmt_time(item.low_s)}–{units.fmt_time(item.high_s)} · {units.fmt_pace(item.pace)}  \n"
            f"{sure} {confidence(item.confidence)}"
        )


def week_strip(active: dict[str, Any] | None, frame: pd.DataFrame, today: dt.date | None = None) -> None:
    """Monday to Sunday of the current week, one column per day.

    With a plan: the planned session and its status. Without one: what was
    actually run, so the strip is never empty for a runner without a plan.
    """
    today = today or dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    cells: dict[dt.date, list[str]] = {}
    if active is not None:
        matched = planning.match(active, frame, today, laps=shell.table("run_laps"))
        for row in matched.itertuples(index=False) if not matched.empty else []:
            if monday <= row.date < monday + dt.timedelta(days=7):
                cell = f"{STATUS_ICONS.get(row.effective, '·')} {row.title}"
                if pd.notna(row.actual_km) and row.actual_km:
                    cell += f"  \n{row.actual_km:.1f} km"
                cells.setdefault(row.date, []).append(cell)
    else:
        week = frame[(frame["day"] >= pd.Timestamp(monday)) & (frame["day"] < pd.Timestamp(monday + dt.timedelta(days=7)))]
        for row in week.itertuples(index=False):
            cells.setdefault(row.day.date(), []).append(f"✓ {kind_label(row.kind)}  \n{row.distance_km:.1f} km")
    for offset, column in enumerate(st.columns(7)):
        day = monday + dt.timedelta(days=offset)
        name = f"{i18n.weekdays()[offset]} {day:%d.%m}"
        label = f"**{name}**" if day == today else name
        column.markdown(label)
        column.caption("  \n".join(cells.get(day, [])) or "—")
