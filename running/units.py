"""Race distances and the pace / time arithmetic every other module leans on.

Paces are minutes per kilometre as floats (``5.5`` = 5:30 /km), durations are
seconds. Formatting returns ``None``-safe text so a missing value never turns
into "nan:nan" on the page.
"""

from __future__ import annotations

import math
import re
from typing import Any

# Official race distances in kilometres.
RACES: dict[str, float] = {
    "5k": 5.0,
    "10k": 10.0,
    "hm": 21.0975,
    "m": 42.195,
}
RACE_LABELS: dict[str, str] = {
    "5k": "5 km",
    "10k": "10 km",
    "hm": "półmaraton",
    "m": "maraton",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def pace_from(seconds: Any, km: Any) -> float | None:
    """Pace in min/km for ``seconds`` over ``km``; None when either is unusable."""
    seconds, km = _number(seconds), _number(km)
    if seconds is None or km is None or seconds <= 0 or km <= 0:
        return None
    return seconds / 60 / km


def time_from(pace_min_km: Any, km: Any) -> float | None:
    """Seconds needed to cover ``km`` at ``pace_min_km``."""
    pace, km = _number(pace_min_km), _number(km)
    if pace is None or km is None or pace <= 0 or km <= 0:
        return None
    return pace * 60 * km


def speed_ms(pace_min_km: Any) -> float | None:
    pace = _number(pace_min_km)
    if pace is None or pace <= 0:
        return None
    return 1000 / (pace * 60)


def pace_from_speed(speed: Any) -> float | None:
    """min/km from metres per second."""
    speed = _number(speed)
    if speed is None or speed <= 0:
        return None
    return 1000 / speed / 60


def fmt_pace(pace_min_km: Any, unit: bool = True) -> str:
    """``5:43 /km``; rounding happens on whole seconds so 5:59.6 becomes 6:00."""
    pace = _number(pace_min_km)
    if pace is None or pace <= 0:
        return "—"
    seconds = int(round(pace * 60))
    text = f"{seconds // 60}:{seconds % 60:02d}"
    return f"{text} /km" if unit else text


def fmt_time(seconds: Any) -> str:
    """``24:05`` under an hour, ``1:52:30`` above it."""
    value = _number(seconds)
    if value is None or value < 0:
        return "—"
    total = int(round(value))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def fmt_delta(seconds: Any) -> str:
    """Signed time difference, ``-1:05`` (faster) or ``+0:40`` (slower)."""
    value = _number(seconds)
    if value is None:
        return "—"
    sign = "-" if value < 0 else "+"
    return sign + fmt_time(abs(value))


_TIME = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})\s*$")


def parse_time(text: Any) -> float | None:
    """``"1:45:00"`` / ``"45:30"`` / ``"45:30.0"`` -> seconds; None if unparsable."""
    if text is None:
        return None
    raw = str(text).strip().split(".")[0]
    match = _TIME.match(raw)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes, seconds = int(match.group(2)), int(match.group(3))
    if seconds >= 60 or (match.group(1) and minutes >= 60):
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return float(total) if total > 0 else None


def parse_pace(text: Any) -> float | None:
    """``"5:30"`` (min:s per km) -> 5.5."""
    if text is None:
        return None
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(?:/km)?\s*$", str(text))
    if not match:
        return None
    minutes, seconds = int(match.group(1)), int(match.group(2))
    if seconds >= 60 or (minutes == 0 and seconds == 0):
        return None
    return minutes + seconds / 60


def race_key(distance_km: Any, tolerance: float = 0.02) -> str | None:
    """Map a distance to a race key when it is within 2% of an official one."""
    km = _number(distance_km)
    if km is None:
        return None
    for key, official in RACES.items():
        if abs(km - official) <= official * tolerance:
            return key
    return None
