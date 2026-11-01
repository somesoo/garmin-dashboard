"""The day in facts: what the hero page (``views/day.py``) says around a run.

No suggestions here -- every item is something that happened, measured against
the visitor's own recent normal: today's run (or the last one, when today's is
still ahead), its most telling stretch, last night against the week before it,
the body this morning, the next race and a few pieces of trivia.

The run is the centre of the page. A fact that belongs to a place on it (the
start, a stop, the kilometre where the heart rate climbed) carries an anchor,
and the browser (``hero_component/``) lays the text out in the free space
around the track, as close to that place as it fits. Which facts fit is the
browser's call too -- it knows the screen -- so facts come with a priority and
a small screen simply shows the first few.

Pure pandas: the page gathers the tables, this module turns them into a
JSON-ready payload. Every sentence goes through ``i18n.tr``.
"""

from __future__ import annotations

import datetime as dt
import html
import math
from typing import Any

import pandas as pd

import i18n
from running import text as rtext, units, workouts
from sport import catalog

# Heart-rate zone edges as a share of HRmax (Z1 | Z2 | Z3 | Z4 | Z5): the
# colour of each stretch of the track.
ZONE_EDGES = (0.70, 0.80, 0.87, 0.93)
EARTH_KM = 40_075
EVEREST_M = 8_849
# A drift worth naming: the same pace (±3%) at least this many beats higher.
DRIFT_BPM = 6
# Stops shorter than this in total are not a fact, they are a pause for breath.
STOP_FACT_S = 10


# ------------------------------------------------------------------ formatting

def _dec(value: float, digits: int = 1) -> str:
    """A decimal in the interface language: ``10,25`` / ``10.25``."""
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if i18n.lang() == "pl" else text


def _int(value: float) -> str:
    """Thousands with a thin space (pl) or a comma (en): ``17 843`` / ``17,843``."""
    text = f"{int(round(value)):,}"
    return text.replace(",", " ") if i18n.lang() == "pl" else text


def _hm(hours: float) -> str:
    """Hours as ``5:28``."""
    minutes = int(round(hours * 60))
    return f"{minutes // 60}:{minutes % 60:02d}"


def _clock(hour: float) -> str:
    """A clock time from an hour that may run past midnight (26.6 -> ``2:36``)."""
    minutes = int(round(hour * 60)) % (24 * 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _span(minutes: float) -> str:
    """A duration in words: ``2 h 45 min`` / ``35 min``."""
    minutes = int(round(abs(minutes)))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} h {rest} min"
    return f"{hours} h" if hours else f"{rest} min"


def _pace(minutes: float) -> str:
    return units.fmt_pace(minutes, unit=False)


def _date(day: Any) -> str:
    day = pd.Timestamp(day)
    return f"{day.day}.{day.month:02d}"


def _weekday(day: Any) -> str:
    return i18n.weekdays(long=True)[pd.Timestamp(day).weekday()]


def _weekday_name(index: int) -> str:
    return i18n.weekdays(long=True)[index]


def _days(count: int) -> str:
    return f"{count} " + i18n.plural(count, pl=("dzień", "dni", "dni"), en=("day", "days"))


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _fact(key: str, group: str, head: str, body: str, priority: float, **extra: Any) -> dict[str, Any]:
    return {"key": key, "group": group, "head": head, "text": body, "priority": priority, **extra}


# ------------------------------------------------------------------ the run

def pick_run(runs: pd.DataFrame, today: dt.date) -> tuple[pd.Series | None, bool]:
    """The run the page is drawn around and whether it happened today.

    Today's latest run when there is one; otherwise the last run before today
    (the page then talks about the day ahead and shows that run faded).
    """
    if runs is None or runs.empty:
        return None, False
    frame = runs.copy()
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    frame = frame[frame["start_local"].dt.date <= today].sort_values("start_local")
    if frame.empty:
        return None, False
    row = frame.iloc[-1]
    return row, row["start_local"].date() == today


def zone_edges(hr_max: Any) -> list[int] | None:
    hr_max = _num(hr_max)
    return [int(round(hr_max * edge)) for edge in ZONE_EDGES] if hr_max else None


def track(route: pd.DataFrame, stops: pd.DataFrame) -> dict[str, Any]:
    """The run's points for the canvas: ``[lat, lon, hr, km]`` plus stop rings."""
    points: list[list[Any]] = []
    if route is not None and not route.empty:
        frame = route.dropna(subset=["lat", "lon"])
        if "seq" in frame.columns:
            frame = frame.sort_values("seq")
        for row in frame.itertuples(index=False):
            hr = _num(getattr(row, "hr", None))
            km = _num(getattr(row, "distance_km", None))
            points.append([round(float(row.lat), 6), round(float(row.lon), 6),
                           int(hr) if hr else None, round(km, 3) if km is not None else None])
        # A stream without distance still draws; anchors then fall back to the share of the points.
        if points and all(p[3] is None for p in points):
            for index, point in enumerate(points):
                point[3] = index
    rings = []
    if stops is not None and not stops.empty:
        for row in stops.dropna(subset=["lat", "lon"]).itertuples(index=False):
            rings.append([round(float(row.lat), 6), round(float(row.lon), 6), int(round(float(row.seconds)))])
    return {"pts": points, "stops": rings}


