"""Words for what the running module stores as codes, in the interface language.

Anything that outlives one page render -- a plan file, a warehouse table --
stores *what* happened, not a sentence about it: a session keeps
``text: {"key": "threshold", "reps": 4, "rep": 1.6}``, a run keeps
``kind_reason`` as a small JSON code, a best effort keeps ``source = "stream"``.
This module turns those codes into sentences when they are shown, so the same
plan reads in Polish or English and an old file never freezes a language.

Plans written before the codes existed carry Polish sentences; ``migrate_plan``
reads them back into codes (``store`` calls it on load and rewrites the file).
A session whose text is not one of the generated shapes -- written by hand or
by the assistant -- is kept as ``{"key": "custom", "pl": {...}, "en": {...}}``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import i18n
from running import units

PROSE = ("title", "warmup", "main", "cooldown", "purpose")


# --------------------------------------------------------------------------
# labels for stored codes


def kind_label(kind: Any) -> str:
    """Session type (``sessions.KINDS`` codes)."""
    tr = i18n.tr
    return {
        "rest": tr(pl="odpoczynek", en="rest"),
        "recovery": tr(pl="regeneracyjny", en="recovery"),
        "easy": tr(pl="spokojny", en="easy"),
        "long": tr(pl="długie wybieganie", en="long run"),
        "tempo": "tempo",
        "threshold": tr(pl="próg", en="threshold"),
        "intervals": tr(pl="interwały", en="intervals"),
        "race": tr(pl="start / próba", en="race / test"),
    }.get(str(kind), str(kind))


def race_label(key: Any) -> str:
    tr = i18n.tr
    return {"5k": "5 km", "10k": "10 km", "hm": tr(pl="półmaraton", en="half marathon"),
            "m": tr(pl="maraton", en="marathon")}.get(str(key), str(key))


def effort_label(key: Any) -> str:
    """Best-effort distance (``sessions.EFFORT_LABELS`` keys)."""
    key = str(key)
    if key in ("5k", "10k", "hm", "m"):
        return race_label(key)
    names = {"block": i18n.tr(pl="blok workoutu", en="workout block"), "mile": i18n.tr(pl="1 mila", en="1 mile"),
             "1k": "1 km", "3k": "3 km", "400m": "400 m", "800m": "800 m"}
    return names.get(key, key)


# Confidence codes stored by sessions.py and forecast.py (Polish, as data).
HIGH, MEDIUM, LOW = "wysoka", "średnia", "niska"  # i18n: key
CONFIDENCE_ICON = {HIGH: "●●●", MEDIUM: "●●○", LOW: "●○○"}


def confidence_label(code: Any) -> str:
    tr = i18n.tr
    return {HIGH: tr(pl="wysoka", en="high"), MEDIUM: tr(pl="średnia", en="medium"),
            LOW: tr(pl="niska", en="low")}.get(str(code), str(code))


def confidence(code: Any) -> str:
    """``high ●●●``: the label with its dots."""
    return f"{confidence_label(code)} {CONFIDENCE_ICON.get(str(code), '')}".strip()


def action_label(code: str) -> str:
    """The decision ``coach.next_session`` names with a Polish code."""
    tr = i18n.tr
    return {
        "jak w planie": tr(pl="jak w planie", en="as planned"),
        "jak w planie, z kontrolą": tr(pl="jak w planie, z kontrolą", en="as planned, with a check"),  # i18n: key
        "zamień na spokojny": tr(pl="zamień na spokojny", en="swap for an easy run"),  # i18n: key
        "przesuń": tr(pl="przesuń", en="postpone"),  # i18n: key
        "propozycja": tr(pl="propozycja", en="suggestion"),
        "decyzja rano": tr(pl="decyzja rano", en="decide in the morning"),
    }.get(code, code)


def source(code: Any) -> str:
    """Where a best effort came from (``run_efforts.source``)."""
    tr = i18n.tr
    return {
        "garmin": tr(pl="Garmin (najszybszy odcinek)", en="Garmin (fastest stretch)"),
        "whole": tr(pl="cały bieg", en="the whole run"),
        "stream": tr(pl="odcinek ze strumienia próbek", en="a stretch of the sample stream"),
        "block": tr(pl="blok workoutu z zegarka", en="a watch workout block"),
    }.get(str(code), str(code))


def goal_status(code: Any) -> str:
    """``forecast.goal_status``: how far the goal is."""
    tr = i18n.tr
    return {"none": tr(pl="bez celu czasowego", en="no time goal"),
            "now": tr(pl="w zasięgu już dziś", en="within reach today"),
            "plan": tr(pl="realny po planie", en="realistic after the plan"),
            "steady": tr(pl="realny przy obecnym treningu", en="realistic with your current training"),
            "ambitious": tr(pl="ambitny", en="ambitious"),
            "stretch": tr(pl="bardzo ambitny", en="very ambitious")}.get(str(code), str(code))


def phase_label(code: Any) -> str:
    """A plan week's phase."""
    tr = i18n.tr
    return {"base": tr(pl="baza", en="base"), "build": tr(pl="budowa", en="build"),
            "peak": tr(pl="specyfika", en="specific"), "taper": "taper",
            "race": tr(pl="start", en="race")}.get(str(code), str(code))


