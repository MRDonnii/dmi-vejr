"""DMI Vejr: DMI radar, stations, lightning and HARMONIE forecast.

Private integration for this installation. Everything weather-related comes
from DMI open data: radar (500 m composite every 5 minutes) for "raining now"
and an animated radar map with DMI lightning, the nearest DMI stations for
every measured value they report, DMI lightning detection, DMI climate data
for the municipality (today, yesterday, this month), water level, water
temperature and tide at the nearest harbour with DMI's storm surge forecast
(DKSS), DMI's official warnings (via MeteoAlarm), DMI's forecast API for the
ensemble (all its probabilities: frost, rain, cloudburst, snow, fog, storm,
hurricane; and its percentiles as a spread for temperature, wind, rain and
snow), more from HARMONIE DINI (cloud base and layers, freezing level, thunder
energy, sun, visibility), and DMI HARMONIE DINI (via Open-Meteo) for the
forecast, plus an animated satellite map from EUMETSAT (DMI has no
satellite pictures in its open data). The weather entity reports measured values when they are fresh
and follows the radar for the current condition.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import (
    ClimateCoordinator,
    EdrCoordinator,
    ForecastCoordinator,
    LightningCoordinator,
    ObservationCoordinator,
    OceanCoordinator,
    RadarCoordinator,
    SatelliteCoordinator,
    WarningsCoordinator,
)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.IMAGE, Platform.SENSOR, Platform.WEATHER]


@dataclass
class DmiVejrData:
    radar: RadarCoordinator
    forecast: ForecastCoordinator
    observations: ObservationCoordinator
    lightning: LightningCoordinator
    climate: ClimateCoordinator
    ocean: OceanCoordinator
    warnings: WarningsCoordinator
    edr: EdrCoordinator
    satellite: SatelliteCoordinator


type DmiVejrConfigEntry = ConfigEntry[DmiVejrData]


async def async_setup_entry(hass: HomeAssistant, entry: DmiVejrConfigEntry) -> bool:
    data = DmiVejrData(
        RadarCoordinator(hass, entry),
        ForecastCoordinator(hass, entry),
        ObservationCoordinator(hass, entry),
        LightningCoordinator(hass, entry),
        ClimateCoordinator(hass, entry),
        OceanCoordinator(hass, entry),
        WarningsCoordinator(hass, entry),
        EdrCoordinator(hass, entry),
        SatelliteCoordinator(hass, entry),
    )
    data.radar.lightning = data.lightning
    # Stations and lightning are extras: start without them if DMI is slow.
    # Lightning goes first so the first radar map already shows strikes.
    await data.lightning.async_refresh()
    await data.radar.async_config_entry_first_refresh()
    await data.forecast.async_config_entry_first_refresh()
    await data.observations.async_refresh()
    # The rest are extras too; their entities stay unavailable until DMI answers.
    for extra in (data.warnings, data.climate, data.ocean):
        await extra.async_refresh()
    entry.runtime_data = data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # DMI's forecast API takes three spaced-out requests; start-up does not wait for them.
    entry.async_create_task(hass, data.edr.async_refresh(), "dmi_vejr forecast API first refresh")
    # The satellite map (12 pictures from EUMETSAT) is drawn after start-up;
    # its image entity is unavailable until then.
    entry.async_create_background_task(
        hass, data.satellite.async_refresh(), "dmi_vejr satellite first refresh"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DmiVejrConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
