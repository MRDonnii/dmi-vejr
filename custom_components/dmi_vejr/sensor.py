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
from datetime import datetime, timedelta

from .const import (
    ATTRIBUTION,
    DKSS_HOURS,
    EDR_HOURS,
    EDR_SERIES_HOURS,
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
from .extras import (
    Peak,
    hourly_rows,
    month_mean,
    month_sum,
    weather_text,
    window,
    window_min,
    window_sum,
)
from .extras import peak as series_peak
from .places import municipality_name
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
        key="pressure_station", name="Lufttryk ved stationen",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    ObsSensorDescription(
        key="humidity_1h", name="Luftfugtighed middel sidste time",
        device_class=SensorDeviceClass.HUMIDITY, native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
    ),
    _temp("temp_mean_1h", "Middeltemperatur sidste time"),
    _temp("temp_max_1h", "Højeste temperatur sidste time"),
    _temp("temp_min_1h", "Laveste temperatur sidste time"),
    _temp("temp_grass_mean_1h", "Græstemperatur middel sidste time"),
    _temp("temp_grass_max_1h", "Græstemperatur højeste sidste time"),
    _temp("temp_grass_min_1h", "Græstemperatur laveste sidste time"),
    _temp("temp_soil_mean_1h", "Jordtemperatur middel sidste time"),
    _temp("temp_soil_max_1h", "Jordtemperatur højeste sidste time"),
    _temp("temp_soil_min_1h", "Jordtemperatur laveste sidste time"),
    ObsSensorDescription(
        key="precip_1min", name="Nedbør målt sidste minut",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
    ),
    ObsSensorDescription(
        key="precip_duration_10min", name="Nedbørsvarighed sidste 10 min",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
        icon="mdi:timer-outline",
    ),
    ObsSensorDescription(
        key="radiation_1h", name="Solindstråling middel sidste time",
        device_class=SensorDeviceClass.IRRADIANCE,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
    ),
    ObsSensorDescription(
        key="sunshine_10min", name="Solskin sidste 10 min",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
        icon="mdi:weather-sunny",
    ),
    ObsSensorDescription(
        key="visibility_10min", name="Sigtbarhed middel sidste 10 min",
        device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.METERS,
        suggested_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        icon="mdi:eye-outline",
    ),
    _wind("wind_min", "Laveste vind"),
    _wind("wind_speed_1h", "Middelvind sidste time"),
    _wind("wind_min_1h", "Laveste vind sidste time"),
    _wind("wind_max_10min_1h", "Højeste 10-min middelvind sidste time"),
    ObsSensorDescription(
        key="wind_bearing_1h", name="Vindretning middel sidste time",
        device_class=_WIND_DIRECTION, native_unit_of_measurement=DEGREE,
        suggested_display_precision=0,
    ),
    ObsSensorDescription(
        key="snow_cover", name="Snedække",
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0, icon="mdi:snowflake-variant", max_age=OBS_DAILY_MAX_AGE,
    ),
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
    month_mean: bool = False
    # DMI publishes some day values only once the day is over: show the latest day.
    latest: bool = False


def _climate(key, parameter, name, unit=None, device_class=None, total=False, **kw):
    state_class = SensorStateClass.TOTAL_INCREASING if total else SensorStateClass.MEASUREMENT
    if device_class is not None and device_class == _WIND_DIRECTION:
        state_class = getattr(SensorStateClass, "MEASUREMENT_ANGLE", None)
    return ClimateSensorDescription(
        key=key, parameter=parameter, name=name, native_unit_of_measurement=unit,
        device_class=device_class, state_class=state_class, **kw,
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
             "graddage", None, False, suggested_display_precision=1, icon="mdi:home-thermometer"),
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
             UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, suggested_display_precision=1,
             latest=True),
    _climate("climate_snow_depth", "snow_depth", "Snedybde i kommunen",
             UnitOfLength.CENTIMETERS, SensorDeviceClass.DISTANCE, suggested_display_precision=0,
             icon="mdi:snowflake"),
    _climate("climate_max_precip_30m", "max_precip_30m", "Kraftigste 30 min nedbør (seneste døgn)",
             UnitOfPrecipitationDepth.MILLIMETERS, SensorDeviceClass.PRECIPITATION,
             suggested_display_precision=1, icon="mdi:weather-pouring", latest=True),
    _climate("climate_leaf_moisture", "leaf_moisture", "Bladfugt (seneste døgn)",
             UnitOfTime.MINUTES, SensorDeviceClass.DURATION, suggested_display_precision=0,
             suggested_unit_of_measurement=UnitOfTime.HOURS, icon="mdi:leaf", latest=True),
    _climate("climate_cloud_cover_today", "mean_cloud_cover", "Middel skydække (seneste døgn)",
             PERCENTAGE, None, suggested_display_precision=0, icon="mdi:weather-cloudy", latest=True),
    _climate("climate_pressure_today", "mean_pressure", "Middel lufttryk i dag",
             UnitOfPressure.HPA, SensorDeviceClass.ATMOSPHERIC_PRESSURE, suggested_display_precision=1),
    _climate("climate_radiation_today", "mean_radiation", "Middel solindstråling i dag",
             UnitOfIrradiance.WATTS_PER_SQUARE_METER, SensorDeviceClass.IRRADIANCE,
             suggested_display_precision=0),
    _climate("climate_wind_dir_today", "mean_wind_dir", "Middel vindretning i dag",
             DEGREE, _WIND_DIRECTION, suggested_display_precision=0),
    _climate("climate_max_wind_10min_today", "max_wind_speed_10min", "Højeste middelvind i dag",
             UnitOfSpeed.METERS_PER_SECOND, SensorDeviceClass.WIND_SPEED, suggested_display_precision=1,
             suggested_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND),
    _climate("climate_grass_min_today", "temp_grass", "Laveste græstemperatur (seneste døgn)",
             UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, suggested_display_precision=1,
             latest=True),
    _climate("climate_soil_temp_10cm", "temp_soil_10", "Jordtemperatur 10 cm",
             UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, suggested_display_precision=1,
             latest=True),
    _climate("climate_vpd_today", "vapour_pressure_deficit_mean", "Damptryksunderskud i dag",
             UnitOfPressure.HPA, None, suggested_display_precision=1, icon="mdi:water-opacity"),
    # Month so far, summed or averaged from the day values.
    _climate("climate_precip_month", "acc_precip", "Nedbør denne måned",
             UnitOfPrecipitationDepth.MILLIMETERS, SensorDeviceClass.PRECIPITATION, False,
             suggested_display_precision=1, month_total=True),
    _climate("climate_sunshine_month", "bright_sunshine", "Solskinstimer denne måned",
             UnitOfTime.HOURS, SensorDeviceClass.DURATION, False, suggested_display_precision=1,
             icon="mdi:weather-sunny", month_total=True),
    _climate("climate_mean_temp_month", "mean_temp", "Middeltemperatur denne måned",
             UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, suggested_display_precision=1,
             month_mean=True),
    _climate("climate_frost_days_month", "no_frost_days", "Frostdage denne måned",
             "dage", None, False, suggested_display_precision=0, icon="mdi:snowflake-thermometer",
             month_total=True),
    _climate("climate_ice_days_month", "no_ice_days", "Isdage denne måned",
             "dage", None, False, suggested_display_precision=0, icon="mdi:snowflake-alert",
             month_total=True),
    _climate("climate_summer_days_month", "no_summer_days", "Sommerdage denne måned",
             "dage", None, False, suggested_display_precision=0, icon="mdi:white-balance-sunny",
             month_total=True),
    _climate("climate_tropical_nights_month", "no_tropical_nights", "Tropenætter denne måned",
             "nætter", None, False, suggested_display_precision=0, icon="mdi:weather-night",
             month_total=True),
    _climate("climate_rain_days_month", "no_days_acc_precip_1", "Dage med regn (≥1 mm) denne måned",
             "dage", None, False, suggested_display_precision=0, icon="mdi:weather-rainy",
             month_total=True),
    _climate("climate_wet_days_month", "no_days_acc_precip_10", "Dage med meget regn (≥10 mm) denne måned",
             "dage", None, False, suggested_display_precision=0, icon="mdi:weather-pouring",
             month_total=True),
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
    SensorEntityDescription(key="risk_hurricane_gust", name="Risiko for orkanstød næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-hurricane"),
    SensorEntityDescription(key="risk_storm", name="Risiko for storm næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-windy"),
    SensorEntityDescription(key="risk_hurricane", name="Risiko for orkan næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-hurricane"),
    SensorEntityDescription(key="risk_rain_16mm_3h", name="Risiko for over 16 mm regn på 3 timer næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-pouring"),
    SensorEntityDescription(key="risk_rain_24mm_6h", name="Risiko for over 24 mm regn på 6 timer næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-pouring"),
    SensorEntityDescription(key="risk_rain_35mm_6h", name="Risiko for over 35 mm regn på 6 timer næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-pouring"),
    SensorEntityDescription(key="risk_rain_30mm_24h", name="Risiko for over 30 mm regn på et døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-pouring"),
    SensorEntityDescription(key="risk_rain_50mm_24h", name="Risiko for over 50 mm regn på et døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-pouring"),
    SensorEntityDescription(key="risk_snow", name="Snerisiko næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-snowy"),
    SensorEntityDescription(key="risk_snow_5mm", name="Risiko for over 5 mm sne på 6 timer næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-snowy-heavy"),
    SensorEntityDescription(key="risk_snow_10mm", name="Risiko for over 10 mm sne på 6 timer næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-snowy-heavy"),
    SensorEntityDescription(key="risk_snow_15mm", name="Risiko for over 15 mm sne på 6 timer næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-snowy-heavy"),
    SensorEntityDescription(key="risk_fog", name="Tågerisiko næste døgn",
                            native_unit_of_measurement=PERCENTAGE, icon="mdi:weather-fog"),
)
_EDR_KEYS = {
    "risk_frost": "frost", "risk_heavy_rain": "heavy_rain", "risk_cloudburst": "cloudburst",
    "risk_storm_gust": "storm_gust", "risk_lightning": "lightning",
    "risk_hurricane_gust": "hurricane_gust", "risk_storm": "storm", "risk_hurricane": "hurricane",
    "risk_rain_16mm_3h": "rain_16mm_3h", "risk_rain_24mm_6h": "rain_24mm_6h",
    "risk_rain_35mm_6h": "rain_35mm_6h", "risk_rain_30mm_24h": "rain_30mm_24h",
    "risk_rain_50mm_24h": "rain_50mm_24h", "risk_snow": "snow_1mm", "risk_snow_5mm": "snow_5mm",
    "risk_snow_10mm": "snow_10mm", "risk_snow_15mm": "snow_15mm", "risk_fog": "fog",
}
_EDR_LABELS = {
    "frost": "under 0 °C", "heavy_rain": "over 10 mm på 3 timer", "cloudburst": "over 30 mm på 3 timer",
    "storm_gust": "vindstød over 25 m/s", "lightning": "lyn",
    "hurricane_gust": "vindstød over 33 m/s", "storm": "middelvind over 25 m/s",
    "hurricane": "middelvind over 33 m/s", "rain_16mm_3h": "over 16 mm på 3 timer",
    "rain_24mm_6h": "over 24 mm på 6 timer", "rain_35mm_6h": "over 35 mm på 6 timer",
    "rain_30mm_24h": "over 30 mm på 24 timer", "rain_50mm_24h": "over 50 mm på 24 timer",
    "snow_1mm": "over 1 mm sne (vand) på 6 timer", "snow_5mm": "over 5 mm sne (vand) på 6 timer",
    "snow_10mm": "over 10 mm sne (vand) på 6 timer", "snow_15mm": "over 15 mm sne (vand) på 6 timer",
    "fog": "sigtbarhed under 100 m (tåge)",
}