def adjustment_label(code: Any) -> str:
    """``plan.ADJUSTMENTS``: what each correction does."""
    tr = i18n.tr
    return {"fatigue": tr(pl="zmęczenie — 7 dni bez jakości, objętość −20%",
                          en="fatigue — 7 days without quality, volume −20%"),
            "sick": tr(pl="choroba — 4 dni wolne, potem tydzień spokojnie",
                       en="illness — 4 days off, then an easy week"),
            "busy": tr(pl="mniej czasu — tydzień skrócony o 30%, jakość zostaje",
                       en="less time — the week cut by 30%, quality stays")}.get(str(code), str(code))


def history_action(code: Any) -> str:
    """An entry of ``plan["history"]``."""
    tr = i18n.tr
    return {
        "replan": tr(pl="przebudowa", en="rebuild"), "soften": tr(pl="zmiękczenie", en="softened"),
        "postpone": tr(pl="przesunięcie", en="moved"), "fatigue": tr(pl="zmęczenie", en="fatigue"),
        "sick": tr(pl="choroba", en="illness"), "busy": tr(pl="mniej czasu", en="less time"),
        "assistant": tr(pl="asystent", en="assistant"),
    }.get(str(code), str(code))


# --------------------------------------------------------------------------
# why a run got its label (sessions.classify)


