"""Weather entity: DMI HARMONIE forecast, current condition corrected by radar."""

from __future__ import annotations

from typing import Any

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_LIGHTNING_RAINY,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SNOWY_RAINY,
    ATTR_CONDITION_SUNNY,
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from . import DmiVejrConfigEntry
from .const import ATTRIBUTION, HOURLY_FORECAST_HOURS, POURING_MM_H, RAIN_NOW_MM_H
from .coordinator import ForecastCoordinator, local_time
from .entity import device_info, obs_fresh, radar_fresh

# WMO weather interpretation codes -> Home Assistant conditions.
_WMO: dict[int, str] = {
    0: ATTR_CONDITION_SUNNY, 1: ATTR_CONDITION_SUNNY,
    2: ATTR_CONDITION_PARTLYCLOUDY, 3: ATTR_CONDITION_CLOUDY,
    45: ATTR_CONDITION_FOG, 48: ATTR_CONDITION_FOG,
    51: ATTR_CONDITION_RAINY, 53: ATTR_CONDITION_RAINY, 55: ATTR_CONDITION_RAINY,
    56: ATTR_CONDITION_SNOWY_RAINY, 57: ATTR_CONDITION_SNOWY_RAINY,
    61: ATTR_CONDITION_RAINY, 63: ATTR_CONDITION_RAINY, 65: ATTR_CONDITION_POURING,
    66: ATTR_CONDITION_SNOWY_RAINY, 67: ATTR_CONDITION_SNOWY_RAINY,
    71: ATTR_CONDITION_SNOWY, 73: ATTR_CONDITION_SNOWY, 75: ATTR_CONDITION_SNOWY,
    77: ATTR_CONDITION_SNOWY,
    80: ATTR_CONDITION_RAINY, 81: ATTR_CONDITION_RAINY, 82: ATTR_CONDITION_POURING,
    85: ATTR_CONDITION_SNOWY, 86: ATTR_CONDITION_SNOWY,
    95: ATTR_CONDITION_LIGHTNING_RAINY, 96: ATTR_CONDITION_LIGHTNING_RAINY,
    99: ATTR_CONDITION_LIGHTNING_RAINY,
}
_SNOW = {ATTR_CONDITION_SNOWY, ATTR_CONDITION_SNOWY_RAINY}
_SKY = {
    ATTR_CONDITION_SUNNY, ATTR_CONDITION_CLEAR_NIGHT, ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_CLOUDY, ATTR_CONDITION_FOG,
}


def wmo_condition(code: Any, is_day: Any = 1) -> str | None:
    if code is None:
        return None
    condition = _WMO.get(int(code))
    if condition == ATTR_CONDITION_SUNNY and not is_day:
        return ATTR_CONDITION_CLEAR_NIGHT
    return condition


def radar_condition(model: str | None, rate_mm_h: float) -> str | None:
    """Condition when the radar sees precipitation; None when it is dry."""
    if rate_mm_h < RAIN_NOW_MM_H:
        return None
    if model in _SNOW or model == ATTR_CONDITION_LIGHTNING_RAINY:
        return model
    return ATTR_CONDITION_POURING if rate_mm_h >= POURING_MM_H else ATTR_CONDITION_RAINY


async def async_setup_entry(
    hass: HomeAssistant, entry: DmiVejrConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DmiWeather(entry)])


