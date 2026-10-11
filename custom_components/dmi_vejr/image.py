"""Animated DMI radar map and EUMETSAT satellite map around the home."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DmiVejrConfigEntry
from .const import ATTRIBUTION, MAP_FRAMES, MAP_HALF_KM, SAT_ATTRIBUTION, SAT_FRAMES, SAT_HALF_KM
from .coordinator import RadarCoordinator, SatelliteCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: DmiVejrConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([RadarMap(hass, entry), SatelliteMap(hass, entry)])


class RadarMap(CoordinatorEntity[RadarCoordinator], ImageEntity):
    """Last hour of DMI radar, 130 x 130 km around the home, as an animated GIF."""

    _attr_has_entity_name = True
    _attr_name = "Radarkort"
    _attr_content_type = "image/gif"
    _attr_attribution = ATTRIBUTION

    def __init__(self, hass: HomeAssistant, entry: DmiVejrConfigEntry) -> None:
        CoordinatorEntity.__init__(self, entry.runtime_data.radar)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{entry.entry_id}_radar_map"
        self._attr_device_info = device_info(entry.entry_id)
        self._attr_image_last_updated = self.coordinator.data.map_updated
        self._attr_extra_state_attributes = {
            "billeder": MAP_FRAMES,
            "udsnit_km": int(MAP_HALF_KM * 2),
        }

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.map_gif is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = self.coordinator.data.map_updated
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        return self.coordinator.data.map_gif


class SatelliteMap(CoordinatorEntity[SatelliteCoordinator], ImageEntity):
    """Last two hours of EUMETSAT satellite pictures, 600 x 600 km, as animated WebP."""

    _attr_has_entity_name = True
    _attr_name = "Satellitkort"
    _attr_content_type = "image/webp"
    _attr_attribution = SAT_ATTRIBUTION

    def __init__(self, hass: HomeAssistant, entry: DmiVejrConfigEntry) -> None:
        CoordinatorEntity.__init__(self, entry.runtime_data.satellite)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{entry.entry_id}_satellite_map"
        self._attr_device_info = device_info(entry.entry_id)
        self._attr_image_last_updated = self._data_value("updated")
        self._attr_extra_state_attributes = {
            "billeder": SAT_FRAMES,
            "udsnit_km": int(SAT_HALF_KM * 2),
            "seneste_billede": None,
        }

    def _data_value(self, key: str):
        data = self.coordinator.data
        return getattr(data, key) if data is not None else None

    @property
    def available(self) -> bool:
        return super().available and self._data_value("image") is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = self._data_value("updated")
        latest = self._data_value("latest")
        self._attr_extra_state_attributes["seneste_billede"] = latest.isoformat() if latest else None
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        return self._data_value("image")