def reason(value: Any) -> str:
    """``kind_reason`` as a sentence; a value that is not a code is shown as is."""
    try:
        code = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return str(value)
    if not isinstance(code, dict) or "key" not in code:
        return "" if value is None else str(value)
    tr = i18n.tr
    get = code.get
    hr = f"{get('hr', 0):.0%}"
    pace = units.fmt_pace(get("pace")) if get("pace") is not None else "—"
    block = f"{get('km', 0):.1f} km" if get("km") is not None else ""
    name = get("name", "")
    texts = {
        "manual": lambda: tr(pl="oznaczone ręcznie na stronie Zawody", en="marked by hand on the Races page"),
        "name_race": lambda: tr(pl=f"nazwa „{name}” wskazuje na start lub test",
                                en=f"the name “{name}” points to a race or a test"),
        "watch_reps": lambda: tr(pl=f"workout z zegarka: {get('reps')} powtórzeń z przerwami",
                                 en=f"a watch workout: {get('reps')} reps with recoveries"),
        "block_threshold": lambda: tr(pl=f"blok {block} w {pace} — w tempie progowym lub szybciej",
                                      en=f"a {block} block at {pace} — at threshold pace or faster"),
        "block_tempo": lambda: tr(pl=f"blok {block} w {pace} — między tempem maratońskim a progiem",
                                  en=f"a {block} block at {pace} — between marathon pace and threshold"),
        "block_faster": lambda: tr(pl=f"blok {block} w {pace} — wyraźnie szybciej niż zwykle",
                                   en=f"a {block} block at {pace} — clearly faster than usual"),
        "name_reps": lambda: tr(pl=f"nazwa „{name}” opisuje powtórzenia", en=f"the name “{name}” describes reps"),
        "variability": lambda: tr(pl=f"zmienność prędkości {get('cv', 0):.0%} i TE beztlenowy {get('te', 0):.1f}",
                                  en=f"speed variability {get('cv', 0):.0%} and anaerobic TE {get('te', 0):.1f}"),
        "hr_continuous": lambda: tr(pl=f"ciągły wysiłek na {hr} HRmax przez {get('min', 0):.0f} min",
                                    en=f"a continuous effort at {hr} HRmax for {get('min', 0):.0f} min"),
        "hr_above_easy": lambda: tr(pl=f"średnie tętno {hr} HRmax — powyżej strefy spokojnej",
                                    en=f"average HR {hr} HRmax — above the easy zone"),
        "easy_hot": lambda: tr(pl=f"tempo spokojne ({pace}), ale tętno {hr} HRmax — upał, zmęczenie albo teren",
                               en=f"easy pace ({pace}) but HR {hr} HRmax — heat, fatigue or terrain"),
        "long_hr": lambda: tr(pl=f"{get('km', 0):.1f} km, wyraźnie dłużej niż zwykle ({get('ref', 0):.1f} km)",
                              en=f"{get('km', 0):.1f} km, clearly longer than usual ({get('ref', 0):.1f} km)"),
        "recovery": lambda: tr(pl=f"krótko i lekko: {hr} HRmax", en=f"short and light: {hr} HRmax"),
        "easy_hr": lambda: tr(pl=f"średnie tętno {hr} HRmax — strefa spokojna", en=f"average HR {hr} HRmax — the "
                                                                                     "easy zone"),
        "long_nohr": lambda: tr(pl=f"{get('km', 0):.1f} km — dłużej niż zwykle (brak tętna)",
                                en=f"{get('km', 0):.1f} km — longer than usual (no heart rate)"),
        "tempo_nohr": lambda: tr(pl="wyraźnie szybciej niż zwykle (brak tętna)",
                                 en="clearly faster than usual (no heart rate)"),
        "easy_nohr": lambda: tr(pl="brak tętna i struktury — przyjęto bieg spokojny",
                                en="no heart rate and no structure — taken as an easy run"),
    }
    render = texts.get(code["key"])
    return render() if render else str(value)


def reason_code(key: str, **params: Any) -> str:
    """What ``sessions.classify`` stores in ``kind_reason``."""
    clean = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in params.items() if v is not None}
    return json.dumps({"key": key, **clean}, ensure_ascii=False)


# --------------------------------------------------------------------------
# plan sessions


def _band(session: dict[str, Any]) -> str:
    lo, hi = session.get("pace_lo"), session.get("pace_hi")
    if not lo or not hi:
        return "—"
    return f"{units.fmt_pace(lo, False)}–{units.fmt_pace(hi)}"


def _km(value: Any) -> str:
    return f"{float(value or 0):.0f}"