# Ensemble spread over the next EDR_HOURS hours: (key, band, how, name, unit, device class, icon, precision).
@dataclass(frozen=True, kw_only=True)
class BandSensorDescription(SensorEntityDescription):
    band: str
    how: str  # "min10", "max90", "sum50", "max50"


BAND_SENSORS = (
    BandSensorDescription(
        key="forecast_temp_low", band="temperature", how="min10",
        name="Laveste temperatur næste døgn (ensemble 10 %)",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1, icon="mdi:thermometer-chevron-down",
    ),
    BandSensorDescription(
        key="forecast_temp_high", band="temperature", how="max90",
        name="Højeste temperatur næste døgn (ensemble 90 %)",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1, icon="mdi:thermometer-chevron-up",
    ),
    BandSensorDescription(
        key="forecast_gust_high", band="gust", how="max90",
        name="Kraftigste vindstød næste døgn (ensemble 90 %)",
        device_class=SensorDeviceClass.WIND_SPEED, native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1, icon="mdi:weather-windy-variant",
    ),
    BandSensorDescription(
        key="forecast_wind_mid", band="wind", how="max50",
        name="Højeste middelvind næste døgn (ensemble median)",
        device_class=SensorDeviceClass.WIND_SPEED, native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1, icon="mdi:weather-windy",
    ),
    BandSensorDescription(
        key="forecast_precip_24h", band="precip", how="sum50",
        name="Nedbør næste døgn (ensemble median)",
        device_class=SensorDeviceClass.PRECIPITATION, native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        suggested_display_precision=1, icon="mdi:weather-rainy",
    ),
    BandSensorDescription(
        key="forecast_snow_24h", band="snow", how="sum50",
        name="Sne næste døgn (ensemble median, vand)",
        device_class=SensorDeviceClass.PRECIPITATION, native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        suggested_display_precision=1, icon="mdi:weather-snowy",
    ),
)


