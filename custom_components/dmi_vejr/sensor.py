"""Sensors for DMI Vejr: radar, measured station values and lightning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfIrradiance,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumetricFlux,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from . import DmiVejrConfigEntry
from datetime import timedelta

from .const import (
    ATTRIBUTION,
    EDR_HOURS,
    LIGHTNING_RADIUS_KM,
    LIGHTNING_WINDOW,
    NEARBY_RADIUS_KM,
    OBS_12H_MAX_AGE,
    OBS_DAILY_MAX_AGE,
    OBS_MAX_AGE,
    SEARCH_RADIUS_KM,
)
from .coordinator import (
    ClimateCoordinator,
    EdrCoordinator,
    LightningCoordinator,
    ObservationCoordinator,
    OceanCoordinator,
    RadarCoordinator,
    WarningsCoordinator,
)
from .entity import device_info, obs_fresh, radar_fresh
from .extras import month_sum, weather_text
from .radar import RadarSample

_WIND_DIRECTION = getattr(SensorDeviceClass, "WIND_DIRECTION", None)


@dataclass(frozen=True, kw_only=True)
class RadarSensorDescription(SensorEntityDescription):
    value: Callable[[RadarSample], Any]
    needs_fresh: bool = True


RADAR_SENSORS = (
    RadarSensorDescription(
        key="precipitation_now",
        name="Nedbør lige nu",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda s: s.rate_mm_h,
    ),
    RadarSensorDescription(
        key="precipitation_max_nearby",
        name=f"Nedbør maks inden for {NEARBY_RADIUS_KM:g} km",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda s: s.max_nearby_mm_h,
    ),
    RadarSensorDescription(
        key="nearest_rain",
        name="Afstand til nærmeste regn",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda s: s.nearest_rain_km,
    ),
    RadarSensorDescription(
        key="radar_time",
        name="Radartidspunkt",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.time,
        needs_fresh=False,
    ),
)

@dataclass(frozen=True, kw_only=True)
class ObsSensorDescription(SensorEntityDescription):
    value: Callable[[float], Any] = lambda v: v
    max_age: timedelta = OBS_MAX_AGE
    code_attribute: bool = False


def _temp(key: str, name: str) -> ObsSensorDescription:
    return ObsSensorDescription(
        key=key, name=name, device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    )


def _wind(key: str, name: str) -> ObsSensorDescription:
    return ObsSensorDescription(
        key=key, name=name, device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    )


OBS_SENSORS = (
    _temp("temperature", "Temperatur"),
    ObsSensorDescription(
        key="humidity", name="Luftfugtighed",
        device_class=SensorDeviceClass.HUMIDITY, native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
    ),
    _wind("wind_speed", "Vindhastighed"),
    _wind("wind_gust", "Vindstød"),
    ObsSensorDescription(
        key="wind_bearing", name="Vindretning",
        device_class=_WIND_DIRECTION, native_unit_of_measurement=DEGREE,
        suggested_display_precision=0,
    ),
    ObsSensorDescription(
        key="pressure", name="Lufttryk",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    ObsSensorDescription(
        key="precip_10min", name="Nedbør målt sidste 10 min",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    ObsSensorDescription(
        key="precip_1h", name="Nedbør målt sidste time",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    _temp("dew_point", "Dugpunkt"),
    replace(_temp("temp_max_12h", "Højeste temperatur sidste 12 timer"), max_age=OBS_12H_MAX_AGE),
    replace(_temp("temp_min_12h", "Laveste temperatur sidste 12 timer"), max_age=OBS_12H_MAX_AGE),
    _temp("temp_grass", "Græstemperatur"),
    _temp("temp_soil", "Jordtemperatur"),
    ObsSensorDescription(
        key="radiation", name="Solindstråling",
        device_class=SensorDeviceClass.IRRADIANCE,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
    ),
    ObsSensorDescription(
        key="sunshine_1h", name="Solskin sidste time",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
        icon="mdi:weather-sunny",
    ),
    ObsSensorDescription(
        key="visibility", name="Sigtbarhed",
        device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.METERS,
        suggested_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        icon="mdi:eye-outline",
    ),
    ObsSensorDescription(
        key="cloud_cover", name="Skydække",
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0, icon="mdi:weather-cloudy",
        value=lambda v: v if v <= 100 else None,  # 112/113: sky obscured
    ),
    ObsSensorDescription(
        key="weather_code", name="Observeret vejr", icon="mdi:weather-partly-rainy",
        value=weather_text, code_attribute=True,
    ),
    ObsSensorDescription(
        key="precip_duration_1h", name="Nedbørsvarighed sidste time",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
        icon="mdi:timer-outline",
    ),
    _wind("wind_gust_1h", "Kraftigste vindstød sidste time"),
    ObsSensorDescription(
        key="snow_depth", name="Snedybde",
        device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
        icon="mdi:snowflake", max_age=OBS_DAILY_MAX_AGE,
    ),
)

LIGHTNING_SENSORS = (
    SensorEntityDescription(
        key="lightning_count", name=f"Lyn sidste {int(LIGHTNING_WINDOW.total_seconds() // 60)} min",
        native_unit_of_measurement="lyn", state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
    ),
    SensorEntityDescription(
        key="lightning_distance", name="Lyn nærmeste afstand",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0, icon="mdi:flash-alert",
    ),
    SensorEntityDescription(
        key="lightning_bearing", name="Lyn retning",
        device_class=_WIND_DIRECTION, native_unit_of_measurement=DEGREE,
        icon="mdi:compass-outline",
    ),
    SensorEntityDescription(
        key="lightning_last", name="Seneste lyn",
        device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:flash-outline",
    ),
)


@dataclass(frozen=True, kw_only=True)
class ClimateSensorDescription(SensorEntityDescription):
    parameter: str
    month_total: bool = False


def _climate(key, parameter, name, unit=None, device_class=None, total=False, **kw):
    return ClimateSensorDescription(
        key=key, parameter=parameter, name=name, native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=SensorStateClass.TOTAL_INCREASING if total else SensorStateClass.MEASUREMENT,
        **kw,
    )


CLIMATE_SENSORS = (
    _climate("climate_precip_today", "acc_precip", "Nedbør i dag",
             UnitOfPrecipitationDepth.MILLIMETERS, SensorDeviceClass.PRECIPITATION, True,
             suggested_display_precision=1),
    _climate("climate_mean_temp_today", "mean_temp", "Middeltemperatur i dag",
             UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, suggested_display_precision=1),
    _climate("climate_max_temp_today", "max_temp_w_date", "Højeste temperatur i dag",
             UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, suggested_display_precision=1),
    _climate("climate_min_temp_today", "min_temp", "Laveste temperatur i dag",
             UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, suggested_display_precision=1),
    _climate("climate_sunshine_today", "bright_sunshine", "Solskinstimer i dag",
             UnitOfTime.HOURS, SensorDeviceClass.DURATION, True, suggested_display_precision=1,
             icon="mdi:weather-sunny"),
    _climate("climate_degree_days_today", "acc_heating_degree_days_17", "Graddage i dag",
             "graddage", None, True, suggested_display_precision=1, icon="mdi:home-thermometer"),
    _climate("climate_degree_days_month", "acc_heating_degree_days_17", "Graddage denne måned",
             "graddage", None, False, suggested_display_precision=1, icon="mdi:home-thermometer",
             month_total=True),
    _climate("climate_mean_wind_today", "mean_wind_speed", "Middelvind i dag",
             UnitOfSpeed.METERS_PER_SECOND, SensorDeviceClass.WIND_SPEED, suggested_display_precision=1,
             suggested_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND),
    _climate("climate_max_gust_today", "max_wind_speed_3sec", "Kraftigste vindstød i dag",
             UnitOfSpeed.METERS_PER_SECOND, SensorDeviceClass.WIND_SPEED, suggested_display_precision=1,
             suggested_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND),
    _climate("climate_humidity_today", "mean_relative_hum", "Middel luftfugtighed i dag",
             PERCENTAGE, SensorDeviceClass.HUMIDITY, suggested_display_precision=0),
    _climate("climate_drought_index", "drought_index", "Tørkeindeks", None, None,
             suggested_display_precision=1, icon="mdi:water-off-outline"),
    _climate("climate_evaporation_today", "pot_evaporation_makkink", "Fordampning i dag",
             UnitOfPrecipitationDepth.MILLIMETERS, SensorDeviceClass.PRECIPITATION, True,
             suggested_display_precision=1, icon="mdi:water-percent"),
    _climate("climate_lightning_today", "no_lightning_strikes", "Lyn i kommunen i dag",
             "lyn", None, True, icon="mdi:flash"),
    _climate("climate_soil_temp_30cm", "temp_soil_30", "Jordtemperatur 30 cm",
             UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, suggested_display_precision=1),
    _climate("climate_snow_depth", "snow_depth", "Snedybde i kommunen",
             UnitOfLength.CENTIMETERS, SensorDeviceClass.DISTANCE, suggested_display_precision=0,
             icon="mdi:snowflake"),
)

OCEAN_SENSORS = (
    ObsSensorDescription(
        key="water_level", name="Vandstand havn", native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:waves-arrow-up",
    ),
    ObsSensorDescription(
        key="water_temperature", name="Vandtemperatur havn",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:coolant-temperature",
    ),
)

TIDE_SENSORS = (
    SensorEntityDescription(key="tide_high", name="Næste højvande", device_class=SensorDeviceClass.TIMESTAMP,
                            icon="mdi:arrow-collapse-up"),
    SensorEntityDescription(key="tide_low", name="Næste lavvande", device_class=SensorDeviceClass.TIMESTAMP,
                            icon="mdi:arrow-collapse-down"),
)

EDR_SENSORS = (
    SensorEntityDescription(key="risk_frost", name="Frostrisiko næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:snowflake-thermometer"),
    SensorEntityDescription(key="risk_heavy_rain", name="Risiko for kraftig regn næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-pouring"),
    SensorEntityDescription(key="risk_cloudburst", name="Risiko for skybrud næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-hail"),
    SensorEntityDescription(key="risk_storm_gust", name="Risiko for stormstød næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-windy-variant"),
    SensorEntityDescription(key="risk_lightning", name="Lynrisiko næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-lightning"),
    SensorEntityDescription(key="precip_type", name="Nedbørstype (prognose)", icon="mdi:weather-snowy-rainy"),
)
_EDR_KEYS = {
    "risk_frost": "frost", "risk_heavy_rain": "heavy_rain", "risk_cloudburst": "cloudburst",
    "risk_storm_gust": "storm_gust", "risk_lightning": "lightning",
}
_EDR_LABELS = {
    "frost": "under 0 °C", "heavy_rain": "over 10 mm på 3 timer", "cloudburst": "over 30 mm på 3 timer",
    "storm_gust": "vindstød over 25 m/s", "lightning": "lyn",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: DmiVejrConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = entry.runtime_data
    async_add_entities(
        [RadarSensor(entry, d) for d in RADAR_SENSORS]
        + [ObservationSensor(entry, data.observations, d) for d in OBS_SENSORS]
        + [LightningSensor(entry, d) for d in LIGHTNING_SENSORS]
        + [ClimateSensor(entry, d) for d in CLIMATE_SENSORS]
        + [OceanSensor(entry, d) for d in OCEAN_SENSORS]
        + [TideSensor(entry, d) for d in TIDE_SENSORS]
        + [EdrSensor(entry, d) for d in EDR_SENSORS]
        + [WarningsSensor(entry)]
    )


class _Base(SensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def _setup(self, entry: DmiVejrConfigEntry, description: SensorEntityDescription) -> None:
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry.entry_id)


class RadarSensor(CoordinatorEntity[RadarCoordinator], _Base):
    entity_description: RadarSensorDescription

    def __init__(self, entry: DmiVejrConfigEntry, description: RadarSensorDescription) -> None:
        super().__init__(entry.runtime_data.radar)
        self._setup(entry, description)

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        return radar_fresh(self.coordinator.data.sample) or not self.entity_description.needs_fresh

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data.sample)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "nearest_rain":
            return {"søgeradius_km": SEARCH_RADIUS_KM}
        if self.entity_description.key == "precipitation_now":
            return {"dbz": self.coordinator.data.sample.dbz}
        return None


class ObservationSensor(CoordinatorEntity[ObservationCoordinator], _Base):
    entity_description: ObsSensorDescription

    def __init__(self, entry: DmiVejrConfigEntry, coordinator, description: ObsSensorDescription) -> None:
        super().__init__(coordinator)
        self._setup(entry, description)

    @property
    def _obs(self):
        return self._observations().get(self.entity_description.key)

    def _observations(self) -> dict:
        return self.coordinator.data or {}

    @property
    def available(self) -> bool:
        return (
            super().available
            and obs_fresh(self._obs, self.entity_description.max_age)
            and self.native_value is not None
        )

    @property
    def native_value(self) -> Any:
        obs = self._obs
        return self.entity_description.value(obs.value) if obs else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        obs = self._obs
        if obs is None:
            return None
        attrs = {
            "station": obs.station_name or obs.station_id,
            "station_id": obs.station_id,
            "afstand_km": obs.distance_km,
            "målt": obs.observed.isoformat(),
        }
        if self.entity_description.code_attribute:
            attrs["kode"] = int(obs.value)
        return attrs


class OceanSensor(ObservationSensor):
    def __init__(self, entry: DmiVejrConfigEntry, description: ObsSensorDescription) -> None:
        super().__init__(entry, entry.runtime_data.ocean, description)

    def _observations(self) -> dict:
        return self.coordinator.data.observations if self.coordinator.data else {}


class LightningSensor(CoordinatorEntity[LightningCoordinator], _Base):
    def __init__(self, entry: DmiVejrConfigEntry, description: SensorEntityDescription) -> None:
        super().__init__(entry.runtime_data.lightning)
        self._setup(entry, description)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def native_value(self) -> Any:
        stats = self.coordinator.data
        return {
            "lightning_count": stats.count,
            "lightning_distance": stats.nearest_km,
            "lightning_bearing": stats.nearest_bearing,
            "lightning_last": stats.last_strike,
        }[self.entity_description.key]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "lightning_count":
            return {"radius_km": LIGHTNING_RADIUS_KM}
        return None


class ClimateSensor(CoordinatorEntity[ClimateCoordinator], _Base):
    entity_description: ClimateSensorDescription

    def __init__(self, entry: DmiVejrConfigEntry, description: ClimateSensorDescription) -> None:
        super().__init__(entry.runtime_data.climate)
        self._setup(entry, description)

    def _day(self, offset: int) -> float | None:
        today = dt_util.now().date()
        return (self.coordinator.data or {}).get(today - timedelta(days=offset), {}).get(
            self.entity_description.parameter
        )

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        if self.entity_description.month_total:
            return month_sum(
                self.coordinator.data or {}, self.entity_description.parameter, dt_util.now().date()
            )
        return self._day(0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = {"kilde": f"DMI klimadata, kommune {self.coordinator.municipality}"}
        if not self.entity_description.month_total:
            attrs["i_går"] = self._day(1)
        return attrs


class TideSensor(CoordinatorEntity[OceanCoordinator], _Base):
    def __init__(self, entry: DmiVejrConfigEntry, description: SensorEntityDescription) -> None:
        super().__init__(entry.runtime_data.ocean)
        self._setup(entry, description)

    @property
    def _extreme(self):
        tide = self.coordinator.data.tide if self.coordinator.data else None
        if tide is None:
            return None, None
        return tide, tide.next_high if self.entity_description.key == "tide_high" else tide.next_low

    @property
    def available(self) -> bool:
        return super().available and self._extreme[1] is not None

    @property
    def native_value(self):
        return self._extreme[1].time

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        tide, extreme = self._extreme
        if extreme is None:
            return None
        return {
            "niveau_cm": extreme.level_cm,
            "tidevand_nu_cm": tide.now_cm,
            "station": tide.station_name or tide.station_id,
            "kilde": "DMI tidevandsprognose",
        }


class EdrSensor(CoordinatorEntity[EdrCoordinator], _Base):
    def __init__(self, entry: DmiVejrConfigEntry, description: SensorEntityDescription) -> None:
        super().__init__(entry.runtime_data.edr)
        self._setup(entry, description)

    @property
    def _peaks(self):
        key = _EDR_KEYS.get(self.entity_description.key)
        data = self.coordinator.data
        if data is None or key is None:
            return None, None
        return data.peaks.get(key), data.peaks_6h.get(key)

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        if self.entity_description.key == "precip_type":
            return True
        day = self._peaks[0]
        return day is not None and day.value is not None

    @property
    def native_value(self):
        if self.entity_description.key == "precip_type":
            return self.coordinator.data.precip_type or "Ingen"
        return self._peaks[0].value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "precip_type":
            return {"kilde": "DMI HARMONIE DINI"}
        day, six = self._peaks
        key = _EDR_KEYS[self.entity_description.key]
        return {
            "hændelse": _EDR_LABELS[key],
            "tidspunkt": day.time.isoformat() if day and day.time else None,
            "næste_6_timer": six.value if six else None,
            "timer": EDR_HOURS,
            "kilde": "DMI HARMONIE DINI EPS" if key != "lightning" else "DMI HARMONIE DINI",
            "beregnet": self.coordinator.data.fetched.isoformat(),
        }


class WarningsSensor(CoordinatorEntity[WarningsCoordinator], _Base):
    _attr_icon = "mdi:alert-outline"

    def __init__(self, entry: DmiVejrConfigEntry) -> None:
        super().__init__(entry.runtime_data.warnings)
        self._setup(entry, SensorEntityDescription(key="warnings", name="Varsler"))

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def native_value(self) -> int:
        now = dt_util.utcnow()
        return len([w for w in self.coordinator.data.items if w.expires > now])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now = dt_util.utcnow()
        data = self.coordinator.data
        items = [w for w in data.items if w.expires > now]
        active = data.active(now)
        return {
            "område": data.area,
            "aktive": len(active),
            "højeste_niveau": max((w.level for w in items), default=0),
            "højeste_aktive_niveau": max((w.level for w in active), default=0),
            "varsler": [w.as_dict for w in items],
            "kilde": "DMI via MeteoAlarm",
        }