def _title(spec: dict[str, Any], km: float) -> str:
    tr = i18n.tr
    key = spec.get("key")
    km = spec.get("km", km)
    if key == "easy":
        return tr(pl=f"Spokojny {_km(km)} km", en=f"Easy {_km(km)} km")
    if key == "recovery":
        return tr(pl=f"Regeneracyjny {_km(km)} km", en=f"Recovery {_km(km)} km")
    if key == "long":
        return tr(pl=f"Długie wybieganie {_km(km)} km", en=f"Long run {_km(km)} km")
    if key == "threshold":
        return tr(pl=f"Próg {spec['reps']}×{spec['rep']:g} km", en=f"Threshold {spec['reps']}×{spec['rep']:g} km")
    if key == "intervals":
        return tr(pl=f"Interwały {spec['reps']}×{spec['rep'] * 1000:.0f} m",
                  en=f"Intervals {spec['reps']}×{spec['rep'] * 1000:.0f} m")
    if key == "tempo":
        return f"Tempo {spec['work']:.0f} km"
    if key == "race":
        return tr(pl="Start", en="Race")
    if key == "sick":
        return tr(pl="Odpoczynek (choroba)", en="Rest (illness)")
    if key == "adjusted":
        return tr(pl=f"Spokojny {_km(km)} km (korekta)", en=f"Easy {_km(km)} km (adjusted)")
    if key == "softened":
        before = _title(spec.get("before") or {}, spec.get("before_km") or km)
        return tr(pl=f"Spokojny {_km(km)} km (zamiast: {before})", en=f"Easy {_km(km)} km (instead of: {before})")
    return "—"


