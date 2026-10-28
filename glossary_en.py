"""English text of the glossary: the same keys as ``glossary.TERMS``.

Each entry is ``(name, what, why, read)`` in the order of ``glossary.Term``;
``tests/test_i18n.py`` checks that every Polish entry has one here and that a
field filled in Polish is filled in English.
"""

from __future__ import annotations

GROUPS = {
    "Regeneracja": "Recovery",
    "Obciążenie i forma": "Load and form",
    "Wydolność": "Fitness",
    "Prognoza i bieganie": "Forecast and running",
    "Sen i rytm dobowy": "Sleep and daily rhythm",
    "Statystyka": "Statistics",
}

TERMS: dict[str, tuple[str, str, str, str]] = {
    # ---- Recovery
    "readiness": (
        "Readiness (training readiness)",
        "Garmin's 0–100 score built from HRV, sleep, resting heart rate, recent load "
        "and the time since the last hard session.",
        "Suggests whether today your body will absorb a hard session or an easy one is the better call.",
        "Above ~75 — green light for quality. 50–75 — a normal day. Below ~40 — an easy day "
        "or rest. A run of several days matters more than a single reading.",
    ),
    "hrv": (
        "HRV (heart rate variability)",
        "How much the gaps between consecutive heartbeats vary, measured overnight (ms). "
        "High variability = the nervous system is in rest mode.",
        "The most sensitive recovery signal: it drops after hard training, illness, alcohol, stress.",
        "Only meaningful against your own normal (the grey band) — values differ between people "
        "several times over. Several days below the band = the body is not keeping up.",
    ),
    "rhr": (
        "RHR (resting heart rate)",
        "The lowest sustained heart rate of the day, usually at night.",
        "Rises with fatigue, illness, dehydration and heat; falls slowly as fitness grows.",
        "A rise of 5+ beats above your own average is a warning sign. Here down is good.",
    ),
    "sleep_score": (
        "Sleep score",
        "Garmin's 0–100 score: duration, stages (deep, REM), awakenings and stress during the night.",
        "Sleep is the main source of recovery — a worse night lowers the next day's readiness.",
        "80+ good, 60–80 average, below 60 poor.",
    ),
    "body_battery": (
        "Body Battery",
        "Garmin's 0–100 estimate of “how much energy is left”: charges during sleep and rest, "
        "drains with effort and stress.",
        "Shows whether the night really refilled the reserves after the day.",
        "What counts is the morning peak (how well the night charged) and the evening low "
        "(what the day cost).",
    ),
    "stress": (
        "Stress",
        "Garmin's 0–100 score from daytime HRV: high when the sympathetic system dominates "
        "(effort, nerves, digestion, coffee).",
        "A lot of stress by day and by night slows recovery regardless of training.",
        "A daily average below ~25 is calm. Stress during sleep should be low — if it is not, "
        "the night does not restore.",
    ),
    "quadrants": (
        "Recovery quadrants",
        "Each day placed by two deviations from your own 60-day baseline: HRV (horizontal axis) and "
        "resting heart rate (vertical axis).",
        "Together they say more than apart: high HRV with low heart rate is good recovery, "
        "the reverse — strain.",
        "Recovered: HRV ↑ RHR ↓. Strained: HRV ↓ RHR ↑ (back off). Aroused: both ↑ "
        "(stress, coffee, heat). Suppressed: both ↓ (can follow very heavy fatigue).",
    ),
    "deviation": (
        "Deviation from normal",
        "The difference between today's value and your own average of the last few days.",
        "Compares you with you, not with a table — the only way HRV and heart rate make sense.",
        "Zero = a typical day. Values in σ (standard deviations): ±1 is common, ±2 rare.",
    ),
    # ---- Load and form
    "training_load": (
        "Load (training load)",
        "Garmin's number (EPOC) for how much a session “cost” the body — grows with time and intensity.",
        "A common currency for different sessions: an easy 10 km and 5 km of intervals become comparable.",
        "An easy run is usually 50–100, a hard one 150–250+.",
    ),
    "ctl": (
        "CTL — fitness",
        "Average load over the last ~6 weeks (exponential, 42 days).",
        "Shows how much training your body is used to handling — “fitness” as a number.",
        "Rises slowly when you train regularly; falls during a break. Higher = more base built.",
    ),
    "atl": (
        "ATL — fatigue",
        "Average load over the last week (exponential, 7 days).",
        "Shows fresh fatigue — it reacts to every hard week.",
        "Higher than CTL = lately you have been training more than you are used to.",
    ),
    "tsb": (
        "TSB — form (freshness)",
        "CTL minus ATL: fitness less fatigue.",
        "Before a race you want a positive TSB — rested while keeping your fitness.",
        "Below −30 overload, −30…−10 building form (normal in training), −10…+5 neutral, "
        "+5…+25 fresh (a good moment to race), above +25 detraining. A model, not a measurement.",
    ),
    "ramp": (
        "CTL gain / 7 days",
        "How much fitness (CTL) grew in the last week.",
        "Building form too fast is the classic road to injury.",
        "Up to ~5 points a week is safe; more for several weeks in a row is risky.",
    ),
    "acwr": (
        "ACWR (acute to chronic workload ratio)",
        "Last week's load divided by the average of the last 4 weeks.",
        "Shows whether the last week was bigger than usual. As an injury predictor it does not work: in the "
        "Garmin-RUNSAFE study (BJSM 2025) the week-to-week ratio showed no link with injuries, and the 0.8–1.3 "
        "“safe band” was also criticised for mathematical coupling (the same week in numerator and denominator).",
        "0.8–1.3 — gradual increase; above 1.5 — clearly more than usual. A description, not a limit: the risk shows "
        "rather in a single run longer than 1.1× the longest of 30 days.",
    ),
    "run_ratio": (
        "Km 7 d / 28-day average",
        "The same idea as ACWR, counted from running kilometres only.",
        "Tendons and bones respond to running kilometres, not to cycling or the gym.",
        "0.8–1.3 — a steady increase; above 1.5 — sharply more than usual. It describes the rate of increase, it is "
        "not a safety threshold — the plan watches the length of a single run (1.1× the longest of 30 days).",
    ),
    "monotony": (
        "Monotony (Foster)",
        "Average daily load in a week divided by its variability.",
        "A week where every day is alike (no easy days) tires you more than the total suggests.",
        "Below 1.5 — hard and easy days well mixed. Above 2 — too little difference between days.",
    ),
    "strain": (
        "Strain (Foster)",
        "Weekly load total × monotony.",
        "Combines quantity and lack of variety into one number for the risk of overreaching.",
        "Compare with your own weeks — a jump well above the usual level is a signal.",
    ),
    "banister": (
        "Banister model",
        "A model in which every session builds fitness (decays slowly) and fatigue "
        "(decays fast) at the same time; fitted to your data.",
        "Gives your body's time constants and an estimate of how many days to taper before a race.",
        "Look at R² first: below ~0.3 the model describes your data poorly and the numbers under it "
        "are rough.",
    ),
    "intensity": (
        "Intensity distribution",
        "What share of the week's time was spent in easy (1–2), middle (3) and hard (4–5) zones.",
        "For amateurs most progress comes from lots of easy running and very little truly hard work.",
        "About 75–80% easy is a healthy model. Lots of zone 3 is the “grey zone” — too hard to recover, "
        "too easy to be a stimulus.",
    ),
    "hr_zones": (
        "Heart rate zones",
        "Five heart rate ranges from the watch settings, from 1 (very easy) to 5 (maximal).",
        "Let you check whether a session had the intended intensity.",
        "Easy run: mostly 1–2. Threshold: 4. Intervals: 4–5.",
    ),
    "te": (
        "Training Effect (TE)",
        "Garmin's 0–5 score of how strongly a session stimulated aerobic and anaerobic fitness.",
        "Says whether the session was a stimulus or just maintenance.",
        "Below 2 — recovery, 2–3 maintaining, 3–4 improving, 4–5 highly improving, 5 — overreaching.",
    ),
    # ---- Fitness
    "vo2max": (
        "VO₂max",
        "Garmin's estimate of how much oxygen the body can use per minute per kg — the ceiling of "
        "aerobic fitness.",
        "The simplest measure of the “engine”; higher usually means faster times at every distance.",
        "Changes over weeks. A jump of 1–2 in a few days is usually heat, terrain or a measurement error.",
    ),
    "cs": (
        "CS — critical speed",
        "The fastest pace that in theory can be held for a long time without mounting acidosis; "
        "computed from your best efforts.",
        "Close to threshold pace — a good anchor for tempo sessions.",
        "Trustworthy when R² is high and the fit rests on several different distances.",
    ),
    "d_prime": (
        "D′ — anaerobic reserve",
        "How many metres you can run faster than CS before you have to slow down.",
        "Speaks to the finishing kick and efforts shorter than ~10 minutes.",
        "Typically 100–300 m. Grows with intervals, shrinks when you only run easy.",
    ),
    "riegel": (
        "Riegel exponent",
        "How much you slow down as the distance grows (time ∝ distance^b).",
        "Shows whether you are more of a “speed” or more of an “endurance” runner.",
        "About 1.06 — good endurance. Above ~1.12 — pace clearly fades over long distances, "
        "i.e. long runs are missing.",
    ),
    "ef": (
        "EF — running economy",
        "Metres run per heartbeat (grade-adjusted speed ÷ heart rate).",
        "When it rises at the same heart rate, the same effort gives more speed — that is progress.",
        "Look at the average of many runs; a single run depends on weather, terrain and sleep.",
    ),
    "cadence": (
        "Cadence",
        "Steps per minute (both feet).",
        "A very low cadence often means a long, “braking” stride.",
        "Typically 160–185 spm; rises with pace. There is no single ideal number.",
    ),
    # ---- Forecast and running
    "vdot": (
        "VDOT",
        "A single number for running fitness from Daniels' tables, derived from a time over a distance. "
        "Works like “VO₂max from a result”.",
        "Lets you translate a result at one distance to another and set training paces.",
        "+1 VDOT is about 1.5–2% faster at every distance. Realistically about 1 VDOT can be gained "
        "per 4–6 weeks of training.",
    ),
    "realistic": (
        "Realistic result",
        "The time forecast at your fitness today and your preparation for this distance today.",
        "The time to plan a race around if it were today.",
        "It is the middle of the range — it is as likely to come out faster as slower.",
    ),
    "potential": (
        "Potential",
        "The same time, assuming the endurance for the distance were fully built.",
        "Shows what the lack of long runs and kilometres costs you today.",
        "The gap potential − realistic is what you can gain without getting faster, by training "
        "for the distance alone.",
    ),
    "after_plan": (
        "On race day (after the plan / as now)",
        "The forecast for race day. When the plan covers the race: +1 VDOT per ~5 weeks and the preparation "
        "the plan builds before that race. Without a plan: today's preparation and a fitness gain times "
        "consistency, fading after ~6 weeks.",
        "Shows whether the goal is reachable by the race date — and what the plan adds over training as so far.",
        "In brackets the cautious and the optimistic variant. Shown only for a distance with a race entered.",
    ),
    "interval80": (
        "80% range",
        "The range the result should fall into in 8 races out of 10.",
        "Honestly says how much the model knows — a narrow range = plenty of good data.",
        "One race in five will land outside it. When the lower bound is clearly further away than the "
        "upper one, the last effort was not maximal and you may be faster than the middle says.",
    ),
    "confidence": (
        "Forecast confidence",
        "A summary of the range width and the anchor quality: ●●● high, ●●○ medium, ●○○ low.",
        "Says how far to trust the number before you set your race pace by it.",
        "High: a fresh (≤ 6 weeks) near-maximal effort and the methods agree (range about ±5%). "
        "Medium: there is a documented effort, range up to about ±10%. Low: wider — usually a far "
        "extrapolation (e.g. from 4 km to a marathon), weak preparation or methods that disagree. To raise "
        "it: run hard (a race, a test) at a distance close to the target.",
    ),
    "preparation": (
        "Preparation for the distance",
        "0–100%: the longest run and weekly kilometres of the last 6 weeks, and consistency, "
        "against the minimum assumed for the distance.",
        "5 km speed does not carry over to a half marathon without long runs — this number prices that in.",
        "100% = the minimum is met. The lower it is, the further the realistic time lags behind the potential.",
    ),
    "near_max": (
        "Near-maximal effort",
        "A race or a stretch where heart rate was ≥ 91% of maximum for at least 6 minutes.",
        "Only such a result says what you are really capable of; an easy session is only a lower bound.",
        "A filled point on the forecast chart = a maximal anchor, a hollow one = a lower bound.",
    ),
    "methods": (
        "Forecast methods",
        "Three independent estimates: from documented efforts (the anchor), from the heart rate–pace "
        "relation on easy runs, and from Garmin's forecast.",
        "When they agree, the range is narrow; when they diverge — wider.",
        "The anchor sets the number, the other two only the uncertainty.",
    ),
    "backtest": (
        "Backtest",
        "Each of your hard runs compared with what the model predicted a week earlier.",
        "The only way to know what the forecast is worth on your data.",
        "A median error of ~5% is good, ~10% — average. A positive error = the model was too cautious.",
    ),
    "run_kind": (
        "Session type",
        "A label assigned by rules from heart rate, pace and distance: recovery, easy, long, tempo, "
        "threshold, intervals, race.",
        "Lets the balance of easy and hard kilometres be counted without manual tagging.",
        "The reason and confidence of the label are in the session details.",
    ),
    "today_decision": (
        "Today's decision",
        "The next session from the plan (or a suggestion from the data when there is no plan) set against "
        "last night's recovery signals and the load of the last 7 days.",
        "The plan is laid out weeks ahead, while form changes day to day. The decision reconciles the two: "
        "it never adds more than the plan intended, at most it backs off.",
        "“As planned” — run. One signal against — start and judge after the warm-up. Two or more "
        "on a hard session — swap it for an easy run or move it by a day. Signals older than a day are "
        "ignored. When there is no session today, the tile only announces the next one — the decision is "
        "made on the morning of its day.",
    ),
    "quality_sessions": (
        "Quality sessions",
        "Tempo, threshold, interval sessions and races.",
        "They provide the stimulus; the rest is base and recovery.",
        "For amateurs 1–2 a week is usually enough with ~75–80% easy kilometres.",
    ),
    "rep_fade": (
        "Rep fade",
        "How much slower the last rep of a workout was than the first (s/km) and how much higher heart "
        "rate went on it.",
        "Shows whether the pace matched your form: even reps with slightly rising heart rate mean a "
        "well-spread effort.",
        "Up to ~5 s/km and a few beats — even. The last one clearly slower with heart rate at the ceiling "
        "— pace too ambitious or recoveries too short. A negative fade (speeding up) — there was something "
        "left.",
    ),
    "same_route": (
        "Same route",
        "Runs whose GPS tracks overlap by at least 80% (both ways, a ~50 m grid) with distances "
        "differing by at most 15%. Direction does not matter.",
        "On the same route pace does not depend on hills or surface — the comparison is fair "
        "for long and easy runs too, which have no laps from the watch.",
        "Read pace together with heart rate and session type: faster at the same heart rate is progress, "
        "faster at a higher one — simply harder.",
    ),
    "shared_stretch": (
        "Shared stretch",
        "The longest piece of route this run shares with another (tracks ≤ 35 m apart, same direction, "
        "at least 400 m) — a segment of whatever length came out, without drawing one.",
        "Compares any two runs on exactly the same ground, even when the whole routes differ.",
        "Time comes from the sample stream (a few seconds of accuracy). A stop at the lights counts toward "
        "the time, so check a single big gap on the map.",
    ),
    "efficiency_delta": (
        "Δ efficiency",
        "The change in metres run per heartbeat against that run, on the same stretch.",
        "Separates form from effort: faster at a higher heart rate is a harder run, faster at the "
        "same heart rate — better form.",
        "Positive = more metres per beat than back then. Compare with runs of a similar type; heat, wind "
        "and fatigue move it by a few percent.",
    ),
    "best_effort": (
        "Best efforts",
        "The fastest continuous part of a run at standard distances (1 km, mile, 3 km, 5 km, 10 km, "
        "half marathon, marathon) — cut from anywhere in the run.",
        "Records happen in training too, not only in races; the rank in history shows how good "
        "the run was.",
        "🏆 = all-time best, 🏅 = best of the last 365 days. Source: Garmin or the sample stream.",
    ),
    "segment": (
        "Segment",
        "Your private stretch of route, cut from one run (like Strava segments, but never sent "
        "anywhere). A run completes it when it passes the start and finish within 35 m and the whole "
        "track between them stays on the segment's route (40 m).",
        "The same hill or park straight shows up in many runs of different types — a segment "
        "lets you compare exactly that piece.",
        "Time comes from the sample stream (a few seconds of accuracy), pace is computed over the segment "
        "length. Direction matters: from start to finish. “auto” = found on its own on a route run "
        "at least 4 times; save it as yours to give it a name.",
    ),
    "pace_at_hr": (
        "Pace at the same heart rate",
        "A pace ~ heart rate line fitted through the reps of earlier workouts (2 years) and this "
        "session's reps' distance from it, in s/km.",
        "Compares workouts with different rep lengths: 5×800 m is run faster than 3×2 km, but at the "
        "same heart rate a faster pace is progress.",
        "Negative = faster than before at the same heart rate. A rep's average heart rate lags behind "
        "the effort, so long reps come out a little worse here than short ones — compare mainly "
        "with similar ones (colour in the legend).",
    ),
    # ---- Sleep and daily rhythm
    "sri": (
        "SRI — sleep regularity",
        "The chance that at the same minute of the day you are in the same state (asleep/awake) two "
        "nights in a row.",
        "Regular sleep times improve its quality regardless of its length.",
        "100 = identical nights. Above ~80 regular, below ~60 a scattered rhythm.",
    ),
    "midpoint": (
        "Sleep midpoint and its spread",
        "The hour halfway between falling asleep and waking up; the spread is the typical deviation "
        "over 30 nights.",
        "The sleep midpoint describes your chronotype well; a large spread = a deregulated body clock.",
        "A spread below ±0.5 h is very regular, above ±1 h — irregular.",
    ),
    "social_jetlag": (
        "Social jetlag",
        "How much later the sleep midpoint falls at the weekend than on weekdays.",
        "Every shifted weekend acts on the body like a small time-zone change.",
        "Up to ~1 h is typical; above 2 h Mondays start with “jetlag”.",
    ),
    "night_profile": (
        "Night profile (heart rate nadir)",
        "The night's lowest heart rate and when it happened (percent of the night).",
        "An early nadir = the body calmed down quickly. A late one = it was digesting the day for a long "
        "time (late training, a meal, alcohol).",
        "A nadir in the first half of the night is a good sign.",
    ),
    "hrv_slope": (
        "Overnight HRV slope",
        "How HRV changes from the start to the end of the night (ms per hour).",
        "Positive = the night was “catching up” and recovery progressed.",
        "Negative several nights in a row — sleep stops restoring.",
    ),
    "sleep_stages": (
        "Sleep stages",
        "Deep (body recovery), REM (nervous system recovery, memory), light, awake.",
        "The proportions say more than the sleep length alone.",
        "Deep is usually 13–23% of the night, REM 20–25%. Garmin estimates stages from movement and "
        "heart rate, so a single night can be inaccurate.",
    ),
    # ---- Statistics
    "r2": (
        "R² (model fit)",
        "What share of the variability in the data the model explains: from 0 (none) to 1 (perfect).",
        "Says whether the numbers derived from the model can be trusted.",
        "Above ~0.9 for CS — solid. For the Banister model even 0.3–0.5 can be a good result; "
        "below ~0.3 treat the result as rough.",
    ),
    "correlation": (
        "Lagged correlation",
        "Whether a factor on one day (e.g. sleep) relates to a response a few days later (e.g. HRV). "
        "ρ from −1 to 1.",
        "Helps find what really affects your recovery.",
        "Read q, not p: q < 0.05 survived the correction for the number of tests. No such pairs is also a "
        "result — correlation is not causation.",
    ),
    "acf": (
        "Autocorrelation",
        "How much today's value resembles the value n days earlier.",
        "Says how long a state “persists” and whether there is a weekly rhythm.",
        "Bars outside the grey band are significant. A peak at 7 days = a weekly rhythm (work, a long run "
        "on Sunday).",
    ),
    "changepoint": (
        "Baseline change point",
        "The day from which a metric's average shifted up or down for good.",
        "Separates a real change (a new plan, a move, an illness) from day-to-day noise.",
        "Check what was happening in your life around that date.",
    ),
    "weekday": (
        "Day-of-week effect",
        "How much a given weekday departs from the average, with a test of whether the differences are real.",
        "Shows habits: worse sleep on Sunday, higher stress on Monday.",
        "p < 0.05 in the Kruskal-Wallis test = the weekdays really differ.",
    ),
}

TREND_HOW = (
    "Faint dots are single days, the bold line is the rolling average — it carries the signal. "
    "The grey band is your normal, the number at the end of the line is the latest value."
)
