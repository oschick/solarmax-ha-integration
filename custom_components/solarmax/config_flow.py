"""Config, options, and inverter subentry flows for Solarmax."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback

from .configuration import (
    ADDRESS_SCHEMA,
    INVERTER_DEFAULTS,
    OPTION_DEFAULTS,
    RESPONSE_TIMEOUT_SCHEMA,
    TCP_PORT_SCHEMA,
    CannotConnect,
    EntryReloadError,
    async_apply_and_reload,
    configuration_mutation_lock,
    endpoint_unique_id,
    entry_option,
    find_address_conflict,
    find_endpoint_conflict,
    split_entry_input,
    update_device_name,
    validate_connection,
    validate_endpoint,
    validation_handoff,
)
from .const import (
    CONF_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_NIGHT_KEEP_VALUES,
    CONF_PORT,
    CONF_RESPONSE_TIMEOUT,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    DEFAULT_ADDRESS,
    DEFAULT_DEVICE_NAME,
    DEFAULT_PORT,
    DEFAULT_RESPONSE_TIMEOUT,
    DEFAULT_VERIFY_CHECKSUM,
    DOMAIN,
    SUBENTRY_TYPE_INVERTER,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_VALUES: dict[str, Any] = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: DEFAULT_PORT,
    CONF_ADDRESS: DEFAULT_ADDRESS,
    CONF_DEVICE_NAME: DEFAULT_DEVICE_NAME,
    **OPTION_DEFAULTS,
    **INVERTER_DEFAULTS,
}


def _inverter_fields(values: Mapping[str, Any]) -> dict[Any, Any]:
    """Schema fields shared by initial setup and the inverter subentry flow."""
    return {
        vol.Required(CONF_ADDRESS, default=values[CONF_ADDRESS]): ADDRESS_SCHEMA,
        vol.Required(CONF_DEVICE_NAME, default=values[CONF_DEVICE_NAME]): str,
        vol.Optional(
            CONF_TWILIGHT_ELEVATION_THRESHOLD,
            default=values[CONF_TWILIGHT_ELEVATION_THRESHOLD],
        ): vol.All(vol.Coerce(float), vol.Range(min=0, max=90)),
        vol.Optional(
            CONF_NIGHT_KEEP_VALUES, default=values[CONF_NIGHT_KEEP_VALUES]
        ): bool,
    }


def _option_fields(values: Mapping[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(
            CONF_UPDATE_INTERVAL, default=values[CONF_UPDATE_INTERVAL]
        ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
        vol.Optional(CONF_VERIFY_CHECKSUM, default=values[CONF_VERIFY_CHECKSUM]): bool,
        vol.Optional(
            CONF_RESPONSE_TIMEOUT, default=values[CONF_RESPONSE_TIMEOUT]
        ): RESPONSE_TIMEOUT_SCHEMA,
    }


def _build_schema(values: Mapping[str, Any]) -> vol.Schema:
    """Initial setup: endpoint, global options, and the first inverter."""
    return vol.Schema(
        {
            vol.Required(
                CONF_HOST, description={"suggested_value": values[CONF_HOST]}
            ): str,
            vol.Required(CONF_PORT, default=values[CONF_PORT]): TCP_PORT_SCHEMA,
            **_inverter_fields(values),
            **_option_fields(values),
        }
    )


def _inverter_schema(values: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(_inverter_fields(values))


def _build_options_schema(values: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(_option_fields(values))


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Solarmax endpoint."""

    VERSION = 3
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Inverters are added and edited as subentries."""
        return {SUBENTRY_TYPE_INVERTER: InverterSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the endpoint entry with its first inverter."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data, options, inverter = split_entry_input(user_input)
            host = data[CONF_HOST]
            port = data[CONF_PORT]

            async with configuration_mutation_lock(self.hass):
                if find_endpoint_conflict(self.hass, host, port) is not None:
                    return self.async_abort(reason="already_configured")
                await self.async_set_unique_id(endpoint_unique_id(host, port))
                self._abort_if_unique_id_configured()
                try:
                    await validate_connection(
                        host=host,
                        port=port,
                        address=inverter[CONF_ADDRESS],
                        verify_checksum=options[CONF_VERIFY_CHECKSUM],
                        response_timeout=options[CONF_RESPONSE_TIMEOUT],
                    )
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"
                else:
                    if find_endpoint_conflict(self.hass, host, port) is not None:
                        return self.async_abort(reason="already_configured")
                    return self.async_create_entry(
                        title=host,
                        data=data,
                        options=options,
                        subentries=[
                            ConfigSubentryData(
                                data=inverter,
                                subentry_type=SUBENTRY_TYPE_INVERTER,
                                title=inverter[CONF_DEVICE_NAME],
                                unique_id=str(inverter[CONF_ADDRESS]),
                            )
                        ],
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(_DEFAULT_VALUES),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and atomically replace the endpoint."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            async with configuration_mutation_lock(self.hass):
                entry = self._get_reconfigure_entry()
                try:
                    return await self._async_reconfigure(entry, user_input)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except EntryReloadError:
                    errors["base"] = "reload_failed"

        values = dict(entry.data) if user_input is None else user_input
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=values[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=values[CONF_PORT]): TCP_PORT_SCHEMA,
                }
            ),
            errors=errors,
        )

    async def _async_reconfigure(
        self, entry: ConfigEntry, values: dict[str, Any]
    ) -> ConfigFlowResult:
        """Apply a submitted endpoint change while the mutation lock is held."""
        host, port = values[CONF_HOST], values[CONF_PORT]
        if (host, port) == (entry.data[CONF_HOST], entry.data[CONF_PORT]):
            return self.async_abort(reason="reconfigure_successful")
        if find_endpoint_conflict(
            self.hass, host, port, exclude_entry_id=entry.entry_id
        ):
            return self.async_abort(reason="already_configured")
        async with validation_handoff(entry):
            await validate_endpoint(entry, host, port)
        # Release the handoff before unload closes the runtime.
        if find_endpoint_conflict(
            self.hass, host, port, exclude_entry_id=entry.entry_id
        ):
            return self.async_abort(reason="already_configured")
        await async_apply_and_reload(
            self.hass,
            entry,
            data={CONF_HOST: host, CONF_PORT: port},
            options=entry.options,
            title=entry.title,
            unique_id=endpoint_unique_id(host, port),
        )
        return self.async_abort(reason="reconfigure_successful")


class OptionsFlow(config_entries.OptionsFlow):
    """Global polling preferences for the endpoint."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update settings without opening a second inverter connection."""
        errors: dict[str, str] = {}
        if user_input is not None:
            async with configuration_mutation_lock(self.hass):
                entry = self.config_entry
                options = dict(entry.options)
                if user_input == options:
                    return self.async_create_entry(title="", data=None)  # type: ignore[arg-type]
                try:
                    await async_apply_and_reload(
                        self.hass,
                        entry,
                        data=dict(entry.data),
                        options=user_input,
                        title=entry.title,
                        unique_id=entry.unique_id,
                    )
                except EntryReloadError:
                    errors["base"] = "reload_failed"
                else:
                    return self.async_create_entry(title="", data=user_input)

        values = {
            key: entry_option(self.config_entry, key, default)
            for key, default in OPTION_DEFAULTS.items()
        }
        if user_input is not None:
            values = user_input

        return self.async_show_form(
            step_id="init",
            data_schema=_build_options_schema(values),
            errors=errors,
        )