def session_text(session: dict[str, Any]) -> dict[str, str]:
    """Title, warm-up, main set, cool-down and purpose of one plan session."""
    spec = session.get("text") or {}
    key = spec.get("key")
    if key == "custom":
        side = spec.get(i18n.lang()) or spec.get("pl") or {}
        return {field: str(side.get(field, "—")) for field in PROSE}
    tr = i18n.tr
    km = float(session.get("distance_km") or 0)
    band = _band(session)
    out = {"title": _title(spec, km), "warmup": "—", "cooldown": "—"}
    if key in ("easy", "recovery"):
        strides = tr(pl=", na końcu 6×20 s przebieżek", en=", 6×20 s strides at the end") if spec.get("strides") else ""
        out["main"] = tr(pl=f"{km:.1f} km ciągle w tempie {band}{strides}",
                         en=f"{km:.1f} km continuous at {band}{strides}")
        out["purpose"] = (tr(pl="Objętość tlenowa: buduje sieć naczyń włosowatych i ekonomię bez kosztu regeneracji. "
                                "Za szybko = zmęczenie bez dodatkowego bodźca.",
                             en="Aerobic volume: builds the capillary network and economy without a recovery cost. "
                                "Too fast = fatigue with no extra stimulus.")
                          if key == "easy" else
                          tr(pl="Ruch dla krążenia między mocnymi dniami; cel to świeżość na następną jakość.",
                             en="Movement for circulation between hard days; the aim is freshness for the next "
                                "quality session."))
    elif key == "long":
        part = spec.get("part")
        segment = ""
        if part:
            race_pace = units.fmt_pace(spec.get("race_pace"))
            segment = tr(pl=f"; ostatnie {part:.0f} km w tempie startowym {race_pace}",
                         en=f"; the last {part:.0f} km at race pace {race_pace}")
        out.update(
            warmup=tr(pl="pierwsze 2 km wolniej", en="the first 2 km slower"),
            main=tr(pl=f"{km:.1f} km w tempie {band}{segment}", en=f"{km:.1f} km at {band}{segment}"),
            cooldown=tr(pl="ostatni km trucht", en="the last km a jog"),
            purpose=tr(pl="Wytrzymałość specyficzna: glikogen, mięśnie i ścięgna przyzwyczajone do czasu na nogach. ",
                       en="Specific endurance: glycogen, muscles and tendons used to time on feet. ")
            + (tr(pl="Odcinek w tempie startowym uczy utrzymać je na zmęczeniu.",
                  en="The race-pace stretch teaches you to hold it when tired.") if part else
               tr(pl="Tempo spokojne — liczy się czas, nie prędkość.", en="An easy pace — time counts, not speed.")),
        )
    elif key == "threshold":
        out.update(
            warmup=tr(pl="2 km spokojnie + 4 przebieżki", en="2 km easy + 4 strides"),
            main=tr(pl=f"{spec['reps']}×{spec['rep']:g} km w tempie {band}, przerwa 1 min truchtu",
                    en=f"{spec['reps']}×{spec['rep']:g} km at {band}, 1 min jog recovery"),
            cooldown=tr(pl="1,5 km spokojnie", en="1.5 km easy"),
            purpose=tr(pl="Próg mleczanowy: najszybsze tempo, które utrzymasz ok. godziny. Podnosi tempo dla 10 km i "
                          "półmaratonu; 'komfortowo ciężko', nie na maksa.",
                       en="Lactate threshold: the fastest pace you can hold for about an hour. It lifts your 10 km "
                          "and half-marathon pace; 'comfortably hard', not all out."),
        )
    elif key == "intervals":
        metres = f"{spec['rep'] * 1000:.0f}"
        out.update(
            warmup=tr(pl="2 km spokojnie + 4–6 przebieżek", en="2 km easy + 4–6 strides"),
            main=tr(pl=f"{spec['reps']}×{metres} m w tempie {band}, przerwa trucht równy czasowi odcinka",
                    en=f"{spec['reps']}×{metres} m at {band}, jog recovery as long as the rep"),
            cooldown=tr(pl="1,5 km spokojnie", en="1.5 km easy"),
            purpose=tr(pl="VO₂max: kilka minut łącznie blisko maksymalnego poboru tlenu. Największy bodziec dla 5 i "
                          "10 km; tempo równe na wszystkich powtórzeniach ważniejsze niż szybkie pierwsze.",
                       en="VO₂max: several minutes in total close to maximal oxygen uptake. The biggest stimulus "
                          "for 5 and 10 km; an even pace across all reps matters more than fast first ones."),
        )
    elif key == "tempo":
        out.update(
            warmup=tr(pl="2 km spokojnie", en="2 km easy"),
            main=tr(pl=f"{spec['work']:.0f} km ciągle w tempie {band}", en=f"{spec['work']:.0f} km continuous at {band}"),
            cooldown=tr(pl="1,5 km spokojnie", en="1.5 km easy"),
            purpose=(tr(pl="Wytrzymałość tempowa: długi, równy wysiłek poniżej progu. W fazie specyfiki — w tempie "
                           "startowym, żeby je zautomatyzować.",
                        en="Tempo endurance: a long, even effort below threshold. In the specific phase — at race "
                           "pace, to make it automatic.")
                     if spec.get("distance") in ("hm", "m") else
                     tr(pl="Wprowadzenie do pracy tempowej: równy, kontrolowany wysiłek przed cięższymi sesjami.",
                        en="An introduction to tempo work: an even, controlled effort before harder sessions.")),
        )
    elif key == "race":
        short = spec.get("distance") in ("5k", "10k")
        out.update(
            warmup=tr(pl="10–15 min truchtu + 3 przebieżki", en="10–15 min jog + 3 strides") if short
            else tr(pl="5–10 min truchtu", en="5–10 min jog"),
            main=tr(pl=f"{race_label(spec.get('distance'))} — pierwszy kilometr nie szybciej niż planowane tempo",
                    en=f"{race_label(spec.get('distance'))} — the first kilometre no faster than the planned pace"),
            cooldown=tr(pl="trucht i marsz", en="jog and walk"),
            purpose=tr(pl="Dzień, do którego prowadzi plan.", en="The day the plan leads to."),
        )
    elif key == "sick":
        out.update(main=tr(pl="bez biegania", en="no running"),
                   purpose=tr(pl="Przy infekcji bieganie wydłuża chorobę i nie buduje formy.",
                              en="With an infection running prolongs the illness and builds no form."))
    elif key == "adjusted":
        out.update(main=tr(pl=f"{km:.1f} km spokojnie", en=f"{km:.1f} km easy"),
                   purpose=tr(pl="Korekta planu: najpierw regeneracja, jakość wraca, gdy wróci świeżość.",
                              en="A plan adjustment: recovery first, quality returns once freshness does."))
    elif key == "softened":
        out.update(main=tr(pl=f"{km:.1f} km spokojnie", en=f"{km:.1f} km easy"),
                   purpose=tr(pl="Regeneracja nie pozwalała na jakość; spokojny bieg utrzymuje objętość bez długu "
                                 "zmęczenia.",
                              en="Recovery did not allow quality; an easy run keeps the volume without a fatigue "
                                 "debt."))
    else:
        out.update(main="—", purpose="—")
    return out


