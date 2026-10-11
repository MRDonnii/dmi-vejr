"""Read DMI's radar composite (ODIM HDF5) around one location.

Pure and synchronous; the coordinator runs it in the executor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import io
import math

import h5py
import numpy as np

_WGS84_A = 6378137.0
_WGS84_F = 1 / 298.257223563
_E = math.sqrt(_WGS84_F * (2 - _WGS84_F))


class RadarFormatError(ValueError):
    """The composite does not have the layout this module understands."""


@dataclass(frozen=True)
class RadarSample:
    """Precipitation from one radar composite around one location."""

    time: datetime
    rate_mm_h: float | None
    dbz: float | None
    max_nearby_mm_h: float | None
    nearest_rain_km: float | None
    covered: bool


@dataclass(frozen=True)
class GridWindow:
    """A rectangular cut of the composite grid around the home pixel."""

    r0: int
    r1: int
    c0: int
    c1: int
    home_row: int
    home_col: int
    grid_shape: tuple[int, int]
    pixel_m: float


@dataclass(frozen=True)
class RadarWindow:
    time: datetime
    rate: np.ndarray  # mm/h; NaN = no radar coverage
    centre_dbz: float | None
    window: GridWindow
    project: Callable[[float, float], tuple[int, int]]  # (lat, lon) -> (row, col)
    inside: bool


def _ssfn(phit: float, sinphi: float) -> float:
    sinphi *= _E
    return math.tan(0.5 * (math.pi / 2 + phit)) * ((1 - sinphi) / (1 + sinphi)) ** (
        0.5 * _E
    )


def stereographic(lat0: float, lon0: float):
    """Return PROJ "stere" forward (WGS84, oblique aspect, k0=1) as f(lon, lat)."""
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    t = math.sin(phi0)
    x1 = 2 * math.atan(_ssfn(phi0, t)) - math.pi / 2
    akm1 = 2 * math.cos(phi0) / math.sqrt(1 - (_E * t) ** 2)
    sin_x1, cos_x1 = math.sin(x1), math.cos(x1)

    def forward(lon: float, lat: float) -> tuple[float, float]:
        phi, lam = math.radians(lat), math.radians(lon) - lam0
        chi = 2 * math.atan(_ssfn(phi, math.sin(phi))) - math.pi / 2
        sin_x, cos_x = math.sin(chi), math.cos(chi)
        coslam, sinlam = math.cos(lam), math.sin(lam)
        a = akm1 / (cos_x1 * (1 + sin_x1 * sin_x + cos_x1 * cos_x * coslam))
        y = a * (cos_x1 * sin_x - sin_x1 * cos_x * coslam)
        x = a * cos_x * sinlam
        return x * _WGS84_A, y * _WGS84_A

    return forward


def _attr(group, name):
    value = group.attrs[name]
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, np.ndarray):
        return value.item() if value.size == 1 else value
    return value


def _projdef(text: str) -> dict[str, str]:
    params = {}
    for part in text.split():
        key, _, value = part.lstrip("+").partition("=")
        params[key] = value
    if params.get("proj") != "stere" or params.get("ellps", "WGS84") != "WGS84":
        raise RadarFormatError(f"Unsupported projection: {text}")
    if "lat_ts" in params and float(params["lat_ts"]) != float(params["lat_0"]):
        raise RadarFormatError(f"Unsupported lat_ts in projection: {text}")
    return params


def dbz_to_mm_h(dbz):
    """Marshall-Palmer, Z = 200 R^1.6."""
    return (10 ** (np.asarray(dbz, dtype=float) / 10) / 200) ** (1 / 1.6)


def read_window(
    data: bytes, latitude: float, longitude: float, *, half_km: float, min_dbz: float
) -> RadarWindow:
    """Precipitation rate in a square of +-half_km around the location."""
    with h5py.File(io.BytesIO(data), "r") as f:
        what, where = f["what"], f["where"]
        if _attr(what, "product") != "DBZH":
            raise RadarFormatError(f"Unexpected product {_attr(what, 'product')}")
        gain, offset = float(_attr(what, "gain")), float(_attr(what, "offset"))
        nodata, undetect = float(_attr(what, "nodata")), float(_attr(what, "undetect"))
        scan = datetime.strptime(
            f"{_attr(what, 'date')}{str(_attr(what, 'time'))[:6]}", "%Y%m%d%H%M%S"
        ).replace(tzinfo=UTC)

        params = _projdef(_attr(where, "projdef"))
        forward = stereographic(float(params["lat_0"]), float(params["lon_0"]))
        x0, y0 = forward(float(_attr(where, "UL_lon")), float(_attr(where, "UL_lat")))
        xscale, yscale = float(_attr(where, "xscale")), float(_attr(where, "yscale"))

        def project(lat: float, lon: float) -> tuple[int, int]:
            x, y = forward(lon, lat)
            return int((y0 - y) // yscale), int((x - x0) // xscale)

        row, col = project(latitude, longitude)
        grid = f["dataset1/data1/data"]
        rows, cols = grid.shape
        reach = int(math.ceil(half_km * 1000 / min(xscale, yscale)))
        r0, r1 = row - reach, row + reach + 1
        c0, c1 = col - reach, col + reach + 1
        raw = np.full((r1 - r0, c1 - c0), nodata, dtype=float)
        inside = 0 <= row < rows and 0 <= col < cols
        sr0, sr1, sc0, sc1 = max(0, r0), min(rows, r1), max(0, c0), min(cols, c1)
        if sr0 < sr1 and sc0 < sc1:
            raw[sr0 - r0 : sr1 - r0, sc0 - c0 : sc1 - c0] = grid[sr0:sr1, sc0:sc1]

    dbz = raw * gain + offset
    rate = np.where(
        raw == nodata,
        np.nan,
        np.where((raw == undetect) | (dbz < min_dbz), 0.0, dbz_to_mm_h(dbz)),
    )
    centre_raw = raw[row - r0, col - c0]
    centre_dbz = (
        None if centre_raw in (nodata, undetect) else round(float(centre_raw * gain + offset), 1)
    )
    window = GridWindow(r0, r1, c0, c1, row, col, (rows, cols), min(xscale, yscale))
    return RadarWindow(scan, rate, centre_dbz, window, project, inside)


def sample_window(
    rw: RadarWindow, *, nearby_km: float, search_km: float, nearest_rain_mm_h: float
) -> RadarSample:
    """House value (3x3 mean), max nearby and distance to the nearest rain."""
    if not rw.inside:
        return RadarSample(rw.time, None, None, None, None, False)
    w = rw.window
    rr, cc = w.home_row - w.r0, w.home_col - w.c0
    yy, xx = np.indices(rw.rate.shape)
    dist_km = np.hypot(yy - rr, xx - cc) * w.pixel_m / 1000
    centre = rw.rate[rr - 1 : rr + 2, cc - 1 : cc + 2]
    if np.all(np.isnan(centre)):
        return RadarSample(rw.time, None, None, None, None, False)
    nearby = rw.rate[dist_km <= nearby_km]
    wet = (rw.rate >= nearest_rain_mm_h) & (dist_km <= search_km)
    return RadarSample(
        time=rw.time,
        rate_mm_h=round(float(np.nanmean(centre)), 2),
        dbz=rw.centre_dbz,
        max_nearby_mm_h=round(float(np.nanmax(nearby)), 2),
        nearest_rain_km=round(float(dist_km[wet].min()), 1) if wet.any() else None,
        covered=True,
    )


def parse_composite(
    data: bytes,
    latitude: float,
    longitude: float,
    *,
    nearby_km: float,
    search_km: float,
    min_dbz: float,
    nearest_rain_mm_h: float,
) -> RadarSample:
    """Sample one composite at the location."""
    rw = read_window(data, latitude, longitude, half_km=search_km, min_dbz=min_dbz)
    return sample_window(
        rw, nearby_km=nearby_km, search_km=search_km, nearest_rain_mm_h=nearest_rain_mm_h
    )
