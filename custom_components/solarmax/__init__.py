"""The Solarmax Inverter integration."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change

from .configuration import (
    INVERTER_DEFAULTS,
    OPTION_DEFAULTS,
    endpoint_unique_id,
    find_endpoint_conflict,
    inverter_fingerprint,
    inverter_subentries,
    subentry_option,
)
from .const import (
    CONF_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_NIGHT_KEEP_VALUES,
    CONF_PORT,
    CONF_RESPONSE_TIMEOUT,
    DEFAULT_ADDRESS,
    DEFAULT_DEVICE_NAME,
    DEFAULT_NIGHT_KEEP_VALUES,
    DEFAULT_RESPONSE_TIMEOUT,
    DOMAIN,
    SUBENTRY_TYPE_INVERTER,
)
from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Mapping of old unique_id suffixes to new ones for entity migration
_UNIQUE_ID_MIGRATIONS = {
    "kdl": "kld",  # v1.2.1: Energy Yesterday key fix (KDL → KLD)
}


async def async_migrate_entry(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> bool:
    """Bring an entry to schema version 3, falling through every older step."""
    if entry.version > 3 or (entry.version == 3 and entry.minor_version > 1):
        return False
    if entry.version == 1:
        _migrate_v1_to_v2(hass, entry)
    if entry.version == 2:
        if _merge_duplicate_endpoint(hass, entry):
            # Folded into an existing endpoint; this entry is being removed and
            # must not load.
            return False
        _migrate_v2_to_v3(hass, entry)
    return True


def _merge_duplicate_endpoint(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> bool:
    """Fold a second entry for the same endpoint into the surviving one.

    One host:port has one client slot and one owner, so two entries for it
    cannot both load. This entry's inverter becomes a subentry of the surviving
    entry, its device and entities move across, and this entry is scheduled for
    removal. Returns True when a merge happened.
    """
    survivor = find_endpoint_conflict(
        hass,
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        exclude_entry_id=entry.entry_id,
    )
    if survivor is None:
        return False
    # The survivor must be a version 3 endpoint before another inverter attaches.
    if survivor.version == 1:
        _migrate_v1_to_v2(hass, survivor)
    if survivor.version == 2:
        _migrate_v2_to_v3(hass, survivor)
    address = int(entry.data.get(CONF_ADDRESS, DEFAULT_ADDRESS))
    subentry = _resolve_inverter_subentry(
        hass, survivor, address, dict(entry.data), dict(entry.options)
    )
    _move_records_to_entry(hass, entry, survivor, subentry.subentry_id)
    _LOGGER.warning(
        "Two Solarmax entries share endpoint %s:%s; merging inverter %s into "
        "%r and removing the duplicate entry",
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        address,
        survivor.title,
    )
    hass.async_create_task(
        hass.config_entries.async_remove(entry.entry_id),
        f"remove duplicate Solarmax entry {entry.entry_id}",
    )
    return True


def _move_records_to_entry(
    hass: HomeAssistant,
    entry: SolarmaxConfigEntry,
    survivor: SolarmaxConfigEntry,
    subentry_id: str,
) -> None:
    """Re-parent this entry's sensor entities and device under the survivor.

    Entity IDs and device IDs are preserved; only their owning entry, subentry,
    and unique IDs change.
    """
    entity_registry = er.async_get(hass)
    prefix = f"{entry.entry_id}-"
    for reg_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if reg_entry.domain != Platform.SENSOR or not reg_entry.unique_id.startswith(
            prefix
        ):
            continue
        entity_registry.async_update_entity(
            reg_entry.entity_id,
            config_entry_id=survivor.entry_id,
            config_subentry_id=subentry_id,
            new_unique_id=f"{subentry_id}-{reg_entry.unique_id.removeprefix(prefix)}",
        )
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if device is not None:
        device_registry.async_update_device(
            device.id,
            new_config_entry_id=survivor.entry_id,
            new_config_subentry_id=subentry_id,
            new_identifiers={(DOMAIN, subentry_id)},
        )


def _migrate_v1_to_v2(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> None:
    """Split connection data from preferences (unchanged 1.4.0 behaviour)."""
    data = dict(entry.data)
    data.setdefault(CONF_ADDRESS, DEFAULT_ADDRESS)
    options = dict(entry.options)
    for key, default in {**OPTION_DEFAULTS, **INVERTER_DEFAULTS}.items():
        options.setdefault(key, data.get(key, default))
        data.pop(key, None)

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        unique_id=f"{data[CONF_HOST]}:{data[CONF_PORT]}:{data[CONF_ADDRESS]}",
        version=2,
        minor_version=1,
    )


def _migrate_v2_to_v3(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> None:
    """Move the inverter into a subentry; idempotent, version bump last."""
    data = dict(entry.data)
    options = dict(entry.options)
    address = int(data.get(CONF_ADDRESS, DEFAULT_ADDRESS))
    subentry = _resolve_inverter_subentry(hass, entry, address, data, options)
    _reconcile_entities(hass, entry, subentry.subentry_id)
    _reconcile_device(hass, entry, subentry.subentry_id)

    data.pop(CONF_ADDRESS, None)
    data.pop(CONF_DEVICE_NAME, None)
    for key in INVERTER_DEFAULTS:
        options.pop(key, None)
    options.setdefault(CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT)
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        unique_id=endpoint_unique_id(data[CONF_HOST], data[CONF_PORT]),
        version=3,
        minor_version=1,
    )


def _resolve_inverter_subentry(
    hass: HomeAssistant,
    entry: SolarmaxConfigEntry,
    address: int,
    data: dict[str, Any],
    options: dict[str, Any],
) -> ConfigSubentry:
    """Reuse the inverter subentry for `address` or create it once."""
    for subentry in entry.subentries.values():
        if (
            subentry.subentry_type == SUBENTRY_TYPE_INVERTER
            and subentry.unique_id == str(address)
        ):
            return subentry
    name = data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME)
    inverter = {CONF_ADDRESS: address, CONF_DEVICE_NAME: name}
    for key, default in INVERTER_DEFAULTS.items():
        inverter[key] = options.get(key, data.get(key, default))
    subentry = ConfigSubentry(
        data=MappingProxyType(inverter),
        subentry_type=SUBENTRY_TYPE_INVERTER,
        title=name,
        unique_id=str(address),
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return subentry


def _reconcile_entities(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, subentry_id: str
) -> None:
    """Move `{entry_id}-key` entities under the subentry, keeping entity IDs."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}-"
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != Platform.SENSOR or not reg_entry.unique_id.startswith(
            prefix
        ):
            continue
        registry.async_update_entity(
            reg_entry.entity_id,
            config_subentry_id=subentry_id,
            new_unique_id=f"{subentry_id}-{reg_entry.unique_id.removeprefix(prefix)}",
        )


