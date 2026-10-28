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

import datetime as dt
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
        "assistant": tr(pl="asystent", en="assistant"), "goals": tr(pl="zmiana celów", en="goals changed"),
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


def _hr_lead(session: dict[str, Any]) -> list[int] | None:
    """The heart-rate band an easy run is steered by (its first step), if any."""
    steps = session.get("steps") or []
    return steps[0].get("hr") if steps and isinstance(steps[0], dict) else None


def _km(value: Any) -> str:
    return _n(value)


def _rest(seconds: Any) -> str:
    seconds = int(seconds or 0)
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    if seconds > 120 and seconds % 30 == 0:
        return f"{_n(seconds / 60)} min"
    return f"{seconds} s"


def _n(value: Any) -> str:
    """A distance or a count as read in the interface language: 12,5 / 12.5, no trailing ,0."""
    text_value = f"{round(float(value or 0), 1):g}"
    return i18n.tr(pl=text_value.replace(".", ","), en=text_value)


def _rep(value: Any) -> str:
    return i18n.tr(pl=f"{float(value):g}".replace(".", ","), en=f"{float(value):g}")


def _work(spec: dict[str, Any]) -> float:
    """Tempo work in km: the old code stored ``work``, the library stores reps x rep."""
    return float(spec.get("work") or spec.get("reps", 1) * spec.get("rep", 0))


def family_label(key: Any) -> str:
    """A workout family of the library (``text.key`` of a quality session)."""
    tr = i18n.tr
    return {"threshold": tr(pl="próg", en="threshold"), "intervals": tr(pl="interwały", en="intervals"),
            "hills": tr(pl="podbiegi", en="hills"), "race_pace": tr(pl="tempo startowe", en="race pace"),
            "tempo": "tempo", "long_finish": tr(pl="długi z finiszem", en="long run with a finish")}.get(key, str(key))


