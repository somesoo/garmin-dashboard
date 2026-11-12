"""Opt-in terrain elevations. Public NMT tiles are cached; tracks stay local.

The loader never uses the network. The fetch/rebuild coordinator prepares
missing fixed EPSG:2180 tiles before publishing any tables. No GPS trace or
activity identifier is sent to the terrain provider.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from core import config, tenant

SOURCE = "gugik_nmt_evrf2007_2m_v1"
URL = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModel"
TILE_M = 2000
CELL_M = 2
HALO_M = 2
MAX_BYTES = 40 * 1024 * 1024


def settings_path() -> Path:
    return tenant.current().root / "terrain.json"


def settings() -> dict | None:
    path = settings_path()
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    dt.date.fromisoformat(value["since"])
    if value.get("source") != SOURCE:
        raise ValueError("Unknown terrain source")
    return value


def cache_dir() -> Path:
    # Public rasters contain no user data and are shared by all people.
    return config.DATA / "terrain" / SOURCE


def eligible(activities: pd.DataFrame, options: dict) -> set:
    if activities.empty:
        return set()
    days = pd.to_datetime(activities["start_local"], errors="coerce", format="mixed")
    return set(activities.loc[days >= pd.Timestamp(options["since"]), "activity_id"])


def projected(track: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer

    lat = pd.to_numeric(track["lat"], errors="coerce").to_numpy(dtype=float)
    lon = pd.to_numeric(track["lon"], errors="coerce").to_numpy(dtype=float)
    # Fail rather than invent a correction outside this provider's coverage.
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()
            and ((lat >= 48.6) & (lat <= 55.1) & (lon >= 13.7) & (lon <= 24.9)).all()):
        raise ValueError("NMT correction requires valid GPS points in Poland")
    x, y = Transformer.from_crs(4326, 2180, always_xy=True).transform(lon, lat)
    return np.asarray(x), np.asarray(y)


def tile_path(ix: int, iy: int) -> Path:
    return cache_dir() / f"{ix}_{iy}.npz"


def parse_ascii(body: bytes) -> tuple[np.ndarray, float, float, float]:
    stream = io.BytesIO(body)
    header = {}
    while True:
        pos = stream.tell()
        parts = stream.readline().decode("ascii").split()
        if not parts or parts[0].lower() not in {
            "ncols", "nrows", "xllcorner", "yllcorner", "cellsize", "nodata_value"
        }:
            stream.seek(pos)
            break
        header[parts[0].lower()] = float(parts[1])
    nrows, ncols = int(header["nrows"]), int(header["ncols"])
    if nrows > 1100 or ncols > 1100 or min(nrows, ncols) < 2:
        raise ValueError("Unexpected NMT grid dimensions")
    values = np.fromstring(stream.read().decode("ascii"), sep=" ", dtype=np.float32)
    if values.size != nrows * ncols:
        raise ValueError("Incomplete NMT raster")
    values = values.reshape(nrows, ncols)[::-1].copy()  # south to north
    nodata = header.get("nodata_value", -9999)
    values[(values == nodata) | (values < -500) | (values > 9000)] = np.nan
    return values, header["xllcorner"], header["yllcorner"], header["cellsize"]


def download(ix: int, iy: int) -> None:
    path = tile_path(ix, iy)
    if path.exists():
        return
    print("NMT: downloading a missing public terrain tile", flush=True)
    left, bottom = ix * TILE_M - HALO_M, iy * TILE_M - HALO_M
    side = TILE_M + 2 * HALO_M
    params = dict(SERVICE="WCS", VERSION="1.0.0", REQUEST="GetCoverage",
                  COVERAGE="DTM_PL-EVRF2007-NH", CRS="EPSG:2180", RESPONSE_CRS="EPSG:2180",
                  BBOX=f"{left},{bottom},{left + side},{bottom + side}",
                  WIDTH=side // CELL_M, HEIGHT=side // CELL_M,
                  FORMAT="image/x-aaigrid", INTERPOLATION="bilinear")
    # Only fixed public grid squares are requested, never a route-shaped bbox.
    request = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "GarminDashboard-NMT/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError("NMT response too large")
            grid, x, y, cell = parse_ascii(body)
            if not (abs(x - left) < 0.01 and abs(y - bottom) < 0.01 and abs(cell - CELL_M) < 0.001
                    and grid.shape == (side // CELL_M, side // CELL_M) and np.isfinite(grid).any()):
                raise ValueError("NMT grid does not match requested tile")
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.part")
            try:
                with tmp.open("wb") as out:
                    np.savez_compressed(out, elevation=grid, x=x, y=y, cell=cell)
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
            return
        except (OSError, ValueError, KeyError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def sample(track: pd.DataFrame, *, prepare: bool = False) -> np.ndarray:
    x, y = projected(track)
    keys = np.column_stack((np.floor(x / TILE_M).astype(int), np.floor(y / TILE_M).astype(int)))
    result = np.full(len(track), np.nan)
    for ix, iy in sorted(set(map(tuple, keys))):
        if prepare:
            download(int(ix), int(iy))
        path = tile_path(int(ix), int(iy))
        if not path.exists():
            raise FileNotFoundError("NMT tile missing; run python -m etl.terrain --prepare")
        mask = (keys[:, 0] == ix) & (keys[:, 1] == iy)
        with np.load(path, allow_pickle=False) as tile:
            z = tile["elevation"]
            # ASCII grid coordinates refer to cell corners; sample cell centres.
            u = (x[mask] - float(tile["x"])) / float(tile["cell"]) - 0.5
            v = (y[mask] - float(tile["y"])) / float(tile["cell"]) - 0.5
            col, row = np.floor(u).astype(int), np.floor(v).astype(int)
            if ((col < 0) | (row < 0) | (col + 1 >= z.shape[1]) | (row + 1 >= z.shape[0])).any():
                raise ValueError("GPS outside cached NMT raster")
            a, b = u - col, v - row
            result[mask] = ((1-a)*(1-b)*z[row, col] + a*(1-b)*z[row, col+1]
                            + (1-a)*b*z[row+1, col] + a*b*z[row+1, col+1])
    if not np.isfinite(result).all():
        raise ValueError("NMT has missing cells; activity was not corrected")
    return result.round(2)


def cumulative(track: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """One distance-smoothed profile for the total, laps and replay (metres)."""
    distance = pd.to_numeric(track["distance_km"], errors="coerce").to_numpy(dtype=float) * 1000
    elevation = pd.to_numeric(track["elevation_m"], errors="coerce").to_numpy(dtype=float)
    if not (np.isfinite(distance).all() and np.isfinite(elevation).all()):
        raise ValueError("Terrain profile requires a complete distance/elevation stream")
    distance = np.maximum.accumulate(distance)
    keep = np.r_[True, np.diff(distance) > 0]
    if keep.sum() < 2:
        return np.zeros(len(track)), np.zeros(len(track))
    axis = np.r_[np.arange(distance[0], distance[-1], 10.0), distance[-1]]
    profile = np.interp(axis, distance[keep], elevation[keep])
    smoothed = pd.Series(profile).rolling(5, center=True, min_periods=1).mean().to_numpy()
    change = np.diff(smoothed, prepend=smoothed[0])
    up, down = np.cumsum(np.maximum(change, 0)), np.cumsum(np.maximum(-change, 0))
    return np.interp(distance, axis, up).round(3), np.interp(distance, axis, down).round(3)


def correct_routes(routes: pd.DataFrame, activities: pd.DataFrame, *, prepare: bool = False) -> pd.DataFrame:
    options = settings()
    if options is None or routes.empty:
        return routes
    ids = eligible(activities, options)
    out = routes.copy()
    for aid, track in routes[routes.activity_id.isin(ids)].groupby("activity_id", sort=False):
        track = track.sort_values("seq").copy()
        values = sample(track, prepare=prepare)
        if prepare:
            continue
        if "elevation_original_m" not in out:
            out["elevation_original_m"] = out.get("elevation_m", np.nan)
            out["elevation_source"] = None
        track["elevation_m"] = values
        up, down = cumulative(track)
        out.loc[track.index, "elevation_m"] = values
        out.loc[track.index, "elevation_source"] = SOURCE
        out.loc[track.index, "elevation_gain_cum_m"] = up
        out.loc[track.index, "elevation_loss_cum_m"] = down
    return out


def correct_summaries(activities: pd.DataFrame, summary: pd.DataFrame, laps: pd.DataFrame,
                      routes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if "elevation_source" not in routes:
        return activities, summary, laps
    activities, summary, laps = activities.copy(), summary.copy(), laps.copy()
    for frame in (activities, summary, laps):
        if "elevation_gain_m" in frame:
            if "elevation_gain_original_m" not in frame:
                frame["elevation_gain_original_m"] = frame["elevation_gain_m"]
            if "elevation_source" not in frame:
                frame["elevation_source"] = None
    for aid, track in routes[routes.elevation_source == SOURCE].groupby("activity_id", sort=False):
        track = track.sort_values("seq")
        total = round(float(track.elevation_gain_cum_m.iloc[-1]), 1)
        for frame in (activities, summary):
            mask = frame.activity_id == aid
            frame.loc[mask, "elevation_gain_m"] = total
            frame.loc[mask, "elevation_source"] = SOURCE
        if not laps.empty:
            selected = laps[laps.activity_id == aid].sort_values("lap")
            distances = pd.to_numeric(selected.distance_m, errors="coerce")
            if not distances.notna().all() or (distances < 0).any():
                raise ValueError("Cannot align terrain elevations with lap distances")
            edges = np.r_[0, distances.cumsum().to_numpy()]
            gains = np.interp(edges, np.maximum.accumulate(track.distance_km.to_numpy() * 1000),
                              track.elevation_gain_cum_m.to_numpy())
            laps.loc[selected.index, "elevation_gain_m"] = np.diff(gains).round(1)
            laps.loc[selected.index, "elevation_source"] = SOURCE
    return activities, summary, laps


def prepare() -> None:
    if settings() is None:
        return
    from core import privacy
    from etl import load

    if privacy.required(tenant.current()):
        raise PermissionError("Current privacy consent required")
    activities = load.build_activities()
    routes, _ = load.build_routes(correct=False)
    correct_routes(routes, activities, prepare=True)


def backfill() -> int:
    """Publish only elevation fields in existing tables; keep older rows exact.

    Called through etl/run.py, which owns the fetch lock. Build and verify all
    six frames before writing; roll back on a publication error.
    """
    from core import audit, privacy
    from etl import load
    from running import sessions

    person = tenant.current()
    if privacy.required(person):
        raise PermissionError("Current privacy consent required")
    options = settings()
    if options is None:
        raise ValueError("Enable terrain correction before backfilling")
    audit.record("admin", person.id, by="owner", detail="backfill elevation fields from configured local date")
    names = ("activities", "routes", "route_summary", "run_laps", "run_sessions", "run_splits")
    old = {name: pd.read_parquet(config.tables() / f"{name}.parquet") for name in names}
    raw = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in config.raw().rglob("*") if p.is_file()}
    ids = eligible(old["activities"], options) & set(old["routes"].activity_id)
    correct_routes(old["routes"], old["activities"], prepare=True)
    routes = correct_routes(old["routes"], old["activities"])
    activities, summary, laps = correct_summaries(old["activities"], old["route_summary"], old["run_laps"], routes)
    new = dict(activities=activities, routes=routes, route_summary=summary, run_laps=laps)
    runs = old["run_sessions"].copy()
    if "elevation_gain_original_m" not in runs:
        runs["elevation_gain_original_m"] = runs["elevation_gain_m"]
    if "elevation_source" not in runs:
        runs["elevation_source"] = None
    gain_by_id = activities.set_index("activity_id").elevation_gain_m
    mask = runs.activity_id.isin(ids)
    runs.loc[mask, "elevation_gain_m"] = runs.loc[mask, "activity_id"].map(gain_by_id)
    runs.loc[mask, "elevation_source"] = SOURCE
    new["run_sessions"] = runs
    splits = old["run_splits"].copy()
    for aid, track in routes[routes.activity_id.isin(ids)].groupby("activity_id", sort=False):
        selected = splits[splits.activity_id == aid]
        if selected.empty:
            continue
        computed = sessions.km_splits(track).set_index("km")
        for column in ("elev_gain_m", "elev_loss_m"):
            values = selected["km"].map(computed[column])
            if values.isna().any():
                raise ValueError("Cannot align corrected kilometre splits")
            splits.loc[selected.index, column] = values
    new["run_splits"] = splits
    allowed = {"routes": {"elevation_m"}, "run_splits": {"elev_gain_m", "elev_loss_m"}}
    for name in names:
        before, after = old[name], new[name]
        historic = ~before.activity_id.isin(ids)
        pd.testing.assert_frame_equal(before.loc[historic], after.loc[historic, before.columns], check_exact=True)
        changed = allowed.get(name, {"elevation_gain_m"})
        unchanged = [c for c in before if c not in changed]
        pd.testing.assert_frame_equal(before[unchanged], after[unchanged], check_exact=True)
    if raw != {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in config.raw().rglob("*") if p.is_file()}:
        raise RuntimeError("Raw data changed during terrain preparation; retry")
    written = []
    try:
        for name in names:
            load.write_table(new[name], name)
            written.append(name)
        for name in names:
            pd.testing.assert_frame_equal(new[name], pd.read_parquet(config.tables() / f"{name}.parquet"),
                                          check_exact=True, check_dtype=False)
    except Exception:
        for name in written:
            load.write_table(old[name], name)
        raise
    load.mark_built()
    print(f"NMT: corrected {len(ids)} activities; older rows and other fields verified unchanged", flush=True)
    return len(ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare local GUGiK terrain tiles for the current person")
    parser.add_argument("--since", type=dt.date.fromisoformat, help="enable corrections from this local date")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    from core import audit, privacy

    person = tenant.current()
    if privacy.required(person):
        raise PermissionError("Current privacy consent required")
    if person.source != "garmin":
        raise ValueError("Terrain correction currently supports Garmin activities")
    audit.record("admin", person.id, by="owner", detail="configure/prepare local terrain correction")
    if args.since:
        settings_path().parent.mkdir(parents=True, exist_ok=True)
        settings_path().write_text(json.dumps({"since": args.since.isoformat(), "source": SOURCE}), encoding="utf-8")
    if args.prepare:
        prepare()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
