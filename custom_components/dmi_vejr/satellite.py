"""Animated satellite map around the home from EUMETSAT's open WMS.

DMI's open data has no satellite pictures (dmi.dk shows EUMETSAT's), so they
come from EUMETView: Meteosat Third Generation (MTG-I) "GeoColour" every 10
minutes. That is true colour by day and infrared clouds over city lights by
night. The map is a square in Web Mercator around the home with Natural Earth
coastlines and borders from the same service. The geometry and the rendering
are pure and synchronous; the coordinator does the fetching.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import io
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont

from .places import TOWNS

WMS_URL = "https://view.eumetsat.int/geoserver/wms"
LAYER = "mtg_fd:rgb_geocolour"
# The layer's own capabilities (a few kB) carry the newest picture time.
CAPS_URL = "https://view.eumetsat.int/geoserver/mtg_fd/rgb_geocolour/ows"
OVERLAYS = "backgrounds:ne_10m_coastline,backgrounds:ne_boundary_lines_land"
STEP = timedelta(minutes=10)
EARTH_R = 6378137.0
TOWN_SPACING_PX = 50

@dataclass(frozen=True)
class SatView:
    """A square map of `half_km` around (lat, lon) in Web Mercator."""

    lat: float
    lon: float
    half_km: float
    size: int

    def _merc(self, lat: float, lon: float) -> tuple[float, float]:
        return (
            EARTH_R * math.radians(lon),
            EARTH_R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
        )

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """minx, miny, maxx, maxy in EPSG:3857 (ground km stretched to Mercator)."""
        x, y = self._merc(self.lat, self.lon)
        half = self.half_km * 1000 / math.cos(math.radians(self.lat))
        return x - half, y - half, x + half, y + half

    def pixel(self, lat: float, lon: float) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        x, y = self._merc(lat, lon)
        return (x - x0) / (x1 - x0) * self.size, (y1 - y) / (y1 - y0) * self.size

    def params(self, layers: str, fmt: str, when: datetime | None = None) -> dict[str, str]:
        p = {
            "service": "WMS", "version": "1.3.0", "request": "GetMap",
            "layers": layers, "styles": "", "crs": "EPSG:3857",
            "bbox": ",".join(f"{v:.0f}" for v in self.bbox),
            "width": str(self.size), "height": str(self.size), "format": fmt,
        }
        if fmt == "image/png":
            p["transparent"] = "true"
        if when is not None:
            p["time"] = iso(when)
        return p


def iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_time(capabilities: str) -> datetime | None:
    """The newest picture time from the layer's WMS capabilities."""
    m = re.search(r'<Dimension name="time"[^>]*>([^<]+)</Dimension>', capabilities)
    if not m:
        return None
    end = m.group(1).split(",")[-1].split("/")
    stamp = end[1] if len(end) == 3 else end[0]
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def frame_times(latest: datetime, count: int) -> list[datetime]:
    """`count` picture times ending at `latest`, oldest first."""
    return [latest - STEP * i for i in range(count - 1, -1, -1)]


# DejaVu Sans (Bitstream Vera licence), Latin-1 subset: Pillow's own font has
# no æ, ø, å or ö for the town names.
FONT = Path(__file__).parent / "DejaVuSans-latin.ttf"


def _font(size: int):
    try:
        return ImageFont.truetype(str(FONT), size)
    except OSError:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # Pillow without FreeType
            return ImageFont.load_default()


def render_frames(
    frames: list[tuple[datetime, bytes]],  # (local time, JPEG), oldest first
    overlay_png: bytes | None,
    view: SatView,
    *,
    frame_ms: int = 450,
    last_frame_ms: int = 2000,
) -> bytes:
    """Animated WebP of the frames with coastlines, towns and the home on top."""
    if not frames:
        raise ValueError("no satellite frames")
    size = (view.size, view.size)
    top = Image.new("RGBA", size, (0, 0, 0, 0))
    if overlay_png:
        with Image.open(io.BytesIO(overlay_png)) as ov:
            lines = ov.convert("RGBA").resize(size)
        # The service draws them white; soften them so the clouds stay in front.
        alpha = lines.getchannel("A").point(lambda a: a * 150 // 255)
        lines.putalpha(alpha)
        top.alpha_composite(lines)
    draw = ImageDraw.Draw(top)
    small, font = _font(12), _font(14)
    drawn: list[tuple[float, float]] = []
    for name, lat, lon, big in TOWNS:
        if not big:
            continue
        tx, ty = view.pixel(lat, lon)
        room = all(math.hypot(tx - dx, ty - dy) >= TOWN_SPACING_PX for dx, dy in drawn)
        if 0 <= tx < view.size and 0 <= ty < view.size and room:
            drawn.append((tx, ty))
            draw.ellipse((tx - 2, ty - 2, tx + 2, ty + 2), fill=(255, 255, 255, 220))
            draw.text((tx + 5, ty - 8), name, fill=(255, 255, 255, 230), font=small,
                      stroke_width=2, stroke_fill=(0, 0, 0, 150))
    cx, cy = view.pixel(view.lat, view.lon)
    draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=(255, 255, 255, 255))
    draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(230, 40, 40, 255))

    images = []
    for when, jpeg in frames:
        with Image.open(io.BytesIO(jpeg)) as pic:
            img = pic.convert("RGBA").resize(size)
        img.alpha_composite(top)
        d = ImageDraw.Draw(img)
        d.rectangle((0, img.height - 26, img.width, img.height), fill=(0, 0, 0, 150))
        d.text((10, img.height - 22), f"Satellit (EUMETSAT)  {when:%H:%M}", fill=(255, 255, 255, 255), font=font)
        images.append(img.convert("RGB"))
    out = io.BytesIO()
    durations = [frame_ms] * (len(images) - 1) + [last_frame_ms]
    images[0].save(
        out, format="WEBP", save_all=True, append_images=images[1:],
        duration=durations, loop=0, quality=72, method=4,
    )
    return out.getvalue()
