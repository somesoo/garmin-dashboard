"""A synthetic Apple Health export shaped like an Apple Watch's -- to build against before the watch arrives.

    .venv/bin/python tools/synthetic_watch.py out.zip [--days 180] [--seed 7]
    .venv/bin/python -m core.tenant add demo --name "Demo (Apple Watch)" --source apple
    GARMIN_USER=demo .venv/bin/python -m etl.apple import out.zip

Everything is made up, seeded and labelled (source "Apple Watch (demo)"); it
never goes into a real person's directory. What it imitates, from real exports:

- heart rate every 5 min through the day and the night, every 5 s in a workout;
- HRV (SDNN) a few times a night and twice a day, resting HR once a day,
  respiratory rate, SpO2 and sleeping wrist temperature overnight, VO2max after
  outdoor runs;
- sleep in 90-minute cycles (core/deep early, REM late, short wakes) from the
  watch, and "in bed" from the iPhone -- two sources of one night;
- steps, distance and energy hourly from the watch *and* the iPhone (the same
  walk counted twice -- the importer must not add them);
- runs 4x a week (easy, intervals, tempo, long) with HR statistics, elevation,
  a GPX route every 5 s, running power, stride, vertical oscillation, ground
  contact, effort score and one-minute HR recovery; strength sessions without GPS.

The physiology is coherent on purpose: a hard day raises next morning's resting
HR and lowers overnight HRV, a short night does too, and fitness (pace at the
same HR) improves slowly over the period.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import math
import random
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Warsaw")
WATCH = "Apple Watch (demo)"
PHONE = "iPhone (demo)"
WATCH_DEVICE = ("&lt;&lt;HKDevice: 0x0&gt;, name:Apple Watch, manufacturer:Apple Inc., model:Watch, "
                "hardware:Watch7,1, software:11.0&gt;")
PHONE_DEVICE = ("&lt;&lt;HKDevice: 0x0&gt;, name:iPhone, manufacturer:Apple Inc., model:iPhone, "
                "hardware:iPhone16,1, software:19.0&gt;")
Q = "HKQuantityTypeIdentifier"
HOME = (52.2297, 21.0122)  # a park loop in Warsaw


def stamp(t: dt.datetime) -> str:
    offset = t.replace(tzinfo=ZONE).strftime("%z")
    return f"{t:%Y-%m-%d %H:%M:%S} {offset}"


class Export:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.files: dict[str, bytes] = {}

    def record(self, kind: str, start: dt.datetime, value: float | str, unit: str = "", *,
               end: dt.datetime | None = None, source: str = WATCH, category: bool = False) -> None:
        device = WATCH_DEVICE if source == WATCH else PHONE_DEVICE
        prefix = "HKCategoryTypeIdentifier" if category else Q
        unit_attr = "" if category else f' unit="{unit}"'
        self.parts.append(
            f'<Record type="{prefix}{kind}" sourceName="{source}" sourceVersion="11.0" device="{device}"'
            f'{unit_attr} creationDate="{stamp(end or start)}" startDate="{stamp(start)}" '
            f'endDate="{stamp(end or start)}" value="{value}"/>')

    def xml(self, birth: dt.date) -> str:
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<HealthData locale="pl_PL">\n'
                f'<ExportDate value="{stamp(dt.datetime.now())}"/>\n'
                f'<Me HKCharacteristicTypeIdentifierDateOfBirth="{birth}" '
                'HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale" '
                'HKCharacteristicTypeIdentifierBloodType="HKBloodTypeNotSet"/>\n'
                + "\n".join(self.parts) + "\n</HealthData>\n")


# ------------------------------------------------------------------ the body


class Body:
    """Slow fitness, fast fatigue: what turns a training log into believable vitals."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.fitness = 0.0  # 0 -> 1 over the period: same HR, faster pace
        self.fatigue = 0.0  # decays daily, rises with hard sessions
        self.rhr_base, self.hrv_base, self.hr_max = 51.0, 58.0, 191.0

    def night(self, slept_h: float) -> tuple[float, float]:
        short = max(0.0, 7.0 - slept_h)
        rhr = self.rhr_base - 2.5 * self.fitness + 4.0 * self.fatigue + 1.5 * short + self.rng.gauss(0, 1.2)
        hrv = self.hrv_base * math.exp(0.12 * self.fitness - 0.25 * self.fatigue - 0.06 * short + self.rng.gauss(0, 0.08))
        return round(rhr), round(hrv, 1)

    def after_day(self, load: float, day_index: int, days: int) -> None:
        self.fatigue = self.fatigue * 0.55 + load / 220
        self.fitness = min(1.0, day_index / max(days, 1))


# ------------------------------------------------------------------ pieces