def fill(plan: dict[str, Any]) -> dict[str, Any]:
    """Sessions with their prose in the current language (in place, returned)."""
    for session in plan.get("sessions", []):
        session.update(session_text(session))
    return plan


def strip(plan: dict[str, Any]) -> dict[str, Any]:
    """A copy without the generated prose: what goes into the file."""
    out = dict(plan)
    sessions = []
    for session in plan.get("sessions", []):
        session = dict(session)
        if (session.get("text") or {}).get("key") != "custom":
            for field in PROSE:
                session.pop(field, None)
        sessions.append(session)
    out["sessions"] = sessions
    return out


def warning(item: Any) -> str:
    """One entry of ``plan["warnings"]``."""
    if isinstance(item, str):
        return item
    tr = i18n.tr
    key = item.get("key")
    if key == "goal_too_fast":
        goal, low = units.fmt_time(item.get("goal_s")), units.fmt_time(item.get("low_s"))
        return tr(pl=f"Cel {goal} jest szybszy niż optymistyczny kraniec dzisiejszej prognozy ({low}). Odcinki "
                     "startowe w planie idą w tempie prognozy; przebuduj plan po kolejnym teście.",
                  en=f"The goal {goal} is faster than the optimistic end of today's forecast ({low}). Race-pace "
                     "stretches in the plan follow the forecast pace; rebuild the plan after the next test.")
    if key == "short":
        return tr(pl="Mniej niż 3 tygodnie do startu: to nie budowa formy, tylko utrzymanie i świeżość.",
                  en="Less than 3 weeks to the race: this is not building form, only keeping it and freshness.")
    if key == "no_running":
        return tr(pl="W ostatnich 4 tygodniach prawie nie było biegania — plan startuje od minimum i rośnie "
                     "ostrożnie. Pierwsze 2 tygodnie traktuj jako sprawdzian tolerancji.",
                  en="There was almost no running in the last 4 weeks — the plan starts from the minimum and grows "
                     "carefully. Treat the first 2 weeks as a tolerance test.")
    if key == "custom":
        return str(item.get(i18n.lang()) or item.get("pl") or "")
    return str(item)


def warnings(plan: dict[str, Any]) -> list[str]:
    return [warning(item) for item in plan.get("warnings", [])]


# --------------------------------------------------------------------------
# reading old plans (Polish sentences) back into codes


def _work_steps(session: dict[str, Any]) -> tuple[int | None, float | None]:
    """Reps and rep length (km) from a session's steps."""
    for step in session.get("steps") or []:
        if step.get("kind") == "repeat":
            work = next((s for s in step["steps"] if s.get("kind") == "run" and "km" in s), None)
            return step.get("reps"), work["km"] if work else None
    return None, None


_TITLES = [
    (re.compile(r"^Próg (\d+)×([\d.,]+) km"), lambda m: {"key": "threshold", "reps": int(m[1]),  # i18n: key
                                                          "rep": float(m[2].replace(",", "."))}),
    (re.compile(r"^Interwały (\d+)×(\d+) m"), lambda m: {"key": "intervals", "reps": int(m[1]),  # i18n: key
                                                          "rep": int(m[2]) / 1000}),
    (re.compile(r"^Tempo (\d+) km"), lambda m: {"key": "tempo", "work": float(m[1])}),
    (re.compile(r"^Długie wybieganie (\d+) km"), lambda m: {"key": "long", "km": float(m[1])}),  # i18n: key
    (re.compile(r"^Spokojny (\d+) km"), lambda m: {"key": "easy", "km": float(m[1])}),
    (re.compile(r"^Regeneracyjny (\d+) km"), lambda m: {"key": "recovery", "km": float(m[1])}),
    (re.compile(r"^Start$"), lambda m: {"key": "race"}),
]


