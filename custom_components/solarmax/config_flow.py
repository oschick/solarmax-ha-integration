"""Config, options, and inverter subentry flows for Solarmax."""

from __future__ import annotations

import asyncio
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
    inverter_subentries,
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
            await self._validate_reconfigured_endpoint(entry, host, port)
        # Release the handoff before unload closes the runtime.
        if find_endpoint_conflict(
            self.hass, host, port, exclude_entry_id=entry.entry_id
        ):
            return self.async_abort(reason="already_configured")
        # The title tracks the host only while the user never renamed it.
        title = host if entry.title == entry.data[CONF_HOST] else entry.title
        await async_apply_and_reload(
            self.hass,
            entry,
            # Merge, never replace: legacy address/device_name in data and the
            # twilight/night-keep options must survive until migration runs.
            data=dict(entry.data) | {CONF_HOST: host, CONF_PORT: port},
            options=dict(entry.options),
            title=title,
            unique_id=endpoint_unique_id(host, port),
        )
        return self.async_abort(reason="reconfigure_successful")

    async def _validate_reconfigured_endpoint(
        self, entry: ConfigEntry, host: str, port: int
    ) -> None:
        """Probe the candidate endpoint, covering a not-yet-migrated entry.

        A migrated entry probes its inverter subentries. A legacy entry that
        has not reached version 3 yet has no subentries but still carries its
        single inverter address in data, so that address is probed instead of
        probing nothing.
        """
        if not inverter_subentries(entry) and CONF_ADDRESS in entry.data:
            await validate_connection(
                host=host,
                port=port,
                address=int(entry.data[CONF_ADDRESS]),
                verify_checksum=entry_option(
                    entry, CONF_VERIFY_CHECKSUM, DEFAULT_VERIFY_CHECKSUM
                ),
                response_timeout=entry_option(
                    entry, CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT
                ),
            )
            return
        await validate_endpoint(entry, host, port)


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
                # Merge, never replace: a not-yet-migrated entry keeps its
                # legacy twilight/night-keep options until migration removes them.
                merged_options = dict(entry.options) | user_input
                try:
                    await async_apply_and_reload(
                        self.hass,
                        entry,
                        data=dict(entry.data),
                        options=merged_options,
                        title=entry.title,
                        unique_id=entry.unique_id,
                    )
                except EntryReloadError:
                    errors["base"] = "reload_failed"
                else:
                    return self.async_create_entry(title="", data=merged_options)

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
                if await self._try_probe(entry, address, errors):
                    if find_address_conflict(entry, address) is not None:
                        return self.async_abort(reason="already_configured")
                    result = self.async_create_entry(
                        title=user_input[CONF_DEVICE_NAME],
                        data=user_input,
                        unique_id=str(address),
                    )
                    self._schedule_reload_after_commit(entry, address)
                    return result

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
                    await self._try_probe(entry, address, errors)
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
                    # A not-loaded entry has no fingerprint listener to pick up
                    # an address/preference change, so reload it here as well.
                    self._schedule_reload_after_commit(entry, address)
                    return result

        values = dict(subentry.data) if user_input is None else user_input
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_inverter_schema(values),
            errors=errors,
        )

    async def _try_probe(
        self, entry: ConfigEntry, address: int, errors: dict[str, str]
    ) -> bool:
        """Probe an address through the handoff, mapping failures to errors.

        Returns True when the address answered. Shared by the add and
        reconfigure steps.
        """
        try:
            async with validation_handoff(entry):
                await self._probe(entry, address)
        except CannotConnect:
            errors["base"] = "cannot_connect"
            return False
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
            return False
        return True

    def _schedule_reload_after_commit(self, entry: ConfigEntry, address: int) -> None:
        """Reload a not-loaded entry once the manager has committed the subentry.

        A subentry flow's result is committed by the subentry manager after the
        step returns, so an idle or failed entry (which has no fingerprint
        listener to notice the change) is reloaded from a deferred task that
        waits for the commit, verifies the subentry exists, then reloads. A
        loaded entry relies on the fingerprint listener instead.
        """
        if entry.state is ConfigEntryState.LOADED or not entry.state.recoverable:
            return

        async def _reload_when_committed() -> None:
            # Two yields let the subentry manager's async_finish_flow commit
            # the subentry before the reload rebuilds the coordinator.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            if any(
                subentry.unique_id == str(address)
                for subentry in entry.subentries.values()
            ):
                self.hass.config_entries.async_schedule_reload(entry.entry_id)

        self.hass.async_create_task(
            _reload_when_committed(), f"reload Solarmax entry {entry.entry_id}"
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