def sleep_night(ex: Export, rng: random.Random, morning: dt.date) -> tuple[dt.datetime, dt.datetime, float]:
    bed = dt.datetime.combine(morning - dt.timedelta(days=1), dt.time(23, 10)) + dt.timedelta(
        minutes=rng.gauss(0, 35) + (40 if morning.weekday() in (5, 6) else 0))
    hours = max(4.5, min(9.5, rng.gauss(7.3, 0.7)))
    asleep_at = bed + dt.timedelta(minutes=rng.uniform(5, 20))
    wake = asleep_at + dt.timedelta(hours=hours)
    ex.record("SleepAnalysis", bed, "HKCategoryValueSleepAnalysisInBed", end=wake + dt.timedelta(minutes=8),
              source=PHONE, category=True)
    t, cycle = asleep_at, 0
    while t < wake:
        early = cycle < 2
        plan = [("Core", rng.uniform(15, 30)), ("Deep", rng.uniform(25, 45) if early else rng.uniform(0, 12)),
                ("Core", rng.uniform(10, 20)), ("REM", rng.uniform(8, 15) if early else rng.uniform(20, 35))]
        if rng.random() < 0.35:
            plan.append(("Awake", rng.uniform(1, 6)))
        for stage, minutes in plan:
            if minutes < 1 or t >= wake:
                continue
            end = min(wake, t + dt.timedelta(minutes=minutes))
            ex.record("SleepAnalysis", t, f"HKCategoryValueSleepAnalysisAsleep{stage}" if stage != "Awake"
                      else "HKCategoryValueSleepAnalysisAwake", end=end, category=True)
            t = end
        cycle += 1
    return asleep_at, wake, hours


def overnight(ex: Export, rng: random.Random, start: dt.datetime, end: dt.datetime, rhr: float, hrv: float) -> None:
    t = start
    while t < end:
        depth = math.sin(math.pi * (t - start) / (end - start))  # lowest in the middle of the night
        ex.record("HeartRate", t, round(rhr + 6 - 7 * depth + rng.gauss(0, 1.5)), "count/min")
        t += dt.timedelta(minutes=5)
    for k in range(rng.randint(3, 6)):
        when = start + (end - start) * rng.uniform(0.1, 0.9)
        ex.record("HeartRateVariabilitySDNN", when, round(hrv * math.exp(rng.gauss(0, 0.12)), 1), "ms")
    for k in range(4):
        when = start + (end - start) * (k + 0.5) / 4
        ex.record("RespiratoryRate", when, round(rng.gauss(14.2, 0.6), 1), "count/min")
    ex.record("OxygenSaturation", start + (end - start) / 2, round(min(1.0, rng.gauss(0.965, 0.01)), 2), "%")
    ex.record("AppleSleepingWristTemperature", start, round(rng.gauss(35.6, 0.25), 2), "degC", end=end)
    ex.record("RestingHeartRate", end + dt.timedelta(hours=10), rhr, "count/min")


def daytime(ex: Export, rng: random.Random, day: dt.date, wake: dt.datetime, busy: list[tuple]) -> None:
    """Hourly steps/distance/energy from watch and phone; HR every 5 min outside workouts; two HRV readings."""
    total_steps = rng.gauss(8500, 2500)
    for hour in range(7, 23):
        start = dt.datetime.combine(day, dt.time(hour))
        share = rng.uniform(0.02, 0.12)
        steps = max(0, round(total_steps * share))
        if steps:
            for source, factor in ((WATCH, 1.0), (PHONE, rng.uniform(0.7, 0.95))):
                ex.record("StepCount", start, round(steps * factor), "count", end=start + dt.timedelta(minutes=59),
                          source=source)
                ex.record("DistanceWalkingRunning", start, round(steps * factor * 0.00072, 3), "km",
                          end=start + dt.timedelta(minutes=59), source=source)
        ex.record("ActiveEnergyBurned", start, round(steps * 0.04 + rng.uniform(5, 15), 1), "kcal",
                  end=start + dt.timedelta(minutes=59))
    for hour in range(24):
        ex.record("BasalEnergyBurned", dt.datetime.combine(day, dt.time(hour)), 72.5, "kcal",
                  end=dt.datetime.combine(day, dt.time(hour, 59)))
    t = max(wake, dt.datetime.combine(day, dt.time(7)))
    end = dt.datetime.combine(day, dt.time(23))
    while t < end:
        if not any(a <= t <= b for a, b in busy):
            ex.record("HeartRate", t, round(rng.gauss(74, 9)), "count/min")
        t += dt.timedelta(minutes=5)
    for hour in (10, 16):
        ex.record("HeartRateVariabilitySDNN", dt.datetime.combine(day, dt.time(hour, rng.randint(0, 59))),
                  round(rng.gauss(42, 8), 1), "ms")
    ex.record("AppleExerciseTime", dt.datetime.combine(day, dt.time(12)), round(rng.uniform(8, 25)), "min")


