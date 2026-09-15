"""Config entry storage helpers for Solarmax."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Self

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .connection import EngineState, LinkClosed, LinkTimeout, SolarmaxLink
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
    DEFAULT_NIGHT_KEEP_VALUES,
    DEFAULT_PORT,
    DEFAULT_RESPONSE_TIMEOUT,
    DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VERIFY_CHECKSUM,
    DOMAIN,
    MAX_RESPONSE_TIMEOUT,
    MIN_RESPONSE_TIMEOUT,
    SUBENTRY_TYPE_INVERTER,
)
from .protocol import ProtocolError, build_request, parse_response

_CONFIGURATION_LOCK = "configuration_mutation_lock"
_LOGGER = logging.getLogger(__name__)

TCP_PORT_SCHEMA = vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))
RESPONSE_TIMEOUT_SCHEMA = vol.All(
    vol.Coerce(float), vol.Range(min=MIN_RESPONSE_TIMEOUT, max=MAX_RESPONSE_TIMEOUT)
)
ADDRESS_SCHEMA = vol.All(vol.Coerce(int), vol.Range(min=1, max=249))
CONNECTION_KEYS = (CONF_HOST, CONF_PORT)
OPTION_KEYS = (
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    CONF_RESPONSE_TIMEOUT,
)
OPTION_DEFAULTS = {
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM: DEFAULT_VERIFY_CHECKSUM,
    CONF_RESPONSE_TIMEOUT: DEFAULT_RESPONSE_TIMEOUT,
}
INVERTER_KEYS = (
    CONF_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_NIGHT_KEEP_VALUES,
)
INVERTER_DEFAULTS = {
    CONF_TWILIGHT_ELEVATION_THRESHOLD: DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_NIGHT_KEEP_VALUES: DEFAULT_NIGHT_KEEP_VALUES,
}


class CannotConnect(HomeAssistantError):
    """The selected endpoint did not return a valid PAC response."""


class EntryReloadError(HomeAssistantError):
    """The new entry could not load and rollback was required."""


@dataclass(frozen=True)
class EntrySnapshot:
    """Entry values needed to undo a configuration change."""

    data: dict[str, Any]
    options: dict[str, Any]
    title: str
    unique_id: str | None

    @classmethod
    def capture(cls, entry: ConfigEntry) -> Self:
        """Copy persisted values before mutation."""
        return cls(dict(entry.data), dict(entry.options), entry.title, entry.unique_id)


@asynccontextmanager
async def validation_handoff(entry: ConfigEntry) -> AsyncIterator[None]:
    """Wait for setup, then release the runtime connection if one exists."""
    async with entry.setup_lock:
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            yield
            return
        async with runtime.validation_handoff():
            yield


@callback
def update_device_name(
    hass: HomeAssistant, identifier_id: str, device_name: str
) -> None:
    """Rename the device identified by (DOMAIN, identifier_id).

    A subentry ID from 1.5.0 on.
    """
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, identifier_id)})
    if device is not None:
        registry.async_update_device(device.id, name=device_name)


async def _reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        return await hass.config_entries.async_reload(entry.entry_id)
    except Exception:
        _LOGGER.exception("Failed to reload Solarmax entry %s", entry.entry_id)
        return False


async def _apply_reload_or_rollback(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    data: Mapping[str, Any],
    options: Mapping[str, Any],
    title: str,
    unique_id: str | None,
) -> None:
    previous = EntrySnapshot.capture(entry)
    previous_runtime = getattr(entry, "runtime_data", None)
    hass.config_entries.async_update_entry(
        entry, data=data, options=options, title=title, unique_id=unique_id
    )
    if entry.disabled_by is not None:
        return
    if await _reload_entry(hass, entry):
        return

    hass.config_entries.async_update_entry(
        entry,
        data=previous.data,
        options=previous.options,
        title=previous.title,
        unique_id=previous.unique_id,
    )
    old_runtime_survived = (
        previous_runtime is not None
        and getattr(entry, "runtime_data", None) is previous_runtime
    )
    if not old_runtime_survived and not await _reload_entry(hass, entry):
        raise EntryReloadError("new and restored entry setup failed")
    raise EntryReloadError("entry reload failed")


async def _await_atomic(task: asyncio.Task[None]) -> None:
    """Defer repeated caller cancellation until the child reaches stability."""
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.wait((task,))
        except asyncio.CancelledError as err:
            cancellation = cancellation or err
    try:
        task.result()
    except Exception:
        if cancellation is not None:
            raise cancellation from None
        raise
    if cancellation is not None:
        raise cancellation


async def async_apply_and_reload(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    data: Mapping[str, Any],
    options: Mapping[str, Any],
    title: str,
    unique_id: str | None,
) -> None:
    """Apply or restore entry values; caller holds configuration_mutation_lock."""
    transaction = hass.async_create_task(
        _apply_reload_or_rollback(
            hass, entry, data=data, options=options, title=title, unique_id=unique_id
        ),
        f"update Solarmax entry {entry.entry_id}",
    )
    await _await_atomic(transaction)


def configuration_mutation_lock(hass: HomeAssistant) -> asyncio.Lock:
    """Return the domain-scoped lock for configuration mutations."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    lock: asyncio.Lock = domain_data.setdefault(_CONFIGURATION_LOCK, asyncio.Lock())
    return lock