def _full_km(splits: pd.DataFrame) -> pd.DataFrame:
    if splits is None or splits.empty:
        return pd.DataFrame()
    frame = splits.sort_values("km")
    if "length_km" in frame.columns:
        frame = frame[frame["length_km"].fillna(1) >= 0.95]
    return frame.dropna(subset=["pace_min_km"])


def _go_run(run: pd.Series) -> dict[str, Any]:
    return {"page": "bieg", "activity": int(run["activity_id"])}


def run_summary(run: pd.Series, today_run: bool, today: dt.date) -> dict[str, Any]:
    tr = i18n.tr
    start = pd.Timestamp(run["start_local"])
    km, minutes = _num(run.get("distance_km")) or 0, _num(run.get("duration_min")) or 0
    hr, hr_max = _num(run.get("avg_hr")), _num(run.get("max_hr"))
    pace = _pace(run.get("pace_min_km"))
    kind = rtext.kind_label(run.get("kind")) if run.get("kind") else None
    heart = tr(pl=f", tętno średnio {hr:.0f}, maks. {hr_max:.0f}", en=f", heart rate {hr:.0f} on average, max {hr_max:.0f}") \
        if hr and hr_max else ""
    kind_text = tr(pl=f" W naszej klasyfikacji: {kind}.", en=f" Our classification: {kind}.") if kind else ""
    head = tr(pl=f"{_dec(km, 2)} km w {units.fmt_time(minutes * 60)}", en=f"{_dec(km, 2)} km in {units.fmt_time(minutes * 60)}")
    if today_run:
        body = tr(pl=f"Start {start:%H:%M}. Tempo {pace}/km{heart}.", en=f"Started {start:%H:%M}. Pace {pace}/km{heart}.")
        group = tr(pl="Dzisiejszy bieg", en="Today's run")
    else:
        ago = (today - start.date()).days
        body = tr(pl=f"{_weekday(start).capitalize()} {_date(start)}, {_days(ago)} temu. Tempo {pace}/km{heart}.",
                  en=f"{_weekday(start)} {_date(start)}, {_days(ago)} ago. Pace {pace}/km{heart}.")
        group = tr(pl="Ostatni bieg", en="Last run")
    return _fact("run", group, head, body + kind_text, 1, anchor={"km": 0}, big=True, go=_go_run(run))


