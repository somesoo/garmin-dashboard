"""Heart-rate zones of one person: anchored on thresholds, never on Garmin's %HRmax.

Garmin's default zones are 50/60/70/80/90% of HRmax. Fixed fractions of the
maximum put people in different intensity domains, because the thresholds sit
at very different fractions of it from person to person:

- Iannetta et al., *Med Sci Sports Exerc* 52(2):466-473, 2020 (n = 100): LT and
  MLSS at a wide range of %HRmax; fixed-percentage prescription "conforms poorly
  to exercise intensity domains".
- Jamnick et al., *Sports Med* 50:1729-1756, 2020: fractions of VO2max/HRmax add
  little for domain-specific responses; thresholds (CS/CP) do.
- Mann, Lamberts & Lambert, *Sports Med* 43(7):613-625, 2013: every method has
  costs; threshold anchors are the physiological ones.

So the zones hang on two thresholds: the threshold heart rate (LTHR, ~VT2/MLSS)
and the first ventilatory threshold (VT1, the top of "easy"). Each anchor comes,
in this order, from:

1. **manual** -- typed in on the Account page from a test (lab gas exchange or
   lactate, Friel's 30-min field test, DFA-a1 = 0.75 for VT1: Rogers et al.,
   *Front Physiol* 11:596567, 2021), stored in ``<person>/zones.json``;
2. **data** -- LTHR from the hardest near-maximal 18-60 min effort in 120 days
   (``physio.threshold_hr``), HRmax as the third-highest run maximum
   (``physio.robust_hr_max``);
3. **estimate** -- population ratios from 1411 treadmill-tested runners
   (Esteve-Lanao et al., *Sports* 14(1):29, 2026, table 2): VT2 = 93.5 +/- 2.5%
   and VT1 = 85.1 +/- 4.6% of HRpeak, so VT1 ~ 0.91 x LTHR. An estimate is
   labelled as one: its spread is +/- 5-9 bpm.

Nothing is invented: no anchor and no HRmax means no zones (``None``), never
220-age or a constant.

Five zones for display and time-in-zone (lower edges of Z2..Z5):
Z2 from 85% LTHR (Friel), Z3 from VT1, Z4 from 95% LTHR (Friel), Z5 from LTHR.
In the three-domain model (Seiler) Z1-Z2 are below VT1, Z3-Z4 between the
thresholds, Z5 above.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Esteve-Lanao et al. 2026, all 1411 runners (sex is not known for every person here).
VT2_OF_HRMAX = 0.935
VT1_OF_HRMAX = 0.851
VT1_OF_LTHR = round(VT1_OF_HRMAX / VT2_OF_HRMAX, 3)  # 0.91
# Friel's running zones as fractions of LTHR: Z2 from 85%, Z4 from 95%.
Z2_OF_LTHR = 0.85
Z4_OF_LTHR = 0.95

FIELDS = ("lthr", "vt1", "hr_max")
LIMITS = {"lthr": (120, 215), "vt1": (100, 205), "hr_max": (140, 230)}
METHODS = ("lab", "field", "dfa", "other")
# Longest gap between two stream samples counted as time in a zone.
MAX_GAP_S = 60


# ------------------------------------------------------------------ settings


def path() -> Path | None:
    try:
        import tenant

        return tenant.current().zone_settings
    except LookupError:
        return None


def settings(file: Path | None = None) -> dict[str, Any]:
    """The person's typed-in anchors ({} when none): ``lthr``/``vt1``/``hr_max`` (bpm),
    ``method`` (``METHODS``), ``measured`` (ISO date)."""
    file = file or path()
    if file is None:
        return {}
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return clean(raw) if isinstance(raw, dict) else {}


def clean(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in FIELDS:
        value = raw.get(name)
        try:
            value = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        low, high = LIMITS[name]
        if low <= value <= high:
            out[name] = value
    if raw.get("method") in METHODS:
        out["method"] = raw["method"]
    try:
        out["measured"] = dt.date.fromisoformat(str(raw.get("measured"))).isoformat()
    except ValueError:
        pass
    return out


def problems(values: dict[str, Any]) -> list[str]:
    """Codes of what does not fit together: ``vt1_above_lthr``, ``lthr_above_max``, ``range_<field>``."""
    out = []
    for name in FIELDS:
        value = values.get(name)
        if value is not None and not LIMITS[name][0] <= value <= LIMITS[name][1]:
            out.append(f"range_{name}")
    vt1, lthr, top = values.get("vt1"), values.get("lthr"), values.get("hr_max")
    if vt1 and lthr and vt1 >= lthr:
        out.append("vt1_above_lthr")
    if lthr and top and lthr >= top:
        out.append("lthr_above_max")
    return out


def save(values: dict[str, Any], file: Path | None = None) -> dict[str, Any]:
    """Write the typed-in anchors; empty ``values`` removes the file (back to the data)."""
    file = file or path()
    if file is None:
        raise LookupError("no person")
    if problems(values):
        raise ValueError(", ".join(problems(values)))
    stored = clean(values)
    if not any(name in stored for name in FIELDS):
        file.unlink(missing_ok=True)
        return {}
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    return stored


# ------------------------------------------------------------------ anchors


def anchors(*, lthr: float | None = None, hr_max: float | None = None,
            manual: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """LTHR, VT1 and HRmax with where each came from (``manual``/``data``/``estimate``).

    ``lthr``/``hr_max`` are the values from the data; ``manual`` defaults to the
    person's settings. None when neither a threshold nor a maximum is known.
    """
    manual = settings() if manual is None else manual
    out: dict[str, Any] = {}
    if manual.get("hr_max"):
        out["hr_max"], out["hr_max_source"] = int(manual["hr_max"]), "manual"
    elif hr_max and np.isfinite(hr_max):
        out["hr_max"], out["hr_max_source"] = int(round(hr_max)), "data"
    if manual.get("lthr"):
        out["lthr"], out["lthr_source"] = int(manual["lthr"]), "manual"
    elif lthr and np.isfinite(lthr):
        out["lthr"], out["lthr_source"] = int(round(lthr)), "data"
    elif out.get("hr_max"):
        out["lthr"], out["lthr_source"] = int(round(VT2_OF_HRMAX * out["hr_max"])), "estimate"
    else:
        return None
    if manual.get("vt1") and manual["vt1"] < out["lthr"]:
        out["vt1"], out["vt1_source"] = int(manual["vt1"]), "manual"
    else:
        out["vt1"], out["vt1_source"] = int(round(VT1_OF_LTHR * out["lthr"])), "estimate"
    if out.get("hr_max") and out["lthr"] >= out["hr_max"]:
        out["hr_max"], out["hr_max_source"] = None, None  # contradicts the threshold: not used
    for key in ("method", "measured"):
        if manual.get(key):
            out[key] = manual[key]
    return out


def basis(found: dict[str, Any] | None) -> str | None:
    """One word for what the zones rest on: ``manual`` / ``lthr`` (measured in the data) / ``hr_max`` (estimate)."""
    if not found:
        return None
    return {"manual": "manual", "data": "lthr"}.get(found.get("lthr_source"), "hr_max")


def edges(found: dict[str, Any] | None) -> list[int] | None:
    """Lower edges (bpm) of Z2..Z5."""
    if not found or not found.get("lthr"):
        return None
    lthr, vt1 = int(found["lthr"]), int(found["vt1"])
    return [min(int(round(Z2_OF_LTHR * lthr)), vt1 - 1), vt1, max(int(round(Z4_OF_LTHR * lthr)), vt1 + 1), lthr]


def bands(found: dict[str, Any] | None) -> list[tuple[int | None, int | None]] | None:
    """(from, to) bpm per zone; Z1 has no floor, Z5 tops at HRmax when known."""
    cuts = edges(found)
    if cuts is None:
        return None
    lows = [None, *cuts]
    highs = [c - 1 for c in cuts] + [found.get("hr_max")]
    return list(zip(lows, highs))


# ------------------------------------------------------------------ time in zones


def seconds(hr: np.ndarray, gaps: np.ndarray, cuts: list[int]) -> list[float]:
    zone = np.searchsorted(np.asarray(cuts, float), hr, side="right")
    return [round(float(gaps[zone == z].sum())) for z in range(5)]


def zone_time(activities: pd.DataFrame, routes: pd.DataFrame, efforts: pd.DataFrame | None,
              hr_max: float | None, manual: dict[str, Any] | None = None) -> pd.DataFrame:
    """Seconds in Z1..Z5 per activity from its heart-rate stream, with the zones of its day.

    The LTHR of each day is the one the data gave by then (``physio.threshold_hr``
    over the 120 days before); typed-in anchors apply to every day. Activities
    without a stream get no row -- the watch's own split used other limits.
    """
    from running import physio

    columns = ["activity_id", *(f"hr_z{i}_s" for i in range(1, 6)), "zone_lthr", "zone_vt1", "zone_basis"]
    if activities is None or activities.empty or routes is None or routes.empty or "hr" not in routes.columns:
        return pd.DataFrame(columns=columns)
    manual = settings() if manual is None else manual
    days = activities.set_index("activity_id")["day"].map(pd.Timestamp).to_dict()
    stream = routes.dropna(subset=["hr", "duration_s"])
    rows, by_day = [], {}
    for activity_id, track in stream.groupby("activity_id"):
        day = days.get(activity_id)
        if day is None or len(track) < 10:
            continue
        if day not in by_day:
            measured = physio.threshold_hr(efforts, day) if not manual.get("lthr") else None
            by_day[day] = anchors(lthr=(measured or {}).get("bpm"), hr_max=hr_max, manual=manual)
        found = by_day[day]
        cuts = edges(found)
        if cuts is None:
            continue
        track = track.sort_values("duration_s")
        timer = track["duration_s"].to_numpy(float)
        gaps = np.clip(np.diff(timer, append=timer[-1]), 0, MAX_GAP_S)
        rows.append([int(activity_id), *seconds(track["hr"].to_numpy(float), gaps, cuts),
                     found["lthr"], found["vt1"], basis(found)])
    return pd.DataFrame(rows, columns=columns)


def with_zone_time(frame: pd.DataFrame, zones: pd.DataFrame) -> pd.DataFrame:
    """``frame`` with its ``hr_z*_s`` replaced by ``zones``; the watch's split kept as ``garmin_hr_z*_s``.

    Rows without a stream get NaN, except Apple workouts: their split was
    computed in ``etl/apple.py`` from the raw samples with these same anchors.
    """
    if frame is None or frame.empty:
        return frame
    out = frame.copy()
    names = [f"hr_z{i}_s" for i in range(1, 6)]
    own = out["source"].eq("apple") if "source" in out.columns else pd.Series(False, index=out.index)
    for name in names:
        if name in out.columns:
            out[f"garmin_{name}"] = out[name].where(~own)
    indexed = zones.set_index("activity_id") if zones is not None and not zones.empty else None
    ids = out["activity_id"].astype("int64")
    for name in [*names, "zone_lthr", "zone_vt1", "zone_basis"]:
        mapped = ids.map(indexed[name]) if indexed is not None else pd.Series(np.nan, index=out.index)
        if name in names and name in out.columns:
            mapped = mapped.where(mapped.notna() | ~own, out[name])
        out[name] = mapped.to_numpy()
    return out