class InverterSubentryFlow(ConfigSubentryFlow):
    """Add or edit one inverter behind the endpoint."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Probe a new address through the runtime handoff, then add it."""
        entry = self._get_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            async with configuration_mutation_lock(self.hass):
                if find_address_conflict(entry, address) is not None:
                    return self.async_abort(reason="already_configured")
                try:
                    async with validation_handoff(entry):
                        await self._probe(entry, address)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"
                else:
                    if find_address_conflict(entry, address) is not None:
                        return self.async_abort(reason="already_configured")
                    if entry.state is not ConfigEntryState.LOADED:
                        # An idle or failed entry has no update listener to
                        # notice the new inverter.
                        self.hass.config_entries.async_schedule_reload(entry.entry_id)
                    return self.async_create_entry(
                        title=user_input[CONF_DEVICE_NAME],
                        data=user_input,
                        unique_id=str(address),
                    )

        values = _DEFAULT_VALUES if user_input is None else user_input
        return self.async_show_form(
            step_id="user", data_schema=_inverter_schema(values), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit name, preferences, or address of an existing inverter."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            name = user_input[CONF_DEVICE_NAME]
            async with configuration_mutation_lock(self.hass):
                address_changed = address != int(subentry.data[CONF_ADDRESS])
                if address_changed:
                    if (
                        find_address_conflict(
                            entry, address, exclude_subentry_id=subentry.subentry_id
                        )
                        is not None
                    ):
                        return self.async_abort(reason="already_configured")
                    try:
                        async with validation_handoff(entry):
                            await self._probe(entry, address)
                    except CannotConnect:
                        errors["base"] = "cannot_connect"
                    except Exception:
                        _LOGGER.exception("Unexpected exception")
                        errors["base"] = "unknown"
                if not errors:
                    renamed = name != subentry.title
                    # Persist first: the repair text is rendered from titles.
                    result = self.async_update_and_abort(
                        entry,
                        subentry,
                        data=user_input,
                        title=name,
                        unique_id=str(address),
                    )
                    if renamed:
                        update_device_name(self.hass, subentry.subentry_id, name)
                        runtime = getattr(entry, "runtime_data", None)
                        if runtime is not None:
                            runtime.async_refresh_repair_issue()
                    return result

        values = dict(subentry.data) if user_input is None else user_input
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_inverter_schema(values),
            errors=errors,
        )

    async def _probe(self, entry: ConfigEntry, address: int) -> None:
        await validate_connection(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            address=address,
            verify_checksum=entry_option(
                entry, CONF_VERIFY_CHECKSUM, DEFAULT_VERIFY_CHECKSUM
            ),
            response_timeout=entry_option(
                entry, CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT
            ),
        )
