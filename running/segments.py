"""Private segments and same-route runs, from the GPS tracks alone.

Two questions the watch's laps cannot answer -- a long run or an easy loop
has no workout steps:

* **Same route.** Each track becomes a set of ~50 m grid cells (the track is
  densified to 10 m first, so a 400-sample stream of a half marathon does not
  leave holes). Two runs share a route when each covers >= 80% of the other's
  cells (a 3x3 neighbourhood absorbs GPS scatter) and the distances agree
  within ~15%. Direction is ignored: the same loop run the other way is the
  same route.
* **Segments** (a private Strava). A segment is a stretch cut out of one run:
  checkpoints every ~20 m from its start to its end. A run passes it when the
  track comes within 35 m of the start, later within 35 m of the end, the
  distance between the two matches the segment's length, and every checkpoint
  lies within 40 m of the track in between. A run can pass it more than once
  (laps of a park). Direction matters: start to end.

* **Shared stretches** -- segments nobody had to draw. For one run, every
  other run whose track runs alongside it (within 35 m) for at least 400 m:
  the longest such stretch, of whatever length it happens to be, is cut as an
  ad-hoc segment and timed on both runs with the same matcher (so direction
  counts). Saving one makes it a permanent segment.

Timing is on the sample stream, accurate to a few seconds like the km splits.
The pace of a pass uses the segment's own length, so every pass of one
segment is measured on the same distance.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

M_PER_DEG = 111_320.0
STEP_M = 10.0
CELL_M = 50.0
ROUTE_COVER, ROUTE_LENGTH = 0.8, 0.15
NEAR_M, PATH_M = 35.0, 40.0
CHECKPOINT_M = 20.0
SHARED_MIN_M = 400.0


def path(track: pd.DataFrame) -> pd.DataFrame:
    """The track every 10 m: ``m`` (watch distance), ``s`` (timer), lat, lon, hr."""
    columns = ["m", "s", "lat", "lon", "hr"]
    if track is None or track.empty or not {"lat", "lon", "distance_km"} <= set(track.columns):
        return pd.DataFrame(columns=columns)
    track = track.sort_values("seq") if "seq" in track.columns else track
    frame = pd.DataFrame({
        "m": pd.to_numeric(track["distance_km"], errors="coerce").values * 1000,
        "s": pd.to_numeric(track.get("duration_s"), errors="coerce").values
        if "duration_s" in track.columns else np.nan,
        "lat": pd.to_numeric(track["lat"], errors="coerce").values,
        "lon": pd.to_numeric(track["lon"], errors="coerce").values,
        "hr": pd.to_numeric(track["hr"], errors="coerce").values if "hr" in track.columns else np.nan,
    }).dropna(subset=["m", "lat", "lon"])
    if frame["s"].isna().all() and "timestamp_ms" in track.columns:
        stamps = pd.to_numeric(track["timestamp_ms"], errors="coerce")
        frame["s"] = ((stamps - stamps.min()) / 1000).reindex(frame.index).values
    frame = frame.dropna(subset=["s"])
    frame = frame[(frame["m"].diff().fillna(0) >= 0) & (frame["s"].diff().fillna(0) >= 0)]
    frame = frame.drop_duplicates("m")
    if len(frame) < 3:
        return pd.DataFrame(columns=columns)
    grid = np.arange(frame["m"].iloc[0], frame["m"].iloc[-1], STEP_M)
    out = {"m": grid}
    for column in ("s", "lat", "lon"):
        out[column] = np.interp(grid, frame["m"], frame[column])
    hr = frame.dropna(subset=["hr"])
    out["hr"] = np.interp(grid, hr["m"], hr["hr"]) if len(hr) >= 2 else np.full(len(grid), np.nan)
    return pd.DataFrame(out)


def _xy(lat: np.ndarray, lon: np.ndarray, origin: tuple[float, float]) -> np.ndarray:
    """Metres east/north of ``origin`` -- flat over a few kilometres."""
    lat0, lon0 = origin
    return np.column_stack([(lon - lon0) * M_PER_DEG * np.cos(np.radians(lat0)), (lat - lat0) * M_PER_DEG])


# ----------------------------------------------------------------- same route


def cells(points: pd.DataFrame) -> frozenset[tuple[int, int]]:
    """~50 m grid cells the path crosses (one longitude scale per whole degree,
    so every run near one place lands on the same grid)."""
    if points.empty:
        return frozenset()
    lat, lon = points["lat"].to_numpy(), points["lon"].to_numpy()
    scale = np.cos(np.radians(np.round(lat)))
    rows = np.floor(lat * M_PER_DEG / CELL_M).astype(int)
    cols = np.floor(lon * M_PER_DEG * scale / CELL_M).astype(int)
    return frozenset(zip(rows.tolist(), cols.tolist()))


def _cover(a: frozenset, b: frozenset) -> float:
    """Share of ``a``'s cells with a cell of ``b`` in their 3x3 neighbourhood."""
    if not a:
        return 0.0
    hit = sum(1 for r, c in a if any((r + i, c + j) in b for i in (-1, 0, 1) for j in (-1, 0, 1)))
    return hit / len(a)