@dataclass(frozen=True, kw_only=True)
class SeriesSensorDescription(SensorEntityDescription):
    series: str
    scale: float = 1.0


SERIES_SENSORS = (
    SeriesSensorDescription(
        key="forecast_cloud_base", series="cloud_base", name="Skybase (prognose)",
        device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=0, icon="mdi:cloud-arrow-up-outline",
    ),
    SeriesSensorDescription(
        key="forecast_freezing_level", series="freezing_level", name="Nulgradsgrænse (højde)",
        device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=0, icon="mdi:snowflake-melt",
    ),
    SeriesSensorDescription(
        key="forecast_cape", series="cape", name="Tordenenergi (CAPE)",
        native_unit_of_measurement="J/kg", suggested_display_precision=0, icon="mdi:weather-lightning-rainy",
    ),
    SeriesSensorDescription(
        key="forecast_radiation", series="radiation", name="Solindstråling (prognose)",
        device_class=SensorDeviceClass.IRRADIANCE, native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        suggested_display_precision=0, icon="mdi:solar-power-variant",
    ),
    SeriesSensorDescription(
        key="forecast_cloud_low", series="cloud_low", name="Lave skyer (prognose)",
        native_unit_of_measurement=PERCENTAGE, suggested_display_precision=0, icon="mdi:weather-fog",
    ),
    SeriesSensorDescription(
        key="forecast_cloud_medium", series="cloud_medium", name="Mellemhøje skyer (prognose)",
        native_unit_of_measurement=PERCENTAGE, suggested_display_precision=0, icon="mdi:weather-cloudy",
    ),
    SeriesSensorDescription(
        key="forecast_cloud_high", series="cloud_high", name="Høje skyer (prognose)",
        native_unit_of_measurement=PERCENTAGE, suggested_display_precision=0, icon="mdi:weather-partly-cloudy",
    ),
    SeriesSensorDescription(
        key="forecast_visibility", series="visibility", name="Sigtbarhed (prognose)",
        device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.METERS,
        suggested_unit_of_measurement=UnitOfLength.KILOMETERS, suggested_display_precision=1,
        icon="mdi:eye-outline",
    ),
    SeriesSensorDescription(
        key="forecast_snow_cover", series="snow_water", name="Sne på jorden (prognose, vand)",
        device_class=SensorDeviceClass.PRECIPITATION, native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        suggested_display_precision=1, icon="mdi:snowflake",
    ),
)
SOLAR_ENERGY = SensorEntityDescription(
    key="forecast_solar_energy_24h", name="Solenergi næste døgn",
    native_unit_of_measurement="kWh/m²", suggested_display_precision=2, icon="mdi:solar-power",
)
SURGE = SensorEntityDescription(
    key="water_level_forecast", name="Vandstand prognose",
    native_unit_of_measurement=UnitOfLength.CENTIMETERS, suggested_display_precision=0,
    icon="mdi:waves-arrow-up",
)


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
        + [BandSensor(entry, d) for d in BAND_SENSORS]
        + [SeriesSensor(entry, d) for d in SERIES_SENSORS]
        + [SolarEnergySensor(entry), SurgeSensor(entry)]
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


