#!/usr/bin/env python3
"""Generate the installer/app art: ``app_icon.ico``, ``app_icon.png`` and the two
WiX UI bitmaps - from pure maths, with no fonts and no third-party libraries.

Why a generator instead of committed binary art:

* it is deterministic, so ``--check`` can prove the committed files are current
  (the same trick ``tools/screenshot.py`` uses for the README screenshots),
* the mark is drawn from signed-distance fields, so every size - 16 px in the
  title bar up to 256 px in the installer - is genuinely rendered, not scaled,
* recolouring means editing two constants, not re-exporting nine bitmaps.

    python tools/make_assets.py            # (re)write packaging/assets/*
    python tools/make_assets.py --check    # fail if the committed art drifted
    python tools/make_assets.py --sizes 16,32,256 --out /tmp/icons

Only the standard library is used (struct + zlib), so this runs anywhere and the
packaging build never needs Pillow.
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "packaging" / "assets"

# --------------------------------------------------------------------------- #
# palette - mirrors jautomatic/ui/theme.py so the icon matches the app
# --------------------------------------------------------------------------- #
NAVY_TOP = (0x1b, 0x25, 0x40)
NAVY_BOTTOM = (0x0b, 0x10, 0x20)
NAVY_RIM = (0x2c, 0x3a, 0x60)
ACCENT = (0x4f, 0x8c, 0xff)
WHITE = (0xff, 0xff, 0xff)
LIGHT_TOP = (0xf3, 0xf5, 0xfb)
LIGHT_BOTTOM = (0xe4, 0xe9, 0xf6)

DEFAULT_SIZES = (16, 24, 32, 48, 64, 128, 256)
MASTER_PNG_SIZE = 512
BANNER_SIZE = (493, 58)          # WiX WixUIBannerBitmap
DIALOG_SIZE = (499, 312)         # WiX WixUIDialogBitmap
DIALOG_PANEL = 166               # decorative left band of the dialog bitmap
DIALOG_TILE = 112                # mark size (px) inside that band

# The mark, in the unit square of its own tile: a bold "J" (stem + semicircle
# hook) plus an accent dot, both drawn as stroked/filled SDFs.
STEM_TOP = (0.600, 0.205)
STEM_BOTTOM = (0.600, 0.625)
ARC_CENTRE = (0.440, 0.625)
ARC_RADIUS = 0.160
STROKE = 0.115
DOT_CENTRE = (0.782, 0.248)
DOT_RADIUS = 0.062
GLOW_WIDTH = 0.09

#: width of one render sample in normalised units; set per render by rasterise()
AA = 1.0 / 1024.0


# --------------------------------------------------------------------------- #
# signed-distance helpers (all coordinates normalised to 0..1, y pointing down)
# --------------------------------------------------------------------------- #
def edge(distance: float) -> float:
    """Signed distance -> coverage in [0, 1], antialiased over one sample."""
    return min(1.0, max(0.0, 0.5 - distance / AA))


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _rrect_dist(px: float, py: float, hw: float, hh: float, radius: float) -> float:
    """Distance to a rounded rectangle centred on (0.5, 0.5) in unit space."""
    dx = abs(px - 0.5) - (hw - radius)
    dy = abs(py - 0.5) - (hh - radius)
    outside = math.hypot(max(dx, 0.0), max(dy, 0.0))
    return outside + min(max(dx, dy), 0.0) - radius


def _arc_dist(px: float, py: float, cx: float, cy: float, radius: float,
              a0: float, a1: float) -> float:
    """Distance to a circular arc (angles in radians, y pointing down)."""
    dx, dy = px - cx, py - cy
    angle = math.atan2(dy, dx) % (2.0 * math.pi)
    if a0 <= angle <= a1:
        return abs(math.hypot(dx, dy) - radius)
    return min(math.hypot(px - (cx + radius * math.cos(a0)), py - (cy + radius * math.sin(a0))),
               math.hypot(px - (cx + radius * math.cos(a1)), py - (cy + radius * math.sin(a1))))


def _mark_dist(u: float, v: float) -> float:
    """Signed distance to the white "J" stroke of the mark."""
    stem = _seg_dist(u, v, *STEM_TOP, *STEM_BOTTOM)
    hook = _arc_dist(u, v, ARC_CENTRE[0], ARC_CENTRE[1], ARC_RADIUS, 0.0, math.pi)
    return min(stem, hook) - STROKE / 2.0


def _dot_dist(u: float, v: float) -> float:
    """Signed distance to the accent dot."""
    return math.hypot(u - DOT_CENTRE[0], v - DOT_CENTRE[1]) - DOT_RADIUS


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _over(base: tuple, colour: tuple, alpha: float) -> tuple:
    if alpha <= 0.0:
        return base
    if alpha >= 1.0:
        return colour
    return tuple(round(base[i] * (1.0 - alpha) + colour[i] * alpha) for i in range(3))


# --------------------------------------------------------------------------- #
# scenes
# --------------------------------------------------------------------------- #
def _paint_mark(u: float, v: float, aa: float) -> tuple | None:
    """Mark layers at tile coordinates: returns (colour, alpha) or None."""
    saved = AA
    globals()["AA"] = aa
    try:
        layer: tuple | None = None
        glow = _dot_dist(u, v)
        if glow < GLOW_WIDTH:                            # soft accent halo first
            layer = (ACCENT, 0.28 * max(0.0, 1.0 - max(0.0, glow) / GLOW_WIDTH))
        dot = edge(_dot_dist(u, v))
        if dot > 0.0:
            layer = (ACCENT, dot)
        stroke = edge(_mark_dist(u, v))
        if stroke > 0.0:
            layer = (WHITE, stroke)
        return layer
    finally:
        globals()["AA"] = saved


def paint_icon(x: float, y: float, aa: float | None = None) -> tuple:
    """Square app icon: navy rounded tile, white J, accent dot."""
    saved = AA
    if aa is not None:
        globals()["AA"] = aa
    try:
        tile = _rrect_dist(x, y, 0.47, 0.47, 0.195)
        alpha = edge(tile)
        if alpha <= 0.0:
            return (0, 0, 0, 0)
        base = _mix(NAVY_TOP, NAVY_BOTTOM, y)
        base = _over(base, NAVY_RIM, max(0.0, 0.55 - y) * 0.45)      # light from above
        layer = _paint_mark(x, y, globals()["AA"])
        if layer is not None:
            base = _over(base, layer[0], layer[1])
        return (base[0], base[1], base[2], round(255 * alpha))
    finally:
        globals()["AA"] = saved


def _banner_tile(width: int, height: int) -> tuple:
    """(x0, y0, size) of the mark tile inside the banner, right aligned."""
    size = round(height * 0.76)
    x0 = width - size - round(height * 0.18)
    y0 = (height - size) // 2
    return x0, y0, size


def paint_banner(x: float, y: float, width: int, height: int) -> tuple:
    """493x58 light strip: MSI paints the dialog title over the left two thirds."""
    base = _mix(LIGHT_TOP, LIGHT_BOTTOM, y)
    base = _over(base, ACCENT, edge(0.945 - y) * 0.9)                # accent rule
    tx, ty, size = _banner_tile(width, height)
    u, v = (x * width - tx) / size, (y * height - ty) / size
    if -0.05 < u < 1.05 and -0.05 < v < 1.05:
        sub = paint_icon(u, v, AA / (size / width))
        if sub[3]:
            base = _over(base, sub[:3], sub[3] / 255.0)
    return (base[0], base[1], base[2], 255)


def paint_dialog(x: float, y: float, width: int, height: int) -> tuple:
    """499x312: navy left panel with the mark, white elsewhere (MSI draws text)."""
    panel = DIALOG_PANEL / width
    if x > panel:
        return (255, 255, 255, 255)
    strip = DIALOG_PANEL - 3
    strip_d = max(strip / width - x, 0.0)
    if x > strip / width:
        base = _over(_mix(NAVY_TOP, NAVY_BOTTOM, y), ACCENT, edge(strip_d))
        return (base[0], base[1], base[2], 255)
    base = _mix(NAVY_TOP, NAVY_BOTTOM, y)
    tx = (DIALOG_PANEL - DIALOG_TILE) / 2.0
    ty = (height - DIALOG_TILE) / 2.0
    u, v = (x * width - tx) / DIALOG_TILE, (y * height - ty) / DIALOG_TILE
    if -0.05 < u < 1.05 and -0.05 < v < 1.05:
        sub = paint_icon(u, v, AA / (DIALOG_TILE / width))
        if sub[3]:
            base = _over(base, sub[:3], sub[3] / 255.0)
    return (base[0], base[1], base[2], 255)


# --------------------------------------------------------------------------- #
# rasteriser
# --------------------------------------------------------------------------- #
def rasterise(painter, width: int, height: int, supersample: int = 2) -> bytearray:
    """Render ``painter`` into an RGBA buffer with box-filtered antialiasing.

    Colour is accumulated premultiplied by alpha so transparent edges (the icon
    tile corners) stay clean instead of picking up a dark fringe.
    """
    from array import array

    saved = AA
    globals()["AA"] = 1.0 / (width * supersample)
    acc = array("L", [0]) * (width * height * 4)
    try:
        for row in range(height * supersample):
            y = (row + 0.5) / supersample / height
            target_y = row // supersample
            for col in range(width * supersample):
                x = (col + 0.5) / supersample / width
                red, green, blue, alpha = painter(x, y)
                index = (target_y * width + col // supersample) * 4
                acc[index] += red * alpha
                acc[index + 1] += green * alpha
                acc[index + 2] += blue * alpha
                acc[index + 3] += alpha
    finally:
        globals()["AA"] = saved
    total = supersample * supersample
    out = bytearray(width * height * 4)
    for index in range(0, len(out), 4):
        alpha = (acc[index + 3] + total // 2) // total
        out[index + 3] = alpha
        if alpha:
            weight = acc[index + 3] or 1
            out[index] = round(acc[index] / weight)
            out[index + 1] = round(acc[index + 1] / weight)
            out[index + 2] = round(acc[index + 2] / weight)
    return out


def render_icon(size: int) -> bytearray:
    return rasterise(paint_icon, size, size, 3 if size <= 64 else 2)


def render_banner() -> bytearray:
    width, height = BANNER_SIZE
    return rasterise(lambda x, y: paint_banner(x, y, width, height), width, height, 2)


def render_dialog() -> bytearray:
    width, height = DIALOG_SIZE
    return rasterise(lambda x, y: paint_dialog(x, y, width, height), width, height, 2)


# --------------------------------------------------------------------------- #
# container writers (PNG / ICO / BMP) - stdlib only
# --------------------------------------------------------------------------- #
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_bytes(width: int, height: int, pixels: bytearray) -> bytes:
    stride = width * 4
    raw = b"".join(b"\x00" + bytes(pixels[y * stride:(y + 1) * stride]) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _png_chunk(b"IDAT", zlib.compress(raw, 9))
            + _png_chunk(b"IEND", b""))


def write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    path.write_bytes(png_bytes(width, height, pixels))


def ico_bytes(images: list[tuple[int, bytes]]) -> bytes:
    """``images`` = [(size, png_bytes)] -> a multi-resolution .ico (PNG payload)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, payload, offset = b"", b"", 6 + 16 * len(images)
    for size, blob in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        payload += blob
        offset += len(blob)
    return header + entries + payload


