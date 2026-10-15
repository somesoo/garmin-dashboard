"""Training-plan generator, plan-vs-actual matching and re-planning.

Principles the generator follows (and the page states):

* **Start from what was actually run.** The first week is anchored on the mean
  of the last four weeks, not on the volume the goal "needs".
* **Volume grows by absolute steps toward a distance-specific peak**, and
  every week is also capped at 1.3x the mean of the four weeks before it,
  real or planned -- the acute:chronic guard (the upper edge of Gabbett's
  0.8-1.3 band). A runner coming off a break
  therefore climbs slower than one already near the peak, and no week
  jumps because a percentage compounds.
* **Every third or fourth week is lighter** (every third when the recent
  record is irregular, i.e. tolerance is unproven), and the taper scales with
  the distance (1 / 1 / 2 / 3 weeks).
* **Hard days never touch.** Long run on the chosen day; quality sessions on
  the days furthest from it and from each other. When the available days make
  that impossible, the plan schedules fewer quality sessions, not adjacent
  ones.
* **Paces come from current fitness** (VDOT now), not from the goal. The
  goal pace appears only in race-specific segments, and only when the goal is
  within reach of the forecast. Re-planning recalculates paces from the latest
  data, which is how the plan follows real progress.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from running import physio, store, units
from running.sessions import HARD_KINDS

PEAK_KM = {"5k": 32.0, "10k": 42.0, "hm": 50.0, "m": 65.0}
LONG_TARGET_KM = {"5k": 10.0, "10k": 14.0, "hm": 19.0, "m": 32.0}
# Weeks of reduced volume *including* the race week: a marathon gets two
# taper weeks plus race week, a 5 / 10 km only a lighter race week.
TAPER_WEEKS = {"5k": 1, "10k": 1, "hm": 2, "m": 3}
GUARD = 1.3
GUARD_WEEKS = 4
MAX_STEP_KM = 6.0
LONG_STEP_KM = {"5k": 1.0, "10k": 1.5, "hm": 1.5, "m": 2.0}
WEEKDAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
TYPE_LABELS = {
    "rest": "odpoczynek",
    "recovery": "regeneracyjny",
    "easy": "spokojny",
    "long": "długie wybieganie",
    "tempo": "tempo",
    "threshold": "próg",
    "intervals": "interwały",
    "race": "start",
}
HARD_TYPES = ("tempo", "threshold", "intervals", "race", "long")
PHASE_LABELS = {"base": "baza", "build": "budowa", "peak": "specyfika", "taper": "taper", "race": "start"}


@dataclass
class PlanRequest:
    distance: str
    race_date: dt.date
    goal_s: float | None = None
    run_days: list[int] = field(default_factory=lambda: [1, 3, 5, 6])  # Mon=0
    long_day: int = 6
    start: dt.date | None = None
    max_weekly_km: float | None = None
    race_id: str | None = None
    name: str | None = None

    def validate(self) -> list[str]:
        errors = []
        if self.distance not in units.RACES:
            errors.append("Nieznany dystans.")
        days = sorted(set(self.run_days))
        if not 2 <= len(days) <= 7:
            errors.append("Wybierz od 2 do 7 dni biegowych w tygodniu.")
        if any(d < 0 or d > 6 for d in days):
            errors.append("Dni tygodnia to 0–6.")
        start = self.start or dt.date.today()
        if self.race_date <= start:
            errors.append("Data zawodów musi być w przyszłości.")
        if self.goal_s is not None and self.goal_s <= 0:
            errors.append("Cel czasowy musi być dodatni.")
        return errors


# --------------------------------------------------------------------------
# baseline from the data


def baseline(runs: pd.DataFrame, anchor: pd.Timestamp, vdot: float | None) -> dict[str, Any]:
    """What the runner has actually been doing, measured at ``anchor``."""
    weeks = []
    for index in range(8):
        end = anchor - pd.Timedelta(days=7 * index)
        mask = (runs["day"] <= end) & (runs["day"] > end - pd.Timedelta(days=7)) if not runs.empty else []
        frame = runs[mask] if len(runs) else runs
        weeks.append(
            {
                "km": float(frame["distance_km"].sum()) if len(frame) else 0.0,
                "runs": int(len(frame)),
                "hard": int(frame["kind"].isin(HARD_KINDS).sum()) if len(frame) and "kind" in frame else 0,
            }
        )
    recent = runs[(runs["day"] <= anchor) & (runs["day"] > anchor - pd.Timedelta(days=42))] if len(runs) else runs
    last4 = weeks[:4]
    return {
        "anchor": str(pd.Timestamp(anchor).date()),
        "weekly_km_4w": round(sum(w["km"] for w in last4) / 4, 1),
        "weekly_km_8w": round(sum(w["km"] for w in weeks) / 8, 1),
        "weekly_km_last": round(weeks[0]["km"], 1),
        "max_week_km_8w": round(max(w["km"] for w in weeks), 1),
        "runs_per_week_4w": round(sum(w["runs"] for w in last4) / 4, 1),
        "hard_per_week_4w": round(sum(w["hard"] for w in last4) / 4, 1),
        "long_km_6w": round(float(recent["distance_km"].max()), 1) if len(recent) else 0.0,
        "consistency_8w": round(sum(w["runs"] >= 2 for w in weeks) / 8, 2),
        "vdot": None if vdot is None else round(float(vdot), 1),
        "history_km": [round(w["km"], 1) for w in reversed(weeks)],
    }


# --------------------------------------------------------------------------
# week skeleton


def _weeks(request: PlanRequest, start: dt.date) -> list[dict[str, Any]]:
    """Monday-based weeks from the start week to the race week, with phases."""
    first_monday = start - dt.timedelta(days=start.weekday())
    race_monday = request.race_date - dt.timedelta(days=request.race_date.weekday())
    count = (race_monday - first_monday).days // 7 + 1
    taper = min(TAPER_WEEKS[request.distance], max(0, count - 1))
    out = []
    for index in range(count):
        from_end = count - 1 - index
        if from_end == 0:
            phase = "race"
        elif from_end < taper:
            phase = "taper"
        else:
            build_total = count - 1 - taper
            position = index / max(1, build_total)
            phase = "base" if build_total >= 8 and position < 0.34 else ("peak" if position >= 0.67 else "build")
        out.append({"week": index + 1, "monday": first_monday + dt.timedelta(days=7 * index), "phase": phase})
    return out


def _volumes(weeks: list[dict[str, Any]], base: dict[str, Any], request: PlanRequest) -> None:
    """Fill ``volume_km`` / ``long_km`` / ``recovery`` per week, in place."""
    days = len(set(request.run_days))
    start_km = max(base["weekly_km_4w"], 0.8 * base["weekly_km_8w"], 3.0 * days)
    peak_cap = PEAK_KM[request.distance] * (0.8 if days <= 3 else 1.0)
    if request.max_weekly_km:
        peak_cap = min(peak_cap, float(request.max_weekly_km))
    peak = max(start_km, peak_cap)
    cycle = 3 if base["consistency_8w"] < 0.5 else 4

    build = [w for w in weeks if w["phase"] in ("base", "build", "peak")]
    steps = max(1, sum(1 for i, _ in enumerate(build) if (i + 1) % cycle != 0))
    step = min(MAX_STEP_KM, max(0.0, (peak - start_km) / steps))

    history = list(base["history_km"][-GUARD_WEEKS:])
    long_now = max(base["long_km_6w"], 5.0)
    long_target = LONG_TARGET_KM[request.distance]
    long_share = 0.5 if days <= 3 else 0.42 if request.distance != "m" else 0.5
    last_build = start_km
    last_long = long_now
    for index, week in enumerate(weeks):
        chronic = history[-GUARD_WEEKS:]
        guard = GUARD * (sum(chronic) / len(chronic)) if chronic else start_km
        if week["phase"] in ("base", "build", "peak"):
            position = build.index(week)
            recovery = (position + 1) % cycle == 0 and position != len(build) - 1
            if recovery:
                volume = 0.75 * last_build
                long_km = 0.75 * last_long
            else:
                volume = min(last_build + step if position else start_km, peak, max(guard, start_km))
                long_km = min(last_long + (LONG_STEP_KM[request.distance] if position else 0), long_target)
                last_build = volume
                last_long = long_km
            week["recovery"] = recovery
        elif week["phase"] == "taper":
            to_race = len(weeks) - 1 - index
            factor = {1: 0.7, 2: 0.82, 3: 0.9}.get(to_race, 0.85)
            volume, long_km = last_build * factor, last_long * (factor - 0.1)
            week["recovery"] = False
        else:  # race week: volume before the race, the race itself is extra
            volume, long_km = last_build * 0.45, 0.0
            week["recovery"] = False
        long_km = min(long_km, volume * long_share) if long_km else 0.0
        week["volume_km"] = round(volume, 1)
        week["long_km"] = round(long_km, 1)
        history.append(volume)


# --------------------------------------------------------------------------
# days and sessions


def _circular_gap(a: int, b: int) -> int:
    diff = abs(a - b) % 7
    return min(diff, 7 - diff)


def place_hard_days(run_days: list[int], long_day: int, count: int) -> list[int]:
    """Quality days as far as possible from the long run and each other.

    Requires at least one non-hard day between hard days (gap >= 2, counted
    across the week boundary too). Returns fewer days than asked rather than
    break that rule.
    """
    hard = [long_day]
    chosen: list[int] = []
    candidates = [d for d in sorted(set(run_days)) if d != long_day]
    for _ in range(count):
        scored = [(min(_circular_gap(c, h) for h in hard), -c, c) for c in candidates if c not in chosen]
        scored = [s for s in scored if s[0] >= 2]
        if not scored:
            break
        best = max(scored)[2]
        chosen.append(best)
        hard.append(best)
    return sorted(chosen)


QUALITY_BY_PHASE = {
    "5k": {"base": ["tempo"], "build": ["intervals", "threshold"], "peak": ["intervals", "threshold"]},
    "10k": {"base": ["tempo"], "build": ["threshold", "intervals"], "peak": ["threshold", "intervals"]},
    "hm": {"base": ["tempo"], "build": ["threshold", "intervals"], "peak": ["threshold", "tempo"]},
    "m": {"base": ["tempo"], "build": ["threshold", "tempo"], "peak": ["tempo", "threshold"]},
}


def _pace_text(band: tuple[float, float] | None) -> str:
    if not band:
        return "—"
    return f"{units.fmt_pace(band[0], False)}–{units.fmt_pace(band[1])}"


def _session(
    kind: str,
    date: dt.date,
    week: dict[str, Any],
    km: float,
    paces: dict[str, tuple[float, float]],
    hr_max: float | None,
    distance: str,
    race_pace: float | None,
) -> dict[str, Any]:
    """One session with warm-up / main / cool-down, pace band, HR band and purpose."""
    easy = paces.get("E")
    hr_easy = physio.hr_band(hr_max, *physio.HR_FRACTIONS["E"])
    session: dict[str, Any] = {
        "id": store.new_id("s"),
        "date": date.isoformat(),
        "week": week["week"],
        "phase": week["phase"],
        "type": kind,
        "status": "planned",
        "actual_activity_id": None,
        "note": "",
    }
    km = round(max(0.0, km), 1)
    if kind in ("easy", "recovery"):
        band = (easy[0], easy[1]) if kind == "easy" else (easy[1], easy[1] * 1.06) if easy else None
        session.update(
            title=f"{TYPE_LABELS[kind].capitalize()} {km:.0f} km",
            distance_km=km,
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=hr_easy if kind == "easy" else physio.hr_band(hr_max, 0.6, 0.72),
            warmup="—",
            main=f"{km:.1f} km ciągle w tempie {_pace_text(band)}" + (
                ", na końcu 6×20 s przebieżek" if kind == "easy" and week["phase"] in ("build", "peak") else ""),
            cooldown="—",
            purpose=(
                "Objętość tlenowa: buduje sieć naczyń włosowatych i ekonomię bez kosztu regeneracji. "
                "Za szybko = zmęczenie bez dodatkowego bodźca."
                if kind == "easy"
                else "Ruch dla krążenia między mocnymi dniami; cel to świeżość na następną jakość."
            ),
        )
    elif kind == "long":
        segment = ""
        if race_pace and week["phase"] == "peak" and distance in ("hm", "m"):
            part = min(round(km * (0.35 if distance == "m" else 0.3)), 14 if distance == "m" else 8)
            segment = f"; ostatnie {part} km w tempie startowym {units.fmt_pace(race_pace)}"
        session.update(
            title=f"Długie wybieganie {km:.0f} km",
            distance_km=km,
            pace_lo=easy[0] if easy else None,
            pace_hi=easy[1] if easy else None,
            hr=hr_easy,
            warmup="pierwsze 2 km wolniej",
            main=f"{km:.1f} km w tempie {_pace_text(easy)}{segment}",
            cooldown="ostatni km trucht",
            purpose=(
                "Wytrzymałość specyficzna: glikogen, mięśnie i ścięgna przyzwyczajone do czasu na nogach. "
                + ("Odcinek w tempie startowym uczy utrzymać je na zmęczeniu." if segment else
                   "Tempo spokojne — liczy się czas, nie prędkość.")
            ),
        )
    elif kind == "threshold":
        band = paces.get("T")
        # Daniels: threshold work up to ~10% of the week's volume per session.
        work = max(3.0, min(10.0, 0.12 * week["volume_km"]))
        rep = 2.0 if work >= 6 else 1.0 if work < 4 else 1.6
        reps = max(2, round(work / rep))
        work = reps * rep
        session.update(
            title=f"Próg {reps}×{rep:g} km",
            distance_km=round(work + 3.5 + 0.2 * (reps - 1), 1),
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=physio.hr_band(hr_max, *physio.HR_FRACTIONS["T"]),
            warmup="2 km spokojnie + 4 przebieżki",
            main=f"{reps}×{rep:g} km w tempie {_pace_text(band)}, przerwa 1 min truchtu",
            cooldown="1,5 km spokojnie",
            purpose=(
                "Próg mleczanowy: najszybsze tempo, które utrzymasz ok. godziny. Podnosi tempo "
                "dla 10 km i półmaratonu; 'komfortowo ciężko', nie na maksa."
            ),
        )
    elif kind == "intervals":
        band = paces.get("I")
        rep = {"5k": 0.8, "10k": 1.0, "hm": 1.0, "m": 1.0}[distance]
        # Daniels: interval work up to ~8% of the week's volume (and <= 8 km).
        reps = max(3, min(8, round(max(3.0, min(8.0, 0.08 * week["volume_km"])) / rep)))
        session.update(
            title=f"Interwały {reps}×{rep * 1000:.0f} m",
            distance_km=round(reps * rep * 1.5 + 3.5, 1),
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=physio.hr_band(hr_max, *physio.HR_FRACTIONS["I"]),
            warmup="2 km spokojnie + 4–6 przebieżek",
            main=f"{reps}×{rep * 1000:.0f} m w tempie {_pace_text(band)}, przerwa trucht równy czasowi odcinka",
            cooldown="1,5 km spokojnie",
            purpose=(
                "VO₂max: kilka minut łącznie blisko maksymalnego poboru tlenu. Największy bodziec "
                "dla 5 i 10 km; tempo równe na wszystkich powtórzeniach ważniejsze niż szybkie pierwsze."
            ),
        )
    elif kind == "tempo":
        band = paces.get("M") if distance in ("m", "hm") or week["phase"] == "base" else paces.get("T")
        if race_pace and week["phase"] == "peak" and distance in ("hm", "m"):
            band = (race_pace * 0.99, race_pace * 1.01)
        work = max(3.0, min(14.0 if distance == "m" else 8.0, 0.2 * week["volume_km"]))
        session.update(
            title=f"Tempo {work:.0f} km",
            distance_km=round(work + 3.5, 1),
            pace_lo=band[0] if band else None,
            pace_hi=band[1] if band else None,
            hr=physio.hr_band(hr_max, *physio.HR_FRACTIONS["M"]),
            warmup="2 km spokojnie",
            main=f"{work:.0f} km ciągle w tempie {_pace_text(band)}",
            cooldown="1,5 km spokojnie",
            purpose=(
                "Wytrzymałość tempowa: długi, równy wysiłek poniżej progu. W fazie specyfiki — "
                "w tempie startowym, żeby je zautomatyzować."
                if distance in ("hm", "m")
                else "Wprowadzenie do pracy tempowej: równy, kontrolowany wysiłek przed cięższymi sesjami."
            ),
        )
    elif kind == "race":
        session.update(
            title="Start",
            distance_km=units.RACES[distance],
            pace_lo=race_pace * 0.99 if race_pace else None,
            pace_hi=race_pace * 1.01 if race_pace else None,
            hr="—",
            warmup="10–15 min truchtu + 3 przebieżki" if distance in ("5k", "10k") else "5–10 min truchtu",
            main=f"{units.RACE_LABELS[distance]} — pierwszy kilometr nie szybciej niż planowane tempo",
            cooldown="trucht i marsz",
            purpose="Dzień, do którego prowadzi plan.",
        )
    session["duration_min"] = (
        round(session["distance_km"] * ((session.get("pace_lo") or 6.5) + (session.get("pace_hi") or 6.5)) / 2)
        if session.get("distance_km")
        else None
    )
    return session


def generate(
    request: PlanRequest,
    runs: pd.DataFrame,
    result: dict[str, Any],
    *,
    anchor: pd.Timestamp | None = None,
    keep: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a plan dict (store.validate_plan-compatible) from data and request.

    ``result`` is a ``forecast.forecast`` output; ``keep`` holds sessions that
    already happened (re-planning keeps them unchanged).
    """
    errors = request.validate()
    if errors:
        raise ValueError(" ".join(errors))
    if result.get("status") != "ok":
        raise ValueError("Brak prognozy formy — plan potrzebuje co najmniej jednego mierzalnego biegu. "
                         + str(result.get("reason", "")))
    anchor = anchor if anchor is not None else (runs["day"].max() if not runs.empty else pd.Timestamp.today())
    start = request.start or (dt.date.today() + dt.timedelta(days=1))
    vdot = float(result["vdot"])
    hr_max = result.get("hr_max")
    paces = physio.training_paces(vdot)
    base = baseline(runs, pd.Timestamp(anchor), vdot)
    item = result["distances"].get(request.distance)
    warnings: list[str] = []

    race_pace = None
    if request.goal_s and item is not None:
        reach = item.low_s * 0.98
        if request.goal_s >= reach:
            race_pace = units.pace_from(request.goal_s, units.RACES[request.distance])
        else:
            warnings.append(
                f"Cel {units.fmt_time(request.goal_s)} jest szybszy niż optymistyczny kraniec dzisiejszej "
                f"prognozy ({units.fmt_time(item.low_s)}). Odcinki startowe w planie idą w tempie "
                "prognozy; przebuduj plan po kolejnym teście."
            )
    if race_pace is None and item is not None:
        race_pace = units.pace_from(item.realistic_s, units.RACES[request.distance])

    weeks = _weeks(request, start)
    if len(weeks) < 3:
        warnings.append("Mniej niż 3 tygodnie do startu: to nie budowa formy, tylko utrzymanie i świeżość.")
    _volumes(weeks, base, request)
    # Long runs are capped by time on feet, not only by distance: past ~2.5 h
    # (2:45 for the marathon) the run costs more recovery than it builds.
    if "E" in paces:
        limit = (165 if request.distance == "m" else 150) / (sum(paces["E"]) / 2)
        for week in weeks:
            week["long_km"] = round(min(week["long_km"], limit), 1)
    if base["weekly_km_4w"] < 5:
        warnings.append("W ostatnich 4 tygodniach prawie nie było biegania — plan startuje od minimum "
                        "i rośnie ostrożnie. Pierwsze 2 tygodnie traktuj jako sprawdzian tolerancji.")

    run_days = sorted(set(request.run_days))
    long_day = request.long_day if request.long_day in run_days else run_days[-1]
    sessions: list[dict[str, Any]] = []
    kept_dates = {s["date"] for s in keep or []}
    for week in weeks:
        phase = week["phase"]
        quality_wanted = 0 if phase == "race" else 1 if (len(run_days) <= 3 or week.get("recovery") or phase == "taper") else 2
        types = QUALITY_BY_PHASE[request.distance].get(phase if phase in ("base", "build", "peak") else "peak")
        if phase == "taper":
            types = ["intervals" if request.distance in ("5k", "10k") else "threshold"]
        quality_days = place_hard_days(run_days, long_day, quality_wanted)
        week_sessions: list[tuple[int, str]] = []
        for day in run_days:
            date = week["monday"] + dt.timedelta(days=day)
            if date < start or date > request.race_date or date.isoformat() in kept_dates:
                continue
            if date == request.race_date:
                week_sessions.append((day, "race"))
            elif phase == "race" and (request.race_date - date).days <= 1:
                continue  # rest the day before the race
            elif day == long_day and week["long_km"] > 0:
                week_sessions.append((day, "long"))
            elif day in quality_days:
                week_sessions.append((day, types[quality_days.index(day) % len(types)]))
            else:
                week_sessions.append((day, "easy"))
        if request.race_date >= week["monday"] and request.race_date < week["monday"] + dt.timedelta(days=7) \
                and request.race_date.weekday() not in run_days and request.race_date >= start:
            week_sessions.append((request.race_date.weekday(), "race"))

        built = []
        for day, kind in week_sessions:
            date = week["monday"] + dt.timedelta(days=day)
            km = week["long_km"] if kind == "long" else 0.0
            built.append(_session(kind, date, week, km if kind == "long" else 6.0, paces, hr_max,
                                  request.distance, race_pace))
        # A low-volume week cannot carry two quality sessions plus a long run:
        # drop quality (the later one first) rather than overshoot the volume.
        def fixed_km() -> float:
            return sum(s["distance_km"] for s in built if s["type"] not in ("easy", "race"))

        quality = [s for s in built if s["type"] in ("tempo", "threshold", "intervals")]
        easy_count = sum(1 for s in built if s["type"] == "easy")
        # One quality session stays when the record shows it is tolerated.
        keep_one = 1 if (base["hard_per_week_4w"] >= 0.75 or week["volume_km"] >= 15) else 0
        while len(quality) > keep_one and fixed_km() + 3.0 * easy_count > week["volume_km"] * 1.1:
            dropped = quality.pop()
            dropped.update(_session("easy", dt.date.fromisoformat(dropped["date"]), week, 3.0, paces,
                                    hr_max, request.distance, race_pace))
            easy_count += 1
        # Easy days absorb what is left of the weekly volume.
        fixed = fixed_km()
        easy = [s for s in built if s["type"] == "easy"]
        if easy:
            share = max(0.0, week["volume_km"] - fixed) / len(easy)
            cap = max(4.0, min(12.0, 0.8 * week["long_km"] if week["long_km"] else 10.0))
            share = min(max(share, 3.0), cap)
            # The day after a long run or hard session is the recovery run.
            hard_dates = {s["date"] for s in built if s["type"] in HARD_TYPES}
            for s in easy:
                previous = (dt.date.fromisoformat(s["date"]) - dt.timedelta(days=1)).isoformat()
                kind = "recovery" if previous in hard_dates and len(run_days) >= 4 else "easy"
                replacement = _session(kind, dt.date.fromisoformat(s["date"]), week,
                                       share * (0.75 if kind == "recovery" else 1.0), paces, hr_max,
                                       request.distance, race_pace)
                s.clear()
                s.update(replacement)
        week["planned_km"] = round(sum(s["distance_km"] for s in built if s["type"] != "race"), 1)
        sessions.extend(built)

    sessions = sorted((keep or []) + sessions, key=lambda s: s["date"])
    plan = {
        "id": store.new_id("plan"),
        "name": request.name or f"{units.RACE_LABELS[request.distance]} — {request.race_date.isoformat()}",
        "race_id": request.race_id,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "request": {
            **{k: v for k, v in asdict(request).items() if k not in ("race_date", "start")},
            "race_date": request.race_date.isoformat(),
            "start": start.isoformat(),
        },
        "baseline": base,
        "forecast": {
            "vdot": round(vdot, 1),
            "realistic_s": round(item.realistic_s) if item else None,
            "low_s": round(item.low_s) if item else None,
            "high_s": round(item.high_s) if item else None,
            "confidence": item.confidence if item else None,
        },
        "paces": {name: [round(a, 3), round(b, 3)] for name, (a, b) in paces.items()},
        "weeks": [
            {**{k: v for k, v in w.items() if k != "monday"}, "monday": w["monday"].isoformat()} for w in weeks
        ],
        "sessions": sessions,
        "warnings": warnings,
    }
    return plan


