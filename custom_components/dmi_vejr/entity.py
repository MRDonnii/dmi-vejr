"""Shared helpers for DMI Vejr entities."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
import homeassistant.util.dt as dt_util

from .const import DOMAIN, NAME, OBS_MAX_AGE, RADAR_MAX_AGE
from .observations import Observation
from .radar import RadarSample


def device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=NAME,
        manufacturer="DMI",
        model="Radar, stationer, lyn, klima, hav, varsler og HARMONIE",
        entry_type=DeviceEntryType.SERVICE,
    )


def radar_fresh(sample: RadarSample | None) -> bool:
    """True when the radar sample covers the location and is recent."""
    return (
        sample is not None
        and sample.covered
        and dt_util.utcnow() - sample.time <= RADAR_MAX_AGE
    )


def obs_fresh(obs: Observation | None, max_age: timedelta = OBS_MAX_AGE) -> bool:
    return obs is not None and dt_util.utcnow() - obs.observed <= max_age
