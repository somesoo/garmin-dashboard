"""Facts for the page heroes (``story.py``): the loop's four numbers and, per page,
the headline and the satellites around its main chart.

Same rules as ``hero.py``: everything is something that happened, measured
against the visitor's own recent normal; nothing suggests what to do. Pure
pandas, every sentence through ``i18n.tr``; a satellite's anchor is a point on
the main chart (``(day, value)``) or ``None`` when the fact has no place on it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

import i18n
import hero
from hero import _clock, _date, _dec, _hm, _num, _span
from running import units

HARD = ("tempo", "threshold", "intervals", "race")
# Loop stages, in order: the stimulus, the body's response, the adaptation, the goal.
STAGES = ("load", "response", "adapt", "goal")


def sat(side: str, group: str, head: str, text: str = "", anchor: tuple[Any, float] | None = None,
        go: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"side": side, "group": group, "head": head, "text": text, "anchor": anchor, "go": go}


def _nights(daily: pd.DataFrame, column: str = "hrv_last_night") -> pd.DataFrame:
    if daily is None or daily.empty or column not in daily.columns:
        return pd.DataFrame()
    frame = daily.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    return frame.dropna(subset=[column]).sort_values("day")


def hrv_change(daily: pd.DataFrame) -> tuple[pd.Series | None, float | None, float | None]:
    """Last night's row, the mean of the 7 nights before it and the change in %."""
    nights = _nights(daily)
    if len(nights) < 4:
        return None, None, None
    last, week = nights.iloc[-1], nights.iloc[-8:-1]
    mean = float(week["hrv_last_night"].mean())
    return last, mean, (float(last["hrv_last_night"]) / mean - 1) * 100 if mean else None


def weekly_km(runs: pd.DataFrame) -> pd.DataFrame:
    """Running volume per ISO week (Monday): ``week, km, hard_km, easy_km, longest, runs``."""
    if runs is None or runs.empty:
        return pd.DataFrame(columns=["week", "km", "hard_km", "easy_km", "longest", "runs"])
    frame = runs.copy()
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    frame["week"] = frame["start_local"].dt.normalize() - pd.to_timedelta(frame["start_local"].dt.weekday, unit="D")
    kinds = frame["kind"] if "kind" in frame.columns else pd.Series("", index=frame.index)
    frame["hard"] = frame["distance_km"].where(kinds.isin(HARD), 0.0)
    out = frame.groupby("week").agg(km=("distance_km", "sum"), hard_km=("hard", "sum"), longest=("distance_km", "max"),
                                    runs=("distance_km", "size")).reset_index()
    out["easy_km"] = out["km"] - out["hard_km"]
    return out


# ------------------------------------------------------------------ the loop

def loop_values(daily: pd.DataFrame, runs: pd.DataFrame, forecast: pd.DataFrame, races: list[dict[str, Any]],
                today: dt.date) -> dict[str, str]:
    """One number per stage of the loop, as text; ``—`` where there is nothing to say."""
    tr = i18n.tr
    values = {key: "—" for key in STAGES}
    if runs is not None and not runs.empty:
        start = pd.to_datetime(runs["start_local"])
        km = float(runs.loc[(start.dt.date > today - dt.timedelta(days=7)) & (start.dt.date <= today), "distance_km"].sum())
        values["load"] = tr(pl=f"{_dec(km, 0)} km / 7 dni", en=f"{_dec(km, 0)} km / 7 days")
    _, _, change = hrv_change(daily)
    if change is not None:
        values["response"] = f"HRV {change:+.0f}%"
    if forecast is not None and not forecast.empty and "distance" in forecast.columns:
        ten = forecast[forecast["distance"] == "10k"].sort_values("day")
        if not ten.empty and _num(ten["realistic_s"].iloc[-1]):
            values["adapt"] = f"10 km: {units.fmt_time(ten['realistic_s'].iloc[-1])}"
    if races:
        days = (dt.date.fromisoformat(str(races[0]["date"])) - today).days
        values["goal"] = tr(pl="dziś start", en="race day") if days == 0 else \
            tr(pl=f"za {days} " + i18n.plural(days, pl=("dzień", "dni", "dni"), en=("day", "days")),
               en=f"in {days} " + i18n.plural(days, pl=("dzień", "dni", "dni"), en=("day", "days")))
    return values


# ------------------------------------------------------------------ Regeneracja

def hard_days(runs: pd.DataFrame) -> set[dt.date]:
    if runs is None or runs.empty or "kind" not in runs.columns:
        return set()
    return set(pd.to_datetime(runs.loc[runs["kind"].isin(HARD), "start_local"]).dt.date)


