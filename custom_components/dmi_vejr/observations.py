"""Pick the nearest fresh DMI station value per parameter, and lightning stats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any


@dataclass(frozen=True)
class Observation:
    value: float
    station_id: str
    station_name: str | None
    distance_km: float
    observed: datetime


@dataclass(frozen=True)
class Strike:
    lat: float
    lon: float
    observed: datetime


@dataclass(frozen=True)
class LightningStats:
    count: int
    nearest_km: float | None
    nearest_bearing: float | None
    last_strike: datetime | None
    radius_km: float
    strikes: tuple[Strike, ...] = ()


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def bbox(lat: float, lon: float, km: float) -> str:
    dlat = km / 111.2
    dlon = km / (111.2 * math.cos(math.radians(lat)))
    return f"{lon - dlon:.4f},{lat - dlat:.4f},{lon + dlon:.4f},{lat + dlat:.4f}"


RECENT_TOLERANCE = timedelta(minutes=30)


def _observed(feature: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(feature["properties"]["observed"].replace("Z", "+00:00"))


def nearest_observation(
    features: list[dict[str, Any]],
    lat: float,
    lon: float,
    names: dict[str, str],
    max_km: float,
) -> Observation | None:
    """Latest value per station, then the nearest station within max_km.

    Stations whose latest value is more than RECENT_TOLERANCE older than the
    newest one nearby are skipped, so a near station that reports less often
    (or has stopped) does not hide a fresh value a little further away.
    """
    latest: dict[str, dict[str, Any]] = {}
    for feature in features:
        props = feature.get("properties", {})
        if props.get("value") is None or not feature.get("geometry"):
            continue
        sid = props["stationId"]
        if sid not in latest or props["observed"] > latest[sid]["properties"]["observed"]:
            latest[sid] = feature
    nearby = {
        sid: f for sid, f in latest.items()
        if distance_km(lat, lon, f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]) <= max_km
    }
    if nearby:
        newest = max(_observed(f) for f in nearby.values())
        nearby = {sid: f for sid, f in nearby.items() if newest - _observed(f) <= RECENT_TOLERANCE}
    best: Observation | None = None
    for sid, feature in nearby.items():
        slon, slat = feature["geometry"]["coordinates"][:2]
        dist = distance_km(lat, lon, slat, slon)
        if dist > max_km or (best is not None and dist >= best.distance_km):
            continue
        props = feature["properties"]
        best = Observation(
            value=float(props["value"]),
            station_id=sid,
            station_name=names.get(sid),
            distance_km=round(dist, 1),
            observed=datetime.fromisoformat(props["observed"].replace("Z", "+00:00")),
        )
    return best


def lightning_stats(
    features: list[dict[str, Any]], lat: float, lon: float, radius_km: float
) -> LightningStats:
    count, nearest, nearest_bearing, last = 0, None, None, None
    strikes: list[Strike] = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if not coords:
            continue
        slon, slat = coords[:2]
        dist = distance_km(lat, lon, slat, slon)
        if dist > radius_km:
            continue
        count += 1
        observed = datetime.fromisoformat(
            feature["properties"]["observed"].replace("Z", "+00:00")
        )
        strikes.append(Strike(slat, slon, observed))
        if last is None or observed > last:
            last = observed
        if nearest is None or dist < nearest:
            nearest, nearest_bearing = dist, bearing_deg(lat, lon, slat, slon)
    return LightningStats(
        count=count,
        nearest_km=None if nearest is None else round(nearest, 1),
        nearest_bearing=None if nearest_bearing is None else round(nearest_bearing),
        last_strike=last,
        radius_km=radius_km,
        strikes=tuple(strikes),
    )