RUNS = {  # weekday -> (kind, km, easy pace min/km at fitness 0, HR fraction of max)
    0: ("easy", 8.0, 6.0, 0.74), 1: ("intervals", 10.0, 5.2, 0.84), 3: ("tempo", 9.0, 5.3, 0.83),
    6: ("long", 16.0, 6.1, 0.76),
}


def loop(km: float, points: int) -> list[tuple[float, float]]:
    """An out-and-around loop of ``km`` near HOME."""
    radius_km = km / (2 * math.pi)
    out = []
    for i in range(points):
        angle = 2 * math.pi * i / max(points - 1, 1)
        wobble = 1 + 0.08 * math.sin(5 * angle)
        lat = HOME[0] + radius_km * wobble * math.sin(angle) / 111.2
        lon = HOME[1] + radius_km * wobble * (1 - math.cos(angle)) / (111.2 * math.cos(math.radians(HOME[0])))
        out.append((lat, lon))
    return out


def run(ex: Export, rng: random.Random, body: Body, day: dt.date, kind: str, km: float, pace0: float,
        frac: float, index: int) -> tuple[dt.datetime, dt.datetime, float]:
    start = dt.datetime.combine(day, dt.time(17 if kind != "long" else 9, rng.randint(0, 40)))
    pace = pace0 * (1 - 0.06 * body.fitness) * rng.uniform(0.97, 1.03)
    minutes = km * pace
    end = start + dt.timedelta(minutes=minutes)
    step = 5
    count = int(minutes * 60 / step)
    hrs = []
    for i in range(count):
        t = start + dt.timedelta(seconds=i * step)
        warm = min(1.0, i * step / 480)
        surge = 0.08 if kind == "intervals" and (i * step // 180) % 2 == 1 and 0.15 < i / count < 0.85 else 0.0
        drift = 0.03 * i / count
        bpm = body.hr_max * (0.55 + (frac - 0.55 + surge + drift) * warm) + rng.gauss(0, 2)
        hrs.append(bpm)
        ex.record("HeartRate", t, round(bpm), "count/min")
        if i % 2 == 0:
            ex.record("RunningPower", t, round(rng.gauss(250 * (5.5 / pace), 8)), "W")
            ex.record("RunningStrideLength", t, round(rng.gauss(1000 / pace / 170, 0.03), 2), "m")
            ex.record("RunningVerticalOscillation", t, round(rng.gauss(8.6, 0.4), 1), "cm")
            ex.record("RunningGroundContactTime", t, round(rng.gauss(245, 8)), "ms")
        if i % 12 == 0:
            ex.record("StepCount", t, round(rng.gauss(171, 3)), "count", end=t + dt.timedelta(seconds=59))
    ex.record("HeartRateRecoveryOneMinute", end + dt.timedelta(minutes=2), round(rng.gauss(28, 4)), "count/min")
    effort = {"easy": 4, "long": 6, "tempo": 7, "intervals": 8}[kind] + rng.choice((-1, 0, 0, 1))
    ex.record("WorkoutEffortScore", start, effort, "appleEffortScore", end=end)  # spans the workout, as in HealthKit
    if rng.random() < 0.5:
        ex.record("VO2Max", end + dt.timedelta(minutes=5), round(49 + 3 * body.fitness + rng.gauss(0, 0.4), 2),
                  "mL/min·kg")
    route = f"/workout-routes/route_{start:%Y-%m-%d_%H.%M.%S}_{index}.gpx"
    points = loop(km, count)
    utc = start.replace(tzinfo=ZONE).astimezone(dt.timezone.utc)
    trk = "".join(f'<trkpt lon="{lon:.6f}" lat="{lat:.6f}"><ele>{95 + 6 * math.sin(i / 40):.1f}</ele>'
                  f'<time>{(utc + dt.timedelta(seconds=i * step)):%Y-%m-%dT%H:%M:%SZ}</time></trkpt>'
                  for i, (lat, lon) in enumerate(points))
    ex.files[route] = ('<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="Apple Health Export" '
                       'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Route</name><trkseg>'
                       + trk + "</trkseg></trk></gpx>").encode()
    avg, peak = sum(hrs) / len(hrs), max(hrs)
    kcal = minutes * 11.5
    ex.parts.append(
        f'<Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="{minutes:.4f}" durationUnit="min" '
        f'sourceName="{WATCH}" sourceVersion="11.0" device="{WATCH_DEVICE}" creationDate="{stamp(end)}" '
        f'startDate="{stamp(start)}" endDate="{stamp(end)}">'
        f'<MetadataEntry key="HKIndoorWorkout" value="0"/>'
        f'<MetadataEntry key="HKElevationAscended" value="{rng.randint(1500, 6000)} cm"/>'
        f'<MetadataEntry key="HKAverageMETs" value="10.2 kcal/hr·kg"/>'
        f'<WorkoutStatistics type="{Q}ActiveEnergyBurned" startDate="{stamp(start)}" endDate="{stamp(end)}" '
        f'sum="{kcal:.1f}" unit="kcal"/>'
        f'<WorkoutStatistics type="{Q}DistanceWalkingRunning" startDate="{stamp(start)}" endDate="{stamp(end)}" '
        f'sum="{km:.3f}" unit="km"/>'
        f'<WorkoutStatistics type="{Q}HeartRate" startDate="{stamp(start)}" endDate="{stamp(end)}" '
        f'average="{avg:.1f}" minimum="{min(hrs):.0f}" maximum="{peak:.0f}" unit="count/min"/>'
        f'<WorkoutStatistics type="{Q}RunningPower" startDate="{stamp(start)}" endDate="{stamp(end)}" '
        f'average="{250 * 5.5 / pace:.0f}" unit="W"/>'
        f'<WorkoutRoute sourceName="{WATCH}" sourceVersion="11.0" creationDate="{stamp(end)}" '
        f'startDate="{stamp(start)}" endDate="{stamp(end)}"><FileReference path="{route}"/></WorkoutRoute>'
        "</Workout>")
    load = minutes * (frac - 0.5) * 6
    return start, end, load


def strength(ex: Export, rng: random.Random, body: Body, day: dt.date) -> tuple[dt.datetime, dt.datetime, float]:
    start = dt.datetime.combine(day, dt.time(18, rng.randint(0, 30)))
    minutes = rng.uniform(35, 50)
    end = start + dt.timedelta(minutes=minutes)
    t = start
    hrs = []
    while t < end:
        bpm = rng.gauss(118, 12)
        hrs.append(bpm)
        ex.record("HeartRate", t, round(bpm), "count/min")
        t += dt.timedelta(seconds=10)
    ex.parts.append(
        f'<Workout workoutActivityType="HKWorkoutActivityTypeTraditionalStrengthTraining" duration="{minutes:.4f}" '
        f'durationUnit="min" sourceName="{WATCH}" sourceVersion="11.0" device="{WATCH_DEVICE}" '
        f'creationDate="{stamp(end)}" startDate="{stamp(start)}" endDate="{stamp(end)}">'
        f'<MetadataEntry key="HKIndoorWorkout" value="1"/>'
        f'<WorkoutStatistics type="{Q}ActiveEnergyBurned" startDate="{stamp(start)}" endDate="{stamp(end)}" '
        f'sum="{minutes * 6:.1f}" unit="kcal"/>'
        f'<WorkoutStatistics type="{Q}HeartRate" startDate="{stamp(start)}" endDate="{stamp(end)}" '
        f'average="{sum(hrs) / len(hrs):.1f}" maximum="{max(hrs):.0f}" unit="count/min"/></Workout>')
    return start, end, minutes * 1.2


# ------------------------------------------------------------------ assemble


def generate(days: int = 180, seed: int = 7, today: dt.date | None = None) -> bytes:
    rng = random.Random(seed)
    today = today or dt.date.today()
    ex, body = Export(), Body(rng)
    first = today - dt.timedelta(days=days - 1)
    for index in range(days):
        day = first + dt.timedelta(days=index)
        asleep, wake, hours = sleep_night(ex, rng, day)
        rhr, hrv = body.night(hours)
        overnight(ex, rng, asleep, wake, rhr, hrv)
        busy, load = [], 0.0
        plan = RUNS.get(day.weekday())
        if plan and rng.random() > 0.12:  # a missed session now and then
            start, end, l = run(ex, rng, body, day, *plan, index=index)
            busy.append((start, end))
            load += l
        if day.weekday() in (2, 4) and rng.random() > 0.3:
            start, end, l = strength(ex, rng, body, day)
            busy.append((start, end))
            load += l
        daytime(ex, rng, day, wake, busy)
        body.after_day(load, index, days)
    if days >= 30:
        ex.record("BodyMass", dt.datetime.combine(first, dt.time(7)), 74.2, "kg", source=PHONE)
        ex.record("BodyMass", dt.datetime.combine(today, dt.time(7)), 73.1, "kg", source=PHONE)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("apple_health_export/export.xml", ex.xml(dt.date(1995, 5, 10)))
        for name, data in ex.files.items():
            archive.writestr(f"apple_health_export{name}", data)
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    args.out.write_bytes(generate(args.days, args.seed))
    print(f"{args.out}: {args.out.stat().st_size / 1e6:.1f} MB, {args.days} dni")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