def recovery(daily: pd.DataFrame, runs: pd.DataFrame, since: pd.Timestamp | None) -> dict[str, Any]:
    """Headline and satellites for the HRV hero on Regeneracja.

    ``daily`` is the full history (the norms need it); ``since`` is where the
    chart starts (the global range), for the "lowest" fact.
    """
    tr = i18n.tr
    last, mean, change = hrv_change(daily)
    out: dict[str, Any] = {"headline": tr(pl="Regeneracja", en="Recovery"), "satellites": [], "whys": {}}
    if last is None:
        return out
    hrv = float(last["hrv_last_night"])
    low, high = _num(last.get("hrv_baseline_low")), _num(last.get("hrv_baseline_high"))
    state = None
    if low is not None and high is not None:
        state = "below" if hrv < low else "above" if hrv > high else "within"
    nights = _nights(daily, "sleep_h")
    short = long_ = False
    if len(nights) >= 4:
        night, week = nights.iloc[-1], nights.iloc[-8:-1]
        short = float(night["sleep_h"]) <= float(week["sleep_h"].min()) and night["day"] == last["day"]
        long_ = float(night["sleep_h"]) >= float(week["sleep_h"].max()) and night["day"] == last["day"]
    word = {"within": tr(pl="w <em>normie</em>", en="<em>within normal</em>"),
            "below": tr(pl="<em>poniżej normy</em>", en="<em>below normal</em>"),
            "above": tr(pl="<em>powyżej normy</em>", en="<em>above normal</em>")}.get(state, "")
    if state == "within" and short:
        out["headline"] = tr(pl=f"HRV trzyma się {word} mimo najkrótszej nocy tygodnia.",
                             en=f"HRV holds {word} despite the shortest night of the week.")
    elif short:
        out["headline"] = tr(pl=f"HRV {word} po najkrótszej nocy tygodnia.", en=f"HRV {word} after the shortest night of the week.")
    elif long_:
        out["headline"] = tr(pl=f"HRV {word} po najdłuższej nocy tygodnia.", en=f"HRV {word} after the longest night of the week.")
    elif state:
        out["headline"] = tr(pl=f"HRV {word} — {change:+.0f}% wobec tygodnia.", en=f"HRV {word} — {change:+.0f}% against the week.")

    sats = out["satellites"]
    norm = tr(pl=f" Norma Garmina: {low:.0f}–{high:.0f}.", en=f" Garmin's normal: {low:.0f}–{high:.0f}.") \
        if low is not None and high is not None else ""
    sats.append(sat("r", tr(pl="Ostatnia noc", en="Last night"),
                    tr(pl=f"{hrv:.0f} ms — {change:+.0f}% wobec tygodnia", en=f"{hrv:.0f} ms — {change:+.0f}% against the week"),
                    tr(pl=f"Średnia 7 poprzednich nocy: {mean:.0f} ms.", en=f"Mean of the 7 nights before: {mean:.0f} ms.") + norm,
                    anchor=(last["day"], hrv)))

    frame = _nights(daily)
    roll = frame.set_index("day")["hrv_last_night"].rolling(7, min_periods=4).mean()
    if since is not None:
        roll = roll[roll.index >= since + pd.Timedelta(days=7)]
    roll = roll.dropna()
    if len(roll) >= 7:
        day, value = roll.idxmin(), float(roll.min())
        row = frame[frame["day"] == day].iloc[0]
        lo = _num(row.get("hrv_baseline_low"))
        where = (tr(pl=" — poniżej normy Garmina.", en=" — below Garmin's normal.") if lo is not None and value < lo
                 else tr(pl=" — wciąż w normie Garmina.", en=" — still within Garmin's normal."))
        sats.append(sat("l", tr(pl="Najniżej", en="Lowest"), f"{_dec(value, 1)} ms · {_date(day)}",
                        tr(pl="Najniższa średnia 7 nocy w tym okresie", en="The lowest 7-night mean in this period") + where,
                        anchor=(day, value)))

    hard = hard_days(runs)
    if hard:
        recent = frame[frame["day"] >= frame["day"].max() - pd.Timedelta(days=180)].copy()
        before = recent["day"].dt.date - dt.timedelta(days=1)
        run_days = set(pd.to_datetime(runs["start_local"]).dt.date) if runs is not None and not runs.empty else set()
        after_hard = recent[before.isin(hard)]["hrv_last_night"]
        rest = recent[~before.isin(run_days)]["hrv_last_night"]
        if len(after_hard) >= 4 and len(rest) >= 10:
            a, b = float(after_hard.mean()), float(rest.mean())
            diff = a - b
            head = (tr(pl=f"{_dec(a, 1)} ms — tyle co zwykle", en=f"{_dec(a, 1)} ms — the same as usual") if abs(diff) < 2 else
                    tr(pl=f"{_dec(a, 1)} ms — o {abs(diff):.0f} ms {'niżej' if diff < 0 else 'wyżej'}",
                       en=f"{_dec(a, 1)} ms — {abs(diff):.0f} ms {'lower' if diff < 0 else 'higher'}"))
            last_hard = max(d for d in hard if pd.Timestamp(d) <= frame["day"].max())
            next_day = pd.Timestamp(last_hard + dt.timedelta(days=1))
            near = frame.iloc[(frame["day"] - next_day).abs().argsort()[:1]]
            sats.append(sat("r", tr(pl="Po mocnym treningu", en="After a hard session"), head,
                            tr(pl=f"Rano po {len(after_hard)} mocnych treningach (180 dni); po dniach bez biegu {_dec(b, 1)} ms.",
                               en=f"The morning after {len(after_hard)} hard sessions (180 days); after days without a run {_dec(b, 1)} ms."),
                            anchor=(near["day"].iloc[0], float(near["hrv_last_night"].iloc[0])),
                            go={"page": "obciazenie-biegowe", "label": tr(pl="Obciążenie", en="Load")}))

    rhr_frame = _nights(daily, "rhr")
    if len(rhr_frame) >= 20:
        rhr = float(rhr_frame["rhr"].iloc[-1])
        window = rhr_frame["rhr"].iloc[-60:]
        lo, hi = float(window.quantile(0.10)), float(window.quantile(0.90))
        status = (tr(pl="w normie", en="within normal") if lo <= rhr <= hi else
                  tr(pl="powyżej normy", en="above normal") if rhr > hi else tr(pl="poniżej normy", en="below normal"))
        sats.append(sat("l", tr(pl="Tętno spoczynkowe", en="Resting heart rate"),
                        f"{rhr:.0f} — {status} ({lo:.0f}–{hi:.0f})",
                        tr(pl="Norma: 10.–90. percentyl z 60 dni. HRV i tętno razem mówią, czy organizm jest obciążony.",
                           en="Normal: the 10th–90th percentile of 60 days. HRV and heart rate together tell whether the body is strained.")))
    return out