def find_endpoint_conflict(
    hass: HomeAssistant,
    host: str,
    port: int,
    *,
    exclude_entry_id: str | None = None,
) -> ConfigEntry | None:
    """Return an entry that already owns the host and port."""
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id != exclude_entry_id
            and entry.data.get(CONF_HOST) == host
            and entry.data.get(CONF_PORT, DEFAULT_PORT) == port
        ),
        None,
    )


def endpoint_unique_id(host: str, port: int) -> str:
    """Return the stable unique ID for a TCP endpoint shared by its inverters."""
    return f"{host}:{port}"


async def validate_connection(
    *,
    host: str,
    port: int,
    address: int,
    verify_checksum: bool,
    response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
) -> None:
    """Validate one inverter address with a short PAC request."""
    link = SolarmaxLink(host, port, response_timeout=response_timeout)
    try:
        raw = await link.request(build_request(address, ["PAC"]))
        parse_response(raw, verify_checksum, expected_address=address)
    except (LinkTimeout, LinkClosed, ProtocolError, OSError, UnicodeError) as err:
        raise CannotConnect from err
    finally:
        await link.close()


def split_entry_input(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Split setup input into endpoint data, global options, and inverter data."""
    return (
        {key: values[key] for key in CONNECTION_KEYS},
        {key: values[key] for key in OPTION_KEYS},
        {key: values[key] for key in INVERTER_KEYS},
    )


def entry_option(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return an option, falling back to legacy config entry data."""
    return entry.options.get(key, entry.data.get(key, default))


def subentry_option(subentry: ConfigSubentry, key: str, default: Any) -> Any:
    """Return a per-inverter preference stored in subentry data."""
    return subentry.data.get(key, default)


def inverter_subentries(entry: ConfigEntry) -> dict[str, ConfigSubentry]:
    """Return the entry's inverter subentries keyed by subentry ID."""
    return {
        subentry_id: subentry
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_TYPE_INVERTER
    }


def inverter_fingerprint(entry: ConfigEntry) -> frozenset[tuple[str, int, float, bool]]:
    """Runtime-relevant identity of the inverter set; a change needs a reload."""
    return frozenset(
        (
            subentry_id,
            int(subentry.data[CONF_ADDRESS]),
            float(
                subentry_option(
                    subentry,
                    CONF_TWILIGHT_ELEVATION_THRESHOLD,
                    DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
                )
            ),
            bool(
                subentry_option(
                    subentry, CONF_NIGHT_KEEP_VALUES, DEFAULT_NIGHT_KEEP_VALUES
                )
            ),
        )
        for subentry_id, subentry in inverter_subentries(entry).items()
    )


def find_address_conflict(
    entry: ConfigEntry, address: int, *, exclude_subentry_id: str | None = None
) -> ConfigSubentry | None:
    """Return the inverter subentry that already uses the address."""
    return next(
        (
            subentry
            for subentry_id, subentry in inverter_subentries(entry).items()
            if subentry_id != exclude_subentry_id
            and int(subentry.data[CONF_ADDRESS]) == address
        ),
        None,
    )


async def validate_endpoint(entry: ConfigEntry, host: str, port: int) -> None:
    """Probe a candidate endpoint with the entry's inverters.

    Every inverter that is not currently in fault must answer, because those
    prove the new host and port reach the same bus. Inverters already in
    fault are what the caller is trying to recover; a dead one must not make
    the endpoint uneditable, so their silence is tolerated. When every
    inverter is in fault, or no runtime exists, at least one must answer.
    Raises CannotConnect otherwise.
    """
    subentries = inverter_subentries(entry)
    if not subentries:
        return
    runtime = getattr(entry, "runtime_data", None)
    snapshots = getattr(runtime, "data", None)
    if snapshots is None:
        healthy: set[str] = set()
    else:
        healthy = {
            subentry_id
            for subentry_id in subentries
            if subentry_id not in snapshots
            or snapshots[subentry_id].state is not EngineState.OFFLINE_FAULT
        }
    verify_checksum = entry_option(entry, CONF_VERIFY_CHECKSUM, DEFAULT_VERIFY_CHECKSUM)
    response_timeout = entry_option(
        entry, CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT
    )
    answered = 0
    for subentry_id, subentry in subentries.items():
        try:
            await validate_connection(
                host=host,
                port=port,
                address=int(subentry.data[CONF_ADDRESS]),
                verify_checksum=verify_checksum,
                response_timeout=response_timeout,
            )
        except CannotConnect:
            if subentry_id in healthy:
                raise
            continue
        answered += 1
    if answered == 0:
        raise CannotConnect
