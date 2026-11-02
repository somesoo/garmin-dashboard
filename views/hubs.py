"""Menu entries that hold two views behind one switch.

Each pair answers one question from two sides, so it has one place in the
menu: the plan and the races it builds toward, running load and the load of
every sport, today's readiness and the disciplines behind it. The views stay
their own modules; this file only picks one. ``bento.switch`` explains how
another page opens a given view.
"""

from __future__ import annotations

import bento
import i18n
from views import form, run_load, run_plan, run_races, sport, sport_disciplines

PLAN, LOAD, SPORT = "plan_view", "load_view", "sport_view"


def plan() -> None:
    import datetime as dt

    import story
    from views import run_common as rc
    tr = i18n.tr
    today = dt.date.today()
    races = rc.upcoming_races(today)
    active = rc.active_plan(today)
    if races:
        days = (dt.date.fromisoformat(str(races[0]["date"])) - today).days
        name = races[0].get("name") or ""
        if active:
            left = sum(1 for s in active.get("sessions", []) if s.get("date", "") >= today.isoformat()
                       and s.get("type") not in ("rest",))
            headline = tr(pl=f"Plan prowadzi do <em>{name}</em> — {days} dni, {left} sesji przed Tobą.",
                          en=f"The plan leads to <em>{name}</em> — {days} days, {left} sessions ahead.")
        else:
            headline = tr(pl=f"Bez planu — {len(races)} startów przed Tobą, najbliższy za <em>{days} dni</em>.",
                          en=f"No plan — {len(races)} races ahead, the next in <em>{days} days</em>.")
    else:
        headline = tr(pl="Bez startów i bez planu.", en="No races and no plan.")
    story.head("plan", headline)
    choice = bento.switch(PLAN, {"plan": i18n.view("plan"), "races": i18n.view("zawody")})
    (run_races if choice == "races" else run_plan).render()


def load() -> None:
    """Fitness and fatigue of every sport as the hero; the two old views behind the details link."""
    import pandas as pd

    import facts
    import herochart as hc
    import shell
    import story
    from running import plan as planning
    from views import run_common as rc

    tr = i18n.tr
    pmc = shell.table("pmc")
    if pmc.empty:
        _load_views()
        return
    pmc = pmc.copy()
    pmc["day"] = pd.to_datetime(pmc["day"])
    start, end = story.long_span(pmc["day"].min(), pmc["day"].max())
    runs = rc.runs()
    told = facts.load(pmc, planning.spike_table(runs) if not runs.empty else None, shell.daily(), start)

    def hero() -> None:
        c = hc.colors()
        view = pmc[(pmc["day"] >= start) & (pmc["day"] <= end)]
        nights = shell.daily().sort_values("day")
        nights["hrv7"] = nights["hrv_last_night"].rolling(7, min_periods=4).mean()
        nights = nights[nights["day"] >= start]
        last = view.iloc[-1]
        panels = [
            {"kind": "lines", "y": [0, max(30.0, float(view["ctl"].max()) * 1.35)], "decimals": 0,
             "lines": [{"points": hc.points(view, "day", "atl", 1), "color": c["warm"], "width": 1, "opacity": 0.6,
                        "name": tr(pl="zmęczenie (ATL)", en="fatigue (ATL)"),
                        "end": tr(pl=f"zmęczenie {last['atl']:.0f}", en=f"fatigue {last['atl']:.0f}")},
                       {"points": hc.points(view, "day", "ctl", 1), "color": c["series"], "width": 3,
                        "name": tr(pl="forma (CTL)", en="fitness (CTL)"), "end_color": "#ffffff",
                        "end": tr(pl=f"forma {last['ctl']:.0f}", en=f"fitness {last['ctl']:.0f}")}]},
            {"kind": "lines", "strip": True, "y": [-45, 25], "decimals": 0,
             "hlines": [{"v": -30, "color": c["warm"], "dash": True}, {"v": 0, "color": "#2c2f36"}],
             "lines": [{"points": hc.points(view, "day", "tsb", 1), "color": c["light"], "width": 1.6,
                        "name": tr(pl="świeżość (TSB)", en="freshness (TSB)")}],
             "label": {"group": tr(pl="Świeżość", en="Freshness"), "head": tr(pl="TSB = forma − zmęczenie", en="TSB = fitness − fatigue"),
                       "note": tr(pl="przerywana linia: −30", en="dashed line: −30")},
             "why": told["whys"].get("tsb", "")},
            {"kind": "lines", "strip": True, "y": hc.span(nights["hrv7"].dropna()), "decimals": 0, "unit": "ms",
             "lines": [{"points": hc.points(nights, "day", "hrv7", 1), "color": c["series"], "width": 2,
                        "name": tr(pl="HRV, średnia 7 nocy", en="HRV, 7-night mean")}],
             "label": {"group": tr(pl="Odpowiedź · Regeneracja", en="Response · Recovery"), "head": tr(pl="HRV, średnia 7 nocy", en="HRV, 7-night mean"),
                       "note": tr(pl="czy ciało niesie to obciążenie", en="is the body carrying this load")},
             "why": told["whys"].get("hrv", "")},
        ]
        satellites = [{**s, "anchor": {"t": hc.ms(s["anchor"][0]), "v": float(s["anchor"][1])} if s["anchor"] else None}
                      for s in told["satellites"]]
        hc.show({"x": [hc.ms(start), hc.ms(end + pd.Timedelta(days=1))], "panels": panels, "satellites": satellites},
                key="hero_obciazenie", token=story.token("obciazenie", start))

    story.frame_page(
        "obciazenie-biegowe", headline=told["headline"],
        sub=tr(pl="Forma (CTL, średnia obciążenia wszystkich sportów z 42 dni) i zmęczenie (ATL, 7 dni). Świeżość — "
                  "różnica między nimi — i HRV są osobnymi panelami pod spodem, na tej samej osi czasu.",
               en="Fitness (CTL, the 42-day average load of every sport) and fatigue (ATL, 7 days). Freshness — the "
                  "difference — and HRV are separate panels below, on the same time axis."),
        hero=hero,
        more=tr(pl="obciążenie biegowe (objętość, intensywność, skoki, przerwy) i forma wszystkich sportów",
                en="running load (volume, intensity, spikes, breaks) and the form of every sport"),
        more_render=_load_views,
    )


def _load_views() -> None:
    choice = bento.switch(LOAD, {"run": i18n.view("obciazenie-biegowe"), "all": i18n.view("forma")})
    (form if choice == "all" else run_load).render()


def sports() -> None:
    import story
    story.head("sport", sport.headline())
    choice = bento.switch(SPORT, {"today": i18n.view("sport"), "disciplines": i18n.view("dyscypliny")})
    (sport_disciplines if choice == "disciplines" else sport).render()