def recovery_whys(daily: pd.DataFrame, weeks: pd.DataFrame) -> dict[str, str]:
    """The one-line links of the strips under the HRV hero (weekly km, sleep)."""
    tr = i18n.tr
    whys: dict[str, str] = {}
    if weeks is not None and not weeks.empty:
        top = weeks.loc[weeks["km"].idxmax()]
        start = pd.Timestamp(top["week"])
        nights = _nights(daily)
        inside = nights[(nights["day"] > start) & (nights["day"] <= start + pd.Timedelta(days=8))]
        if not inside.empty:
            within = ((inside["hrv_last_night"] >= inside["hrv_baseline_low"]) &
                      (inside["hrv_last_night"] <= inside["hrv_baseline_high"])).mean()
            whys["load"] = tr(pl=f"najwięcej {_dec(top['km'], 0)} km w tyg. od {_date(start)}; w kolejnych nocach HRV w normie {within * 100:.0f}% nocy.",
                              en=f"the most, {_dec(top['km'], 0)} km, in the week of {_date(start)}; the following nights HRV was within normal {within * 100:.0f}% of the time.")
    nights = _nights(daily, "sleep_h")
    if len(nights) >= 2:
        last, prev = nights.iloc[-1], nights.iloc[-2]
        r, rp = _num(last.get("readiness")), _num(prev.get("readiness"))
        text = tr(pl=f"ostatnia noc {_hm(float(last['sleep_h']))}", en=f"last night {_hm(float(last['sleep_h']))}")
        if r is not None and rp is not None:
            text += tr(pl=f"; readiness {rp:.0f} → {r:.0f}.", en=f"; readiness {rp:.0f} → {r:.0f}.")
        whys["sleep"] = text
    return whys



# ------------------------------------------------------------------ Przegląd biegania

GAP_WEEKS = 3      # this many weeks without a run is a break
LONG_GAP = 6       # and from this many it is labelled on the chart


