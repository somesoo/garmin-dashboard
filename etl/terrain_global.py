"""Offline sampling of public Mapzen Terrarium tiles.

Sources: https://registry.opendata.aws/terrain-tiles/ and Tilezen/Joerd.
Only fixed public tile addresses are requested, never GPS arrays or activity IDs.
"""
from __future__ import annotations

import io
import os
import time
import urllib.request

import numpy as np
import pandas as pd

from core import config

SOURCE = "mapzen_terrarium_z12_v1"
ZOOM = 12
PIXELS = 256
WORLD = (2 ** ZOOM) * PIXELS
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium"


def cache_dir():
    return config.DATA / "terrain" / SOURCE


def pixel_coordinates(track: pd.DataFrame):
    lon = pd.to_numeric(track.lon, errors="coerce").to_numpy(dtype=float)
    lat = pd.to_numeric(track.lat, errors="coerce").to_numpy(dtype=float)
    if not (np.isfinite(lon).all() and np.isfinite(lat).all()
            and (np.abs(lon) <= 180).all() and (np.abs(lat) < 85.0511).all()):
        raise ValueError("Invalid GPS coordinates for global terrain")
    x = (lon + 180) / 360 * WORLD - 0.5
    y = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * WORLD - 0.5
    return x, y


def tiles(track: pd.DataFrame) -> set[tuple[int, int]]:
    x, y = pixel_coordinates(track)
    col, row = np.floor(x).astype(int), np.floor(y).astype(int)
    return {(int(cx // PIXELS % (2 ** ZOOM)), int(ry // PIXELS))
            for dx, dy in ((0, 0), (0, 1), (1, 0), (1, 1)) for cx, ry in zip(col + dx, row + dy)}


def download(x: int, y: int) -> None:
    from PIL import Image

    path = cache_dir() / f"{x}_{y}.npz"
    if path.exists():
        return
    request = urllib.request.Request(f"{URL}/{ZOOM}/{x}/{y}.png",
                                     headers={"User-Agent": "GarminDashboard-Terrain/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError("Global terrain tile too large")
            with Image.open(io.BytesIO(body)) as image:
                if image.size != (PIXELS, PIXELS) or image.mode != "RGB":
                    raise ValueError("Unexpected Terrarium tile format")
                rgb = np.asarray(image, dtype=np.float32)
            height = rgb[:, :, 0] * 256 + rgb[:, :, 1] + rgb[:, :, 2] / 256 - 32768
            if not (np.isfinite(height).all() and (height >= -12000).all() and (height <= 9000).all()):
                raise ValueError("Invalid global terrain height")
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.part")
            try:
                with tmp.open("wb") as out:
                    np.savez_compressed(out, elevation=height)
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
            return
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def sample(track: pd.DataFrame) -> np.ndarray:
    x, y = pixel_coordinates(track)
    col, row = np.floor(x).astype(int), np.floor(y).astype(int)
    result = np.zeros(len(track))
    for dx, dy, weight in ((0, 0, (1-(x-col))*(1-(y-row))), (1, 0, (x-col)*(1-(y-row))),
                           (0, 1, (1-(x-col))*(y-row)), (1, 1, (x-col)*(y-row))):
        cx, ry = col + dx, row + dy
        tx, ty = (cx // PIXELS) % (2 ** ZOOM), ry // PIXELS
        for ix, iy in sorted(set(zip(tx, ty))):
            mask = (tx == ix) & (ty == iy)
            path = cache_dir() / f"{ix}_{iy}.npz"
            if not path.exists():
                raise FileNotFoundError("Global terrain tile missing; prepare terrain first")
            with np.load(path, allow_pickle=False) as tile:
                result[mask] += tile["elevation"][ry[mask] % PIXELS, cx[mask] % PIXELS] * weight[mask]
    return result.round(2)
