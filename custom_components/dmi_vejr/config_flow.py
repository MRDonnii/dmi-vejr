"""Config flow for DMI Vejr."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MUNICIPALITY,
    CONF_WARNING_AREA,
    DEFAULT_MUNICIPALITY,
    DEFAULT_WARNING_AREA,
    DOMAIN,
    NAME,
)


class DmiVejrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up DMI Vejr for a location (default: home)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=NAME, data=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_LATITUDE, default=self.hass.config.latitude): cv.latitude,
                vol.Required(CONF_LONGITUDE, default=self.hass.config.longitude): cv.longitude,
                vol.Required(CONF_MUNICIPALITY, default=DEFAULT_MUNICIPALITY): str,
                vol.Required(CONF_WARNING_AREA, default=DEFAULT_WARNING_AREA): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