def _from_title(title: str) -> dict[str, Any] | None:
    for pattern, build in _TITLES:
        found = pattern.match(title.strip())
        if found:
            return build(found)
    return None


def infer(session: dict[str, Any], distance: str | None = None) -> dict[str, Any]:
    """The ``text`` code of a session written as Polish sentences."""
    title = str(session.get("title") or "")
    main = str(session.get("main") or "")
    kind = session.get("type")
    if kind == "rest" and title.startswith("Odpoczynek"):
        return {"key": "sick"}
    if kind == "easy" and "(korekta)" in title:
        return {"key": "adjusted"}
    softened = re.match(r"^Spokojny \d+ km \(zamiast: (.*)\)$", title)
    if kind == "easy" and softened:
        before = _from_title(softened[1]) or {"key": "easy"}
        before_km = before.pop("km", None)
        if before["key"] in ("tempo", "race"):
            before["distance"] = distance
        return {"key": "softened", "before": before, "before_km": before_km}
    spec = _from_title(title)
    if spec is None or spec["key"] != kind:
        return {"key": "custom", "pl": {field: session.get(field, "—") for field in PROSE}}
    spec.pop("km", None)
    if kind == "easy":
        spec["strides"] = "przebieżek" in main  # i18n: key
    elif kind == "long":
        part = re.search(r"ostatnie (\d+) km w tempie startowym", main)
        steps = [s for s in session.get("steps") or [] if s.get("kind") == "run"]
        if part and len(steps) >= 2 and steps[-1].get("pace"):
            spec.update(part=float(part[1]), race_pace=round(sum(steps[-1]["pace"]) / 2, 3))
    elif kind in ("threshold", "intervals"):
        reps, rep = _work_steps(session)
        if reps and rep:
            spec.update(reps=int(reps), rep=float(rep))
    elif kind == "tempo":
        work = next((s["km"] for s in session.get("steps") or [] if s.get("kind") == "run" and "km" in s), None)
        if work:
            spec["work"] = round(float(work), 1)
        spec["distance"] = distance
    elif kind == "race":
        spec["distance"] = distance
    return spec


_ADJUSTMENT_NOTES = re.compile(r"\s*\[(zmęczenie|choroba|mniej czasu) — [^\]]*\]|\s*\[zmiękczone z „[^”]*”\]")  # i18n: key
_WARNINGS = [
    (re.compile(r"^Cel (\S+) jest szybszy .*prognozy \(([^)]+)\)"),
     lambda m: {"key": "goal_too_fast", "goal_s": units.parse_time(m[1]), "low_s": units.parse_time(m[2])}),
    (re.compile(r"^Mniej niż 3 tygodnie"), lambda m: {"key": "short"}),  # i18n: key
    (re.compile(r"^W ostatnich 4 tygodniach prawie nie było"), lambda m: {"key": "no_running"}),  # i18n: key
]


def migrate_plan(plan: dict[str, Any]) -> bool:
    """Turn an old plan's sentences into codes, in place; True when it changed."""
    changed = False
    distance = (plan.get("request") or {}).get("distance")
    for session in plan.get("sessions", []):
        if "text" in session:
            continue
        session["text"] = infer(session, distance)
        note = str(session.get("note") or "")
        cleaned = _ADJUSTMENT_NOTES.sub("", note).strip()
        if cleaned != note:
            session["note"] = cleaned
        changed = True
    items = []
    for item in plan.get("warnings", []):
        if isinstance(item, str):
            changed = True
            for pattern, build in _WARNINGS:
                found = pattern.match(item)
                if found:
                    item = build(found)
                    break
            else:
                item = {"key": "custom", "pl": item}
        items.append(item)
    if "warnings" in plan:
        plan["warnings"] = items
    return changed
