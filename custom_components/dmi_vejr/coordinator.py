"""Data coordinators for DMI Vejr."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import partial
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .const import (
    CLIMATE_INTERVAL,
    CLIMATE_URL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MUNICIPALITY,
    CONF_WARNING_AREA,
    DKSS_COLLECTION,
    DKSS_INTERVAL,
    DKSS_PARAMETER,
    DEFAULT_MUNICIPALITY,
    DEFAULT_WARNING_AREA,
    EDR_HOURS,
    EDR_INTERVAL,
    EDR_INVERTED,
    EDR_PERCENTILE_LEVELS,
    EDR_PERCENTILES,
    EDR_PROBABILITIES,
    EDR_RETRY_INTERVAL,
    EDR_SF,
    EDR_SF_SERIES,
    EDR_URL,
    OBS_SLOW_PARAMETERS,
    OCEAN_INTERVAL,
    OCEAN_OBS_URL,
    OCEAN_PARAMETERS,
    OCEAN_SEARCH_KM,
    OCEAN_STATION_URL,
    TIDE_HOURS,
    TIDE_STATION_URL,
    TIDE_URL,
    WARNINGS_INTERVAL,
    WARNINGS_URL,
    FORECAST_INTERVAL,
    FORECAST_MODEL,
    FORECAST_URL,
    LIGHTNING_INTERVAL,
    LIGHTNING_RADIUS_KM,
    LIGHTNING_URL,
    LIGHTNING_WINDOW,
    MAP_FRAMES,
    MAP_HALF_KM,
    MIN_DBZ,
    NEAREST_RAIN_MM_H,
    NEARBY_RADIUS_KM,
    OBS_INTERVAL,
    OBS_LOOKBACK,
    OBS_PARAMETERS,
    OBS_SEARCH_KM,
    OBS_URL,
    RADAR_FRAMES_URL,
    RADAR_INTERVAL,
    SEARCH_RADIUS_KM,
    SAT_FRAMES,
    SAT_HALF_KM,
    SAT_INTERVAL,
    SAT_SIZE,
    STATION_URL,
)
from .extras import (
    PRECIP_TYPES,
    Peak,
    Tide,
    Warnings,
    as_percent,
    band,
    coverage_series,
    current,
    invert_percent,
    parse_climate,
    parse_warnings,
    peak,
    tide_extremes,
    to_celsius,
)
from .observations import (
    LightningStats,
    Observation,
    bbox,
    distance_km,
    lightning_stats,
    nearest_observation,
)
from .radar import RadarFormatError, RadarSample, RadarWindow, read_window, sample_window
from .radar_map import RadarFrame, render_frames
from . import satellite as sat

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=30)
# The EPS ensemble endpoint often takes 10-20 s to answer.
_EDR_TIMEOUT = aiohttp.ClientTimeout(total=60)
# DMI answers 429 when one client sends many requests at once.
_DMI_CONCURRENCY = 2
_OBS_PAGE = 10000
# DMI's forecast API answers 429 to requests that come back to back; space them out.
EDR_SPACING_S = 3.0

_CURRENT = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
    "weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,is_day,dew_point_2m"
)
_HOURLY = (
    "temperature_2m,apparent_temperature,precipitation,precipitation_probability,"
    "weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,cloud_cover,"
    "relative_humidity_2m,is_day"
)
_DAILY = (
    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,"
    "wind_direction_10m_dominant,relative_humidity_2m_mean"
)
# DMI HARMONIE has no UV index; it comes from Open-Meteo's best model instead.
_UV = {"current": "uv_index", "hourly": "uv_index", "daily": "uv_index_max"}


async def _get_json(
    hass: HomeAssistant,
    url: str,
    params: dict[str, Any] | None = None,
    timeout: aiohttp.ClientTimeout = _TIMEOUT,
) -> Any:
    session = async_get_clientsession(hass)
    slots = hass.data.setdefault("dmi_vejr_request_slots", asyncio.Semaphore(_DMI_CONCURRENCY))
    async with slots, session.get(url, params=params, timeout=timeout) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


def _iso(value: datetime) -> str:
    return value.astimezone(dt_util.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class RadarData:
    sample: RadarSample
    map_gif: bytes | None
    map_updated: datetime | None


class RadarCoordinator(DataUpdateCoordinator[RadarData]):
    """DMI radar composites: the latest sampled at home, the last hour as a map."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="DMI radar", update_interval=RADAR_INTERVAL,
            config_entry=entry,
        )
        self._lat = entry.data[CONF_LATITUDE]
        self._lon = entry.data[CONF_LONGITUDE]
        self._frames: dict[str, RadarWindow] = {}
        # Set by the entry setup; its strikes are drawn on the map.
        self.lightning: LightningCoordinator | None = None

    def _strikes(self) -> list[tuple[float, float, float]] | None:
        stats = self.lightning.data if self.lightning else None
        if stats is None or not self.lightning.last_update_success:
            return None
        now = dt_util.utcnow()
        return [
            (s.lat, s.lon, (now - s.observed).total_seconds() / 60) for s in stats.strikes
        ]

    async def _async_update_data(self) -> RadarData:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                RADAR_FRAMES_URL.format(n=MAP_FRAMES), timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                listing = await resp.json()
            items = [(f["id"], f["asset"]["data"]["href"]) for f in listing["features"]]
            if not items:
                raise UpdateFailed("DMI radar listing is empty")
            changed = False
            for item_id, href in items:
                if item_id in self._frames:
                    continue
                async with session.get(href, timeout=_TIMEOUT) as resp:
                    resp.raise_for_status()
                    payload = await resp.read()
                try:
                    window = await self.hass.async_add_executor_job(
                        lambda p=payload: read_window(
                            p, self._lat, self._lon,
                            half_km=max(MAP_HALF_KM, SEARCH_RADIUS_KM), min_dbz=MIN_DBZ,
                        )
                    )
                except (RadarFormatError, OSError, KeyError) as err:
                    _LOGGER.warning("Could not read DMI radar %s: %s", item_id, err)
                    continue
                self._frames[item_id] = window
                changed = True
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError) as err:
            raise UpdateFailed(f"DMI radar not available: {err}") from err

        wanted = {item_id for item_id, _ in items}
        for item_id in list(self._frames):
            if item_id not in wanted:
                del self._frames[item_id]
        if not self._frames:
            raise UpdateFailed("No readable DMI radar composite")

        ordered = sorted(self._frames.values(), key=lambda w: w.time)
        latest = ordered[-1]
        sample = sample_window(
            latest, nearby_km=NEARBY_RADIUS_KM, search_km=SEARCH_RADIUS_KM,
            nearest_rain_mm_h=NEAREST_RAIN_MM_H,
        )
        if not changed and self.data is not None:
            return self.data

        gif = None
        if latest.inside:
            tz = dt_util.get_time_zone(self.hass.config.time_zone)
            frames = [RadarFrame(w.time.astimezone(tz), w.rate) for w in ordered]
            try:
                gif = await self.hass.async_add_executor_job(
                    partial(
                        render_frames, frames, latest.window, latest.project,
                        strikes=self._strikes(),
                        strike_window_min=int(LIGHTNING_WINDOW.total_seconds() // 60),
                    )
                )
            except (ValueError, OSError) as err:
                _LOGGER.warning("Could not render DMI radar map: %s", err)
        return RadarData(sample, gif, dt_util.utcnow() if gif else None)


class ObservationCoordinator(DataUpdateCoordinator[dict[str, Observation | None]]):
    """Measured values from the nearest DMI station per parameter."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="DMI stations", update_interval=OBS_INTERVAL,
            config_entry=entry,
        )
        self._lat = entry.data[CONF_LATITUDE]
        self._lon = entry.data[CONF_LONGITUDE]
        self._names: dict[str, str] | None = None

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        return await _get_json(self.hass, url, params)

    async def _async_update_data(self) -> dict[str, Observation | None]:
        box = bbox(self._lat, self._lon, OBS_SEARCH_KM)
        now = dt_util.utcnow()
        try:
            if self._names is None:
                stations = await self._get(STATION_URL, {"bbox": box, "status": "Active", "limit": 500})
                self._names = {
                    f["properties"]["stationId"]: f["properties"]["name"]
                    for f in stations.get("features", [])
                }
            # Every parameter from every station nearby in one request.
            recent = await self._get(
                OBS_URL,
                {"bbox": box, "datetime": f"{_iso(now - OBS_LOOKBACK)}/{_iso(now)}", "limit": _OBS_PAGE},
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            if self.data is not None:
                # Values age out by themselves (obs_fresh); keep them meanwhile.
                _LOGGER.debug("DMI stations not available, keeping last values: %s", err)
                return self.data
            raise UpdateFailed(f"DMI stations not available: {err}") from err
        features = recent.get("features", [])
        if len(features) >= _OBS_PAGE:
            _LOGGER.warning("DMI returned %s station values, the page limit; some may be missing", len(features))
        by_param: dict[str, list[dict[str, Any]]] = {}
        for feature in features:
            by_param.setdefault(feature.get("properties", {}).get("parameterId"), []).append(feature)
        result = {
            key: nearest_observation(
                by_param.get(param, []), self._lat, self._lon, self._names or {}, OBS_SEARCH_KM
            )
            for param, key in OBS_PARAMETERS.items()
        }
        for param, (key, max_age) in OBS_SLOW_PARAMETERS.items():
            try:
                daily = await self._get(
                    OBS_URL,
                    {"parameterId": param, "bbox": box,
                     "datetime": f"{_iso(now - max_age)}/{_iso(now)}", "limit": 1000},
                )
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                _LOGGER.debug("DMI %s not available: %s", param, err)
                result[key] = (self.data or {}).get(key)
                continue
            result[key] = nearest_observation(
                daily.get("features", []), self._lat, self._lon, self._names or {}, OBS_SEARCH_KM
            )
        return result


class LightningCoordinator(DataUpdateCoordinator[LightningStats]):
    """DMI lightning detection around the home."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="DMI lightning", update_interval=LIGHTNING_INTERVAL,
            config_entry=entry,
        )
        self._lat = entry.data[CONF_LATITUDE]
        self._lon = entry.data[CONF_LONGITUDE]

    async def _async_update_data(self) -> LightningStats:
        now = dt_util.utcnow()
        params = {
            "bbox": bbox(self._lat, self._lon, LIGHTNING_RADIUS_KM),
            "datetime": f"{_iso(now - LIGHTNING_WINDOW)}/{_iso(now)}",
            "limit": 5000,
        }
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(LIGHTNING_URL, params=params, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"DMI lightning not available: {err}") from err
        return lightning_stats(data.get("features", []), self._lat, self._lon, LIGHTNING_RADIUS_KM)


