"""'Raining now' from DMI radar."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from . import DmiVejrConfigEntry
from .const import ATTRIBUTION, RAIN_NOW_MM_H
from .coordinator import RadarCoordinator, WarningsCoordinator
from .entity import device_info, radar_fresh


async def async_setup_entry(
    hass: HomeAssistant, entry: DmiVejrConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([RainingNow(entry), WarningActive(entry)])


class RainingNow(CoordinatorEntity[RadarCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Regner nu"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_attribution = ATTRIBUTION

    def __init__(self, entry: DmiVejrConfigEntry) -> None:
        super().__init__(entry.runtime_data.radar)
        self._attr_unique_id = f"{entry.entry_id}_raining_now"
        self._attr_device_info = device_info(entry.entry_id)

    @property
    def available(self) -> bool:
        return super().available and radar_fresh(self.coordinator.data.sample)

    @property
    def is_on(self) -> bool:
        return (self.coordinator.data.sample.rate_mm_h or 0) >= RAIN_NOW_MM_H


class WarningActive(CoordinatorEntity[WarningsCoordinator], BinarySensorEntity):
    """On while a DMI warning (yellow or higher) is in force for the area."""

    _attr_has_entity_name = True
    _attr_name = "Varsel aktivt"
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_attribution = ATTRIBUTION

    def __init__(self, entry: DmiVejrConfigEntry) -> None:
        super().__init__(entry.runtime_data.warnings)
        self._attr_unique_id = f"{entry.entry_id}_warning_active"
        self._attr_device_info = device_info(entry.entry_id)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.active(dt_util.utcnow()))

    @property
    def extra_state_attributes(self):
        active = self.coordinator.data.active(dt_util.utcnow())
        return {
            "niveau": max((w.level for w in active), default=0),
            "varsler": [w.as_dict for w in active],
        }