def calendar_weeks(weeks: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Every Monday from ``start`` to ``end``, with zeros where nothing was run."""
    first = (start - pd.Timedelta(days=start.weekday())).normalize()
    monday = pd.date_range(first, end, freq="7D")
    out = pd.DataFrame({"week": monday})
    if weeks is not None and not weeks.empty:
        out = out.merge(weeks, on="week", how="left")
    for column in ("km", "hard_km", "easy_km", "longest", "runs"):
        out[column] = out[column].fillna(0) if column in out.columns else 0.0
    return out


def breaks(calendar: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Runs of empty weeks of at least ``GAP_WEEKS``: (first empty Monday, the Monday running resumed, weeks)."""
    out, start = [], None
    for index, row in calendar.reset_index(drop=True).iterrows():
        if row["km"] <= 0:
            start = index if start is None else start
            continue
        if start is not None and index - start >= GAP_WEEKS:
            out.append((calendar["week"].iloc[start], row["week"], index - start))
        start = None
    return out


def _ctl_at(pmc: pd.DataFrame, day: pd.Timestamp) -> float | None:
    if pmc is None or pmc.empty:
        return None
    frame = pmc.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    row = frame[frame["day"] <= day].tail(1)
    return float(row["ctl"].iloc[0]) if not row.empty and pd.notna(row["ctl"].iloc[0]) else None


def _long_breaks_phrase(n: int) -> str:
    tr = i18n.tr
    if n == 1:
        return tr(pl="jedna długa przerwa", en="one long break")
    if n == 2:
        return tr(pl="dwie długie przerwy", en="two long breaks")
    if n == 3:
        return tr(pl="trzy długie przerwy", en="three long breaks")
    if n == 4:
        return tr(pl="cztery długie przerwy", en="four long breaks")
    return tr(pl=f"{n} długich przerw", en=f"{n} long breaks")


def running_year(runs: pd.DataFrame, pmc: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    """Headline, satellites and breaks for the weekly-volume hero on Przegląd biegania."""
    tr = i18n.tr
    calendar = calendar_weeks(weekly_km(runs), start, end)
    gaps = breaks(calendar)
    out: dict[str, Any] = {"calendar": calendar, "gaps": gaps, "back": None, "satellites": [], "whys": {},
                           "headline": i18n.page("bieganie")}
    if calendar["km"].sum() <= 0:
        return out
    frame = runs.copy()
    frame["start_local"] = pd.to_datetime(frame["start_local"])
    inside = frame[(frame["start_local"] >= calendar["week"].iloc[0]) & (frame["start_local"] <= end + pd.Timedelta(days=1))]
    back = gaps[-1][1] if gaps else calendar.loc[calendar["km"] > 0, "week"].iloc[0]
    out["back"] = back
    since = inside[inside["start_local"] >= back]
    back_weeks = calendar[calendar["week"] >= back]
    weeks_back = max(1, len(back_weeks))
    sats = out["satellites"]

    long_gaps = [g for g in gaps if g[2] >= LONG_GAP]
    if long_gaps and gaps and gaps[-1][1] <= end:
        out["headline"] = tr(pl=f"Ten okres to {_long_breaks_phrase(len(long_gaps))} — i <em>{weeks_back} tyg.</em> od powrotu.",
                             en=f"This period is {_long_breaks_phrase(len(long_gaps))} — and <em>{weeks_back} weeks</em> since the return.")
    else:
        out["headline"] = tr(pl=f"<em>{_dec(calendar['km'].sum(), 0)} km</em> w {len(calendar)} tygodni — {len(inside)} biegów.",
                             en=f"<em>{_dec(calendar['km'].sum(), 0)} km</em> in {len(calendar)} weeks — {len(inside)} runs.")

    if not inside.empty:
        top = inside.loc[inside["distance_km"].idxmax()]
        week = top["start_local"].normalize() - pd.Timedelta(days=top["start_local"].weekday())
        week_km = float(calendar.loc[calendar["week"] == week, "km"].sum()) or float(top["distance_km"])
        text = tr(pl=f"Tempo {units.fmt_pace(top['pace_min_km'], unit=False)}/km.", en=f"Pace {units.fmt_pace(top['pace_min_km'], unit=False)}/km.")
        if len(since) and since["start_local"].min() > top["start_local"]:
            text += tr(pl=f" Od powrotu najdłużej {_dec(since['distance_km'].max(), 1)} km.",
                       en=f" Since the return, the longest {_dec(since['distance_km'].max(), 1)} km.")
        sats.append(sat("l", tr(pl="Najdłuższy w tym okresie", en="Longest in this period"),
                        f"{_dec(top['distance_km'], 1)} km · {_date(top['start_local'])}", text, anchor=(week, week_km)))
    if gaps:
        first, last, n = max(gaps, key=lambda g: g[2])
        before, after = _ctl_at(pmc, first), _ctl_at(pmc, last)
        text = f"{_date(first)}–{_date(last)}."
        if before is not None and after is not None:
            # CTL counts every sport: a running break with cycling in it can leave fitness where it was, or raise it.
            if after < before - 1:
                text += tr(pl=f" Forma (CTL) spadła w tym czasie z {before:.0f} do {after:.0f}.",
                           en=f" Fitness (CTL) fell from {before:.0f} to {after:.0f} in that time.")
            else:
                text += tr(pl=f" Forma (CTL) nie spadła: {before:.0f} → {after:.0f} — liczą się też inne sporty.",
                           en=f" Fitness (CTL) did not drop: {before:.0f} → {after:.0f} — other sports count too.")
        middle = first + (last - first) / 2
        sats.append(sat("l", tr(pl="Najdłuższa przerwa", en="Longest break"),
                        tr(pl=f"{n} tygodni bez biegu", en=f"{n} weeks without a run"), text,
                        anchor=(middle, float(calendar["km"].max()) * 0.55)))
    if len(since):
        km = float(since["distance_km"].sum())
        sats.append(sat("r", tr(pl=f"Od powrotu {_date(back)}", en=f"Since the return {_date(back)}"),
                        tr(pl=f"{_dec(km, 1)} km w {len(since)} biegach", en=f"{_dec(km, 1)} km in {len(since)} runs"),
                        tr(pl=f"~{_dec(km / weeks_back, 0)} km tygodniowo; najwięcej {int(back_weeks['runs'].max())} biegi w tygodniu.",
                           en=f"~{_dec(km / weeks_back, 0)} km a week; at most {int(back_weeks['runs'].max())} runs in a week."),
                        anchor=(back + (end - back) / 2, float(back_weeks["km"].max()))))
        zones = [f"hr_z{i}_s" for i in range(1, 6)]
        if all(z in since.columns for z in zones) and since[zones].sum().sum() > 0:
            total = since[zones].sum().sum()
            easy = (since["hr_z1_s"].sum() + since["hr_z2_s"].sum()) / total * 100
            mid = since["hr_z3_s"].sum() / total * 100
            hard = since["distance_km"].where(since["kind"].isin(HARD), 0).sum() / km * 100 if km else 0
            sats.append(sat("r", tr(pl="Jak mocno", en="How hard"),
                            tr(pl=f"{hard:.0f}% km to treningi jakościowe", en=f"{hard:.0f}% of the km are quality sessions"),
                            tr(pl=f"Według tętna {easy:.0f}% czasu w strefach 1–2, {mid:.0f}% w strefie 3.",
                               en=f"By heart rate {easy:.0f}% of the time in zones 1–2, {mid:.0f}% in zone 3."),
                            go={"page": "obciazenie-biegowe", "label": tr(pl="Obciążenie", en="Load")}))
    if pmc is not None and not pmc.empty:
        frame = pmc.copy()
        frame["day"] = pd.to_datetime(frame["day"])
        peak = frame.loc[frame["ctl"].idxmax()]
        now = float(frame["ctl"].iloc[-1])
        out["whys"]["ctl"] = tr(pl=f"każda przerwa obniża formę; dziś {now:.0f}, czyli {now / peak['ctl'] * 100:.0f}% szczytu ({_date(peak['day'])}.{peak['day'].year}).",
                                en=f"every break lowers fitness; today {now:.0f}, {now / peak['ctl'] * 100:.0f}% of the peak ({_date(peak['day'])}.{peak['day'].year}).")
    return out


# ------------------------------------------------------------------ Obciążenie

def load(pmc: pd.DataFrame, spikes: pd.DataFrame, daily: pd.DataFrame, start: pd.Timestamp) -> dict[str, Any]:
    """Headline and satellites for the fitness / fatigue hero on Obciążenie."""
    tr = i18n.tr
    out: dict[str, Any] = {"headline": tr(pl="Obciążenie", en="Load"), "satellites": [], "whys": {}}
    if pmc is None or pmc.empty:
        return out
    frame = pmc.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    all_time_peak = frame.loc[frame["ctl"].idxmax()]
    view = frame[frame["day"] >= start]
    if view.empty:
        return out
    last = view.iloc[-1]
    ctl, atl, tsb = float(last["ctl"]), float(last["atl"]), float(last["tsb"])
    recent = view[view["day"] >= last["day"] - pd.Timedelta(days=120)]
    low = recent.loc[recent["ctl"].idxmin()]
    high = recent.loc[recent["ctl"].idxmax()]
    share = ctl / float(all_time_peak["ctl"]) * 100 if all_time_peak["ctl"] else 0
    sats = out["satellites"]
    if ctl - float(low["ctl"]) >= 2 and low["day"] < last["day"]:
        weeks = max(1, round((last["day"] - low["day"]).days / 7))
        out["headline"] = tr(pl=f"Forma rośnie od {weeks} tyg., ale to wciąż <em>{share:.0f}% szczytu</em> z {all_time_peak['day'].year}.",
                             en=f"Fitness has been rising for {weeks} weeks, but it is still <em>{share:.0f}% of the peak</em> of {all_time_peak['day'].year}.")
        sats.append(sat("r", tr(pl=f"Od {_date(low['day'])}", en=f"Since {_date(low['day'])}"),
                        tr(pl=f"+{_dec(ctl - float(low['ctl']), 1)} w {weeks} tyg.", en=f"+{_dec(ctl - float(low['ctl']), 1)} in {weeks} weeks"),
                        tr(pl=f"Z {_dec(float(low['ctl']), 1)} do {_dec(ctl, 1)} dziś.", en=f"From {_dec(float(low['ctl']), 1)} to {_dec(ctl, 1)} today."),
                        anchor=(low["day"], float(low["ctl"]))))
    elif float(high["ctl"]) - ctl >= 2:
        weeks = max(1, round((last["day"] - high["day"]).days / 7))
        out["headline"] = tr(pl=f"Forma spada od {weeks} tyg. — dziś <em>{share:.0f}% szczytu</em>.",
                             en=f"Fitness has been falling for {weeks} weeks — <em>{share:.0f}% of the peak</em> today.")
        sats.append(sat("r", tr(pl=f"Od {_date(high['day'])}", en=f"Since {_date(high['day'])}"),
                        tr(pl=f"−{_dec(float(high['ctl']) - ctl, 1)} w {weeks} tyg.", en=f"−{_dec(float(high['ctl']) - ctl, 1)} in {weeks} weeks"),
                        "", anchor=(high["day"], float(high["ctl"]))))
    else:
        out["headline"] = tr(pl=f"Forma stoi — <em>{share:.0f}% szczytu</em> z {all_time_peak['day'].year}.",
                             en=f"Fitness is flat — <em>{share:.0f}% of the peak</em> of {all_time_peak['day'].year}.")
    # The peak the headline measures against: tied to its point when it is on the chart, named when it is not.
    peak = all_time_peak
    inside = peak["day"] >= start
    sats.append(sat("l", tr(pl="Szczyt formy", en="Peak fitness"),
                    f"{peak['ctl']:.0f} · {_date(peak['day'])}.{peak['day'].year}",
                    tr(pl="Najwyższa forma (CTL) w całej historii.", en="The highest fitness (CTL) in the whole history.")
                    + ("" if inside else tr(pl=" Przed wybranym zakresem.", en=" Before the selected range.")),
                    anchor=(peak["day"], float(peak["ctl"])) if inside else None))
    sats.append(sat("r", tr(pl="Dziś", en="Today"),
                    tr(pl=f"Zmęczenie {atl:.0f} {'>' if atl > ctl else '<'} forma {ctl:.0f}",
                       en=f"Fatigue {atl:.0f} {'>' if atl > ctl else '<'} fitness {ctl:.0f}"),
                    tr(pl=f"Świeżość (forma − zmęczenie): {tsb:.0f}.", en=f"Freshness (fitness − fatigue): {tsb:.0f}."),
                    anchor=(last["day"], ctl)))
    if spikes is not None and not spikes.empty:
        row = spikes.iloc[-1]
        if pd.notna(row.get("longest_30d_km")) and row.get("longest_30d_km"):
            sign = ">" if row["spike"] else "≤"
            sats.append(sat("l", tr(pl="Reguła pojedynczego biegu", en="Single-run rule"),
                            f"{_dec(row['km'], 1)} km {sign} {_dec(1.1, 1)} × {_dec(row['longest_30d_km'], 1)}",
                            tr(pl=f"Ostatni bieg ({_date(row['day'])}) wobec najdłuższego z 30 dni przed nim.",
                               en=f"The last run ({_date(row['day'])}) against the longest of the 30 days before it.")))
    lowest = view.loc[view["tsb"].idxmin()]
    out["whys"]["tsb"] = tr(pl=f"najniżej {lowest['tsb']:.0f} ({_date(lowest['day'])}.{lowest['day'].year}): zmęczenie {lowest['atl']:.0f} przy formie {lowest['ctl']:.0f}.",
                            en=f"the lowest {lowest['tsb']:.0f} ({_date(lowest['day'])}.{lowest['day'].year}): fatigue {lowest['atl']:.0f} at fitness {lowest['ctl']:.0f}.")
    nights = _nights(daily)
    nights = nights[nights["day"] >= start]
    if len(nights) >= 14:
        roll = nights["hrv_last_night"].rolling(7, min_periods=4).mean().dropna()
        out["whys"]["hrv"] = tr(pl=f"średnia 7 nocy w tym okresie między {roll.min():.0f} a {roll.max():.0f} ms.",
                                en=f"the 7-night mean in this period ranged {roll.min():.0f}–{roll.max():.0f} ms.")
    return out



# ------------------------------------------------------------------ Rytm i sen

def sleep(daily: pd.DataFrame, circadian: pd.DataFrame, since: pd.Timestamp | None, today: dt.date) -> dict[str, Any]:
    """Headline and satellites for the sleep-length hero (the night facts are hero.py's, said the same way)."""
    tr = i18n.tr
    out: dict[str, Any] = {"headline": i18n.page("sen"), "satellites": [], "whys": {}}
    nights = _nights(daily, "sleep_h")
    if len(nights) < 4:
        return out
    last, week = nights.iloc[-1], nights.iloc[-8:-1]
    hours, usual = float(last["sleep_h"]), float(week["sleep_h"].mean())
    told = {f["key"]: f for f in hero.night_facts(daily, circadian, last["day"].date())}
    bed = told.get("bed")
    later = ""
    if circadian is not None and not circadian.empty:
        rhythm = circadian.copy()
        rhythm["day"] = pd.to_datetime(rhythm["day"])
        this = rhythm[rhythm["day"] == last["day"]]
        before = rhythm[(rhythm["day"] < last["day"]) & (rhythm["day"] >= last["day"] - pd.Timedelta(days=7))]
        if not this.empty and len(before) >= 3 and pd.notna(this["bed_hour_cont"].iloc[0]):
            diff = (float(this["bed_hour_cont"].iloc[0]) - float(before["bed_hour_cont"].mean())) * 60
            if diff >= 30:
                later = tr(pl=f" — zaśnięcie {_span(diff)} później niż zwykle", en=f" — asleep {_span(diff)} later than usual")
            elif diff <= -30:
                later = tr(pl=f" — zaśnięcie {_span(diff)} wcześniej niż zwykle", en=f" — asleep {_span(diff)} earlier than usual")
            out["whys"]["bed"] = tr(pl=f"w tym tygodniu zwykle {_clock(float(before['bed_hour_cont'].mean()))}, ostatnio {_clock(float(this['bed_hour_cont'].iloc[0]))}.",
                                    en=f"usually {_clock(float(before['bed_hour_cont'].mean()))} this week, last night {_clock(float(this['bed_hour_cont'].iloc[0]))}.")
    if hours <= float(week["sleep_h"].min()):
        out["headline"] = tr(pl=f"Najkrótsza noc tygodnia: <em>{_hm(hours)}</em>{later}.", en=f"The shortest night of the week: <em>{_hm(hours)}</em>{later}.")
    elif hours >= float(week["sleep_h"].max()):
        out["headline"] = tr(pl=f"Najdłuższa noc tygodnia: <em>{_hm(hours)}</em>{later}.", en=f"The longest night of the week: <em>{_hm(hours)}</em>{later}.")
    else:
        word = tr(pl="więcej", en="more") if hours >= usual else tr(pl="mniej", en="less")
        out["headline"] = tr(pl=f"Sen <em>{_hm(hours)}</em> — {_span(abs(hours - usual) * 60)} {word} niż średnio w tygodniu{later}.",
                             en=f"<em>{_hm(hours)}</em> of sleep — {_span(abs(hours - usual) * 60)} {word} than the week's average{later}.")
    sats = out["satellites"]
    if "sleep" in told:
        f = told["sleep"]
        sats.append(sat("r", f["group"], f["head"], f["text"], anchor=(last["day"], hours)))
    if bed:
        sats.append(sat("r", bed["group"], bed["head"], bed["text"]))
    view = nights if since is None else nights[nights["day"] >= since]
    if len(view) >= 7:
        low = view.loc[view["sleep_h"].idxmin()]
        sats.append(sat("l", tr(pl="Najkrótsza w tym okresie", en="The shortest in this period"),
                        f"{_hm(float(low['sleep_h']))} · {_date(low['day'])}",
                        tr(pl=f"Średnio w okresie {_hm(float(view['sleep_h'].mean()))}.", en=f"{_hm(float(view['sleep_h'].mean()))} on average in the period."),
                        anchor=(low["day"], float(low["sleep_h"]))))
    if "deep" in told:
        f = told["deep"]
        sats.append(sat("l", f["group"], f["head"], f["text"]))
    _, _, change = hrv_change(daily)
    if change is not None:
        out["whys"]["hrv"] = tr(pl=f"HRV ostatniej nocy {change:+.0f}% wobec 7 poprzednich.", en=f"last night's HRV {change:+.0f}% against the 7 before.")
    return out


# ------------------------------------------------------------------ Prognoza

def forecast(history: pd.DataFrame, races: list[dict[str, Any]], since: pd.Timestamp | None) -> dict[str, Any]:
    """Headline and satellites for the race-time hero: the realistic time for the next race's distance over time."""
    tr = i18n.tr
    from running import text as rtext
    key = str(races[0]["distance"]) if races else "10k"
    out: dict[str, Any] = {"headline": i18n.page("prognoza"), "satellites": [], "whys": {}, "distance": key}
    if history is None or history.empty:
        return out
    frame = history.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame[frame["distance"] == key].dropna(subset=["realistic_s"]).sort_values("day")
    if frame.empty:
        return out
    view = frame if since is None else frame[frame["day"] >= since]
    view = view if len(view) >= 2 else frame.tail(8)
    out["view"] = view
    last = view.iloc[-1]
    label = rtext.race_label(key)
    time = units.fmt_time(last["realistic_s"])
    earlier = frame[frame["day"] <= last["day"] - pd.Timedelta(days=56)].tail(1)
    if not earlier.empty:
        delta = float(last["realistic_s"] - earlier["realistic_s"].iloc[0])
        if abs(delta) < 15:
            out["headline"] = tr(pl=f"Na {label} realnie <em>{time}</em> — tyle co 8 tygodni temu.",
                                 en=f"{label}: realistically <em>{time}</em> — the same as 8 weeks ago.")
        else:
            word = tr(pl="szybciej", en="faster") if delta < 0 else tr(pl="wolniej", en="slower")
            out["headline"] = tr(pl=f"Na {label} realnie <em>{time}</em> — {units.fmt_time(abs(delta))} {word} niż 8 tygodni temu.",
                                 en=f"{label}: realistically <em>{time}</em> — {units.fmt_time(abs(delta))} {word} than 8 weeks ago.")
    else:
        out["headline"] = tr(pl=f"Na {label} realnie <em>{time}</em>.", en=f"{label}: realistically <em>{time}</em>.")
    sats = out["satellites"]
    sats.append(sat("r", tr(pl="Dziś", en="Today"), f"{label}: {time}",
                    tr(pl=f"80% przedziału: {units.fmt_time(last['low_s'])}–{units.fmt_time(last['high_s'])}.",
                       en=f"80% range: {units.fmt_time(last['low_s'])}–{units.fmt_time(last['high_s'])}."),
                    anchor=(last["day"], float(last["realistic_s"]))))
    best = view.loc[view["realistic_s"].idxmin()]
    if best["day"] != last["day"]:
        sats.append(sat("l", tr(pl="Najlepiej w tym okresie", en="Best in this period"),
                        f"{units.fmt_time(best['realistic_s'])} · {_date(best['day'])}.{best['day'].year}",
                        tr(pl="Najszybsza realna prognoza w wybranym zakresie.", en="The fastest realistic forecast in the selected range."),
                        anchor=(best["day"], float(best["realistic_s"]))))
    if races and _num(races[0].get("goal_s")):
        goal = float(races[0]["goal_s"])
        gap = float(last["realistic_s"]) - goal
        name = str(races[0].get("name") or "")
        text = (tr(pl=f"Prognoza jest o {units.fmt_time(gap)} wolniejsza niż cel.", en=f"The forecast is {units.fmt_time(gap)} slower than the goal.")
                if gap > 0 else tr(pl=f"Prognoza jest o {units.fmt_time(-gap)} szybsza niż cel.", en=f"The forecast is {units.fmt_time(-gap)} faster than the goal."))
        sats.append(sat("r", tr(pl=f"Cel: {name}", en=f"Goal: {name}"), units.fmt_time(goal), text,
                        go={"page": "plan", "switch": "plan_view", "view": "races", "label": tr(pl="Zawody i cele", en="Races and goals")}))
    if _num(last.get("vdot")):
        vdot_then = _num(earlier["vdot"].iloc[0]) if not earlier.empty else None
        text = tr(pl=f"8 tygodni temu {_dec(vdot_then, 1)}.", en=f"{_dec(vdot_then, 1)} 8 weeks ago.") if vdot_then else ""
        sats.append(sat("l", "VDOT", _dec(float(last["vdot"]), 1),
                        tr(pl="Waluta prognozy (Daniels): jedna liczba na wszystkie dystanse. ", en="The forecast's currency (Daniels): one number for every distance. ") + text))
    return out


# ------------------------------------------------------------------ Fizjologia

def physio(efficiency: pd.DataFrame, since: pd.Timestamp | None) -> dict[str, Any]:
    """Headline and satellites for the running-economy hero: metres per heartbeat, run by run."""
    tr = i18n.tr
    out: dict[str, Any] = {"headline": i18n.page("fizjologia"), "satellites": [], "whys": {}}
    if efficiency is None or efficiency.empty:
        return out
    frame = efficiency.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame.dropna(subset=["ef"]).sort_values("day")
    view = frame if since is None else frame[frame["day"] >= since]
    if len(view) < 3:
        return out
    out["view"] = view
    last = view.dropna(subset=["ef_roll10"]).iloc[-1] if view["ef_roll10"].notna().any() else view.iloc[-1]
    now = float(last["ef_roll10"] if pd.notna(last.get("ef_roll10")) else last["ef"])
    before = frame[frame["day"] <= last["day"] - pd.Timedelta(days=90)].dropna(subset=["ef_roll10"]).tail(1)
    if not before.empty:
        then = float(before["ef_roll10"].iloc[0])
        change = (now / then - 1) * 100
        word = (tr(pl="rośnie", en="is rising") if change >= 2 else tr(pl="spada", en="is falling") if change <= -2
                else tr(pl="stoi", en="is flat"))
        out["headline"] = tr(pl=f"Ekonomia biegu {word}: <em>{_dec(now, 2)} m na uderzenie</em> ({change:+.0f}% wobec 3 miesięcy temu).",
                             en=f"Running economy {word}: <em>{_dec(now, 2)} m per beat</em> ({change:+.0f}% against 3 months ago).")
    sats = out["satellites"]
    run = view.iloc[-1]
    sats.append(sat("r", tr(pl="Ostatni bieg", en="The last run"), f"{_dec(float(run['ef']), 2)} m · {_date(run['day'])}",
                    tr(pl=f"{_dec(float(run['distance_km']), 1)} km, tętno {run['avg_hr']:.0f}. Średnia 10 biegów: {_dec(now, 2)}.",
                       en=f"{_dec(float(run['distance_km']), 1)} km, heart rate {run['avg_hr']:.0f}. Mean of 10 runs: {_dec(now, 2)}."),
                    anchor=(run["day"], float(run["ef"]))))
    # A 2 km jog with a lagging heart rate is not an economy record: runs of 3 km and more.
    longer = view[view["distance_km"] >= 3]
    pool = longer if not longer.empty else view
    best = pool.loc[pool["ef"].idxmax()]
    sats.append(sat("l", tr(pl="Najwyżej w tym okresie", en="Highest in this period"), f"{_dec(float(best['ef']), 2)} m · {_date(best['day'])}",
                    tr(pl=f"{_dec(float(best['distance_km']), 1)} km przy tętnie {best['avg_hr']:.0f}.",
                       en=f"{_dec(float(best['distance_km']), 1)} km at heart rate {best['avg_hr']:.0f}."),
                    anchor=(best["day"], float(best["ef"]))))
    sats.append(sat("l", tr(pl="Jak czytać", en="How to read it"), tr(pl="Nie każdy wzrost to postęp", en="Not every rise is progress"),
                    tr(pl="EF rośnie też wtedy, gdy biegasz szybciej na wyższym tętnie — porównuj biegi o podobnym tętnie.",
                       en="EF also rises when you run faster at a higher heart rate — compare runs at a similar heart rate.")))
    return out
