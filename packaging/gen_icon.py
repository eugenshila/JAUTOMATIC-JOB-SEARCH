"""Generate ``packaging/jautomatic.ico`` with the standard library only.

The frozen exe, the Start Menu shortcut and the Add/Remove Programs entry all
want an ``.ico``.  Rather than checking in an opaque binary nobody can
rebuild, this module draws the mark (amber "J" on deep navy) and writes a
Vista-style icon: a single 256×256 PNG-compressed entry, which every
supported Windows reads.  Pillow-free on purpose — the icon must be
regenerable on a bare build agent::

    python packaging/gen_icon.py   # rewrites packaging/jautomatic.ico
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 256
NAVY = (26, 34, 51)
AMBER = (245, 176, 65)


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(
        ">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)


def _to_png(pixels: list[bytes]) -> bytes:
    raw = b"".join(b"\x00" + row for row in pixels)  # filter type 0 per scanline
    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(raw, 9))
            + _png_chunk(b"IEND", b""))


def _rounded_mask(x: int, y: int, radius: int) -> bool:
    corners = [(radius, radius), (SIZE - 1 - radius, radius),
               (radius, SIZE - 1 - radius), (SIZE - 1 - radius, SIZE - 1 - radius)]
    for cx, cy in corners:
        dx, dy = x - cx, y - cy
        in_corner = (x < radius or x >= SIZE - radius) and (y < radius or y >= SIZE - radius)
        if in_corner and dx * dx + dy * dy > radius * radius:
            return False
    return True


def render_pixels() -> list[bytes]:
    """Draw the mark: rounded navy tile, amber "J", amber underline bar."""
    rows: list[bytes] = []
    bar_w, stem_x = 44, 140  # bold J stem, slightly right of centre
    top, hook_top = 40, 168
    hook_left = 78
    for y in range(SIZE):
        row = bytearray()
        for x in range(SIZE):
            if not _rounded_mask(x, y, 52):
                row += b"\x00\x00\x00\x00"
                continue
            stem = stem_x - bar_w // 2 <= x < stem_x + bar_w // 2 and top <= y < hook_top + 22
            hook = hook_left <= x < stem_x + bar_w // 2 and hook_top <= y < hook_top + 44
            # Scoop the J's counter out of the hook's upper-left.
            counter = hook_left <= x < stem_x - bar_w // 2 and hook_top <= y < hook_top + 22
            underline = 60 <= x < SIZE - 60 and 208 <= y < 222
            if (stem or hook or underline) and not counter:
                row += bytes(AMBER) + b"\xff"
            else:
                row += bytes(NAVY) + b"\xff"
        rows.append(bytes(row))
    return rows


def to_ico(png: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)  # reserved, type=icon, 1 entry
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    return header + entry + png


def main() -> int:
    ico = to_ico(_to_png(render_pixels()))
    out = Path(__file__).resolve().parent / "jautomatic.ico"
    out.write_bytes(ico)
    print(f"wrote {out} ({len(ico)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