def reached_prep(plan: dict[str, Any], distance: str) -> float:
    """Preparation score the plan reaches at its peak (for the target forecast)."""
    from running.forecast import REQUIREMENTS

    need = REQUIREMENTS[distance]
    weeks = [w for w in plan.get("weeks", []) if w.get("phase") in ("build", "peak", "base")]
    if not weeks:
        return 0.0
    peak_volume = max(w.get("planned_km", w.get("volume_km", 0)) for w in weeks)
    peak_long = max(w.get("long_km", 0) for w in weeks)
    return round(0.4 * min(1, peak_long / need["long_km"]) + 0.4 * min(1, peak_volume / need["weekly_km"]) + 0.2, 3)


# --------------------------------------------------------------------------
# plan vs actual


COMPATIBLE = {
    "easy": {"easy", "recovery", "long"},
    "recovery": {"recovery", "easy"},
    "long": {"long", "easy"},
    "tempo": {"tempo", "threshold"},
    "threshold": {"threshold", "tempo", "intervals"},
    "intervals": {"intervals", "threshold"},
    "race": {"race", "threshold", "tempo"},
}


def match(plan: dict[str, Any], runs: pd.DataFrame, today: dt.date | None = None) -> pd.DataFrame:
    """Each planned session next to the run that fulfilled it (if any).

    A run matches a session on the same date first, then one day either side
    (a session moved by a day is still the same session). A stored status set
    by hand wins over the automatic one.
    """
    today = today or dt.date.today()
    rows = []
    used: set[int] = set()
    sessions = [s for s in plan.get("sessions", []) if s.get("type") != "rest"]
    by_day = {}
    if runs is not None and not runs.empty:
        for run in runs.itertuples(index=False):
            by_day.setdefault(run.day.date(), []).append(run)
    pending = []
    for session in sessions:
        date = dt.date.fromisoformat(session["date"])
        chosen = None
        if session.get("actual_activity_id"):
            for runs_on_day in by_day.values():
                for run in runs_on_day:
                    if int(run.activity_id) == int(session["actual_activity_id"]):
                        chosen = run
        if chosen is None:
            same = [r for r in by_day.get(date, []) if int(r.activity_id) not in used]
            if same:
                chosen = min(same, key=lambda r: abs(r.distance_km - (session.get("distance_km") or 0)))
        if chosen is not None:
            used.add(int(chosen.activity_id))
        pending.append((session, date, chosen))
    for session, date, chosen in pending:
        if chosen is None:
            for offset in (-1, 1):
                near = [r for r in by_day.get(date + dt.timedelta(days=offset), []) if int(r.activity_id) not in used]
                if near:
                    chosen = near[0]
                    used.add(int(chosen.activity_id))
                    break
        rows.append(_compare(session, date, chosen, today))
    return pd.DataFrame(rows)


