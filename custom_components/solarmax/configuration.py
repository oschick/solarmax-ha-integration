"""Config entry storage helpers for Solarmax."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    DEFAULT_NIGHT_KEEP_VALUES,
    DEFAULT_PORT,
    DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VERIFY_CHECKSUM,
    DOMAIN,
)
from .protocol import ProtocolError, build_request, parse_response

_CONFIGURATION_LOCK = "configuration_mutation_lock"

CONNECTION_KEYS = (CONF_HOST, CONF_PORT, CONF_ADDRESS, CONF_DEVICE_NAME)
OPTION_KEYS = (
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_NIGHT_KEEP_VALUES,
)
OPTION_DEFAULTS = {
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM: DEFAULT_VERIFY_CHECKSUM,
    CONF_TWILIGHT_ELEVATION_THRESHOLD: DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_NIGHT_KEEP_VALUES: DEFAULT_NIGHT_KEEP_VALUES,
}


class CannotConnect(HomeAssistantError):
    """The selected endpoint did not return a valid PAC response."""


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


async def validate_connection(
    *, host: str, port: int, address: int, verify_checksum: bool
) -> None:
    """Validate an endpoint with a short PAC request."""
    link = SolarmaxLink(host, port)
    try:
        raw = await link.request(build_request(address, ["PAC"]))
        parse_response(raw, verify_checksum)
    except (LinkTimeout, LinkClosed, ProtocolError, OSError) as err:
        raise CannotConnect from err
    finally:
        await link.close()


def split_entry_input(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split config entry input into connection data and preference options."""
    return (
        {key: values[key] for key in CONNECTION_KEYS},
        {key: values[key] for key in OPTION_KEYS},
    )


def entry_option(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return an option, falling back to legacy config entry data."""
    return entry.options.get(key, entry.data.get(key, default))


def endpoint_unique_id(host: str, port: int, address: int) -> str:
    """Return the stable unique ID for an inverter endpoint."""
    return f"{host}:{port}:{address}"
