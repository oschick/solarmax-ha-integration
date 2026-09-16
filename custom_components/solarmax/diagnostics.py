"""Diagnostics support for Solarmax integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .configuration import inverter_subentries
from .const import CONF_HOST, DEVICE_KEY_SERIAL
from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator

# Redact the host and both names used for inverter serial data.
REDACT_KEYS = {CONF_HOST, DEVICE_KEY_SERIAL, "serial_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SolarmaxConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for an endpoint and every inverter behind it."""
    coordinator: SolarmaxCoordinator = entry.runtime_data
    snapshots = coordinator.data or {}
    integration = await async_get_integration(hass, entry.domain)

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
            "subentries": [
                {
                    "subentry_id": subentry.subentry_id,
                    "title": subentry.title,
                    "data": dict(subentry.data),
                }
                for subentry in inverter_subentries(entry).values()
            ],
        },
        "coordinator": {
            "update_interval": str(coordinator.update_interval),
            "sun_source": coordinator.sun_source,
        },
        "inverters": {},
        "system_info": {
            "ha_version": hass.config.as_dict().get("version"),
            "integration_version": str(integration.version),
        },
    }

    # The link is shared by every engine, so its counters are reported once
    # here rather than copied into each inverter's diagnostics.
    link = coordinator.link
    if link is not None:
        diagnostics_data["coordinator"]["link"] = {
            "attempts": link.attempts,
            "reconnects": link.reconnects,
            "timeouts": link.timeouts,
        }

    for subentry_id in coordinator.subentry_ids():
        snapshot = snapshots.get(subentry_id)
        last_update = coordinator.last_successful_update_for(subentry_id)
        diagnostics_data["inverters"][subentry_id] = {
            "state": snapshot.state if snapshot else None,
            "reconnecting": snapshot.reconnecting if snapshot else None,
            "link_failure": snapshot.link_failure if snapshot else None,
            "fault_since": (
                snapshot.fault_since.isoformat()
                if snapshot and snapshot.fault_since
                else None
            ),
            "last_successful_update": last_update.isoformat() if last_update else None,
            "connection": dict(snapshot.diagnostics) if snapshot else {},
            "sensor_data": async_redact_data(
                {
                    key: {"value": v.get("value"), "raw_value": v.get("raw_value")}
                    for key, v in (snapshot.values if snapshot else {}).items()
                },
                REDACT_KEYS,
            ),
            "device_info": async_redact_data(
                {
                    "identifiers": [(entry.domain, subentry_id)],
                    "name": coordinator.subentry_title(subentry_id),
                    "manufacturer": "Solarmax",
                    "model": coordinator.device_model_for(subentry_id) or "Inverter",
                },
                REDACT_KEYS,
            ),
        }

    return diagnostics_data
