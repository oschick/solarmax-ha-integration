"""Config flow for Solarmax Inverter integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .connection import LinkClosed, LinkTimeout, SolarmaxLink
from .const import (
    CONF_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_NIGHT_KEEP_VALUES,
    CONF_PORT,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    DEFAULT_ADDRESS,
    DEFAULT_DEVICE_NAME,
    DEFAULT_NIGHT_KEEP_VALUES,
    DEFAULT_PORT,
    DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VERIFY_CHECKSUM,
    DOMAIN,
)
from .protocol import build_request

_LOGGER = logging.getLogger(__name__)

# Default field values for a fresh config entry. The options flow overlays the
# entry's current values on top of these before building its schema.
_DEFAULT_VALUES: dict[str, Any] = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: DEFAULT_PORT,
    CONF_ADDRESS: DEFAULT_ADDRESS,
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
    CONF_DEVICE_NAME: DEFAULT_DEVICE_NAME,
    CONF_VERIFY_CHECKSUM: DEFAULT_VERIFY_CHECKSUM,
    CONF_TWILIGHT_ELEVATION_THRESHOLD: DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_NIGHT_KEEP_VALUES: DEFAULT_NIGHT_KEEP_VALUES,
}


def _build_schema(values: dict[str, Any]) -> vol.Schema:
    """Build the shared config/options schema, pre-filled with the given values."""
    return vol.Schema(
        {
            vol.Required(
                CONF_HOST, description={"suggested_value": values[CONF_HOST]}
            ): str,
            vol.Required(CONF_PORT, default=values[CONF_PORT]): vol.Coerce(int),
            vol.Optional(CONF_ADDRESS, default=values[CONF_ADDRESS]): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=249)
            ),
            vol.Optional(
                CONF_UPDATE_INTERVAL, default=values[CONF_UPDATE_INTERVAL]
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            vol.Optional(CONF_DEVICE_NAME, default=values[CONF_DEVICE_NAME]): str,
            vol.Optional(
                CONF_VERIFY_CHECKSUM, default=values[CONF_VERIFY_CHECKSUM]
            ): bool,
            vol.Optional(
                CONF_NIGHT_KEEP_VALUES, default=values[CONF_NIGHT_KEEP_VALUES]
            ): bool,
            vol.Optional(
                CONF_TWILIGHT_ELEVATION_THRESHOLD,
                default=values[CONF_TWILIGHT_ELEVATION_THRESHOLD],
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=90)),
        }
    )


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from the config schema with values provided by the user.
    A one-shot PAC probe over a throwaway link; the `finally` close is a hard
    invariant — a leaked probe socket locks the single-client inverter out
    for ~128s, which would fail the very next setup attempt.
    """
    link = SolarmaxLink(data[CONF_HOST], data[CONF_PORT])
    try:
        address = data.get(CONF_ADDRESS, DEFAULT_ADDRESS)
        await link.request(build_request(address, ["PAC"]))
    except (LinkTimeout, LinkClosed, OSError) as err:
        raise CannotConnect from err
    finally:
        await link.close()

    # Return info that you want to store in the config entry.
    return {"title": data[CONF_DEVICE_NAME]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Solarmax Inverter."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check for duplicate entries
            await self.async_set_unique_id(
                f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
            )
            self._abort_if_unique_id_configured()

            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(_DEFAULT_VALUES),
            errors=errors,
        )


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Solarmax Inverter."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options.

        Finding 1/13: unlike the initial config flow, this does NOT probe
        the inverter. The running coordinator's engine already holds the
        device's single client slot, so a second connection opened here
        would always fail cannot_connect (or always fail at night) —
        making the options flow permanently unsaveable. The engine itself
        is the ongoing connectivity proof; a wrong edit still surfaces
        within one poll after reload. Only the schema is validated, which
        the flow manager already does before this step runs.
        """
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=user_input,
                title=user_input.get(CONF_DEVICE_NAME, self.config_entry.title),
            )

            # Trigger a reload of the integration to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="", data={})

        # Pre-populate the shared schema with the entry's current values.
        current_data = self.config_entry.data
        values = {
            key: current_data.get(key, default)
            for key, default in _DEFAULT_VALUES.items()
        }

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(values),
            description_placeholders={
                "current_host": current_data.get(CONF_HOST, "Unknown"),
                "current_port": str(current_data.get(CONF_PORT, DEFAULT_PORT)),
            },
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
