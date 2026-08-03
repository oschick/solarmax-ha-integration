"""Diagnostics support for Solarmax integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CONF_HOST
from .coordinator import SolarmaxCoordinator

REDACT_KEYS = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SolarmaxCoordinator = entry.runtime_data

    integration = await async_get_integration(hass, entry.domain)

    # Collect all diagnostic data
    diagnostics_data: dict[str, Any] = {
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
            "consecutive_failures": coordinator.consecutive_failures,
            "is_expected_offline": coordinator.is_expected_offline,
        },
        "api_connection": {},
        "sensor_data": {},
        "system_info": {
            "ha_version": hass.config.as_dict().get("version"),
            "integration_version": str(integration.version),
        },
    }

    if coordinator.last_successful_update:
        diagnostics_data["coordinator"]["last_successful_update"] = (
            coordinator.last_successful_update.isoformat()
        )

    # API connection diagnostics
    if coordinator.api.last_successful_connection:
        diagnostics_data["api_connection"]["last_successful_connection"] = (
            coordinator.api.last_successful_connection.isoformat()
        )

    # These counters are optional (not all API versions expose them).
    if hasattr(coordinator.api, "connection_attempts"):
        diagnostics_data["api_connection"]["connection_attempts"] = (
            coordinator.api.connection_attempts
        )

    if hasattr(coordinator.api, "timeout_errors"):
        diagnostics_data["api_connection"]["timeout_errors"] = (
            coordinator.api.timeout_errors
        )

    # Add current sensor data
    if coordinator.data:
        diagnostics_data["sensor_data"] = {
            sensor_key: {
                "value": sensor_data.get("value"),
                "raw_value": sensor_data.get("raw_value"),
                "timestamp": sensor_data.get("timestamp"),
            }
            for sensor_key, sensor_data in coordinator.data.items()
        }

    # Add device information (identifiers as a list: diagnostics payloads are
    # JSON-serialized, and a set would not survive json.dumps)
    diagnostics_data["device_info"] = {
        "identifiers": [(entry.domain, entry.entry_id)],
        "name": entry.data.get("device_name", "Solarmax Inverter"),
        "manufacturer": "Solarmax",
        "model": coordinator.device_model or "Inverter",
    }

    return diagnostics_data