class DmiWeather(CoordinatorEntity[ForecastCoordinator], WeatherEntity):
    """DMI forecast whose current condition follows the radar."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_attribution = ATTRIBUTION
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )

    def __init__(self, entry: DmiVejrConfigEntry) -> None:
        super().__init__(entry.runtime_data.forecast)
        self._radar = entry.runtime_data.radar
        self._obs = entry.runtime_data.observations
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = device_info(entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._radar.async_add_listener(self._handle_radar_update))
        self.async_on_remove(self._obs.async_add_listener(self.async_write_ha_state))

    @callback
    def _handle_radar_update(self) -> None:
        self.async_write_ha_state()
        self.hass.async_create_task(self.async_update_listeners(("hourly",)))

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        self.hass.async_create_task(self.async_update_listeners(("hourly", "daily")))

    @property
    def _current(self) -> dict[str, Any]:
        return self.coordinator.data["current"]

    @property
    def _uv(self) -> dict[str, Any]:
        return self.coordinator.data.get("uv") or {}

    def _radar_rate(self) -> float | None:
        sample = self._radar.data.sample if self._radar.data else None
        return sample.rate_mm_h if radar_fresh(sample) else None

    def _measured(self, key: str, model_key: str) -> float | None:
        """Measured DMI station value when fresh, otherwise the model."""
        obs = (self._obs.data or {}).get(key)
        return obs.value if obs_fresh(obs) else self._current.get(model_key)

    def _fresh_obs(self, key: str) -> float | None:
        obs = (self._obs.data or {}).get(key)
        return obs.value if obs_fresh(obs) else None

    def _sky(self, model: str | None) -> str | None:
        """Without precipitation: DMI's observed fog and measured cloud cover over the model's sky."""
        code = self._fresh_obs("weather_code")
        if code is not None and 30 <= int(code) % 100 <= 35:
            return ATTR_CONDITION_FOG
        cloud = self._fresh_obs("cloud_cover")
        if cloud is None or cloud > 100 or model not in _SKY:
            return model
        if cloud >= 88:  # 7/8 or more
            return ATTR_CONDITION_CLOUDY
        if cloud >= 25:
            return ATTR_CONDITION_PARTLYCLOUDY
        return ATTR_CONDITION_SUNNY if self._current.get("is_day") else ATTR_CONDITION_CLEAR_NIGHT

    @property
    def condition(self) -> str | None:
        model = wmo_condition(self._current.get("weather_code"), self._current.get("is_day"))
        rate = self._radar_rate()
        if rate is None:
            return self._sky(model) if model in _SKY else model
        radar = radar_condition(model, rate)
        if radar is not None:
            return radar
        # Radar says dry: never show rain the radar does not see.
        if model in (ATTR_CONDITION_RAINY, ATTR_CONDITION_POURING, ATTR_CONDITION_LIGHTNING_RAINY):
            model = ATTR_CONDITION_CLOUDY
        return self._sky(model)

    @property
    def native_temperature(self) -> float | None:
        return self._measured("temperature", "temperature_2m")

    @property
    def native_apparent_temperature(self) -> float | None:
        return self._current.get("apparent_temperature")

    @property
    def humidity(self) -> float | None:
        return self._measured("humidity", "relative_humidity_2m")

    @property
    def native_pressure(self) -> float | None:
        return self._measured("pressure", "pressure_msl")

    @property
    def native_wind_speed(self) -> float | None:
        return self._measured("wind_speed", "wind_speed_10m")

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self._measured("wind_gust", "wind_gusts_10m")

    @property
    def wind_bearing(self) -> float | None:
        return self._measured("wind_bearing", "wind_direction_10m")

    @property
    def cloud_coverage(self) -> float | None:
        cloud = self._fresh_obs("cloud_cover")
        return cloud if cloud is not None and cloud <= 100 else self._current.get("cloud_cover")

    @property
    def native_dew_point(self) -> float | None:
        return self._measured("dew_point", "dew_point_2m")

    @property
    def native_visibility(self) -> float | None:
        obs = (self._obs.data or {}).get("visibility")
        return round(obs.value / 1000, 1) if obs_fresh(obs) else None

    @property
    def uv_index(self) -> float | None:
        return self._uv.get("now")

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        hourly = self.coordinator.data["hourly"]
        now = dt_util.now()
        this_hour = now.replace(minute=0, second=0, microsecond=0)
        rate = self._radar_rate()
        uv = self._uv.get("hourly", {})
        out: list[Forecast] = []
        for i, stamp in enumerate(hourly["time"]):
            when = local_time(self.hass, stamp)
            if when < this_hour:
                continue
            if len(out) >= HOURLY_FORECAST_HOURS:
                break
            condition = wmo_condition(hourly["weather_code"][i], hourly["is_day"][i])
            precipitation = hourly["precipitation"][i]
            if when == this_hour and rate is not None:
                condition = radar_condition(condition, rate) or condition
                precipitation = max(precipitation or 0.0, round(rate, 1))
            out.append(
                Forecast(
                    datetime=when.isoformat(),
                    condition=condition,
                    native_temperature=hourly["temperature_2m"][i],
                    native_apparent_temperature=hourly["apparent_temperature"][i],
                    native_precipitation=precipitation,
                    precipitation_probability=hourly["precipitation_probability"][i],
                    native_wind_speed=hourly["wind_speed_10m"][i],
                    native_wind_gust_speed=hourly["wind_gusts_10m"][i],
                    wind_bearing=hourly["wind_direction_10m"][i],
                    cloud_coverage=hourly["cloud_cover"][i],
                    humidity=hourly["relative_humidity_2m"][i],
                    uv_index=uv.get(stamp),
                )
            )
        return out

    async def async_forecast_daily(self) -> list[Forecast] | None:
        daily = self.coordinator.data["daily"]
        uv = self._uv.get("daily", {})
        return [
            Forecast(
                datetime=local_time(self.hass, f"{day}T00:00").isoformat(),
                condition=wmo_condition(daily["weather_code"][i]),
                native_temperature=daily["temperature_2m_max"][i],
                native_templow=daily["temperature_2m_min"][i],
                native_precipitation=daily["precipitation_sum"][i],
                precipitation_probability=daily["precipitation_probability_max"][i],
                native_wind_speed=daily["wind_speed_10m_max"][i],
                native_wind_gust_speed=daily["wind_gusts_10m_max"][i],
                wind_bearing=daily["wind_direction_10m_dominant"][i],
                humidity=daily["relative_humidity_2m_mean"][i],
                uv_index=uv.get(day),
            )
            for i, day in enumerate(daily["time"])
        ]