def _compare(session: dict[str, Any], date: dt.date, run: Any, today: dt.date) -> dict[str, Any]:
    planned_km = session.get("distance_km") or 0
    stored = session.get("status", "planned")
    out = {
        "id": session["id"],
        "date": date,
        "week": session.get("week"),
        "type": session.get("type"),
        "title": session.get("title"),
        "planned_km": planned_km,
        "pace_lo": session.get("pace_lo"),
        "pace_hi": session.get("pace_hi"),
        "activity_id": None,
        "actual_km": None,
        "actual_pace": None,
        "actual_kind": None,
        "distance_ratio": None,
        "type_ok": None,
        "status": stored,
        "auto": None,
        "note": session.get("note", ""),
    }
    if run is not None:
        ratio = (run.distance_km / planned_km) if planned_km else None
        kind = getattr(run, "kind", None)
        type_ok = kind in COMPATIBLE.get(session.get("type"), {kind})
        auto = "done" if type_ok and (ratio is None or 0.8 <= ratio <= 1.25) else "modified"
        out.update(
            activity_id=int(run.activity_id),
            actual_km=round(float(run.distance_km), 2),
            actual_pace=float(run.pace_min_km),
            actual_kind=kind,
            distance_ratio=None if ratio is None else round(ratio, 2),
            type_ok=bool(type_ok),
            auto=auto,
        )
    elif date < today:
        out["auto"] = "missed"
    out["effective"] = stored if stored != "planned" else (out["auto"] or "planned")
    return out