# When DMI's stations are late (their open data stopped for all stations on 2026-10-15), these readings fall back to the
# forecast model's "now" values, like the weather entity does, so Better Thermostat and others keep an outdoor value.
MODEL_FALLBACK = {
    "temperature": "temperature_2m", "humidity": "relative_humidity_2m", "pressure": "pressure_msl",
    "wind_speed": "wind_speed_10m", "wind_gust": "wind_gusts_10m", "wind_bearing": "wind_direction_10m",
    "dew_point": "dew_point_2m",
}


class ObservationSensor(CoordinatorEntity[ObservationCoordinator], _Base):
    entity_description: ObsSensorDescription
    _fallback_keys = MODEL_FALLBACK

    def __init__(self, entry: DmiVejrConfigEntry, coordinator, description: ObsSensorDescription) -> None:
        super().__init__(coordinator)
        self._setup(entry, description)
        self._model_key = self._fallback_keys.get(description.key)
        self._forecast = getattr(getattr(entry, "runtime_data", None), "forecast", None) if self._model_key else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._forecast is not None:
            self.async_on_remove(self._forecast.async_add_listener(self.async_write_ha_state))

    def _model_value(self) -> Any:
        """The forecast model's value now, when the station reading is missing or too old."""
        if self._forecast is None or not self._forecast.data:
            return None
        value = (self._forecast.data.get("current") or {}).get(self._model_key)
        return value if isinstance(value, (int, float)) else None

    def _fresh(self) -> bool:
        return obs_fresh(self._obs, self.entity_description.max_age)

    @property
    def _obs(self):
        return self._observations().get(self.entity_description.key)

    def _observations(self) -> dict:
        return self.coordinator.data or {}

    @property
    def available(self) -> bool:
        if self._fresh():
            return super().available and self.native_value is not None
        return self._model_value() is not None

    @property
    def native_value(self) -> Any:
        obs = self._obs
        if obs is not None and self._fresh():
            return self.entity_description.value(obs.value)
        model = self._model_value()
        if model is not None:
            return self.entity_description.value(model)
        return self.entity_description.value(obs.value) if obs else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        obs = self._obs
        if not self._fresh() and self._model_value() is not None:
            # Shown as a reserve: the model's value, and when the station last measured.
            return {"kilde": "DMI-prognose (stationsmålinger forsinket)",
                    **({"sidst_målt": obs.observed.isoformat(), "station": obs.station_name or obs.station_id} if obs else {})}
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
    _fallback_keys: dict[str, str] = {}

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
        days, param, today = self.coordinator.data or {}, self.entity_description.parameter, dt_util.now().date()
        if self.entity_description.month_total:
            return month_sum(days, param, today)
        if self.entity_description.month_mean:
            return month_mean(days, param, today)
        value = self._day(0)
        if value is None and self.entity_description.latest:
            value = self._day(1)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        municipality = self.coordinator.municipality
        attrs = {"kilde": f"DMI klimadata, {municipality_name(municipality) or 'kommune'} ({municipality})"}
        if self.entity_description.latest:
            today = dt_util.now().date()
            attrs["dato"] = (today if self._day(0) is not None else today - timedelta(days=1)).isoformat()
        elif not (self.entity_description.month_total or self.entity_description.month_mean):
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