def paths(routes: pd.DataFrame) -> dict[int, pd.DataFrame]:
    """``path`` of every track, by activity; the tracks too short to use are left out."""
    if routes is None or routes.empty:
        return {}
    out = {int(a): path(t) for a, t in routes.groupby("activity_id")}
    return {a: p for a, p in out.items() if len(p) >= 20}


def signatures(tracks: dict[int, pd.DataFrame]) -> dict[int, dict[str, Any]]:
    """Per activity with a track: its cells, distance and bounding box."""
    out: dict[int, dict[str, Any]] = {}
    for activity_id, points in tracks.items():
        out[int(activity_id)] = {
            "cells": cells(points), "km": float(points["m"].iloc[-1] - points["m"].iloc[0]) / 1000,
            "box": (points["lat"].min(), points["lat"].max(), points["lon"].min(), points["lon"].max()),
        }
    return out


def same_route(signs: dict[int, dict[str, Any]], activity_id: int) -> list[tuple[int, float]]:
    """Other runs on this run's route: ``(activity_id, overlap)``, best first."""
    me = signs.get(int(activity_id))
    if me is None:
        return []
    found = []
    for other, sign in signs.items():
        longer, shorter = max(sign["km"], me["km"]), min(sign["km"], me["km"])
        if other == activity_id or shorter <= 0 or longer / shorter - 1 > ROUTE_LENGTH:
            continue
        a, b, pad = me["box"], sign["box"], 0.002  # ~150 m: GPS scatter, the other side of the road
        if a[1] + pad < b[0] or b[1] + pad < a[0] or a[3] + pad < b[2] or b[3] + pad < a[2]:
            continue
        overlap = min(_cover(me["cells"], sign["cells"]), _cover(sign["cells"], me["cells"]))
        if overlap >= ROUTE_COVER:
            found.append((other, round(overlap, 3)))
    return sorted(found, key=lambda pair: -pair[1])


# ------------------------------------------------------------------- segments


def cut(track: pd.DataFrame, km_from: float, km_to: float) -> dict[str, Any] | None:
    """A segment definition from a stretch of one run (watch km)."""
    points = path(track)
    if points.empty:
        return None
    offset = points["m"] - points["m"].iloc[0]
    index = np.flatnonzero(((offset >= km_from * 1000) & (offset <= km_to * 1000)).to_numpy())
    return stretch(points, int(index[0]), int(index[-1])) if len(index) >= 3 else None


def _groups(mask: np.ndarray) -> list[np.ndarray]:
    """Index runs where ``mask`` is True."""
    index = np.flatnonzero(mask)
    if index.size == 0:
        return []
    return np.split(index, np.flatnonzero(np.diff(index) > 1) + 1)