class ClimateCoordinator(DataUpdateCoordinator[dict[date, dict[str, float]]]):
    """DMI climate data: day values (today so far, yesterday, this month) for the municipality."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="DMI climate data", update_interval=CLIMATE_INTERVAL,
            config_entry=entry,
        )
        self.municipality = entry.data.get(CONF_MUNICIPALITY, DEFAULT_MUNICIPALITY)

    async def _async_update_data(self) -> dict[date, dict[str, float]]:
        tz = dt_util.get_time_zone(self.hass.config.time_zone)
        today = dt_util.now(tz).date()
        first = min(today.replace(day=1), today - timedelta(days=1))
        start = datetime.combine(first, time.min, tz)
        params = {
            "municipalityId": self.municipality,
            "timeResolution": "day",
            "datetime": f"{_iso(start)}/..",
            "limit": 5000,
        }
        try:
            data = await _get_json(self.hass, CLIMATE_URL, params)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            if self.data is not None:
                _LOGGER.debug("DMI climate data not available, keeping last values: %s", err)
                return self.data
            raise UpdateFailed(f"DMI climate data not available: {err}") from err
        return parse_climate(data.get("features", []), tz)


@dataclass(frozen=True)
class OceanData:
    observations: dict[str, Observation | None]
    tide: Tide | None
    # DKSS water level forecast at the harbour, cm, hourly.
    surge: list[tuple[datetime, float | None]] = field(default_factory=list)
    surge_run: datetime | None = None


class OceanCoordinator(DataUpdateCoordinator[OceanData]):
    """Water level and temperature at the nearest DMI harbour station, and its tide."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="DMI ocean", update_interval=OCEAN_INTERVAL,
            config_entry=entry,
        )
        self._lat = entry.data[CONF_LATITUDE]
        self._lon = entry.data[CONF_LONGITUDE]
        self._names: dict[str, str] | None = None
        self._tide_station: tuple[str, str | None] | None = None
        self._harbour: tuple[float, float] | None = None  # (lat, lon) for the storm surge model
        self._surge: list[tuple[datetime, float | None]] = []
        self._surge_at: datetime | None = None

    async def _stations(self) -> None:
        box = bbox(self._lat, self._lon, OCEAN_SEARCH_KM)
        stations = await _get_json(
            self.hass, OCEAN_STATION_URL,
            {"bbox": box, "status": "Active", "limit": 500},
        )
        self._names = {
            f["properties"]["stationId"]: f["properties"].get("name")
            for f in stations.get("features", [])
        }
        tide_stations = await _get_json(self.hass, TIDE_STATION_URL, {"bbox": box, "limit": 100})
        best: tuple[float, str, str | None] | None = None
        for f in tide_stations.get("features", []):
            coords = (f.get("geometry") or {}).get("coordinates")
            if not coords:
                continue
            dist = distance_km(self._lat, self._lon, coords[1], coords[0])
            if dist <= OCEAN_SEARCH_KM and (best is None or dist < best[0]):
                best = (dist, f["properties"]["stationId"], f["properties"].get("name"))
                self._harbour = (coords[1], coords[0])
        self._tide_station = (best[1], best[2]) if best else ("", None)

    async def _storm_surge(self, now: datetime) -> None:
        """DKSS water level forecast at the harbour, at most once per DKSS_INTERVAL."""
        if self._harbour is None or (self._surge_at and now - self._surge_at < DKSS_INTERVAL):
            return
        lat, lon = self._harbour
        try:
            data = await _get_json(
                self.hass, EDR_URL.format(collection=DKSS_COLLECTION),
                {"coords": f"POINT({lon:.4f} {lat:.4f})", "parameter-name": DKSS_PARAMETER, "crs": "crs84"},
                _EDR_TIMEOUT,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            # Busy (429): try again on the next round, keep the last forecast meanwhile.
            _LOGGER.debug("DMI storm surge forecast not available: %s", err)
            return
        self._surge = [
            (t, None if v is None else round(v * 100, 1))
            for t, v in coverage_series(data, DKSS_PARAMETER)
        ]
        self._surge_at = now

    async def _async_update_data(self) -> OceanData:
        now = dt_util.utcnow()
        box = bbox(self._lat, self._lon, OCEAN_SEARCH_KM)
        try:
            if self._names is None:
                await self._stations()
            span = f"{_iso(now - OBS_LOOKBACK)}/{_iso(now)}"
            results = await asyncio.gather(
                *(
                    _get_json(
                        self.hass, OCEAN_OBS_URL,
                        {"parameterId": p, "bbox": box, "datetime": span, "limit": 1000},
                    )
                    for p in OCEAN_PARAMETERS
                )
            )
            tide = None
            station_id, station_name = self._tide_station or ("", None)
            if station_id:
                predictions = await _get_json(
                    self.hass, TIDE_URL,
                    {
                        "stationId": station_id,
                        "datetime": f"{_iso(now - timedelta(minutes=20))}/{_iso(now + timedelta(hours=TIDE_HOURS))}",
                        "limit": 1000,
                    },
                )
                tide = tide_extremes(predictions.get("features", []), now, station_id, station_name)
            await self._storm_surge(now)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            if self.data is not None:
                _LOGGER.debug("DMI ocean data not available, keeping last values: %s", err)
                return self.data
            raise UpdateFailed(f"DMI ocean data not available: {err}") from err
        observations = {
            key: nearest_observation(
                result.get("features", []), self._lat, self._lon, self._names or {}, OCEAN_SEARCH_KM
            )
            for key, result in zip(OCEAN_PARAMETERS.values(), results)
        }
        return OceanData(observations, tide, self._surge, self._surge_at)


class WarningsCoordinator(DataUpdateCoordinator[Warnings]):
    """DMI's official weather warnings for the area (yellow, orange, red)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="DMI warnings", update_interval=WARNINGS_INTERVAL,
            config_entry=entry,
        )
        self.area = entry.data.get(CONF_WARNING_AREA, DEFAULT_WARNING_AREA)

    async def _async_update_data(self) -> Warnings:
        try:
            feed = await _get_json(self.hass, WARNINGS_URL)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise UpdateFailed(f"DMI warnings not available: {err}") from err
        return parse_warnings(feed, self.area, dt_util.utcnow())


@dataclass(frozen=True)
class EdrData:
    peaks: dict[str, Peak]  # next EDR_HOURS hours
    peaks_6h: dict[str, Peak]
    precip_type: str | None
    fetched: datetime
    # Hourly HARMONIE DINI series (EDR_SF_SERIES keys, temperature in °C).
    series: dict[str, list[tuple[datetime, float | None]]] = field(default_factory=dict)
    # Ensemble percentiles {key: {10: series, 50: series, 90: series}}.
    bands: dict[str, dict[int, list[tuple[datetime, float | None]]]] = field(default_factory=dict)


class EdrCoordinator(DataUpdateCoordinator[EdrData]):
    """DMI's own forecast API: HARMONIE DINI and its ensemble (probabilities and percentiles).

    Three requests an hour. DMI answers 429 when the API is busy; a part that
    fails keeps its last values, and a part that has never answered is retried
    after EDR_RETRY_INTERVAL.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="DMI forecast probabilities", update_interval=EDR_INTERVAL,
            config_entry=entry,
        )
        self._coords = f"POINT({entry.data[CONF_LONGITUDE]:.4f} {entry.data[CONF_LATITUDE]:.4f})"

    async def _position(self, collection: str, names: list[str]) -> dict[str, Any]:
        return await _get_json(
            self.hass, EDR_URL.format(collection=collection),
            {"coords": self._coords, "parameter-name": ",".join(names), "crs": "crs84"},
            _EDR_TIMEOUT,
        )

    async def _async_update_data(self) -> EdrData:
        now = dt_util.utcnow()
        peaks: dict[str, Peak] = {}
        peaks_6h: dict[str, Peak] = {}
        series: dict[str, list[tuple[datetime, float | None]]] = {}
        bands: dict[str, dict[int, list[tuple[datetime, float | None]]]] = {}
        precip_type = None
        errors = []
        try:
            eps = await self._position("harmonie_dini_eps_probabilities", list(EDR_PROBABILITIES))
            for name, key in EDR_PROBABILITIES.items():
                values = as_percent(coverage_series(eps, name))
                if key in EDR_INVERTED:
                    values = invert_percent(values)
                peaks[key] = peak(values, now, EDR_HOURS)
                peaks_6h[key] = peak(values, now, 6)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            errors.append(f"EPS: {err}")
        await asyncio.sleep(EDR_SPACING_S)
        try:
            pct = await self._position(
                "harmonie_dini_eps_percentiles",
                [f"{p}-{level}percentile" for p in EDR_PERCENTILES for level in EDR_PERCENTILE_LEVELS],
            )
            for name, key in EDR_PERCENTILES.items():
                levels = band(pct, name, EDR_PERCENTILE_LEVELS)
                if key == "temperature":
                    levels = {level: to_celsius(values) for level, values in levels.items()}
                bands[key] = levels
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            errors.append(f"PCT: {err}")
        await asyncio.sleep(EDR_SPACING_S)
        try:
            sf = await self._position("harmonie_dini_sf", [*EDR_SF, *EDR_SF_SERIES])
            # HARMONIE gives the lightning probability in percent already.
            lightning = [
                (t, None if v is None else round(v, 1))
                for t, v in coverage_series(sf, "probability-of-lightning")
            ]
            peaks["lightning"] = peak(lightning, now, EDR_HOURS)
            peaks_6h["lightning"] = peak(lightning, now, 6)
            series["lightning"] = lightning
            for name, key in EDR_SF_SERIES.items():
                values = coverage_series(sf, name)
                series[key] = to_celsius(values) if key == "temperature" else values
            kind = current(coverage_series(sf, "precipitation-type"), now)
            precip_type = None if kind is None else PRECIP_TYPES.get(int(kind))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            errors.append(f"DINI: {err}")
        if len(errors) == 3:
            # DMI answers 429 when the forecast API is busy; keep the last values.
            if self.data is not None and now - self.data.fetched < timedelta(hours=6):
                _LOGGER.debug("DMI forecast API unavailable, keeping last values: %s", errors)
                return self.data
            self.update_interval = EDR_RETRY_INTERVAL
            raise UpdateFailed(f"DMI forecast API not available: {'; '.join(errors)}")
        if self.data is not None:  # keep the parts that failed this time
            peaks = {**self.data.peaks, **peaks}
            peaks_6h = {**self.data.peaks_6h, **peaks_6h}
            series = {**self.data.series, **series}
            bands = {**self.data.bands, **bands}
            if any(e.startswith("DINI") for e in errors):
                precip_type = self.data.precip_type
        # A part that has never answered is retried soon, not after an hour.
        complete = (
            "lightning" in peaks
            and all(k in peaks for k in EDR_PROBABILITIES.values())
            and all(k in bands for k in EDR_PERCENTILES.values())
        )
        self.update_interval = EDR_INTERVAL if complete else EDR_RETRY_INTERVAL
        return EdrData(peaks, peaks_6h, precip_type, now, series, bands)


class ForecastCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """DMI HARMONIE forecast (via Open-Meteo) for the home location."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="DMI forecast", update_interval=FORECAST_INTERVAL,
            config_entry=entry,
        )
        self._lat = entry.data[CONF_LATITUDE]
        self._lon = entry.data[CONF_LONGITUDE]

    async def _async_update_data(self) -> dict[str, Any]:
        base = {
            "latitude": f"{self._lat:.4f}",
            "longitude": f"{self._lon:.4f}",
            "forecast_days": 7,
            "timezone": self.hass.config.time_zone,
        }
        params = {
            **base,
            "models": FORECAST_MODEL,
            "current": _CURRENT,
            "hourly": _HOURLY,
            "daily": _DAILY,
            "wind_speed_unit": "ms",
        }
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(FORECAST_URL, params=params, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"DMI forecast not available: {err}") from err
        if "hourly" not in data or "daily" not in data or "current" not in data:
            raise UpdateFailed(f"DMI forecast incomplete: {data.get('reason', data)}")
        data["uv"] = await self._uv(session, base)
        return data

    async def _uv(self, session: aiohttp.ClientSession, base: dict[str, Any]) -> dict[str, Any]:
        """UV index now, per hour and per day; empty when unavailable."""
        try:
            async with session.get(FORECAST_URL, params={**base, **_UV}, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug("UV index not available: %s", err)
            return {}
        hourly = data.get("hourly") or {}
        daily = data.get("daily") or {}
        return {
            "now": (data.get("current") or {}).get("uv_index"),
            "hourly": dict(zip(hourly.get("time", []), hourly.get("uv_index", []))),
            "daily": dict(zip(daily.get("time", []), daily.get("uv_index_max", []))),
        }


def local_time(hass: HomeAssistant, value: str) -> datetime:
    """Open-Meteo returns naive local times for the requested timezone."""
    tz = dt_util.get_time_zone(hass.config.time_zone)
    return datetime.fromisoformat(value).replace(tzinfo=tz)


@dataclass(frozen=True)
class SatelliteData:
    image: bytes | None
    updated: datetime | None
    latest: datetime | None  # time of the newest picture (UTC)


class SatelliteCoordinator(DataUpdateCoordinator[SatelliteData]):
    """EUMETSAT satellite pictures around the home, the last two hours as a map.

    Only new pictures are fetched (one every 10 minutes); a picture the service
    fails on (it answers 500 now and then) is tried again on the next round.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name="EUMETSAT satellite", update_interval=SAT_INTERVAL,
            config_entry=entry,
        )
        self._view = sat.SatView(
            entry.data[CONF_LATITUDE], entry.data[CONF_LONGITUDE], SAT_HALF_KM, SAT_SIZE
        )
        self._frames: dict[datetime, bytes] = {}
        self._overlay: bytes | None = None

    async def _image(self, params: dict[str, str]) -> bytes:
        session = async_get_clientsession(self.hass)
        async with session.get(sat.WMS_URL, params=params, timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            # A WMS error comes back as XML with status 200.
            if not resp.headers.get("Content-Type", "").startswith("image/"):
                raise UpdateFailed(f"EUMETSAT answered {resp.headers.get('Content-Type')}")
            return await resp.read()

    async def _async_update_data(self) -> SatelliteData:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                sat.CAPS_URL,
                params={"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"},
                timeout=_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                latest = sat.latest_time(await resp.text())
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"EUMETSAT not available: {err}") from err
        if latest is None:
            raise UpdateFailed("EUMETSAT capabilities without a picture time")

        wanted = sat.frame_times(latest, SAT_FRAMES)
        changed = False
        for when in wanted:
            if when in self._frames:
                continue
            try:
                self._frames[when] = await self._image(
                    self._view.params(sat.LAYER, "image/jpeg", when)
                )
                changed = True
            except (aiohttp.ClientError, asyncio.TimeoutError, UpdateFailed) as err:
                _LOGGER.debug("EUMETSAT picture %s not fetched: %s", sat.iso(when), err)
        for when in list(self._frames):
            if when not in wanted:
                del self._frames[when]
        if self._overlay is None:
            try:
                self._overlay = await self._image(self._view.params(sat.OVERLAYS, "image/png"))
                changed = True
            except (aiohttp.ClientError, asyncio.TimeoutError, UpdateFailed) as err:
                _LOGGER.debug("EUMETSAT coastlines not fetched: %s", err)
        if not self._frames:
            raise UpdateFailed("No EUMETSAT satellite picture")
        if not changed and self.data is not None and self.data.image is not None:
            return self.data

        tz = dt_util.get_time_zone(self.hass.config.time_zone)
        frames = [(when.astimezone(tz), self._frames[when]) for when in sorted(self._frames)]
        try:
            image = await self.hass.async_add_executor_job(
                sat.render_frames, frames, self._overlay, self._view
            )
        except (ValueError, OSError) as err:
            raise UpdateFailed(f"Could not render the satellite map: {err}") from err
        return SatelliteData(image, dt_util.utcnow(), max(self._frames))
