"""Diagnostics support for Solarmax integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PORT
from .coordinator import SolarmaxCoordinator

REDACT_KEYS = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SolarmaxCoordinator = entry.runtime_data

    # Collect all diagnostic data
    diagnostics_data = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "domain": entry.domain,
            "title": entry.title,
            "data": async_redact_data(entry.data, REDACT_KEYS),
            "options": entry.options,
            "source": entry.source,
            "state": entry.state.value if entry.state else None,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": (
                str(coordinator.last_exception) if coordinator.last_exception else None
            ),
            "update_interval": str(coordinator.update_interval),
            "data_available": coordinator.data is not None,
            "data_keys": list(coordinator.data.keys()) if coordinator.data else [],
        },
        "api_connection": {},
        "sensor_data": {},
        "system_info": {
            "ha_version": hass.config.as_dict().get("version"),
            "integration_version": "1.0.6",
        },
    }

    # Add coordinator-specific diagnostics
    if hasattr(coordinator, "consecutive_failures"):
        diagnostics_data["coordinator"][
            "consecutive_failures"
        ] = coordinator.consecutive_failures

    if (
        hasattr(coordinator, "last_successful_update")
        and coordinator.last_successful_update
    ):
        diagnostics_data["coordinator"][
            "last_successful_update"
        ] = coordinator.last_successful_update.isoformat()

    if hasattr(coordinator, "is_expected_offline"):
        diagnostics_data["coordinator"][
            "is_expected_offline"
        ] = coordinator.is_expected_offline

    # Add API connection diagnostics
    if (
        hasattr(coordinator.api, "last_successful_connection")
        and coordinator.api.last_successful_connection
    ):
        diagnostics_data["api_connection"][
            "last_successful_connection"
        ] = coordinator.api.last_successful_connection.isoformat()

    if hasattr(coordinator.api, "connection_attempts"):
        diagnostics_data["api_connection"][
            "connection_attempts"
        ] = coordinator.api.connection_attempts

    if hasattr(coordinator.api, "timeout_errors"):
        diagnostics_data["api_connection"][
            "timeout_errors"
        ] = coordinator.api.timeout_errors

    # Add current sensor data (with redacted sensitive info)
    if coordinator.data:
        diagnostics_data["sensor_data"] = {}
        for sensor_key, sensor_data in coordinator.data.items():
            diagnostics_data["sensor_data"][sensor_key] = {
                "value": sensor_data.get("value"),
                "raw_value": sensor_data.get("raw_value"),
                "timestamp": sensor_data.get("timestamp"),
            }

    # Add device information
    device_info = {
        "identifiers": f"{entry.domain}_{entry.entry_id}",
        "name": entry.data.get("device_name", "Solarmax Inverter"),
        "manufacturer": "Solarmax",
        "model": "Inverter",
    }
    diagnostics_data["device_info"] = device_info

    return diagnostics_data