def key_stretch(run: pd.Series, splits: pd.DataFrame, laps: pd.DataFrame) -> dict[str, Any] | None:
    """The stretch that tells the most: the reps of a workout, else a heart-rate drift."""
    tr = i18n.tr
    group = tr(pl="Najważniejszy fragment", en="The key stretch")
    reps = workouts.reps(laps) if laps is not None and not laps.empty else pd.DataFrame()
    if len(reps) >= 2:
        reps = reps.reset_index(drop=True)
        length = float(reps["km"].median())
        size = f"{_dec(length, 1).rstrip('0').rstrip(',.')} km" if length >= 1 else f"{length * 1000:.0f} m"
        paces = [_pace(p) for p in reps["pace"]]
        shown = " → ".join(paces) if len(paces) <= 4 else f"{min(paces)}–{max(paces)}"
        drift_s = (reps["pace"].iloc[-1] - reps["pace"].iloc[0]) * 60
        if drift_s > 2:
            trend = tr(pl=f"Ostatnie powtórzenie o {drift_s:.0f} s/km wolniejsze niż pierwsze.",
                       en=f"The last rep {drift_s:.0f} s/km slower than the first.")
        elif drift_s < -2:
            trend = tr(pl=f"Ostatnie powtórzenie o {-drift_s:.0f} s/km szybsze niż pierwsze.",
                       en=f"The last rep {-drift_s:.0f} s/km faster than the first.")
        else:
            trend = tr(pl="Wszystkie powtórzenia w tym samym tempie.", en="Every rep at the same pace.")
        last_hr = _num(reps["hr"].iloc[-1]) if "hr" in reps.columns else None
        heart = tr(pl=f" Tętno na ostatnim: {last_hr:.0f}.", en=f" Heart rate on the last one: {last_hr:.0f}.") \
            if last_hr else ""
        middle = reps.iloc[len(reps) // 2]
        return _fact("stretch", group, f"{len(reps)} × {size}: {shown}", trend + heart, 2,
                     anchor={"km": float(middle["at_km"]) + float(middle["km"]) / 2}, big=True, go=_go_run(run))
    full = _full_km(splits)
    if len(full) < 4 or full["hr"].isna().all():
        return None
    calm = full[full.get("stop_s", pd.Series(0, index=full.index)).fillna(0) <= 0].dropna(subset=["hr"])
    if len(calm) < 3:
        return None
    first = calm.iloc[0]
    same = calm[(calm["km"] > first["km"]) & ((calm["pace_min_km"] / first["pace_min_km"] - 1).abs() <= 0.03)]
    if same.empty:
        return None
    peak = same.loc[same["hr"].idxmax()]
    rise = float(peak["hr"] - first["hr"])
    if rise < DRIFT_BPM:
        return None
    return _fact("stretch", group,
                 tr(pl=f"+{rise:.0f} uderzeń przy tym samym tempie", en=f"+{rise:.0f} beats at the same pace"),
                 tr(pl=f"Na {first['km']:.0f}. km tętno {first['hr']:.0f}, na {peak['km']:.0f}. km {peak['hr']:.0f} — "
                       f"oba kilometry w ~{_pace((first['pace_min_km'] + peak['pace_min_km']) / 2)}.",
                    en=f"Heart rate {first['hr']:.0f} at km {first['km']:.0f}, {peak['hr']:.0f} at km {peak['km']:.0f} — "
                       f"both kilometres at ~{_pace((first['pace_min_km'] + peak['pace_min_km']) / 2)}."),
                 2, anchor={"km": float(peak["km"]) - 0.5}, big=True, go=_go_run(run))


def stops_fact(run: pd.Series, stops: pd.DataFrame, splits: pd.DataFrame) -> dict[str, Any] | None:
    tr = i18n.tr
    if stops is None or stops.empty or stops["seconds"].sum() < STOP_FACT_S:
        return None
    stops = stops.sort_values("km")
    total, count = float(stops["seconds"].sum()), len(stops)
    places = ", ".join(tr(pl=f"{_dec(r.km, 1)} km ({r.seconds:.0f} s)", en=f"km {_dec(r.km, 1)} ({r.seconds:.0f} s)")
                       for r in stops.head(3).itertuples())
    more = tr(pl=f" i {count - 3} więcej", en=f" and {count - 3} more") if count > 3 else ""
    body = tr(pl=f"Na {places}{more}.", en=f"At {places}{more}.")
    full = _full_km(splits)
    if not full.empty and "stop_s" in full.columns:
        slowest = full.loc[full["seconds"].idxmax()]
        if (_num(slowest.get("stop_s")) or 0) > 0:
            body += tr(pl=f" Przez nie {slowest['km']:.0f}. km wyszedł najwolniejszy: {_pace(slowest['pace_min_km'])}.",
                       en=f" They made km {slowest['km']:.0f} the slowest: {_pace(slowest['pace_min_km'])}.")
    longest = stops.loc[stops["seconds"].idxmax()]
    where = i18n.plural(count, pl=("postoju", "postojach", "postojach"), en=("stop", "stops"))
    head = tr(pl=f"{total:.0f} s stania na {count} {where}", en=f"{total:.0f} s standing at {count} {where}")
    anchor = {"lat": float(longest["lat"]), "lon": float(longest["lon"])} \
        if pd.notna(longest.get("lat")) and pd.notna(longest.get("lon")) else {"km": float(longest["km"])}
    return _fact("stops", tr(pl="Postoje", en="Stops"), head, body, 4, anchor=anchor, go=_go_run(run))


def fastest_km(run: pd.Series, splits: pd.DataFrame, efforts: pd.DataFrame) -> dict[str, Any] | None:
    tr = i18n.tr
    full = _full_km(splits)
    if len(full) < 2:
        return None
    best = full.loc[full["seconds"].idxmin()]
    hr = _num(best.get("hr"))
    body = tr(pl=f"Tętno {hr:.0f}.", en=f"Heart rate {hr:.0f}.") if hr else ""
    if efforts is not None and not efforts.empty:
        one = efforts[efforts["effort"] == "1k"]
        if not one.empty and float(one["pace_min_km"].iloc[0]) < float(best["pace_min_km"]) - 0.05:
            body += tr(pl=f" Najlepszy ciągły 1 km według Garmina: {_pace(one['pace_min_km'].iloc[0])}.",
                       en=f" Best continuous 1 km according to Garmin: {_pace(one['pace_min_km'].iloc[0])}.")
    return _fact("fastest", tr(pl="Najszybszy kilometr", en="Fastest kilometre"),
                 tr(pl=f"{best['km']:.0f}. km w {_pace(best['pace_min_km'])}", en=f"Km {best['km']:.0f} in {_pace(best['pace_min_km'])}"),
                 body.strip(), 6, anchor={"km": float(best["km"]) - 0.5}, go=_go_run(run))


def compared(run: pd.Series, runs: pd.DataFrame) -> dict[str, Any] | None:
    """Against the previous run of a similar distance (±15%)."""
    tr = i18n.tr
    km = _num(run.get("distance_km"))
    if not km or runs is None or runs.empty:
        return None
    before = runs[pd.to_datetime(runs["start_local"]) < pd.Timestamp(run["start_local"])]
    before = before[(before["distance_km"] / km - 1).abs() <= 0.15].sort_values("start_local")
    if before.empty:
        return None
    prev = before.iloc[-1]
    delta = (float(run["pace_min_km"]) - float(prev["pace_min_km"])) * 60
    when = f"{_date(prev['start_local'])}"
    if abs(delta) < 3:
        head = tr(pl=f"Tym samym tempem co {when}", en=f"The same pace as on {when}")
    elif delta > 0:
        head = tr(pl=f"O {units.fmt_time(delta)}/km wolniej niż {when}", en=f"{units.fmt_time(delta)}/km slower than on {when}")
    else:
        head = tr(pl=f"O {units.fmt_time(-delta)}/km szybciej niż {when}", en=f"{units.fmt_time(-delta)}/km faster than on {when}")
    body = tr(pl=f"Wtedy {_dec(prev['distance_km'], 1)} km w {_pace(prev['pace_min_km'])}/km",
              en=f"Then {_dec(prev['distance_km'], 1)} km at {_pace(prev['pace_min_km'])}/km")
    hr_now, hr_then = _num(run.get("avg_hr")), _num(prev.get("avg_hr"))
    if hr_now and hr_then:
        diff = hr_now - hr_then
        if abs(diff) < 2:
            body += tr(pl=f" na tym samym tętnie ({hr_then:.0f}).", en=f" at the same heart rate ({hr_then:.0f}).")
        else:
            word = tr(pl="niższe", en="lower") if diff < 0 else tr(pl="wyższe", en="higher")
            body += tr(pl=f" na tętnie {hr_then:.0f} — teraz {word} o {abs(diff):.0f}.",
                       en=f" at heart rate {hr_then:.0f} — now {abs(diff):.0f} {word}.")
    else:
        body += "."
    return _fact("compared", tr(pl="Na tle poprzedniego", en="Against the previous one"), head, body, 5, side="b",
                 go={"page": "bieg", "activity": int(prev["activity_id"])})


def since_last(run: pd.Series, activities: pd.DataFrame, today: dt.date) -> dict[str, Any] | None:
    """Days without running and what happened instead."""
    tr = i18n.tr
    gap = (today - pd.Timestamp(run["start_local"]).date()).days - 1
    if gap < 1:
        return None
    other = pd.DataFrame()
    if activities is not None and not activities.empty:
        frame = activities.copy()
        frame["start_local"] = pd.to_datetime(frame["start_local"])
        other = frame[(frame["start_local"] > pd.Timestamp(run["start_local"])) & (frame["sport"] != "running")]
    if other.empty:
        body = tr(pl="Bez żadnego innego treningu w tym czasie.", en="No other training in between.")
    else:
        bits = []
        for row in other.sort_values("start_local").head(4).itertuples():
            code = catalog.discipline_of(row.sport)
            name = catalog.label(code) if code else str(row.sport)
            km = _num(row.distance_km)
            bits.append(f"{name.lower()} {_dec(km, 1)} km" if km and km >= 0.5 else name.lower())
        body = tr(pl=f"W tym czasie: {', '.join(bits)}.", en=f"In between: {', '.join(bits)}.")
    return _fact("since", tr(pl="Przerwa", en="Break"),
                 tr(pl=f"{_days(gap)} bez biegu", en=f"{_days(gap)} without a run"), body, 2.5, side="t")


# ------------------------------------------------------------------ the plan and the race

def planned(session: dict[str, Any] | None, has_plan: bool) -> dict[str, Any] | None:
    tr = i18n.tr
    group = tr(pl="Dziś w planie", en="Today's plan")
    if session is None:
        if not has_plan:
            return None
        return _fact("plan", group, tr(pl="Dzień bez biegu", en="A day without running"),
                     tr(pl="Plan nie ma na dziś sesji.", en="The plan has no session today."), 1, side="t", big=True,
                     go={"page": "plan", "view": "plan"})
    title = str(session.get("title") or rtext.kind_label(session.get("type")))
    km = _num(session.get("distance_km"))
    head = f"{title}, {_dec(km, 1)} km" if km else title
    body = str(session.get("main") or session.get("purpose") or "")
    return _fact("plan", group, head, body, 1, side="t", big=True, go={"page": "plan", "view": "plan"})


def race_fact(races: list[dict[str, Any]], today: dt.date, run: pd.Series | None, today_run: bool) -> dict[str, Any] | None:
    tr = i18n.tr
    if not races:
        return None
    race = races[0]
    day = dt.date.fromisoformat(str(race["date"]))
    days = (day - today).days
    name = html.escape(str(race.get("name") or ""))
    head = tr(pl=f"Dziś start: {name}", en=f"Race day: {name}") if days == 0 else \
        tr(pl=f"Za {_days(days)}: {name}", en=f"In {_days(days)}: {name}")
    body = rtext.race_label(race.get("distance"))
    goal = _num(race.get("goal_s"))
    distance = {"5k": 5, "10k": 10, "hm": 21.0975, "m": 42.195}.get(str(race.get("distance")))
    if goal and distance:
        pace = goal / 60 / distance
        body += tr(pl=f", cel {units.fmt_time(goal)} — {_pace(pace)}/km", en=f", goal {units.fmt_time(goal)} — {_pace(pace)}/km")
        if today_run and run is not None and _num(run.get("pace_min_km")):
            delta = (float(run["pace_min_km"]) - pace) * 60
            if delta > 3:
                body += tr(pl=f", o {units.fmt_time(delta)}/km szybciej niż dziś",
                           en=f", {units.fmt_time(delta)}/km faster than today")
    return _fact("race", tr(pl="Najbliższy start", en="Next race"), head, body + ".", 3, side="t",
                 go={"page": "plan", "view": "races"})


# ------------------------------------------------------------------ the night and the body

def _night(daily: pd.DataFrame, today: dt.date) -> tuple[pd.Series | None, pd.DataFrame]:
    """Last night (the row of today, or of yesterday if today has not synced) and the 7 nights before it."""
    if daily is None or daily.empty:
        return None, pd.DataFrame()
    frame = daily.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame[frame["day"].dt.date <= today].dropna(subset=["sleep_h"]).sort_values("day")
    if frame.empty or (today - frame["day"].iloc[-1].date()).days > 1:
        return None, pd.DataFrame()
    return frame.iloc[-1], frame.iloc[-8:-1]


def night_facts(daily: pd.DataFrame, circadian: pd.DataFrame, today: dt.date) -> list[dict[str, Any]]:
    tr = i18n.tr
    night, week = _night(daily, today)
    if night is None or len(week) < 3:
        return []
    facts = []
    hours, usual = float(night["sleep_h"]), float(week["sleep_h"].mean())
    if hours <= week["sleep_h"].min():
        head = tr(pl=f"Sen {_hm(hours)} — najkrótszy w tygodniu", en=f"{_hm(hours)} of sleep — the shortest this week")
    elif hours >= week["sleep_h"].max():
        head = tr(pl=f"Sen {_hm(hours)} — najdłuższy w tygodniu", en=f"{_hm(hours)} of sleep — the longest this week")
    else:
        head = tr(pl=f"Sen {_hm(hours)}", en=f"{_hm(hours)} of sleep")
    body = tr(pl=f"{len(week)} poprzednich nocy: średnio {_hm(usual)}.", en=f"The {len(week)} nights before: {_hm(usual)} on average.")
    score, scores = _num(night.get("sleep_score")), week["sleep_score"].dropna() if "sleep_score" in week else pd.Series()
    if score and not scores.empty:
        body += tr(pl=f" Ocena snu {score:.0f}, w tygodniu średnio {scores.mean():.0f}.",
                   en=f" Sleep score {score:.0f}, {scores.mean():.0f} on average this week.")
    facts.append(_fact("sleep", tr(pl="Noc na tle tygodnia", en="The night against the week"), head, body, 3,
                       side="r", big=True, go={"page": "sen"}))

    if circadian is not None and not circadian.empty:
        rhythm = circadian.copy()
        rhythm["day"] = pd.to_datetime(rhythm["day"])
        rhythm = rhythm.sort_values("day")
        this = rhythm[rhythm["day"] == night["day"]]
        before = rhythm[(rhythm["day"] < night["day"]) & (rhythm["day"] >= night["day"] - pd.Timedelta(days=7))]
        if not this.empty and len(before) >= 3 and pd.notna(this["bed_hour_cont"].iloc[0]):
            bed, typical = float(this["bed_hour_cont"].iloc[0]), float(before["bed_hour_cont"].mean())
            wake = _num(this["wake_hour"].iloc[0])
            diff = (bed - typical) * 60
            if abs(diff) >= 20:
                word = tr(pl="później", en="later") if diff > 0 else tr(pl="wcześniej", en="earlier")
                body = tr(pl=f"W tym tygodniu zwykle około {_clock(typical)} — {_span(diff)} {word}.",
                          en=f"Usually around {_clock(typical)} this week — {_span(diff)} {word}.")
            else:
                body = tr(pl=f"Jak zwykle w tym tygodniu (około {_clock(typical)}).", en=f"As usual this week (around {_clock(typical)}).")
            if wake is not None:
                body += tr(pl=f" Pobudka {_clock(wake)}.", en=f" Woke up at {_clock(wake)}.")
            facts.append(_fact("bed", tr(pl="Pora snu", en="Bedtime"),
                               tr(pl=f"Zaśnięcie o {_clock(bed)}", en=f"Asleep at {_clock(bed)}"), body, 7, side="r",
                               go={"page": "sen"}))

    deep = _num(night.get("sleep_deep_h"))
    if deep is not None and "sleep_deep_h" in week and week["sleep_deep_h"].notna().sum() >= 3:
        typical = float(week["sleep_deep_h"].mean())
        ratio = deep / typical if typical else 1
        tail = tr(pl="jak zwykle", en="as usual") if 0.9 <= ratio <= 1.1 else \
            (tr(pl="więcej niż zwykle", en="more than usual") if ratio > 1 else tr(pl="mniej niż zwykle", en="less than usual"))
        body = tr(pl=f"Średnia tygodnia {_hm(typical)}.", en=f"Weekly average {_hm(typical)}.")
        rem = _num(night.get("sleep_rem_h"))
        if rem is not None and week["sleep_rem_h"].notna().sum() >= 3:
            body += tr(pl=f" REM {_hm(rem)} (zwykle {_hm(week['sleep_rem_h'].mean())}).",
                       en=f" REM {_hm(rem)} (usually {_hm(week['sleep_rem_h'].mean())}).")
        facts.append(_fact("deep", tr(pl="Fazy snu", en="Sleep stages"),
                           tr(pl=f"Sen głęboki {_hm(deep)} — {tail}", en=f"Deep sleep {_hm(deep)} — {tail}"), body, 10,
                           side="r", go={"page": "sen"}))
    return facts


def body_facts(daily: pd.DataFrame, today: dt.date) -> list[dict[str, Any]]:
    tr = i18n.tr
    night, week = _night(daily, today)
    if night is None:
        return []
    facts = []
    hrv = _num(night.get("hrv_last_night"))
    if hrv and "hrv_last_night" in week and week["hrv_last_night"].notna().sum() >= 3:
        typical = float(week["hrv_last_night"].mean())
        change = (hrv / typical - 1) * 100
        head = tr(pl=f"HRV {hrv:.0f} ms — {change:+.0f}% wobec tygodnia", en=f"HRV {hrv:.0f} ms — {change:+.0f}% against the week")
        body = tr(pl=f"Średnia {len(week)} poprzednich nocy: {typical:.0f} ms.", en=f"Average of the {len(week)} nights before: {typical:.0f} ms.")
        rhr = _num(night.get("rhr"))
        if rhr and week["rhr"].notna().sum() >= 3:
            body += tr(pl=f" Tętno spoczynkowe {rhr:.0f} (średnio {week['rhr'].mean():.0f}).",
                       en=f" Resting heart rate {rhr:.0f} ({week['rhr'].mean():.0f} on average).")
        facts.append(_fact("hrv", "HRV", head, body, 8, side="b", go={"page": "regeneracja"}))
    battery = _num(night.get("bb_wake"))
    if battery is not None:
        previous = week.iloc[-1] if not week.empty else None
        before = _num(previous.get("bb_wake")) if previous is not None else None
        head = tr(pl=f"Body Battery rano {battery:.0f}", en=f"Body Battery {battery:.0f} on waking")
        body = tr(pl=f"Dzień wcześniej {before:.0f}.", en=f"{before:.0f} the day before.") if before is not None else ""
        ready, ready_before = _num(night.get("readiness")), _num(previous.get("readiness")) if previous is not None else None
        if ready is not None:
            body += tr(pl=f" Readiness {ready:.0f}", en=f" Readiness {ready:.0f}") + (
                tr(pl=f" (dzień wcześniej {ready_before:.0f}).", en=f" ({ready_before:.0f} the day before).")
                if ready_before is not None else ".")
        facts.append(_fact("battery", tr(pl="Ciało rano", en="The body this morning"), head, body.strip(), 9, side="b",
                           go={"page": "regeneracja"}))
    return facts


# ------------------------------------------------------------------ trivia

def trivia(runs: pd.DataFrame, activities: pd.DataFrame, daily: pd.DataFrame, today: dt.date) -> list[dict[str, Any]]:
    """Small true things about the whole history; the page shows one and rotates on click."""
    tr = i18n.tr
    group = tr(pl="Ciekawostka", en="Did you know")
    items: list[dict[str, Any]] = []
    if runs is not None and not runs.empty:
        frame = runs.copy()
        frame["start_local"] = pd.to_datetime(frame["start_local"])
        frame = frame[frame["start_local"].dt.date <= today]
        count, km = len(frame), float(frame["distance_km"].sum())
        if count:
            longest = frame.loc[frame["distance_km"].idxmax()]
            items.append(_fact("total", group,
                               f"{count} {i18n.plural(count, pl=('bieg', 'biegi', 'biegów'), en=('run', 'runs'))}, {_int(km)} km",
                               tr(pl=f"To {_dec(km / EARTH_KM * 100, 1)}% obwodu Ziemi. Najdłuższy: {_dec(longest['distance_km'], 1)} km, "
                                     f"{_date(longest['start_local'])}.{longest['start_local'].year}.",
                                  en=f"That is {_dec(km / EARTH_KM * 100, 1)}% of the Earth's circumference. The longest: "
                                     f"{_dec(longest['distance_km'], 1)} km, {_date(longest['start_local'])}.{longest['start_local'].year}."),
                               11, side="b", go={"page": "atlas"}))
            days = frame["start_local"].dt.weekday.value_counts()
            top = int(days.index[0])
            if count >= 10 and days.iloc[0] / count >= 0.22:
                low = int(days.index[-1]) if len(days) == 7 else next(d for d in range(7) if d not in days.index)
                low_n = int(days.get(low, 0))
                items.append(_fact("weekday", group,
                                   tr(pl=f"{_weekday_name(top).capitalize()} to Twój dzień", en=f"{_weekday_name(top)} is your day"),
                                   tr(pl=f"{int(days.iloc[0])} z {count} biegów wypadło {i18n.on_weekday(top)}; {i18n.on_weekday(low)} — {low_n}.",
                                      en=f"{int(days.iloc[0])} of {count} runs fell {i18n.on_weekday(top)}; {i18n.on_weekday(low)} — {low_n}."),
                                   11, side="b", go={"page": "bieganie"}))
            climb = float(frame["elevation_gain_m"].fillna(0).sum()) if "elevation_gain_m" in frame else 0
            if climb >= 500:
                items.append(_fact("climb", group, tr(pl=f"{_int(climb)} m w górę", en=f"{_int(climb)} m of climbing"),
                                   tr(pl=f"Suma przewyższeń wszystkich biegów to {_dec(climb / EVEREST_M, 1)} × Mount Everest.",
                                      en=f"All runs together climbed {_dec(climb / EVEREST_M, 1)} × Mount Everest.")
                                   if climb >= EVEREST_M else
                                   tr(pl=f"Suma przewyższeń wszystkich biegów to {climb / EVEREST_M * 100:.0f}% wysokości Mount Everestu.",
                                      en=f"All runs together climbed {climb / EVEREST_M * 100:.0f}% of Mount Everest's height."),
                                   11, side="b", go={"page": "atlas"}))
    if daily is not None and not daily.empty and "steps" in daily:
        frame = daily.copy()
        frame["day"] = pd.to_datetime(frame["day"])
        row = frame[frame["day"].dt.date == today]
        steps = _num(row["steps"].iloc[0]) if not row.empty else None
        if steps and steps >= 3000:
            higher = frame[(frame["day"].dt.date < today) & (frame["steps"] > steps)]
            when = tr(pl=f"Najwięcej od {_date(higher['day'].max())}.", en=f"The most since {_date(higher['day'].max())}.") \
                if not higher.empty else tr(pl="Najwięcej w całej historii.", en="The most in the whole history.")
            items.append(_fact("steps", group, tr(pl=f"{_int(steps)} kroków dziś", en=f"{_int(steps)} steps today"),
                               tr(pl="Do tej pory. ", en="So far. ") + when, 11, side="b", go={"page": "regeneracja"}))
    if activities is not None and not activities.empty:
        frame = activities.copy()
        frame["start_local"] = pd.to_datetime(frame["start_local"])
        month = frame[(frame["start_local"].dt.year == today.year) & (frame["start_local"].dt.month == today.month)]
        if today.day <= 3:  # the month barely started: talk about the previous one
            first = dt.date(today.year, today.month, 1) - dt.timedelta(days=1)
            month = frame[(frame["start_local"].dt.year == first.year) & (frame["start_local"].dt.month == first.month)]
            name = i18n.month_name(first.month - 1)
        else:
            name = i18n.month_name(today.month - 1)
        if len(month) >= 3:
            runs_in = month[month["sport"] == "running"]
            items.append(_fact("month", group,
                               f"{name.capitalize()}: {len(month)} "
                               f"{i18n.plural(len(month), pl=('trening', 'treningi', 'treningów'), en=('session', 'sessions'))}",
                               tr(pl=f"W tym {len(runs_in)} biegów, {_dec(runs_in['distance_km'].sum(), 0)} km.",
                                  en=f"{len(runs_in)} of them runs, {_dec(runs_in['distance_km'].sum(), 0)} km."),
                               11, side="b", go={"page": "atlas"}))
    return items


# ------------------------------------------------------------------ the page

def build(today: dt.date, *, runs: pd.DataFrame, activities: pd.DataFrame, daily: pd.DataFrame,
          splits: pd.DataFrame, stops: pd.DataFrame, efforts: pd.DataFrame, laps: pd.DataFrame,
          circadian: pd.DataFrame, route: pd.DataFrame, races: list[dict[str, Any]],
          session: dict[str, Any] | None, has_plan: bool) -> dict[str, Any]:
    """Everything the hero component draws, for one day.

    ``splits``/``stops``/``efforts``/``laps``/``route`` are already narrowed to
    the run :func:`pick_run` chose; ``session`` is today's plan session, if any.
    """
    tr = i18n.tr
    run, today_run = pick_run(runs, today)
    facts: list[dict[str, Any]] = []
    payload: dict[str, Any] = {"state": "done" if today_run else ("planned" if session else "rest")}
    if run is not None:
        facts += [run_summary(run, today_run, today), key_stretch(run, splits, laps), stops_fact(run, stops, splits),
                  fastest_km(run, splits, efforts), compared(run, runs)]
        if not today_run:
            facts.append(since_last(run, activities, today))
        payload["run"] = {**track(route, stops), "dim": not today_run, "zones": zone_edges(run.get("hr_max_used"))}
    if not today_run:
        facts.append(planned(session, has_plan))
    facts.append(race_fact(races, today, run, today_run))
    facts += night_facts(daily, circadian, today) + body_facts(daily, today)
    facts = sorted((f for f in facts if f), key=lambda f: f["priority"])

    night, week = _night(daily, today)
    suffix = ""
    if night is not None and len(week) >= 3:
        hours = float(night["sleep_h"])
        if hours <= week["sleep_h"].min():
            suffix = tr(pl=" — po najkrótszej nocy tygodnia", en=" — after the shortest night of the week")
        elif hours >= week["sleep_h"].max():
            suffix = tr(pl=" — po najdłuższej nocy tygodnia", en=" — after the longest night of the week")
        else:
            suffix = tr(pl=f" — po {_hm(hours)} snu", en=f" — after {_hm(hours)} of sleep")
    if today_run:
        headline = tr(pl=f"Dziś <em>{_dec(run['distance_km'], 2)} km</em> w {_pace(run['pace_min_km'])}/km{suffix}.",
                      en=f"Today <em>{_dec(run['distance_km'], 2)} km</em> at {_pace(run['pace_min_km'])}/km{suffix}.")
        state = tr(pl="po biegu", en="after the run")
        meta = tr(pl=f"<b>dziś, {pd.Timestamp(run['start_local']):%H:%M}</b>", en=f"<b>today, {pd.Timestamp(run['start_local']):%H:%M}</b>")
    else:
        if session is not None:
            title = html.escape(str(session.get("title") or rtext.kind_label(session.get("type"))))
            headline = tr(pl=f"Dziś w planie <em>{title}</em>{suffix}.", en=f"Planned today: <em>{title}</em>{suffix}.")
            state = tr(pl="przed biegiem", en="before the run")
        elif run is not None:
            when = pd.Timestamp(run["start_local"])
            headline = tr(pl=f"Ostatni bieg: <em>{_weekday(when)}, {_dec(run['distance_km'], 1)} km</em>{suffix}.",
                          en=f"Last run: <em>{_weekday(when)}, {_dec(run['distance_km'], 1)} km</em>{suffix}.")
            state = ""
        else:
            headline = tr(pl=f"Dzień w faktach{suffix}.", en=f"The day in facts{suffix}.")
            state = ""
        meta = ""
        if run is not None:
            when = pd.Timestamp(run["start_local"])
            meta = tr(pl=f"na mapie ostatni bieg: <b>{_weekday(when)} {_date(when)}</b>",
                      en=f"on the map, the last run: <b>{_weekday(when)} {_date(when)}</b>")
    date = f"{_weekday(today)}, {today.day} {i18n.month_name(today.month - 1, genitive=True)} {today.year}"
    payload.update({
        "date": date + (f" · {state}" if state else ""),
        "headline": headline,
        "meta": meta,
        "facts": facts,
        "trivia": trivia(runs, activities, daily, today),
    })
    return payload
