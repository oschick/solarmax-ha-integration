"""Sensor platform for Solarmax integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_NAME,
    DOMAIN,
    SAL_ALARM_MAP,
    SAL_STATE_MULTIPLE,
    SAL_STATE_UNKNOWN,
    SENSOR_TYPE_ALARM,
    SENSOR_TYPE_STATUS,
    SENSOR_TYPES,
    SYS_STATE_CONNECTION_FAILED,
    SYS_STATE_OFFLINE_NIGHT,
    SYS_STATE_UNKNOWN,
    SYS_STATUS_MAP,
)
from .coordinator import SolarmaxCoordinator

_LOGGER = logging.getLogger(__name__)

# Limit parallel updates to prevent overwhelming the inverter
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solarmax sensor platform."""
    coordinator: SolarmaxCoordinator = entry.runtime_data
    device_name = entry.data.get(CONF_DEVICE_NAME, "Solarmax Inverter")

    async_add_entities(
        SolarmaxSensor(coordinator, entry, description, device_name)
        for description in SENSOR_TYPES
    )


class SolarmaxSensor(CoordinatorEntity[SolarmaxCoordinator], SensorEntity):
    """Representation of a Solarmax sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarmaxCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.sensor_key = description.key

        # No hardware identifier is available, so the unique_id falls back to the
        # config entry id per HA guidance: {entry_id}-{key}.
        sensor_type = description.key.lower()
        self._attr_unique_id = f"{entry.entry_id}-{sensor_type}"

        # Force a stable, readable entity_id derived from the device name.
        device_name_normalized = device_name.lower().replace(" ", "_").replace("-", "_")
        self.entity_id = generate_entity_id(
            "sensor.{}",
            f"{device_name_normalized}_{sensor_type}",
            hass=coordinator.hass,
        )

        # Model/firmware/serial are resolved by the coordinator's first refresh,
        # which runs before the sensor platform is set up.
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": device_name,
            "manufacturer": "Solarmax",
            "model": coordinator.device_model or "Inverter",
            "sw_version": coordinator.sw_version,
            "serial_number": coordinator.serial_number,
        }

    @staticmethod
    def _decode_sal_alarms(value: int) -> list[str]:
        """Return the active alarm option keys encoded in a SAL bitmask."""
        return [
            SAL_ALARM_MAP[bit]
            for bit in sorted(SAL_ALARM_MAP)
            if bit > 0 and value & bit
        ]

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the sensor."""
        is_status = self.sensor_key == SENSOR_TYPE_STATUS

        # Status sensor reports the offline reason when the coordinator fails.
        if is_status and not self.coordinator.last_update_success:
            if self.coordinator.is_expected_offline:
                return SYS_STATE_OFFLINE_NIGHT
            return SYS_STATE_CONNECTION_FAILED

        if not self.coordinator.data:
            return None

        sensor_data = self.coordinator.data.get(self.sensor_key)
        if sensor_data is None:
            return None

        value = sensor_data.get("value")

        # Map status/alarm registers to enum option keys (HA handles translation).
        if is_status and isinstance(value, int):
            return SYS_STATUS_MAP.get(value, SYS_STATE_UNKNOWN)

        if self.sensor_key == SENSOR_TYPE_ALARM and isinstance(value, int):
            if value in SAL_ALARM_MAP:
                return SAL_ALARM_MAP[value]
            # Bitmask with multiple bits set (0 is already a direct match above).
            if self._decode_sal_alarms(value):
                return SAL_STATE_MULTIPLE
            return SAL_STATE_UNKNOWN

        return value

    def _offline_attributes(self) -> dict[str, Any]:
        """Diagnostic attributes shown on the status sensor while offline."""
        attributes: dict[str, Any] = {
            "raw_value": "offline",
            "code": "offline",
            "consecutive_failures": self.coordinator.consecutive_failures,
            "expected_offline": self.coordinator.is_expected_offline,
        }
        if self.coordinator.last_successful_update:
            attributes["last_successful_update"] = (
                self.coordinator.last_successful_update.isoformat()
            )
        if self.coordinator.api.last_successful_connection:
            attributes["last_api_connection"] = (
                self.coordinator.api.last_successful_connection.isoformat()
            )
        return attributes

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        is_status = self.sensor_key == SENSOR_TYPE_STATUS

        if is_status and not self.coordinator.last_update_success:
            return self._offline_attributes()

        if not self.coordinator.data:
            return None

        sensor_data = self.coordinator.data.get(self.sensor_key)
        if sensor_data is None:
            return None

        attributes: dict[str, Any] = {}
        if "raw_value" in sensor_data:
            attributes["raw_value"] = sensor_data["raw_value"]

        value = sensor_data.get("value")
        is_register = self.sensor_key in (SENSOR_TYPE_STATUS, SENSOR_TYPE_ALARM)
        # Expose the raw numeric code for the status/alarm registers.
        if is_register and isinstance(value, int):
            attributes["code"] = value

        # Decode the SAL bitmask into the list of active alarms.
        if self.sensor_key == SENSOR_TYPE_ALARM and isinstance(value, int) and value:
            if active_alarms := self._decode_sal_alarms(value):
                attributes["active_alarms"] = active_alarms

        # Surface connection health on the status sensor.
        if is_status:
            attributes["consecutive_failures"] = self.coordinator.consecutive_failures
            if self.coordinator.last_successful_update:
                attributes["last_successful_update"] = (
                    self.coordinator.last_successful_update.isoformat()
                )

        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.coordinator.last_update_success:
            return True

        # The status sensor stays available so it can report the offline state.
        if self.sensor_key == SENSOR_TYPE_STATUS:
            return True

        # Other sensors go unavailable when the inverter is expectedly offline
        # (night) or after a sustained run of day-time failures.
        if self.coordinator.is_expected_offline or self.coordinator.is_night_time:
            return False

        return self.coordinator.consecutive_failures <= 5
