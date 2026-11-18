"""Generate LANLauncherNG app icons without external dependencies.

Outputs:
- src/frontend/assets/icons/lanlauncherng.svg (source artwork)
- src/frontend/assets/icons/lanlauncherng.png (512x512)
- src/frontend/assets/icons/lanlauncherng.ico (multi-size PNG-in-ICO)
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
import zlib


ROOT = Path(__file__).resolve().parents[2]
ICON_DIR = ROOT / "src" / "frontend" / "assets" / "icons"
PNG_PATH = ICON_DIR / "lanlauncherng.png"
ICO_PATH = ICON_DIR / "lanlauncherng.ico"
SVG_PATH = ICON_DIR / "lanlauncherng.svg"


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    x = clamp(t)
    return (
        int(a[0] + (b[0] - a[0]) * x),
        int(a[1] + (b[1] - a[1]) * x),
        int(a[2] + (b[2] - a[2]) * x),
    )


def put_px(buf: list[list[tuple[int, int, int, int]]], x: int, y: int, color: tuple[int, int, int, int]) -> None:
    if 0 <= y < len(buf) and 0 <= x < len(buf[0]):
        buf[y][x] = color


def blend_px(
    buf: list[list[tuple[int, int, int, int]]], x: int, y: int, color: tuple[int, int, int, int]
) -> None:
    if not (0 <= y < len(buf) and 0 <= x < len(buf[0])):
        return
    sr, sg, sb, sa = color
    dr, dg, db, da = buf[y][x]
    a = sa / 255.0
    ia = 1.0 - a
    out_a = int(sa + da * ia)
    if out_a <= 0:
        buf[y][x] = (0, 0, 0, 0)
        return
    out_r = int(sr * a + dr * ia)
    out_g = int(sg * a + dg * ia)
    out_b = int(sb * a + db * ia)
    buf[y][x] = (out_r, out_g, out_b, out_a)


def draw_line(
    buf: list[list[tuple[int, int, int, int]]],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: float,
    color: tuple[int, int, int, int],
) -> None:
    min_x = int(math.floor(min(x0, x1) - width - 2))
    max_x = int(math.ceil(max(x0, x1) + width + 2))
    min_y = int(math.floor(min(y0, y1) - width - 2))
    max_y = int(math.ceil(max(y0, y1) + width + 2))
    dx = x1 - x0
    dy = y1 - y0
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq <= 0.0001:
        return

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            px = x + 0.5
            py = y + 0.5
            t = ((px - x0) * dx + (py - y0) * dy) / seg_len_sq
            t = clamp(t)
            qx = x0 + t * dx
            qy = y0 + t * dy
            dist = math.hypot(px - qx, py - qy)
            if dist <= width:
                edge = clamp((width - dist) / max(1.0, width * 0.35))
                alpha = int(color[3] * edge)
                blend_px(buf, x, y, (color[0], color[1], color[2], alpha))


def draw_circle(
    buf: list[list[tuple[int, int, int, int]]],
    cx: float,
    cy: float,
    radius: float,
    color: tuple[int, int, int, int],
) -> None:
    min_x = int(math.floor(cx - radius - 2))
    max_x = int(math.ceil(cx + radius + 2))
    min_y = int(math.floor(cy - radius - 2))
    max_y = int(math.ceil(cy + radius + 2))
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            d = math.hypot((x + 0.5) - cx, (y + 0.5) - cy)
            if d <= radius:
                edge = clamp((radius - d) / max(1.0, radius * 0.2))
                alpha = int(color[3] * edge)
                blend_px(buf, x, y, (color[0], color[1], color[2], alpha))


def draw_rounded_rect(
    buf: list[list[tuple[int, int, int, int]]],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    r: float,
    color: tuple[int, int, int, int],
) -> None:
    min_x = int(math.floor(x0))
    max_x = int(math.ceil(x1))
    min_y = int(math.floor(y0))
    max_y = int(math.ceil(y1))
    for y in range(min_y, max_y):
        for x in range(min_x, max_x):
            px = x + 0.5
            py = y + 0.5
            qx = min(max(px, x0 + r), x1 - r)
            qy = min(max(py, y0 + r), y1 - r)
            d = math.hypot(px - qx, py - qy)
            if d <= r:
                edge = clamp((r - d) / max(1.0, r * 0.22))
                alpha = int(color[3] * edge)
                blend_px(buf, x, y, (color[0], color[1], color[2], alpha))


def render_icon(size: int) -> list[list[tuple[int, int, int, int]]]:
    buf: list[list[tuple[int, int, int, int]]] = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]
    c_a = (22, 30, 53)
    c_b = (8, 118, 154)
    c_c = (255, 138, 41)

    for y in range(size):
        for x in range(size):
            nx = x / max(1, size - 1)
            ny = y / max(1, size - 1)
            t = clamp(0.58 * nx + 0.42 * ny)
            base = mix(c_a, c_b, t)
            # Soft warm glow in the top-left corner for depth.
            gx = nx - 0.16
            gy = ny - 0.12
            glow = clamp(1.0 - math.hypot(gx, gy) / 0.72)
            warm = mix(base, c_c, glow * 0.42)
            put_px(buf, x, y, (warm[0], warm[1], warm[2], 255))

    s = size / 512.0
    draw_rounded_rect(buf, 86 * s, 86 * s, 426 * s, 426 * s, 74 * s, (18, 25, 42, 220))
    draw_rounded_rect(buf, 114 * s, 122 * s, 398 * s, 336 * s, 28 * s, (11, 49, 83, 215))
    draw_rounded_rect(buf, 124 * s, 132 * s, 388 * s, 326 * s, 20 * s, (32, 162, 203, 70))

    # Stylized LAN topology: one hub with three peers.
    center = (256 * s, 250 * s)
    p1 = (196 * s, 204 * s)
    p2 = (320 * s, 198 * s)
    p3 = (254 * s, 305 * s)
    line_color = (255, 189, 96, 230)
    draw_line(buf, center[0], center[1], p1[0], p1[1], 9 * s, line_color)
    draw_line(buf, center[0], center[1], p2[0], p2[1], 9 * s, line_color)
    draw_line(buf, center[0], center[1], p3[0], p3[1], 9 * s, line_color)
    draw_circle(buf, center[0], center[1], 22 * s, (255, 153, 47, 255))
    draw_circle(buf, p1[0], p1[1], 18 * s, (241, 244, 248, 245))
    draw_circle(buf, p2[0], p2[1], 18 * s, (241, 244, 248, 245))
    draw_circle(buf, p3[0], p3[1], 18 * s, (241, 244, 248, 245))

    # Minimal launcher stand.
    draw_rounded_rect(buf, 206 * s, 346 * s, 306 * s, 368 * s, 10 * s, (210, 216, 225, 245))
    draw_rounded_rect(buf, 172 * s, 374 * s, 340 * s, 398 * s, 12 * s, (156, 167, 184, 238))

    # Vignette.
    for y in range(size):
        for x in range(size):
            nx = (x + 0.5) / size
            ny = (y + 0.5) / size
            d = math.hypot(nx - 0.5, ny - 0.5)
            shade = clamp((d - 0.42) / 0.35)
            if shade > 0:
                blend_px(buf, x, y, (6, 10, 18, int(shade * 120)))

    return buf


def encode_png_rgba(image: list[list[tuple[int, int, int, int]]]) -> bytes:
    height = len(image)
    width = len(image[0]) if height else 0
    raw = bytearray()
    for row in image:
        raw.append(0)  # filter type 0 (none)
        for r, g, b, a in row:
            raw.extend((r, g, b, a))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def write_ico(path: Path, png_images: list[tuple[int, bytes]]) -> None:
    count = len(png_images)
    header = struct.pack("<HHH", 0, 1, count)
    entries = bytearray()
    data_block = bytearray()
    offset = 6 + 16 * count
    for size, png_data in png_images:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                w,
                h,
                0,
                0,
                1,
                32,
                len(png_data),
                offset,
            )
        )
        data_block.extend(png_data)
        offset += len(png_data)
    path.write_bytes(header + entries + data_block)


def write_svg(path: Path) -> None:
    path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1a2a47"/>
      <stop offset="60%" stop-color="#0d6f95"/>
      <stop offset="100%" stop-color="#ff8a29"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="96" fill="url(#bg)"/>
  <rect x="86" y="86" width="340" height="340" rx="74" fill="#101b2f" fill-opacity=".86"/>
  <rect x="114" y="122" width="284" height="214" rx="28" fill="#0d3154" fill-opacity=".9"/>
  <path d="M256 250 196 204M256 250 320 198M256 250 254 305" stroke="#ffbd60" stroke-width="10" stroke-linecap="round"/>
  <circle cx="256" cy="250" r="22" fill="#ff992f"/>
  <circle cx="196" cy="204" r="18" fill="#f1f4f8"/>
  <circle cx="320" cy="198" r="18" fill="#f1f4f8"/>
  <circle cx="254" cy="305" r="18" fill="#f1f4f8"/>
  <rect x="206" y="346" width="100" height="22" rx="10" fill="#d2d8e1"/>
  <rect x="172" y="374" width="168" height="24" rx="12" fill="#9ca7b8"/>
</svg>
""",
        encoding="utf-8",
    )


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    write_svg(SVG_PATH)

    base = render_icon(512)
    PNG_PATH.write_bytes(encode_png_rgba(base))

    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    ico_images = [(size, encode_png_rgba(render_icon(size))) for size in ico_sizes]
    write_ico(ICO_PATH, ico_images)

    print(f"Generated icons in: {ICON_DIR}")


if __name__ == "__main__":
    main()
