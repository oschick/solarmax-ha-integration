"""Config entry storage helpers for Solarmax."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry

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
    DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VERIFY_CHECKSUM,
)

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