class _ForecastBase(CoordinatorEntity[EdrCoordinator], _Base):
    # The hourly rows are for charts; they are not kept in the history database.
    _unrecorded_attributes = frozenset({"timer"})

    def __init__(self, entry: DmiVejrConfigEntry, description: SensorEntityDescription) -> None:
        super().__init__(entry.runtime_data.edr)
        self._setup(entry, description)

    def _base_attrs(self, source: str) -> dict[str, Any]:
        return {"kilde": source, "beregnet": self.coordinator.data.fetched.isoformat()}


class BandSensor(_ForecastBase):
    """A next-day value from DMI's ensemble percentiles, with the hourly band for charts."""

    entity_description: BandSensorDescription

    @property
    def _band(self) -> dict[int, list] | None:
        data = self.coordinator.data
        return data.bands.get(self.entity_description.band) if data else None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        band = self._band
        if not band:
            return None
        now, how = dt_util.utcnow(), self.entity_description.how
        if how == "min10":
            return window_min(band.get(10, []), now, EDR_HOURS).value
        if how == "max90":
            return series_peak(band.get(90, []), now, EDR_HOURS).value
        if how == "max50":
            return series_peak(band.get(50, []), now, EDR_HOURS).value
        return window_sum(band.get(50, []), now, EDR_HOURS)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        band = self._band
        if not band:
            return None
        now = dt_util.utcnow()
        attrs = self._base_attrs("DMI HARMONIE DINI EPS (percentiler)")
        if self.entity_description.how == "sum50":
            attrs["op_til_90_procent"] = window_sum(band.get(90, []), now, EDR_HOURS)
            attrs["mindst_10_procent"] = window_sum(band.get(10, []), now, EDR_HOURS)
        else:
            attrs["median"] = (
                window_min(band.get(50, []), now, EDR_HOURS)
                if self.entity_description.how == "min10"
                else series_peak(band.get(50, []), now, EDR_HOURS)
            ).value
        attrs["timer"] = hourly_rows({"p10": band.get(10, []), "p50": band.get(50, []), "p90": band.get(90, [])},
                                     now, EDR_SERIES_HOURS)
        return attrs