def strength_label(stage: Any) -> str:
    tr = i18n.tr
    return {"adapt": tr(pl="adaptacja", en="adaptation"), "strength": tr(pl="ciężko", en="heavy"),
            "maintain": tr(pl="utrzymanie", en="maintenance"), "light": tr(pl="lekko", en="light")}.get(stage,
                                                                                                    str(stage))


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
        if spec.get("reps") == 1:
            return tr(pl=f"Próg ciągły {_rep(spec['rep'])} km", en=f"Continuous threshold {_rep(spec['rep'])} km")
        return tr(pl=f"Próg {spec['reps']}×{_rep(spec['rep'])} km", en=f"Threshold {spec['reps']}×{spec['rep']:g} km")
    if key == "hills":
        return tr(pl=f"Podbiegi {spec['reps']}×{spec['s']} s", en=f"Hill reps {spec['reps']}×{spec['s']} s")
    if key == "race_pace":
        reps = "" if spec.get("reps") == 1 else f"{spec['reps']}×"
        return tr(pl=f"Tempo startowe {reps}{_rep(spec['rep'])} km", en=f"Race pace {reps}{_rep(spec['rep'])} km")
    if key == "strength":
        return tr(pl=f"Siła — {strength_label(spec.get('stage'))}", en=f"Strength — {strength_label(spec.get('stage'))}")
    if key == "intervals":
        return tr(pl=f"Interwały {spec['reps']}×{spec['rep'] * 1000:.0f} m",
                  en=f"Intervals {spec['reps']}×{spec['rep'] * 1000:.0f} m")
    if key == "tempo":
        return f"Tempo {_work(spec):.0f} km"
    if key == "race":
        return tr(pl="Start", en="Race")
    if key == "sick":
        return tr(pl="Odpoczynek (choroba)", en="Rest (illness)")
    if key == "rest_strength":
        return tr(pl="Bez siłowni (regeneracja)", en="No strength (recovery)")
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
        count = 4 if km < 5 else 6
        strides = tr(pl=f", na końcu {count}×20 s przebieżek", en=f", {count}×20 s strides at the end") \
            if spec.get("strides") else ""
        hr = _hr_lead(session)
        out["main"] = tr(pl=f"{_n(km)} km na tętnie {hr[0]}–{hr[1]} bpm (tempo wychodzi samo, zwykle ok. {band})"
                            f"{strides}",
                         en=f"{_n(km)} km at a heart rate of {hr[0]}–{hr[1]} bpm (the pace follows, usually about "
                            f"{band}){strides}") if hr else \
            tr(pl=f"{_n(km)} km ciągle w tempie {band}{strides}", en=f"{_n(km)} km continuous at {band}{strides}")
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
            main=(tr(pl=f"{_n(km)} km na tętnie {_hr_lead(session)[0]}–{_hr_lead(session)[1]} bpm{segment}",
                     en=f"{_n(km)} km at a heart rate of {_hr_lead(session)[0]}–{_hr_lead(session)[1]} bpm{segment}")
                  if _hr_lead(session) else
                  tr(pl=f"{_n(km)} km w tempie {band}{segment}", en=f"{_n(km)} km at {band}{segment}")),
            cooldown=tr(pl="ostatni km trucht", en="the last km a jog"),
            purpose=tr(pl="Wytrzymałość specyficzna: glikogen, mięśnie i ścięgna przyzwyczajone do czasu na nogach. ",
                       en="Specific endurance: glycogen, muscles and tendons used to time on feet. ")
            + (tr(pl="Odcinek w tempie startowym uczy utrzymać je na zmęczeniu.",
                  en="The race-pace stretch teaches you to hold it when tired.") if part else
               tr(pl="Tempo spokojne — liczy się czas, nie prędkość.", en="An easy pace — time counts, not speed.")),
        )
    elif key == "threshold":
        rest = _rest(spec.get("rest", 60))
        out.update(
            warmup=tr(pl="2 km spokojnie + 4 przebieżki", en="2 km easy + 4 strides"),
            main=tr(pl=f"{_rep(spec['rep'])} km ciągle w tempie {band}", en=f"{spec['rep']:g} km continuous at {band}")
            if spec.get("reps") == 1 else
            tr(pl=f"{spec['reps']}×{spec['rep']:g} km w tempie {band}, przerwa {rest} truchtu",
               en=f"{spec['reps']}×{spec['rep']:g} km at {band}, {rest} jog recovery"),
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
            main=tr(pl=f"{spec['reps']}×{metres} m w tempie {band}, przerwa {_rest(spec['rest'])} truchtu",
                    en=f"{spec['reps']}×{metres} m at {band}, {_rest(spec['rest'])} jog recovery")
            if spec.get("rest") else
            tr(pl=f"{spec['reps']}×{metres} m w tempie {band}, przerwa trucht równy czasowi odcinka",
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
            main=tr(pl=f"{_work(spec):.0f} km ciągle w tempie {band}", en=f"{_work(spec):.0f} km continuous at {band}"),
            cooldown=tr(pl="1,5 km spokojnie", en="1.5 km easy"),
            purpose=(tr(pl="Wytrzymałość tempowa: długi, równy wysiłek poniżej progu. W fazie specyfiki — w tempie "
                           "startowym, żeby je zautomatyzować.",
                        en="Tempo endurance: a long, even effort below threshold. In the specific phase — at race "
                           "pace, to make it automatic.")
                     if spec.get("distance") in ("hm", "m") else
                     tr(pl="Wprowadzenie do pracy tempowej: równy, kontrolowany wysiłek przed cięższymi sesjami.",
                        en="An introduction to tempo work: an even, controlled effort before harder sessions.")),
        )
    elif key == "hills":
        out.update(
            warmup=tr(pl="2 km spokojnie do podbiegu", en="2 km easy to the hill"),
            main=tr(pl=f"{spec['reps']}×{spec['s']} s pod górę (nachylenie 4–8%, wiadukt albo schody też się "
                       "nadają) z wysiłkiem jak na 5 km, w dół truchtem",
                    en=f"{spec['reps']}×{spec['s']} s uphill (a 4–8% grade; a bridge ramp or stairs will do) at 5 km "
                       "effort, jog back down"),
            cooldown=tr(pl="1,5 km spokojnie", en="1.5 km easy"),
            purpose=tr(pl="Siła biegowa w fazie bazy: duży bodziec dla mięśni i ekonomii przy małym obciążeniu "
                          "stawów. Na zboczu tempo nic nie mówi — liczy się wysiłek i postawa: wysoko biodra, krótki "
                          "krok.",
                       en="Running strength in the base phase: a big stimulus for the muscles and economy at a low "
                          "load on the joints. On a slope pace means nothing — effort and posture count: hips high, "
                          "short steps."),
        )
    elif key == "race_pace":
        race = race_label(spec.get("distance"))
        main = tr(pl=f"{_rep(spec['rep'])} km ciągle w tempie startowym {band}",
                  en=f"{spec['rep']:g} km continuous at race pace {band}") if spec.get("reps") == 1 else \
            tr(pl=f"{spec['reps']}×{_rep(spec['rep'])} km w tempie startowym {band}, przerwa "
                  f"{_rest(spec.get('rest'))} truchtu",
               en=f"{spec['reps']}×{spec['rep']:g} km at race pace {band}, {_rest(spec.get('rest'))} jog recovery")
        out.update(
            warmup=tr(pl="2 km spokojnie + 4 przebieżki", en="2 km easy + 4 strides"),
            main=main,
            cooldown=tr(pl="1,5 km spokojnie", en="1.5 km easy"),
            purpose=tr(pl="Ostatni bodziec przed startem: kilka krótkich odcinków w tempie startowym, żeby nogi "
                          "pamiętały rytm. Objętość mała, więc świeżość zostaje — w taperze tnie się kilometry, nie "
                          "intensywność (Bosquet 2007).",
                       en="The last stimulus before the race: a few short reps at race pace so the legs remember the "
                          "rhythm. The volume is small, so freshness stays — a taper cuts kilometres, not intensity "
                          "(Bosquet 2007).") if spec.get("sharpen") else
            tr(pl=f"Blok specyficzny ({race}): z tygodnia na tydzień więcej kilometrów w tempie startowym, aż "
                  "staje się ono rytmem, a nie wysiłkiem.",
               en=f"The specific block ({race}): more kilometres at race pace week after week, until it is a "
                  "rhythm rather than an effort."),
        )
    elif key == "strength":
        out.update(_strength_text(spec.get("stage")))
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
    elif key == "rest_strength":
        out.update(main="—", purpose=tr(pl="Przy zmęczeniu siłownia dokłada obciążenie bez zysku; wraca, gdy wróci "
                                           "świeżość.",
                                        en="When tired, strength work adds load with no gain; it returns with "
                                           "freshness."))
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
    return _with_distances(session, spec, out)


def km(value: Any) -> str:
    """``12,5 km`` / ``12.5 km``: a planned distance as the tables show it."""
    return f"{_n(value)} km"


def table_title(session: dict[str, Any]) -> str:
    """A session's title with the full distance to run when the title does not carry it
    (quality sessions, hill reps and the race: warm-up, recoveries and cool-down included)."""
    title = str(session.get("title") or "")
    if (session.get("text") or {}).get("key") in (*QUALITY_KEYS, "race") and session.get("distance_km"):
        return f"{title} · {km(session['distance_km'])}"
    return title


def _parts(session: dict[str, Any]) -> dict[str, float]:
    """Kilometres of a run's parts from its steps; what is left of ``distance_km``
    (timed recoveries, uphill reps and the jog back down) is ``between``."""
    warmup = cooldown = work = 0.0
    warmup_s = 0.0
    for step in session.get("steps") or []:
        if step.get("kind") == "repeat":
            inner = sum(s.get("km", 0.0) for s in step.get("steps", []) if s.get("kind") == "run")
            work += step.get("reps", 1) * inner
        elif step.get("kind") == "warmup":
            warmup += step.get("km", 0.0)
            warmup_s += step.get("s", 0.0)
        elif step.get("kind") == "cooldown":
            cooldown += step.get("km", 0.0)
        elif step.get("kind") == "run":
            work += step.get("km", 0.0)
    total = float(session.get("distance_km") or 0)
    if warmup_s and not warmup:  # a timed warm-up (race day): its kilometres are what the run adds to the race
        warmup = max(0.0, total - work - cooldown)
    return {"warmup": warmup, "warmup_s": warmup_s, "work": work, "cooldown": cooldown, "total": total,
            "between": max(0.0, total - warmup - work - cooldown)}


QUALITY_KEYS = ("threshold", "intervals", "race_pace", "tempo", "hills")


def _with_distances(session: dict[str, Any], spec: dict[str, Any], out: dict[str, str]) -> dict[str, str]:
    """Warm-up, cool-down and the total of a structured run in kilometres, from the
    steps the watch gets -- so the description and the table say the same distance."""
    key = spec.get("key")
    if not session.get("steps") or key not in (*QUALITY_KEYS, "race", "long"):
        return out
    tr = i18n.tr
    parts = _parts(session)
    total, warm, cool = _n(parts["total"]), _n(parts["warmup"]), _n(parts["cooldown"])
    if key in QUALITY_KEYS:
        strides = tr(pl=" + 4 przebieżki", en=" + 4 strides") if key != "hills" else ""
        where = tr(pl=" do podbiegu", en=" to the hill") if key == "hills" else ""
        out["warmup"] = tr(pl=f"{warm} km spokojnie{where}{strides}", en=f"{warm} km easy{where}{strides}")
        out["cooldown"] = tr(pl=f"{cool} km spokojnie", en=f"{cool} km easy")
        if key == "hills":
            line = tr(pl=f"Razem ok. {total} km: rozgrzewka {warm} km, podbiegi z zbiegami ok. "
                         f"{_n(parts['between'])} km, schłodzenie {cool} km.",
                      en=f"About {total} km in total: warm-up {warm} km, hill reps with the jogs down about "
                         f"{_n(parts['between'])} km, cool-down {cool} km.")
        else:
            rest = tr(pl=f", przerwy ok. {_n(parts['between'])} km", en=f", recoveries about {_n(parts['between'])} km") \
                if parts["between"] >= 0.05 else ""
            line = tr(pl=f"Razem {total} km: rozgrzewka {warm} km, odcinki {_n(parts['work'])} km{rest}, schłodzenie "
                         f"{cool} km.",
                      en=f"{total} km in total: warm-up {warm} km, reps {_n(parts['work'])} km{rest}, cool-down "
                         f"{cool} km.")
        out["main"] = f"{out['main']}. {line}"
    elif key == "race":
        minutes = round(parts["warmup_s"] / 60)
        short = spec.get("distance") in ("5k", "10k")
        extra = tr(pl=" + 3 przebieżki", en=" + 3 strides") if short else ""
        out["warmup"] = tr(pl=f"{minutes} min truchtu (ok. {warm} km){extra}",
                           en=f"{minutes} min jogging (about {warm} km){extra}")
        out["main"] = f"{out['main']}. " + tr(pl=f"Razem ok. {total} km: rozgrzewka ok. {warm} km + start "
                                                 f"{_n(parts['work'])} km.",
                                              en=f"About {total} km in total: warm-up about {warm} km + the race "
                                                 f"{_n(parts['work'])} km.")
    elif key == "long" and spec.get("part"):
        easy = _n(parts["total"] - spec["part"])
        out["main"] = f"{out['main']}. " + tr(pl=f"Razem {total} km: {easy} km spokojnie + {_n(spec['part'])} km w "
                                                 "tempie startowym.",
                                              en=f"{total} km in total: {easy} km easy + {_n(spec['part'])} km at "
                                                 "race pace.")
    return out


# Exercises of library.STRENGTH_PROGRAMMES: (name, technique cue), built in the current language.
def _exercises() -> dict[str, tuple[str, str]]:
    tr = i18n.tr
    return {
        'Goblet Squat': (
            tr(pl='Przysiad goblet', en='Goblet squat'),
            tr(pl='hantel albo kettlebell przy mostku, łokcie między kolanami; zejście do równoległej lub niżej, pięty na ziemi, kolana nad palcami',
               en='a dumbbell or kettlebell at the chest, elbows between the knees; down to parallel or lower, heels down, knees over the toes'),
        ),
        'Romanian Deadlift': (
            tr(pl='Martwy ciąg rumuński', en='Romanian deadlift'),
            tr(pl='kolana lekko ugięte i nieruchome, biodra w tył, plecy proste; ciężar blisko nóg do połowy piszczeli — ciągnie tył uda, nie lędźwie',
               en='knees slightly bent and still, hips back, back straight; the weight close to the legs down to mid-shin — the back of the thigh works, not the lower back'),
        ),
        'Dumbbell Reverse Lunge': (
            tr(pl='Wykrok w tył z hantlami', en='Dumbbell reverse lunge'),
            tr(pl='krok w tył, kolano tylnej nogi prawie do ziemi, tułów pionowo, powrót z pięty przedniej nogi',
               en='step back, rear knee almost to the floor, torso upright, drive back up through the front heel'),
        ),
        'Barbell Hip Thrust on Floor': (
            tr(pl='Hip thrust', en='Hip thrust'),
            tr(pl='łopatki na ławce, sztanga na biodrach (z podkładką); pełny wyprost bioder, 1 s napięcia pośladków u góry, bez wyginania lędźwi',
               en='shoulder blades on a bench, the bar on the hips (padded); full hip extension, a 1 s glute squeeze at the top, no arching of the lower back'),
        ),
        'Standing Calf Raise': (
            tr(pl='Wspięcia na palce stojąc', en='Standing calf raise'),
            tr(pl='na krawędzi stopnia, noga prosta; pełny zakres — pięta poniżej stopnia, potem najwyżej; 2 s w górę, 2 s w dół',
               en='on the edge of a step, leg straight; full range — heel below the step, then as high as possible; 2 s up, 2 s down'),
        ),
        'Single-leg Bent-knee Calf Raise': (
            tr(pl='Wspięcia na palce jednonóż z ugiętym kolanem', en='Single-leg bent-knee calf raise'),
            tr(pl='kolano ugięte ~30° — pracuje mięsień płaszczkowaty, który przy bieganiu dźwiga najwięcej; wolno i w pełnym zakresie',
               en='knee bent ~30° — this works the soleus, which carries the most load in running; slow and through the full range'),
        ),
        'Plank': (
            tr(pl='Deska', en='Plank'),
            tr(pl='przedramiona pod barkami, prosta linia od głowy do pięt, napięty brzuch i pośladki, oddech spokojny',
               en='forearms under the shoulders, a straight line from head to heels, abs and glutes tight, calm breathing'),
        ),
        'Side Plank': (
            tr(pl='Deska bokiem', en='Side plank'),
            tr(pl='łokieć pod barkiem, biodra wysoko w jednej linii z barkami i stopami',
               en='elbow under the shoulder, hips high in line with the shoulders and feet'),
        ),
        'Barbell Back Squat': (
            tr(pl='Przysiad ze sztangą', en='Barbell back squat'),
            tr(pl='sztanga na górze pleców, stopy na szerokość bioder lub szerzej; zejście do równoległej, kolana na zewnątrz nad palcami, w górę dynamicznie',
               en='the bar on the upper back, feet hip-width or wider; down to parallel, knees out over the toes, up explosively'),
        ),
        'Dumbbell Bulgarian Split Squat': (
            tr(pl='Przysiad bułgarski z hantlami', en='Dumbbell Bulgarian split squat'),
            tr(pl='tylna stopa na ławce, przednia 60–80 cm przed nią; kolano przednie nad stopą, tułów lekko pochylony',
               en='rear foot on a bench, front foot 60–80 cm ahead; front knee over the foot, torso slightly forward'),
        ),
        'Weighted Standing Calf Raise': (
            tr(pl='Wspięcia na palce z obciążeniem', en='Weighted standing calf raise'),
            tr(pl='jak wspięcia stojąc, z hantlami albo sztangą; 3 s w dół, pełny zakres',
               en='like standing calf raises, with dumbbells or a bar; 3 s down, full range'),
        ),
        'Plyo': (
            tr(pl='Skoki pogo', en='Pogo jumps'),
            tr(pl='sprężyste podskoki na sztywnych kostkach, kolana prawie proste, jak najkrótszy kontakt z ziemią',
               en='springy hops on stiff ankles, knees almost straight, the shortest possible ground contact'),
        ),
        'Box Jump': (
            tr(pl='Wyskoki na skrzynię', en='Box jumps'),
            tr(pl='skrzynia 40–60 cm; wybicie obunóż, miękkie lądowanie w półprzysiadzie, zejście krokiem, nie skokiem w dół; każdy skok z pełną mocą',
               en='a 40–60 cm box; take off from both feet, land softly in a half squat, step down rather than jump; every jump at full power'),
        ),
    }


def exercise_cue(name: str) -> str:
    """The technique cue of one programme exercise in the interface language (the watch shows it on the step)."""
    cue = _exercises()[name][1]
    return cue[:1].upper() + cue[1:]


def _strength_text(stage: Any) -> dict[str, str]:
    """A strength session written out from its programme (``library.STRENGTH_PROGRAMMES``), exercise by
    exercise -- the same sets, reps and rests the watch gets."""
    from running import library

    tr = i18n.tr
    stage = stage if stage in library.STRENGTH_PROGRAMMES else "adapt"
    load = {
        "adapt": tr(pl="Ciężar: taki, przy którym po serii zostają 3–4 powtórzenia zapasu. Gdy wszystkie serie "
                       "wychodzą lekko, następnym razem +1–2 kg na hantel.",
                    en="Load: one that leaves 3–4 reps in reserve after a set. When every set feels easy, add 1–2 kg "
                       "per dumbbell next time."),
        "strength": tr(pl="Ciężar: ok. 80–85% maksimum — po serii zostają 2–3 powtórzenia zapasu; technika przed "
                          "kilogramami. Gdy wszystkie serie wychodzą z większym zapasem, +2,5–5 kg. Skoki na "
                          "początku, na świeżo.",
                       en="Load: about 80–85% of your maximum — 2–3 reps left in reserve after a set; technique "
                          "before kilograms. When every set leaves more in reserve, add 2.5–5 kg. Jumps first, "
                          "fresh."),
        "maintain": tr(pl="Ciężar jak w fazie ciężkiej (2–3 powtórzenia zapasu), o połowę mniej serii — siła zostaje, "
                          "zmęczenie nie.",
                       en="Load as in the heavy phase (2–3 reps in reserve), half the sets — strength stays, fatigue "
                          "does not."),
        "light": tr(pl="Połowa zwykłego ciężaru, bez skoków i bez zmęczenia — tylko przypomnienie ruchu.",
                    en="Half the usual load, no jumps and no fatigue — only a reminder of the movement."),
    }[stage]
    lines = [load]
    for number, (name, sets, reps, hold, rest) in enumerate(library.STRENGTH_PROGRAMMES[stage], 1):
        label, cue = _exercises()[name]
        side = name in library.ONE_SIDED
        amount = (tr(pl=f"{sets}×{reps}" + (" na nogę" if side else ""), en=f"{sets}×{reps}" + (" per leg" if side else ""))
                  if reps else
                  tr(pl=f"{sets}×{hold} s" + (" na stronę" if side else ""),
                     en=f"{sets}×{hold} s" + (" per side" if side else "")))
        cue = cue[:1].upper() + cue[1:]
        lines.append(tr(pl=f"{number}. **{label}** — {amount}, przerwa {_rest(rest)}. {cue}.",
                        en=f"{number}. **{label}** — {amount}, rest {_rest(rest)}. {cue}."))
    purpose = {
        "adapt": tr(pl="Adaptacja: ścięgna i technika przed ciężarami. Pierwsze 6 sesji umiarkowanie — potem ciężko.",
                    en="Adaptation: tendons and technique before heavy loads. The first 6 sessions are moderate — "
                       "then heavy."),
        "strength": tr(pl="Ciężka siła i plyometria poprawiają ekonomię biegu — mniej tlenu na to samo tempo — i "
                          "wytrzymałość ścięgien (Blagrove 2018, Llanos-Lagos 2024).",
                       en="Heavy strength and plyometrics improve running economy — less oxygen for the same pace — "
                          "and tendon resilience (Blagrove 2018, Llanos-Lagos 2024)."),
        "maintain": tr(pl="Utrzymanie: siła zostaje przy połowie objętości, bez zmęczenia przed akcentami szczytu.",
                       en="Maintenance: strength holds at half the volume, without fatigue before the peak's key "
                          "sessions."),
        "light": tr(pl="Lekko: podtrzymanie bodźca w tygodniu lżejszym albo przed startem — bez zakwasów.",
                    en="Light: keeping the stimulus in a lighter week or before a race — without soreness."),
    }[stage]
    when = tr(pl=" Najlepiej po biegu tego samego dnia (albo ≥ 6 h później), żeby dni spokojne zostały spokojne.",
              en=" Best after the run on the same day (or ≥ 6 h later), so easy days stay easy.")
    return {
        "warmup": tr(pl="5–10 min roweru albo truchtu, wymachy nóg, 10 przysiadów i 10 wykroków bez obciążenia; przed "
                        "pierwszym ćwiczeniem z ciężarem 1–2 serie rozgrzewkowe na połowie ciężaru",
                     en="5–10 min on a bike or jogging, leg swings, 10 unloaded squats and 10 lunges; before the first "
                        "loaded exercise 1–2 warm-up sets at half the load"),
        "main": "\n".join(lines),
        "cooldown": tr(pl="5 min: rozciąganie łydek, tyłu uda i zginaczy biodra",
                       en="5 min: stretching the calves, hamstrings and hip flexors"),
        "purpose": purpose + when,
    }


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
        race = f"{item['race']}: " if item.get("race") else ""
        return race + tr(pl=f"Cel {goal} jest szybszy niż optymistyczny kraniec dzisiejszej prognozy ({low}). Odcinki "
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
    if key == "close_a_races":
        first, second, weeks = item.get("first"), item.get("second"), f"{item.get('weeks', 0):g}".replace(".", ",")
        return tr(pl=f"„{first}” i „{second}” to oba starty A, {weeks} tyg. od siebie. Na dwa szczyty to za mało: "
                     "drugi blok to tylko regeneracja, tydzień budowy i taper. Zmień jeden z nich na B na stronie "
                     "Zawody — wtedy plan buduje przez niego do głównego celu (B: tylko lżejszy tydzień startu).",
                  en=f"“{first}” and “{second}” are both A races, {item.get('weeks', 0):g} weeks apart. That is too "
                     "little for two peaks: the second block is only recovery, a build week and a taper. Make one of "
                     "them B on the Races page — the plan then builds through it to the main goal (B: only a lighter "
                     "race week).")
    if key == "custom":
        return str(item.get(i18n.lang()) or item.get("pl") or "")
    return str(item)


def why(session: dict[str, Any]) -> list[str]:
    """``session["why"]``: why the plan put this session here instead of the usual pattern."""
    return [why_line(item) for item in session.get("why") or []]


def why_line(item: dict[str, Any]) -> str:
    tr = i18n.tr
    key = item.get("key")
    when = _day(item.get("date"))
    name = f" ({item['name']})" if item.get("name") else ""
    if key == "week_quality_done":
        return tr(pl=f"Akcent tego tygodnia już był: {when}{name}. Przy Twoich dniach biegowych i objętości tydzień "
                     "niesie jeden akcent plus długi bieg, więc reszta tygodnia jest spokojna.",
                  en=f"This week's quality session is done: {when}{name}. With your running days and volume a week "
                     "carries one quality session plus the long run, so the rest of the week is easy.")
    if key == "week_long_done":
        return tr(pl=f"Długi bieg tego tygodnia już był: {when}{name}.",
                  en=f"This week's long run is done: {when}{name}.")
    if key == "after_hard":
        return tr(pl=f"Mocny trening {when}{name} — akcent nie ląduje dzień przed ani dzień po mocnym dniu.",
                  en=f"A hard session on {when}{name} — quality never lands the day before or after a hard day.")
    if key == "pre_race_long":
        days = item.get("days")
        return tr(pl=f"Start za {days} dni: zamiast długiego biegu spokojna objętość. Długi bieg najpóźniej "
                     f"{item.get('gap', 7)} dni przed startem — inaczej startujesz na zmęczonych nogach.",
                  en=f"Race in {days} days: easy volume instead of the long run. The long run comes at least "
                     f"{item.get('gap', 7)} days before a race — otherwise you race on tired legs.")
    if key == "pre_race_quality":
        days = item.get("days")
        return tr(pl=f"Start za {days} dni: bez akcentu, świeżość ważniejsza niż ostatni bodziec.",
                  en=f"Race in {days} days: no quality session, freshness matters more than one last stimulus.")
    if key == "shakeout":
        days = item.get("run_days")
        return tr(pl=f"Dzień przed startem to Twój zwykły dzień biegowy, a biegasz {days} dni w tygodniu — wolne "
                     "zmieniłoby rytm, więc krótki rozruch: 15–20 min bardzo spokojnie i 4 przebieżki po 20 s. To za "
                     "mało, żeby zmęczyć, wystarczy, żeby nogi nie były „zastane”. Przy 3 i mniej dniach biegowych "
                     "albo gdy dzień przed startem nie jest dniem biegowym, plan daje wolne.",
                  en=f"The day before the race is one of your usual running days, and you run {days} days a week — a "
                     "day off would break the rhythm, so a short shakeout: 15–20 min very easy and 4 strides of 20 s. "
                     "Too little to tire you, enough to keep the legs from going stale. With 3 or fewer running days, "
                     "or when the day before is not a running day, the plan gives a rest day.")
    if key == "post_race_easy":
        days, need, race = item.get("days"), item.get("easy_days"), race_label(item.get("distance"))
        return tr(pl=f"{days}. dzień po starcie ({race}): bez akcentu i długiego biegu przez {need} dni — reguła "
                     "Danielsa, jeden spokojny dzień na każde 3 km startu. Mięśnie po starcie regenerują się dłużej, "
                     "niż mówi samopoczucie.",
                  en=f"Day {days} after the race ({race}): no quality and no long run for {need} days — Daniels' "
                     "rule, one easy day per 3 km raced. Muscles recover from a race longer than it feels.")
    if key == "response":
        signals = "; ".join(signal_line(x) for x in item.get("signals") or [])
        if item.get("decision") == "lighter":
            return tr(pl=f"Ten tydzień jest lżejszy (−25%), bo organizm słabo przyjmuje obciążenie: {signals}. Lżejszy "
                         "tydzień z kalendarza przesuwa się dalej.",
                      en=f"This week is lighter (−25%) because the body is not taking the load well: {signals}. The "
                         "scheduled lighter week moves further on.")
        return tr(pl=f"W tym tygodniu bez przyrostu objętości, bo jeden sygnał jest przeciw: {signals}. Wzrost wraca "
                     "przy następnej przebudowie, jeśli sygnał zniknie.",
                  en=f"No step up in volume this week, because one signal is against it: {signals}. Growth returns "
                     "with the next rebuild if the signal is gone.")
    if key == "rung_hold":
        family, reason = family_label(item.get("family")), item.get("reason")
        if reason == "missed":
            return tr(pl=f"Poprzedni trening tego rodzaju ({family}, {when}) się nie odbył — ten sam szczebel "
                         "drabinki, zamiast wyżej.",
                      en=f"The previous session of this kind ({family}, {when}) did not happen — the same rung of "
                         "the ladder instead of the next one.")
        if reason == "other_kind":
            kind = kind_label(item.get("kind"))
            return tr(pl=f"{when} zamiast „{family}” wyszedł trening typu „{kind}” — ten sam szczebel.",
                      en=f"On {when} the “{family}” session turned into “{kind}” — the same rung.")
        if reason == "short":
            return tr(pl=f"{when}: zrobione {item.get('done')} z {item.get('planned')} odcinków — powtórka szczebla, "
                         "zanim pójdzie wyżej.",
                      en=f"{when}: {item.get('done')} of {item.get('planned')} reps done — the rung is repeated "
                         "before moving up.")
        if reason == "off_pace":
            return tr(pl=f"{when}: w paśmie tempa {item.get('on_pace')} z {item.get('planned')} odcinków (z okrążeń "
                         "zegarka) — powtórka szczebla; awans po ⅔ odcinków w tempie.",
                      en=f"{when}: {item.get('on_pace')} of {item.get('planned')} reps within the pace band (from the "
                         "watch laps) — the rung is repeated; it moves up with ⅔ of the reps on pace.")
        if reason == "drift":
            value = f"{item.get('drift'):.1f}"
            return tr(pl=f"{when}: w spokojnej części długiego biegu tętno odjechało od tempa o {value.replace('.', ',')}% "
                         f"(granica {item.get('limit'):g}%) — wytrzymałość jeszcze nie trzyma, więc odcinek w tempie "
                         "startowym na końcu zostaje tej samej długości.",
                      en=f"{when}: in the easy part of the long run heart rate drifted from pace by {value}% (limit "
                         f"{item.get('limit'):g}%) — endurance is not holding yet, so the race-pace finish stays the "
                         "same length.")
        if reason == "hr_high":
            return tr(pl=f"{when}: średnie tętno odcinków {item.get('hr')} bpm, powyżej strefy progu (do "
                         f"{item.get('top')}) — tempo było za ciężkie na dziś; ten sam szczebel.",
                      en=f"{when}: average rep heart rate {item.get('hr')} bpm, above the threshold zone (up to "
                         f"{item.get('top')}) — the pace was too hard for now; the same rung.")
    if key == "spike":
        return tr(pl=f"Skrócone z {item['from_km']:g} do {item['cap']:g} km: najdłuższy bieg z ostatnich 30 dni to "
                     f"{item['longest']:g} km, a pojedynczy bieg dłuższy o ponad 10% od niego wyraźnie zwiększa "
                     "ryzyko przeciążenia (Garmin-RUNSAFE, BJSM 2025).",
                  en=f"Cut from {item['from_km']:g} to {item['cap']:g} km: the longest run of the last 30 days is "
                     f"{item['longest']:g} km, and a single run more than 10% longer than that clearly raises the "
                     "risk of an overuse injury (Garmin-RUNSAFE, BJSM 2025).")
    if key == "post_race":
        days = item.get("days")
        return tr(pl=f"{days} dni po starcie: krótko i bardzo spokojnie, nogi się odbudowują.",
                  en=f"{days} days after the race: short and very easy, the legs are rebuilding.")
    return str(key)


def signal_line(item: dict[str, Any]) -> str:
    """One signal of ``plan.response``."""
    tr = i18n.tr
    key = item.get("key")
    if key == "hrv_low":
        now, base, floor = (f"{item[k]:.1f}" for k in ("now", "base", "floor"))
        return tr(pl=f"HRV z 7 dni {now.replace('.', ',')} ms poniżej własnej normy ({base.replace('.', ',')} ms, "
                     f"dolna granica {floor.replace('.', ',')})",
                  en=f"7-day HRV {now} ms below your own norm ({base} ms, lower edge {floor})")
    if key == "rhr_up":
        return tr(pl=f"tętno spoczynkowe z 7 dni {item['now']:g} vs {item['base']:g} bpm",
                  en=f"7-day resting heart rate {item['now']:g} vs {item['base']:g} bpm")
    if key == "ef_down":
        change = f"{item['change_pct']:.1f}"
        return tr(pl=f"efektywność spokojnych biegów przy tym samym tętnie {change.replace('.', ',')}% wobec 8 tygodni "
                     f"wcześniej ({item['runs']} biegów)",
                  en=f"efficiency of easy runs at the same heart rate {change}% against the 8 weeks before "
                     f"({item['runs']} runs)")
    if key == "not_run":
        return tr(pl=f"z ostatnich 2 tygodni przebiegnięte {item['actual']:.0f} z {item['planned']:.0f} km",
                  en=f"{item['actual']:.0f} of {item['planned']:.0f} km of the last 2 weeks were run")
    return str(key)


def _day(value: Any) -> str:
    if not value:
        return ""
    date = dt.date.fromisoformat(str(value))
    return f"{i18n.weekdays()[date.weekday()]} {date:%d.%m}"


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
    (re.compile(r"^Długie wybieganie ([\d,]+) km"), lambda m: {"key": "long",  # i18n: key
                                                               "km": float(m[1].replace(",", "."))}),
    (re.compile(r"^Spokojny ([\d,]+) km"), lambda m: {"key": "easy", "km": float(m[1].replace(",", "."))}),
    (re.compile(r"^Regeneracyjny ([\d,]+) km"), lambda m: {"key": "recovery", "km": float(m[1].replace(",", "."))}),
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
    softened = re.match(r"^Spokojny [\d,]+ km \(zamiast: (.*)\)$", title)
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
