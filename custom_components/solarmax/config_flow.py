"""Config flow for Solarmax Inverter integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_DEVICE_NAME,
    DEFAULT_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .solarmax_api import SolarmaxAPI

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, description={"suggested_value": "192.168.1.100"}): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT, description={"suggested_value": DEFAULT_PORT}): vol.Coerce(int),
        vol.Optional(
            CONF_UPDATE_INTERVAL, 
            default=DEFAULT_UPDATE_INTERVAL,
            description={"suggested_value": DEFAULT_UPDATE_INTERVAL}
        ): vol.Coerce(int),
        vol.Optional(
            CONF_DEVICE_NAME, 
            default=DEFAULT_DEVICE_NAME,
            description={"suggested_value": DEFAULT_DEVICE_NAME}
        ): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    api = SolarmaxAPI(data[CONF_HOST], data[CONF_PORT])

    # Test the connection
    if not await hass.async_add_executor_job(api.test_connection):
        raise CannotConnect

    # Return info that you want to store in the config entry.
    return {"title": data[CONF_DEVICE_NAME]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Solarmax Inverter."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            # Check for duplicate entries
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", 
            data_schema=STEP_USER_DATA_SCHEMA, 
            errors=errors,
            description_placeholders={
                "host": "IP address of your Solarmax inverter",
                "port": "Communication port (usually 12345)",
                "update_interval": "How often to poll for data (seconds)",
                "device_name": "Friendly name for this inverter"
            }
        )


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Solarmax Inverter."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Validate the new configuration
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during reconfiguration")
                errors["base"] = "unknown"
            else:
                # Update the config entry with new data
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=user_input,
                    title=user_input.get(CONF_DEVICE_NAME, self.config_entry.title),
                )

                # Trigger a reload of the integration to apply changes
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(title="", data={})

        # Pre-populate form with current values
        current_data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=current_data.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_PORT, default=current_data.get(CONF_PORT, DEFAULT_PORT)
                ): vol.Coerce(int),
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=current_data.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ): vol.Coerce(int),
                vol.Optional(
                    CONF_DEVICE_NAME,
                    default=current_data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "current_host": current_data.get(CONF_HOST, "Unknown"),
                "current_port": str(current_data.get(CONF_PORT, DEFAULT_PORT)),
            },
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