class SeriesSensor(_ForecastBase):
    """The current HARMONIE DINI value, with the next hours for charts."""

    entity_description: SeriesSensorDescription

    @property
    def _series(self) -> list:
        data = self.coordinator.data
        return data.series.get(self.entity_description.series, []) if data else []

    @property
    def available(self) -> bool:
        return super().available and bool(window(self._series, dt_util.utcnow(), 1))

    @property
    def native_value(self) -> float | None:
        values = window(self._series, dt_util.utcnow(), 1)
        return round(values[0][1], 1) if values else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        now = dt_util.utcnow()
        top: Peak = series_peak(self._series, now, EDR_HOURS)
        low: Peak = window_min(self._series, now, EDR_HOURS)
        attrs = self._base_attrs("DMI HARMONIE DINI")
        attrs |= {
            "højeste_næste_døgn": None if top.value is None else round(top.value, 1),
            "højeste_tidspunkt": top.time.isoformat() if top.time else None,
            "laveste_næste_døgn": None if low.value is None else round(low.value, 1),
            "timer": hourly_rows({"v": self._series}, now, EDR_SERIES_HOURS),
        }
        return attrs


class SolarEnergySensor(_ForecastBase):
    """Sun energy on a flat surface over the next 24 hours (sum of hourly irradiance)."""

    def __init__(self, entry: DmiVejrConfigEntry) -> None:
        super().__init__(entry, SOLAR_ENERGY)

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        total = window_sum(data.series.get("radiation", []), dt_util.utcnow(), EDR_HOURS) if data else None
        return None if total is None else round(total / 1000, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self._base_attrs("DMI HARMONIE DINI") if self.coordinator.data else None


class SurgeSensor(CoordinatorEntity[OceanCoordinator], _Base):
    """DMI's storm surge model (DKSS) at the harbour: the water level now and ahead."""

    _unrecorded_attributes = frozenset({"timer"})

    def __init__(self, entry: DmiVejrConfigEntry) -> None:
        super().__init__(entry.runtime_data.ocean)
        self._setup(entry, SURGE)

    @property
    def _surge(self) -> list:
        return self.coordinator.data.surge if self.coordinator.data else []

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        values = window(self._surge, dt_util.utcnow(), 1)
        return values[0][1] if values else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None or not data.surge:
            return None
        now = dt_util.utcnow()
        top = series_peak(data.surge, now, DKSS_HOURS)
        low = window_min(data.surge, now, DKSS_HOURS)
        tide = data.tide
        rows = hourly_rows({"cm": data.surge}, now, DKSS_HOURS, 0)
        if tide and tide.series:
            # The astronomical tide for the same hours (DMI tide table), for comparison.
            for row in rows:
                when = datetime.fromisoformat(row["t"])
                nearest = min(tide.series, key=lambda tv: abs(tv[0] - when))
                if abs(nearest[0] - when) <= timedelta(minutes=30):
                    row["tidevand"] = round(nearest[1])
        return {
            "højeste_næste_48_timer": top.value,
            "højeste_tidspunkt": top.time.isoformat() if top.time else None,
            "laveste_næste_48_timer": low.value,
            "laveste_tidspunkt": low.time.isoformat() if low.time else None,
            "station": (tide.station_name or tide.station_id) if tide else None,
            "modelkørsel": data.surge_run.isoformat() if data.surge_run else None,
            "kilde": "DMI stormflodsmodel DKSS (indre danske farvande)",
            "timer": rows,
        }