def compliance(matched: pd.DataFrame) -> dict[str, Any]:
    """Summary of the plan so far: done / modified / skipped and km ratio."""
    if matched is None or matched.empty:
        return {"due": 0}
    due = matched[matched["date"] < dt.date.today() + dt.timedelta(days=1)]
    if due.empty:
        return {"due": 0}
    counts = due["effective"].value_counts()
    planned_km = float(due["planned_km"].sum())
    actual_km = float(due["actual_km"].fillna(0).sum())
    hard = due[due["type"].isin(("tempo", "threshold", "intervals"))]
    return {
        "due": int(len(due)),
        "done": int(counts.get("done", 0)),
        "modified": int(counts.get("modified", 0)),
        "skipped": int(counts.get("skipped", 0) + counts.get("missed", 0)),
        "planned_km": round(planned_km, 1),
        "actual_km": round(actual_km, 1),
        "km_ratio": round(actual_km / planned_km, 2) if planned_km else None,
        "quality_done": int(hard["effective"].isin(("done", "modified")).sum()),
        "quality_due": int(len(hard)),
    }


# --------------------------------------------------------------------------
# changing a plan


def replan(
    plan: dict[str, Any],
    runs: pd.DataFrame,
    result: dict[str, Any],
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Rebuild everything from ``today`` on with fresh data; the past stays as it was."""
    today = today or dt.date.today()
    request_data = dict(plan["request"])
    request = PlanRequest(
        distance=request_data["distance"],
        race_date=dt.date.fromisoformat(request_data["race_date"]),
        goal_s=request_data.get("goal_s"),
        run_days=list(request_data.get("run_days") or [1, 3, 5, 6]),
        long_day=int(request_data.get("long_day", 6)),
        start=today,
        max_weekly_km=request_data.get("max_weekly_km"),
        race_id=plan.get("race_id"),
        name=plan.get("name"),
    )
    keep = [s for s in plan.get("sessions", []) if s["date"] < today.isoformat()]
    fresh = generate(request, runs, result, keep=keep)
    fresh["id"] = plan["id"]
    fresh["created"] = plan.get("created", fresh["created"])
    fresh["request"]["start"] = plan["request"].get("start", fresh["request"]["start"])
    fresh["history"] = list(plan.get("history", [])) + [
        {"at": dt.datetime.now().isoformat(timespec="seconds"), "action": "replan",
         "vdot": fresh["forecast"]["vdot"]}
    ]
    return fresh


ADJUSTMENTS = {
    "fatigue": "zmęczenie — 7 dni bez jakości, objętość −20%",
    "sick": "choroba — 4 dni wolne, potem tydzień spokojnie",
    "busy": "mniej czasu — tydzień skrócony o 30%, jakość zostaje",
}


def adjust(plan: dict[str, Any], reason: str, today: dt.date | None = None) -> dict[str, Any]:
    """Local change after a change in condition; the rest of the plan is untouched."""
    if reason not in ADJUSTMENTS:
        raise ValueError(f"Nieznany powód: {reason}")
    today = today or dt.date.today()
    horizon = today + dt.timedelta(days=11 if reason == "sick" else 7)
    plan = dict(plan)
    paces = {k: tuple(v) for k, v in (plan.get("paces") or {}).items()}
    easy = paces.get("E")
    changed = []
    for session in plan.get("sessions", []):
        date = dt.date.fromisoformat(session["date"])
        if not today <= date < horizon or session.get("status") != "planned" or session["type"] == "race":
            continue
        if reason == "sick" and date < today + dt.timedelta(days=4):
            session.update(type="rest", title="Odpoczynek (choroba)", distance_km=0.0, duration_min=0,
                           main="bez biegania", purpose="Przy infekcji bieganie wydłuża chorobę i nie buduje formy.")
        elif reason in ("sick", "fatigue"):
            factor = 0.8
            km = round((session.get("distance_km") or 0) * factor, 1)
            if session["type"] in ("tempo", "threshold", "intervals"):
                km = round(min(km, 6.0), 1)
            if session["type"] != "long":
                session.update(type="easy", title=f"Spokojny {km:.0f} km (korekta)",
                               pace_lo=easy[0] if easy else None, pace_hi=easy[1] if easy else None,
                               main=f"{km:.1f} km spokojnie", warmup="—", cooldown="—")
            session["distance_km"] = km
            session["purpose"] = "Korekta planu: najpierw regeneracja, jakość wraca, gdy wróci świeżość."
        else:  # busy
            session["distance_km"] = round((session.get("distance_km") or 0) * 0.7, 1)
        session["note"] = (session.get("note") or "") + f" [{ADJUSTMENTS[reason]}]"
        changed.append(session["id"])
    plan["history"] = list(plan.get("history", [])) + [
        {"at": dt.datetime.now().isoformat(timespec="seconds"), "action": reason, "sessions": len(changed)}
    ]
    return plan


def set_status(plan: dict[str, Any], session_id: str, status: str, note: str | None = None,
               activity_id: int | None = None) -> dict[str, Any]:
    if status not in store.STATUSES:
        raise ValueError(f"Status spoza {store.STATUSES}")
    for session in plan.get("sessions", []):
        if session["id"] == session_id:
            session["status"] = status
            if note is not None:
                session["note"] = note
            if activity_id is not None:
                session["actual_activity_id"] = int(activity_id)
    return plan


def week_table(plan: dict[str, Any]) -> pd.DataFrame:
    """Per plan week: phase, planned km, long run, quality count."""
    weeks = pd.DataFrame(plan.get("weeks", []))
    if weeks.empty:
        return weeks
    sessions = pd.DataFrame(plan.get("sessions", []))
    if not sessions.empty:
        quality = sessions[sessions["type"].isin(("tempo", "threshold", "intervals"))].groupby("week").size()
        weeks["quality"] = weeks["week"].map(quality).fillna(0).astype(int)
    weeks["phase_label"] = weeks["phase"].map(PHASE_LABELS)
    return weeks