def bmp_bytes(width: int, height: int, pixels: bytearray) -> bytes:
    """24-bit bottom-up BMP, the format WiX's UI bitmaps expect."""
    stride = width * 3
    pad = b"\x00" * ((-stride) % 4)
    rows = bytearray()
    for y in range(height - 1, -1, -1):
        line = bytearray(stride)
        base = y * width * 4
        for x in range(width):
            source = base + x * 4
            target = x * 3
            line[target] = pixels[source + 2]        # B
            line[target + 1] = pixels[source + 1]    # G
            line[target + 2] = pixels[source]        # R
        rows += line + pad
    header = struct.pack("<2sIHHI", b"BM", 14 + 40 + len(rows), 0, 0, 14 + 40)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(rows), 2835, 2835, 0, 0)
    return bytes(header) + bytes(info) + bytes(rows)


def write_bmp(path: Path, width: int, height: int, pixels: bytearray) -> None:
    path.write_bytes(bmp_bytes(width, height, pixels))


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def build_assets(sizes: tuple[int, ...] = DEFAULT_SIZES) -> dict[str, bytes]:
    """Render every artefact and return {asset file name: bytes}."""
    return {
        "app_icon.ico": ico_bytes(
            [(size, png_bytes(size, size, render_icon(size))) for size in sorted(sizes)]),
        "app_icon.png": png_bytes(MASTER_PNG_SIZE, MASTER_PNG_SIZE,
                                  render_icon(MASTER_PNG_SIZE)),
        "app_banner.bmp": bmp_bytes(BANNER_SIZE[0], BANNER_SIZE[1], render_banner()),
        "app_dialog.bmp": bmp_bytes(DIALOG_SIZE[0], DIALOG_SIZE[1], render_dialog()),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the app/installer artwork")
    parser.add_argument("--out", default=str(ASSET_DIR), help="output directory")
    parser.add_argument("--sizes", default=",".join(str(s) for s in DEFAULT_SIZES),
                        help="comma-separated .ico resolutions")
    parser.add_argument("--check", action="store_true",
                        help="do not write: exit 1 if the committed art is not byte-identical")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sizes = tuple(int(s) for s in args.sizes.split(",") if s.strip())
    assets = build_assets(sizes)
    out_dir = Path(args.out)
    if args.check:
        drift = []
        for name, blob in assets.items():
            path = out_dir / name
            if not path.exists():
                drift.append(f"{name}: missing")
            elif path.read_bytes() != blob:
                drift.append(f"{name}: differs (run: python tools/make_assets.py)")
        for line in drift:
            print(f"asset drift: {line}", file=sys.stderr)
        if drift:
            return 1
        print(f"assets OK ({len(assets)} files, sizes {sizes})")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, blob in assets.items():
        (out_dir / name).write_bytes(blob)
        print(f"wrote {out_dir / name}  ({len(blob):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
