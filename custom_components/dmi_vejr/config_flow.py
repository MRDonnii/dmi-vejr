"""Config flow for DMI Vejr.

The place is an address (looked up in OpenStreetMap) or a pin on the map
(default: home). The municipality for DMI's climate data and the warning
region follow the place unless chosen by hand. "Configure" changes them later.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    LocationSelector,
    LocationSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_ADDRESS,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_MUNICIPALITY,
    CONF_WARNING_AREA,
    DOMAIN,
    NAME,
)
from .places import (
    MAX_DISTANCE_KM,
    MUNICIPALITIES,
    WARNING_REGIONS,
    entry_settings,
    municipality_by_name,
    nearest_municipality,
    warning_region,
)

AUTO = "auto"
GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
# OpenStreetMap's usage policy asks for an identifying User-Agent.
USER_AGENT = "HomeAssistant-DMI-Vejr (+https://github.com/MRDonnii/dmi-vejr)"
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class CannotConnect(Exception):
    """OpenStreetMap did not answer."""


async def _nominatim(hass: HomeAssistant, url: str, params: dict[str, Any]) -> Any:
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            url,
            params={"format": "jsonv2", "addressdetails": 1, **params},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "da"},
            timeout=_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
        raise CannotConnect from err


async def geocode(hass: HomeAssistant, address: str) -> tuple[float, float, str, str | None] | None:
    """(lat, lon, display name, municipality name) of a Danish address, or None."""
    found = await _nominatim(hass, GEOCODE_URL, {"q": address, "countrycodes": "dk", "limit": 1})
    if not found:
        return None
    hit = found[0]
    return (
        float(hit["lat"]),
        float(hit["lon"]),
        hit.get("display_name") or address,
        (hit.get("address") or {}).get("municipality"),
    )


async def reverse_municipality(hass: HomeAssistant, lat: float, lon: float) -> str | None:
    """Municipality name at a point, or None when OpenStreetMap does not know."""
    try:
        hit = await _nominatim(hass, REVERSE_URL, {"lat": lat, "lon": lon, "zoom": 10})
    except CannotConnect:
        return None
    return (hit.get("address") or {}).get("municipality") if isinstance(hit, dict) else None


def _schema(
    defaults: Mapping[str, Any], lat: float, lon: float, address: str = ""
) -> vol.Schema:
    municipalities = [SelectOptionDict(value=AUTO, label="Automatisk (følger placeringen)")] + [
        SelectOptionDict(value=code, label=f"{name} ({code})")
        for code, name, *_ in sorted(MUNICIPALITIES, key=lambda m: m[1])
    ]
    regions = [SelectOptionDict(value=AUTO, label="Automatisk (følger kommunen)")] + [
        SelectOptionDict(value=code, label=f"{name} ({code})")
        for code, name in WARNING_REGIONS.items()
    ]
    return vol.Schema(
        {
            vol.Optional(CONF_ADDRESS, description={"suggested_value": address}): TextSelector(),
            vol.Required(
                CONF_LOCATION, default={"latitude": lat, "longitude": lon}
            ): LocationSelector(LocationSelectorConfig(radius=False)),
            vol.Required(
                CONF_MUNICIPALITY, default=defaults.get(CONF_MUNICIPALITY, AUTO)
            ): SelectSelector(
                SelectSelectorConfig(options=municipalities, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(
                CONF_WARNING_AREA, default=defaults.get(CONF_WARNING_AREA, AUTO)
            ): SelectSelector(
                SelectSelectorConfig(options=regions, mode=SelectSelectorMode.DROPDOWN)
            ),
        }
    )


async def resolve(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None, dict[str, str]]:
    """Settings from the form: (settings, title, errors)."""
    address = (user_input.get(CONF_ADDRESS) or "").strip()
    location = user_input.get(CONF_LOCATION) or {}
    title: str | None = None
    osm_municipality: str | None = None
    if address:
        try:
            found = await geocode(hass, address)
        except CannotConnect:
            return None, None, {"base": "cannot_connect"}
        if found is None:
            return None, None, {CONF_ADDRESS: "address_not_found"}
        lat, lon, _, osm_municipality = found
        title = address
    else:
        lat, lon = float(location["latitude"]), float(location["longitude"])
    nearest, km = nearest_municipality(lat, lon)
    if km > MAX_DISTANCE_KM:
        return None, None, {"base": "outside_denmark"}

    municipality = user_input.get(CONF_MUNICIPALITY, AUTO)
    if municipality == AUTO:
        if not address:
            osm_municipality = await reverse_municipality(hass, lat, lon)
        municipality = municipality_by_name(osm_municipality) or nearest
    area = user_input.get(CONF_WARNING_AREA, AUTO)
    if area == AUTO:
        area = warning_region(municipality) or "DK004"
    settings = {
        CONF_LATITUDE: round(lat, 5),
        CONF_LONGITUDE: round(lon, 5),
        CONF_MUNICIPALITY: municipality,
        CONF_WARNING_AREA: area,
        CONF_ADDRESS: address or None,
    }
    return settings, title, {}


class DmiVejrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up DMI Vejr for an address or a place on the map (default: home)."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DmiVejrOptionsFlow:
        return DmiVejrOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            settings, title, errors = await resolve(self.hass, user_input)
            if settings is not None:
                return self.async_create_entry(title=title or NAME, data=settings)
        lat, lon = self.hass.config.latitude, self.hass.config.longitude
        if user_input and CONF_LOCATION in user_input:
            lat, lon = user_input[CONF_LOCATION]["latitude"], user_input[CONF_LOCATION]["longitude"]
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}, lat, lon, (user_input or {}).get(CONF_ADDRESS, "")),
            errors=errors,
        )


class DmiVejrOptionsFlow(OptionsFlowWithReload):
    """Change the place, municipality or warning region; the entry reloads."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = entry_settings(self.config_entry)
        if user_input is not None:
            settings, title, errors = await resolve(self.hass, user_input)
            if settings is not None:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, title=title or NAME
                )
                return self.async_create_entry(data=settings)
        lat = (user_input or {}).get(CONF_LOCATION, {}).get("latitude", current[CONF_LATITUDE])
        lon = (user_input or {}).get(CONF_LOCATION, {}).get("longitude", current[CONF_LONGITUDE])
        # The dropdowns open on "automatic" so a new place brings its own
        # municipality and region; a choice made by hand is kept when the form
        # is shown again after an error.
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                user_input or {}, lat, lon, (user_input or {}).get(CONF_ADDRESS, "")
            ),
            errors=errors,
        )
