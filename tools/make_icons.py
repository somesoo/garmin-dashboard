"""PNG icons for the PWA (pwa/icon-192.png, icon-512.png) without an imaging library.

Same picture as pwa/icon.svg: a blue ring with a white dot on black -- flat
colours, no gradient; the edge is anti-aliased by 4x4 supersampling.

    .venv/bin/python tools/make_icons.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

PWA = Path(__file__).resolve().parents[1] / "pwa"
BLUE, WHITE, BLACK = (0x39, 0x87, 0xE5), (0xFA, 0xFA, 0xFA), (0, 0, 0)


def colour(x: float, y: float, size: int) -> tuple[int, int, int]:
    s = size / 512
    d = math.hypot(x - 256 * s, y - 256 * s)
    if d <= 46 * s:
        return WHITE
    if abs(d - 150 * s) <= 22 * s:
        return BLUE
    return BLACK


def png(size: int) -> bytes:
    rows = bytearray()
    for py in range(size):
        rows.append(0)
        for px in range(size):
            acc = [0, 0, 0]
            for sy in range(4):
                for sx in range(4):
                    c = colour(px + (sx + 0.5) / 4, py + (sy + 0.5) / 4, size)
                    acc = [a + b for a, b in zip(acc, c)]
            rows.extend(round(a / 16) for a in acc)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    for size in (192, 512):
        (PWA / f"icon-{size}.png").write_bytes(png(size))
        print(f"pwa/icon-{size}.png")
