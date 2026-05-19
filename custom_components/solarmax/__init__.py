"""The Solarmax Inverter integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_HOST, CONF_PORT, DOMAIN
from .coordinator import SolarmaxCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Mapping of old unique_id suffixes to new ones for entity migration
_UNIQUE_ID_MIGRATIONS = {
    "kdl": "kld",  # v1.2.1: Energy Yesterday key fix (KDL → KLD)
}


def _async_migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate renamed sensor unique IDs to prevent orphaned entities."""
    registry = er.async_get(hass)

    for old_suffix, new_suffix in _UNIQUE_ID_MIGRATIONS.items():
        old_unique_id = f"{entry.entry_id}-{old_suffix}"
        new_unique_id = f"{entry.entry_id}-{new_suffix}"

        entity_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, old_unique_id)
        if entity_id is not None:
            _LOGGER.info(
                "Migrating entity %s unique_id: %s → %s",
                entity_id,
                old_unique_id,
                new_unique_id,
            )
            registry.async_update_entity(entity_id, new_unique_id=new_unique_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solarmax Inverter from a config entry."""
    # Migrate renamed entity unique IDs (v1.2.0 → v1.2.1: KDL → KLD)
    _async_migrate_unique_ids(hass, entry)

    coordinator = SolarmaxCoordinator(hass, entry)

    # Test connection before proceeding with setup
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.error("Failed to connect to inverter during setup: %s", err)
        raise ConfigEntryNotReady(f"Failed to connect to inverter: {err}") from err

    # Use runtime_data instead of hass.data
    entry.runtime_data = coordinator

    # Set up update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Successfully set up Solarmax inverter at %s:%s",
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
    )
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    # Reload the integration when options are updated
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Runtime data is automatically cleaned up
        pass

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
