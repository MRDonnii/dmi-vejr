"""Render an animated radar map around the home from DMI composites.

Pure and synchronous; the coordinator runs it in the executor. Geography is a
coastline/lake/border overlay (Natural Earth, public domain) pre-rasterised
into DMI's composite grid (basemap.png); all weather data is DMI's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .places import TOWNS
from .radar import GridWindow

BASEMAP = Path(__file__).parent / "basemap.png"
BASEMAP_SHAPE = (1728, 1984)  # rows, cols of the DMI 500 m composite

# mm/h lower bounds -> colour.
SCALE = [
    (0.1, (120, 180, 255)),
    (0.5, (60, 130, 255)),
    (1.0, (20, 90, 230)),
    (2.0, (40, 190, 90)),
    (5.0, (240, 220, 40)),
    (10.0, (250, 140, 30)),
    (20.0, (230, 40, 40)),
    (50.0, (200, 40, 200)),
]
BACKGROUND = (18, 24, 32)
NO_COVERAGE = (34, 36, 42)
COAST = {255: (110, 126, 145), 180: (80, 100, 122), 120: (120, 92, 92)}

RINGS_KM = (10, 25, 50)
# Lightning by age: recent strikes bright, older ones dimmer.
STRIKE_RECENT_MIN = 10
STRIKE_RECENT = (255, 236, 60)
STRIKE_OLDER = (255, 150, 40)


TOWN_SPACING_PX = 44


def _room(drawn: list[tuple[float, float]], x: float, y: float) -> bool:
    """True when no town already drawn is too close for another label."""
    return all(math.hypot(x - dx, y - dy) >= TOWN_SPACING_PX for dx, dy in drawn)


@dataclass(frozen=True)
class RadarFrame:
    time: datetime  # local time for the label
    rate: np.ndarray  # mm/h, NaN where the radar has no coverage


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow without FreeType
        return ImageFont.load_default()


def _basemap_crop(window: GridWindow) -> np.ndarray | None:
    if window.grid_shape != BASEMAP_SHAPE or not BASEMAP.exists():
        return None
    with Image.open(BASEMAP) as img:
        base = np.asarray(img.convert("L"))
    return base[window.r0 : window.r1, window.c0 : window.c1]


def _strike(draw: ImageDraw.ImageDraw, x: float, y: float, colour: tuple[int, int, int]) -> None:
    """A small lightning bolt centred on (x, y)."""
    bolt = [(1.5, -10), (-6, 1.5), (0, 1.5), (-3, 10), (6, -1.5), (0, -1.5), (3, -10)]
    draw.polygon([(x + dx, y + dy) for dx, dy in bolt], fill=(*colour, 255), outline=(15, 15, 15, 255))


def colourise(rate: np.ndarray) -> np.ndarray:
    """RGBA array for the precipitation rate."""
    rgba = np.zeros((*rate.shape, 4), dtype=np.uint8)
    for lower, colour in SCALE:
        mask = rate >= lower
        rgba[mask, :3] = colour
        rgba[mask, 3] = 225
    return rgba


def render_frames(
    frames: list[RadarFrame],
    window: GridWindow,
    project,  # (lat, lon) -> (row, col) in the full grid
    *,
    scale: int = 3,
    frame_ms: int = 400,
    last_frame_ms: int = 1800,
    strikes: list[tuple[float, float, float]] | None = None,  # (lat, lon, age in minutes)
    strike_window_min: int = 30,
) -> bytes:
    """Animated GIF of the frames, oldest first, with recent lightning on top."""
    if not frames:
        raise ValueError("no radar frames")
    h, w = frames[0].rate.shape
    base = _basemap_crop(window)
    home_r, home_c = window.home_row - window.r0, window.home_col - window.c0
    px_km = window.pixel_m / 1000

    # Static layer: background, coverage, coastlines.
    static = np.empty((h, w, 3), dtype=np.uint8)
    static[:] = BACKGROUND
    static[np.isnan(frames[-1].rate)] = NO_COVERAGE
    if base is not None:
        for value, colour in COAST.items():
            static[base == value] = colour
    static_img = Image.fromarray(static).resize((w * scale, h * scale), Image.NEAREST)

    font, small = _font(15), _font(12)
    overlay = Image.new("RGBA", static_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx, cy = (home_c + 0.5) * scale, (home_r + 0.5) * scale
    for km in RINGS_KM:
        r = km / px_km * scale
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(200, 210, 225, 90), width=1)
        draw.text((cx + r * 0.71 + 3, cy - r * 0.71 - 14), f"{km} km", fill=(200, 210, 225, 150), font=small)
    drawn: list[tuple[float, float]] = []
    for name, lat, lon, _big in TOWNS:
        row, col = project(lat, lon)
        tx, ty = (col - window.c0 + 0.5) * scale, (row - window.r0 + 0.5) * scale
        if 0 <= tx < w * scale and 0 <= ty < h * scale and _room(drawn, tx, ty):
            drawn.append((tx, ty))
            draw.ellipse((tx - 2, ty - 2, tx + 2, ty + 2), fill=(225, 230, 240, 220))
            draw.text((tx + 5, ty - 8), name, fill=(225, 230, 240, 220), font=small)
    shown = 0
    for lat, lon, age in strikes or ():
        row, col = project(lat, lon)
        sx, sy = (col - window.c0 + 0.5) * scale, (row - window.r0 + 0.5) * scale
        if 0 <= sx < w * scale and 0 <= sy < h * scale:
            _strike(draw, sx, sy, STRIKE_RECENT if age < STRIKE_RECENT_MIN else STRIKE_OLDER)
            shown += 1
    draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=(255, 255, 255, 255))
    draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(230, 40, 40, 255))
    # Legend.
    lx, ly = 10, 10
    for i, (lower, colour) in enumerate(SCALE):
        draw.rectangle((lx + i * 34, ly, lx + i * 34 + 32, ly + 10), fill=(*colour, 230))
        draw.text((lx + i * 34, ly + 12), f"{lower:g}", fill=(220, 225, 235, 230), font=small)
    draw.text((lx + len(SCALE) * 34 + 4, ly + 2), "mm/t", fill=(220, 225, 235, 230), font=small)
    if strikes is not None:  # None: lightning data unavailable, say nothing
        _strike(draw, lx + 6, ly + 40, STRIKE_RECENT)
        draw.text(
            (lx + 16, ly + 33), f"DMI lyn sidste {strike_window_min} min: {shown}",
            fill=(220, 225, 235, 230), font=small,
        )

    images = []
    for frame in frames:
        radar = Image.fromarray(colourise(np.nan_to_num(frame.rate, nan=0.0))).resize(
            static_img.size, Image.NEAREST
        )
        img = static_img.convert("RGBA")
        img.alpha_composite(radar)
        img.alpha_composite(overlay)
        d = ImageDraw.Draw(img)
        label = f"DMI radar  {frame.time:%H:%M}"
        d.rectangle((0, img.height - 26, img.width, img.height), fill=(0, 0, 0, 150))
        d.text((10, img.height - 22), label, fill=(255, 255, 255, 255), font=font)
        images.append(img.convert("RGB").quantize(colors=128, method=Image.Quantize.MEDIANCUT))

    out = io.BytesIO()
    durations = [frame_ms] * (len(images) - 1) + [last_frame_ms]
    images[0].save(
        out, format="GIF", save_all=True, append_images=images[1:],
        duration=durations, loop=0, optimize=True, disposal=1,
    )
    return out.getvalue()
