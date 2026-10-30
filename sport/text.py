"""Sentences for the codes ``readiness`` and ``recommend`` return.

The engine keeps codes and numbers; the words are put together here, at display
time, in the interface language.
"""

from __future__ import annotations

from typing import Any

import i18n
from sport import catalog


def _days(n: int) -> str:
    tr = i18n.tr
    if n == 0:
        return tr(pl="dziś", en="today")
    if n == 1:
        return tr(pl="wczoraj", en="yesterday")
    if n >= 365:
        years = n // 365
        return tr(pl=f"ponad {years} {i18n.plural(years, pl=('rok', 'lata', 'lat'), en=('year', 'years'))} temu",
                  en=f"over {years} {i18n.plural(years, pl=('rok', 'lata', 'lat'), en=('year', 'years'))} ago")
    return tr(pl=f"{n} dni temu", en=f"{n} days ago")


def _n(value: float, decimals: int = 1) -> str:
    """A number with the decimal comma in Polish prose."""
    shown = f"{value:.{decimals}f}"
    return i18n.tr(pl=shown.replace(".", ","), en=shown)


def ago(n: int | None) -> str:
    return "—" if n is None else _days(int(n))


def reason(item: dict[str, Any]) -> str:
    tr = i18n.tr
    code = item["code"]
    if code == "never":
        return tr(pl="jeszcze nie próbowane", en="never tried")
    if code == "variety":
        return tr(pl=f"ostatnio {_days(item['days'])}", en=f"last done {_days(item['days'])}")
    if code == "familiar":
        n = item["sessions"]
        return tr(pl=f"znasz to ({n} {i18n.plural(n, pl=('raz', 'razy', 'razy'), en=('time', 'times'))})",
                  en=f"you know it ({n} {i18n.plural(n, pl=('raz', 'razy', 'razy'), en=('time', 'times'))})")
    if code == "dominant":
        share = round(item["share"] * 100)
        return tr(pl=f"{share}% czasu z 28 dni — już go dużo", en=f"{share}% of the last 28 days — plenty already")
    if code == "gap":
        quality = catalog.quality_label(item["quality"])
        return tr(pl=f"uzupełnia: {quality}", en=f"fills a gap: {quality}")
    if code == "tired":
        system = catalog.system_label(item["system"])
        return tr(pl=f"obciąża zmęczone: {system}", en=f"loads what is tired: {system}")
    if code == "fresh":
        system = catalog.system_label(item["system"])
        return tr(pl=f"pracuje wypoczęte: {system}", en=f"works what is rested: {system}")
    if code == "before":
        return tr(pl="jutro kluczowy bieg — nogi bez szarży", en="key run tomorrow — legs stay moderate")
    if code == "waste":
        return tr(pl="nie wykorzysta dzisiejszej gotowości", en="does not use today's readiness")
    return code


def reasons(items: list[dict[str, Any]], count: int = 3) -> str:
    return " · ".join(reason(r) for r in [r for r in items if not r.get("quiet")][:count])


def level_advice(level: str) -> str:
    tr = i18n.tr
    return {
        "hard": tr(pl="Zielone światło: dzień na mecz, interwały albo długie wyjście w teren.",
                   en="Green light: a day for a match, intervals or a long day outside."),
        "moderate": tr(pl="Normalny dzień: ruszaj się z przyjemnością, bez wyciskania maksimum.",
                       en="An ordinary day: move for the fun of it, without squeezing out the maximum."),
        "easy": tr(pl="Dzień na luz: spokojny tlen, technika albo mobilność.",
                   en="An easy day: gentle aerobic work, technique or mobility."),
        "recover": tr(pl="Organizm prosi o odpoczynek: spacer, rozciąganie, wcześniejszy sen.",
                      en="Your body asks for rest: a walk, stretching, an early night."),
    }[level]


def part_label(key: str) -> str:
    tr = i18n.tr
    return {
        "garmin": tr(pl="Readiness Garmina", en="Garmin readiness"),
        "hrv": "HRV",
        "rhr": tr(pl="Tętno spoczynkowe", en="Resting heart rate"),
        "sleep": tr(pl="Sen", en="Sleep"),
        "load": tr(pl="Obciążenie 7/28 d", en="Load 7/28 d"),
        "fresh": tr(pl="Od mocnego treningu", en="Since a hard session"),
    }[key]


def part_detail(key: str, part: dict[str, Any]) -> str:
    tr = i18n.tr
    if key == "garmin":
        return part.get("level") or f"{part['value']:.0f}"
    if key == "hrv":
        z = part["z"]
        side = tr(pl="ponad normą", en="above normal") if z > 0 else tr(pl="pod normą", en="below normal")
        return f"{part['value']:.0f} ms, {_n(abs(z))} SD {side}"
    if key == "rhr":
        return tr(pl=f"{part['value']:.0f} bpm ({part['diff']:+.0f} wobec mediany 60 d)",
                  en=f"{part['value']:.0f} bpm ({part['diff']:+.0f} vs the 60-day median)")
    if key == "sleep":
        bits = []
        if part.get("value") is not None:
            bits.append(f"{_n(part['value'])} h")
        if part.get("sleep_score") is not None:
            bits.append(tr(pl=f"ocena {part['sleep_score']:.0f}", en=f"score {part['sleep_score']:.0f}"))
        return ", ".join(bits)
    if key == "load":
        return tr(pl=f"iloraz {_n(part['value'], 2)} (7 d: {part['acute']}, tydz. 28 d: {part['chronic']})",
                  en=f"ratio {part['value']:.2f} (7 d: {part['acute']}, 28-d week: {part['chronic']})")
    if key == "fresh":
        if part.get("hours") is None:
            return tr(pl="brak mocnego treningu w 14 dni", en="no hard session in 14 days")
        hours = part["hours"]
        when = tr(pl=f"{hours} h temu", en=f"{hours} h ago") if hours < 72 else \
            tr(pl=f"{hours // 24} dni temu", en=f"{hours // 24} days ago")
        return f"{catalog.label(part['discipline']).lower()}, {when}"
    return ""


def skipped(item: dict[str, Any]) -> str:
    tr = i18n.tr
    name = catalog.label(item["discipline"])
    if item["reason"] == "season":
        return tr(pl=f"{name} — nie ten sezon", en=f"{name} — out of season")
    if item["reason"] == "needs":
        needs = ", ".join(catalog.condition_label(n) for n in item["needs"])
        return tr(pl=f"{name} — brak: {needs}", en=f"{name} — missing: {needs}")
    if item["reason"] == "too_hard":
        lowest = catalog.level_label(item["lowest"])
        return tr(pl=f"{name} — najlżej to wciąż „{lowest}”", en=f"{name} — even its lightest is “{lowest}”")
    return name