def passes(segment: dict[str, Any], points: pd.DataFrame) -> list[dict[str, Any]]:
    """Every time this path runs the segment start to end."""
    checkpoints = np.asarray(segment.get("points") or [], dtype=float)
    length = float(segment.get("length_m") or 0)
    if len(checkpoints) < 2 or length <= 0 or points.empty:
        return []
    origin = (float(checkpoints[0][0]), float(checkpoints[0][1]))
    xy = _xy(points["lat"].to_numpy(), points["lon"].to_numpy(), origin)
    marks = _xy(checkpoints[:, 0], checkpoints[:, 1], origin)
    to_start = np.hypot(*(xy - marks[0]).T)
    to_end = np.hypot(*(xy - marks[-1]).T)
    metres, seconds, hr = points["m"].to_numpy(), points["s"].to_numpy(), points["hr"].to_numpy()
    starts = [g[np.argmin(to_start[g])] for g in _groups(to_start < NEAR_M)]
    ends = [g[np.argmin(to_end[g])] for g in _groups(to_end < NEAR_M)]
    found: list[dict[str, Any]] = []
    for i in starts:
        if found and i <= found[-1]["_end"]:
            continue
        j = next((j for j in ends if j > i and 0.85 * length <= metres[j] - metres[i] <= 1.2 * length), None)
        if j is None:
            continue
        stretch = xy[i:j + 1]
        gaps = np.min(np.hypot(stretch[None, :, 0] - marks[:, None, 0], stretch[None, :, 1] - marks[:, None, 1]),
                      axis=1)
        if gaps.max() > PATH_M:
            continue
        elapsed = float(seconds[j] - seconds[i])
        if elapsed <= 0:
            continue
        beats = hr[i:j + 1]
        found.append({
            "_end": j,
            "seconds": round(elapsed, 1),
            "pace_min_km": elapsed / 60 / (length / 1000),
            "hr": round(float(np.nanmean(beats)), 0) if np.isfinite(beats).any() else np.nan,
            "at_km": round(float(metres[i] - metres[0]) / 1000, 2),
        })
    for item in found:
        item.pop("_end")
    return found


def efforts(segment_list: list[dict[str, Any]], tracks: dict[int, pd.DataFrame], runs: pd.DataFrame) -> pd.DataFrame:
    """Every pass of every segment by every run with a track, ranked per
    segment (1 = fastest)."""
    columns = ["segment_id", "activity_id", "start_local", "kind", "pass", "at_km", "seconds", "pace_min_km",
               "hr", "rank", "of"]
    if not segment_list or not tracks or runs is None or runs.empty:
        return pd.DataFrame(columns=columns)
    meta = runs.set_index("activity_id")
    tracks = {a: p for a, p in tracks.items() if a in meta.index}
    rows = []
    for segment in segment_list:
        marks = np.asarray(segment.get("points") or [], dtype=float)
        if len(marks) < 2:
            continue
        lat_lo, lat_hi = marks[:, 0].min() - 0.001, marks[:, 0].max() + 0.001
        lon_lo, lon_hi = marks[:, 1].min() - 0.0015, marks[:, 1].max() + 0.0015
        for activity_id, points in tracks.items():
            if points.empty or points["lat"].max() < lat_lo or points["lat"].min() > lat_hi \
                    or points["lon"].max() < lon_lo or points["lon"].min() > lon_hi:
                continue
            for number, item in enumerate(passes(segment, points), start=1):
                rows.append({"segment_id": segment["id"], "activity_id": activity_id,
                             "start_local": meta.at[activity_id, "start_local"],
                             "kind": meta.at[activity_id, "kind"] if "kind" in meta.columns else None,
                             "pass": number, **item})
    frame = pd.DataFrame(rows, columns=columns[:-2])
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame["rank"] = frame.groupby("segment_id")["seconds"].rank(method="min").astype(int)
    frame["of"] = frame.groupby("segment_id")["seconds"].transform("size")
    return frame.sort_values(["segment_id", "start_local", "pass"]).reset_index(drop=True)


def stretch(points: pd.DataFrame, i: int, j: int) -> dict[str, Any]:
    """A segment definition from path rows ``i..j`` (checkpoints every ~20 m)."""
    every = max(1, int(round(CHECKPOINT_M / STEP_M)))
    picked = points.iloc[list(range(i, j, every)) + [j]]
    return {
        "length_m": round(float(points["m"].iloc[j] - points["m"].iloc[i]), 1),
        "points": [[round(lat, 6), round(lon, 6)] for lat, lon in zip(picked["lat"], picked["lon"])],
    }