def _reconcile_device(
    hass: HomeAssistant, entry: SolarmaxConfigEntry, subentry_id: str
) -> None:
    """Re-identify the inverter device by subentry, keeping its device ID."""
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if device is None:
        return
    registry.async_update_device(
        device.id,
        new_identifiers={(DOMAIN, subentry_id)},
        new_config_subentry_id=subentry_id,
    )


def _migrate_unique_ids(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> None:
    """Migrate renamed sensor unique IDs to prevent orphaned entities."""
    registry = er.async_get(hass)

    for subentry_id in inverter_subentries(entry):
        for old_suffix, new_suffix in _UNIQUE_ID_MIGRATIONS.items():
            old_unique_id = f"{subentry_id}-{old_suffix}"
            new_unique_id = f"{subentry_id}-{new_suffix}"

            entity_id = registry.async_get_entity_id(
                Platform.SENSOR, DOMAIN, old_unique_id
            )
            if entity_id is None:
                continue
            if registry.async_get_entity_id(Platform.SENSOR, DOMAIN, new_unique_id):
                _LOGGER.info(
                    "Removing orphaned entity %s (new entity already exists)",
                    entity_id,
                )
                registry.async_remove(entity_id)
            else:
                _LOGGER.info(
                    "Migrating entity %s unique_id: %s → %s",
                    entity_id,
                    old_unique_id,
                    new_unique_id,
                )
                registry.async_update_entity(entity_id, new_unique_id=new_unique_id)


async def _async_entry_updated(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> None:
    """Reload only when the runtime-relevant inverter set changed."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return
    if inverter_fingerprint(entry) != coordinator.fingerprint:
        hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> bool:
    """Set up the endpoint and every inverter behind it."""
    _migrate_unique_ids(hass, entry)

    coordinator = SolarmaxCoordinator(hass, entry)

    try:
        # A dark inverter still produces a snapshot, so entities can be created
        # immediately without ConfigEntryNotReady.
        await coordinator.async_config_entry_first_refresh()

        entry.runtime_data = coordinator

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        if not coordinator.sensor_setup_complete:
            raise RuntimeError("Solarmax sensor platform setup failed")

        # Register only after platform setup succeeds so failed setup cannot
        # leave callbacks targeting a closed coordinator.
        if any(
            subentry_option(subentry, CONF_NIGHT_KEEP_VALUES, DEFAULT_NIGHT_KEEP_VALUES)
            for subentry in inverter_subentries(entry).values()
        ):
            entry.async_on_unload(
                async_track_time_change(
                    hass, coordinator.async_handle_midnight, hour=0, minute=0, second=0
                )
            )
        entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

        _LOGGER.info(
            "Successfully set up Solarmax endpoint %s:%s with %d inverter(s)",
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            len(coordinator.engines),
        )
    except BaseException:
        # HA skips integration unload after failed setup. Release this setup's
        # client slot before rollback, including when setup was cancelled.
        try:
            await coordinator.async_shutdown()
        finally:
            if getattr(entry, "runtime_data", None) is coordinator:
                object.__delattr__(entry, "runtime_data")
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolarmaxConfigEntry) -> bool:
    """Unload platforms, then close every engine and the shared link once.

    Keep the runtime usable if platform teardown fails and Home Assistant
    leaves the config entry loaded.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