def shared(activity_id: int, tracks: dict[int, pd.DataFrame], runs: pd.DataFrame) -> pd.DataFrame:
    """For one run: the longest stretch it shares with each other run (same
    direction, >= 400 m), timed on both. ``d_pace_s`` < 0 = this run faster."""
    columns = ["other_id", "start_local", "kind", "km_from", "km_to", "length_m", "seconds", "seconds_other",
               "pace", "pace_other", "hr", "hr_other", "d_pace_s", "d_hr", "d_eff_pct", "segment"]
    me = tracks.get(int(activity_id))
    if me is None or me.empty or runs is None or runs.empty:
        return pd.DataFrame(columns=columns)
    meta = runs.set_index("activity_id")
    origin = (float(me["lat"].iloc[0]), float(me["lon"].iloc[0]))
    mine = _xy(me["lat"].to_numpy(), me["lon"].to_numpy(), origin)
    low, high = mine.min(axis=0) - 200, mine.max(axis=0) + 200
    rows = []
    for other, points in tracks.items():
        if other == activity_id or other not in meta.index or points.empty:
            continue
        theirs = _xy(points["lat"].to_numpy(), points["lon"].to_numpy(), origin)
        inside = np.all((theirs >= low) & (theirs <= high), axis=1)
        if inside.sum() < SHARED_MIN_M / STEP_M:
            continue
        near, _ = cKDTree(theirs[inside]).query(mine, distance_upper_bound=NEAR_M)
        close = np.isfinite(near)
        # Bridge GPS dropouts of up to ~50 m inside an otherwise shared stretch.
        gaps = _groups(~close)
        for gap in gaps:
            if 0 < gap[0] and gap[-1] < len(close) - 1 and len(gap) <= 5:
                close[gap] = True
        best = None
        for group in sorted(_groups(close), key=len, reverse=True):
            i, j = int(group[0]), int(group[-1])
            if me["m"].iloc[j] - me["m"].iloc[i] < SHARED_MIN_M:
                break
            segment = stretch(me, i, j)
            there = passes(segment, points)
            if there:
                best = (i, j, segment, min(there, key=lambda p: p["seconds"]))
                break
        if best is None:
            continue
        i, j, segment, there = best
        seconds = float(me["s"].iloc[j] - me["s"].iloc[i])
        if seconds <= 0:
            continue
        km = segment["length_m"] / 1000
        hr = float(np.nanmean(me["hr"].iloc[i:j + 1])) if me["hr"].iloc[i:j + 1].notna().any() else np.nan
        pace, pace_other = seconds / 60 / km, there["seconds"] / 60 / km
        efficiency = (1000 / pace) / hr if hr else np.nan  # metres per beat
        efficiency_other = (1000 / pace_other) / there["hr"] if there["hr"] else np.nan
        rows.append({
            "other_id": other, "start_local": meta.at[other, "start_local"],
            "kind": meta.at[other, "kind"] if "kind" in meta.columns else None,
            "km_from": round(float(me["m"].iloc[i] - me["m"].iloc[0]) / 1000, 2),
            "km_to": round(float(me["m"].iloc[j] - me["m"].iloc[0]) / 1000, 2),
            "length_m": segment["length_m"], "seconds": round(seconds, 1), "seconds_other": there["seconds"],
            "pace": pace, "pace_other": pace_other, "hr": round(hr) if pd.notna(hr) else np.nan,
            "hr_other": there["hr"], "d_pace_s": (pace - pace_other) * 60,
            "d_hr": hr - there["hr"] if pd.notna(hr) and pd.notna(there["hr"]) else np.nan,
            "d_eff_pct": (efficiency / efficiency_other - 1) * 100
            if pd.notna(efficiency) and pd.notna(efficiency_other) else np.nan,
            "segment": segment,
        })
    frame = pd.DataFrame(rows, columns=columns)
    return frame.sort_values("length_m", ascending=False).reset_index(drop=True)
