"""Sensor platform for Solarmax integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
    SAL_ALARM_MAP,
    SAL_STATE_MULTIPLE,
    SAL_STATE_UNKNOWN,
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

    entities = []
    device_name = entry.data.get(CONF_DEVICE_NAME, "Solarmax Inverter")

    # Create sensors for all available data types
    for sensor_key, sensor_config in SENSOR_TYPES.items():
        entities.append(
            SolarmaxSensor(
                coordinator=coordinator,
                entry=entry,
                sensor_key=sensor_key,
                sensor_config=sensor_config,
                device_name=device_name,
            )
        )

    async_add_entities(entities)


class SolarmaxSensor(CoordinatorEntity[SolarmaxCoordinator], SensorEntity):
    """Representation of a Solarmax sensor."""

    def __init__(
        self,
        coordinator: SolarmaxCoordinator,
        entry: ConfigEntry,
        sensor_key: str,
        sensor_config: dict[str, Any],
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self.sensor_key = sensor_key
        self.sensor_config = sensor_config

        # Create unique ID following HA guidelines:
        # Since we don't have access to physical device identifiers (serial number, MAC, etc.),
        # we use the Config Entry ID as "last resort" per HA documentation
        config_entry_id = entry.entry_id

        # Use the passed device name for readability (normalized)
        # Don't override the device_name parameter that was passed to constructor
        device_name_normalized = device_name.lower().replace(" ", "_").replace("-", "_")

        # Combine config entry ID with sensor type (following HA pattern: {device_id}-{sensor_type})
        sensor_type = sensor_key.lower()  # PAC -> pac, SYS -> sys, etc.
        self._attr_unique_id = f"{config_entry_id}-{sensor_type}"

        # Suggest object ID using device name for better entity naming
        suggested_entity_id = f"{device_name_normalized}_{sensor_type}"
        self._attr_suggested_object_id = suggested_entity_id

        # Use descriptive name from sensor config or a meaningful fallback
        # We'll load the translated name in the name property to avoid blocking I/O here
        self._base_name = self.sensor_config.get("name", self.sensor_key.upper())
        self._translation_key = self.sensor_config.get(
            "translation_key", self.sensor_key.lower()
        )

        # Override the translation_key to enable HA's translation system for display names
        self._attr_translation_key = self._translation_key

        # Enable HA's translation system for entity names
        self._attr_has_entity_name = True

        # Set entity category and enabled by default from sensor config
        if "entity_category" in sensor_config:
            self._attr_entity_category = sensor_config["entity_category"]

        if "enabled_by_default" in sensor_config:
            self._attr_entity_registry_enabled_default = sensor_config[
                "enabled_by_default"
            ]
        else:
            # Fallback to True if not specified
            self._attr_entity_registry_enabled_default = True

        # Force the exact entity ID we want using generate_entity_id
        desired_object_id = f"{device_name_normalized}_{sensor_type}"
        self.entity_id = generate_entity_id(
            "sensor.{}", desired_object_id, hass=coordinator.hass
        )

        # Set sensor properties
        if "unit" in sensor_config:
            self._attr_native_unit_of_measurement = sensor_config["unit"]
        if "device_class" in sensor_config:
            self._attr_device_class = sensor_config["device_class"]
        if "options" in sensor_config:
            self._attr_options = sensor_config["options"]
        if "state_class" in sensor_config:
            self._attr_state_class = sensor_config["state_class"]
        if "icon" in sensor_config:
            self._attr_icon = sensor_config["icon"]
        if "suggested_display_precision" in sensor_config:
            self._attr_suggested_display_precision = sensor_config[
                "suggested_display_precision"
            ]

        # Device info - model is already resolved since async_config_entry_first_refresh
        # runs before sensor platform setup
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": device_name,
            "manufacturer": "Solarmax",
            "model": coordinator.device_model or "Inverter",
            "sw_version": coordinator.sw_version,
            "serial_number": coordinator.serial_number,
        }

    @property
    def translation_key(self) -> str:
        """Return the translation key for this entity."""
        return self._translation_key

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the sensor."""
        # Special handling for SYS sensor when coordinator update fails
        if not self.coordinator.last_update_success and self.sensor_key == "SYS":
            # Check if this is expected offline vs unexpected failure
            if (
                hasattr(self.coordinator, "is_expected_offline")
                and self.coordinator.is_expected_offline
            ):
                return SYS_STATE_OFFLINE_NIGHT
            else:
                return SYS_STATE_CONNECTION_FAILED

        if not self.coordinator.data:
            return None

        sensor_data = self.coordinator.data.get(self.sensor_key)
        if sensor_data is None:
            return None

        value = sensor_data.get("value")

        # Map status and alarm codes to enum option keys (HA handles translation)
        if self.sensor_key == "SYS" and isinstance(value, int):
            return SYS_STATUS_MAP.get(value, SYS_STATE_UNKNOWN)

        elif self.sensor_key == "SAL" and isinstance(value, int):
            if value == 0:
                return SAL_ALARM_MAP[0]
            # Direct match for single-bit alarm
            if value in SAL_ALARM_MAP:
                return SAL_ALARM_MAP[value]
            # Bitmask: check if multiple alarm bits are set
            active = [
                SAL_ALARM_MAP[bit]
                for bit in sorted(SAL_ALARM_MAP)
                if bit > 0 and value & bit
            ]
            if active:
                return SAL_STATE_MULTIPLE
            return SAL_STATE_UNKNOWN

        # For all other sensors, return raw value
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        # Special handling for SYS sensor when coordinator update fails
        if not self.coordinator.last_update_success and self.sensor_key == "SYS":
            attributes = {
                "raw_value": "offline",
                "code": "offline",
            }

            # Add diagnostic information
            if hasattr(self.coordinator, "consecutive_failures"):
                attributes["consecutive_failures"] = (
                    self.coordinator.consecutive_failures
                )

            if hasattr(self.coordinator, "is_expected_offline"):
                attributes["expected_offline"] = self.coordinator.is_expected_offline

            if (
                hasattr(self.coordinator, "last_successful_update")
                and self.coordinator.last_successful_update
            ):
                attributes["last_successful_update"] = (
                    self.coordinator.last_successful_update.isoformat()
                )

            # Add last API connection time if available
            if (
                hasattr(self.coordinator.api, "last_successful_connection")
                and self.coordinator.api.last_successful_connection
            ):
                attributes["last_api_connection"] = (
                    self.coordinator.api.last_successful_connection.isoformat()
                )

            return attributes

        if not self.coordinator.data:
            return None

        sensor_data = self.coordinator.data.get(self.sensor_key)
        if sensor_data is None:
            return None

        attributes = {}
        if "raw_value" in sensor_data:
            attributes["raw_value"] = sensor_data["raw_value"]

        # For status and alarm sensors, add the raw numeric code as an attribute
        value = sensor_data.get("value")
        if self.sensor_key in ["SYS", "SAL"] and isinstance(value, int):
            attributes["code"] = value

        # For SAL, decode bitmask and add active alarm list as attribute
        if self.sensor_key == "SAL" and isinstance(value, int) and value > 0:
            active_alarms = [
                SAL_ALARM_MAP[bit]
                for bit in sorted(SAL_ALARM_MAP)
                if bit > 0 and value & bit
            ]
            if active_alarms:
                attributes["active_alarms"] = active_alarms

        # Add connection health information for diagnostic purposes
        if self.sensor_key == "SYS":
            if hasattr(self.coordinator, "consecutive_failures"):
                attributes["consecutive_failures"] = (
                    self.coordinator.consecutive_failures
                )

            if (
                hasattr(self.coordinator, "last_successful_update")
                and self.coordinator.last_successful_update
            ):
                attributes["last_successful_update"] = (
                    self.coordinator.last_successful_update.isoformat()
                )

        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Always consider the coordinator's last update success first
        if self.coordinator.last_update_success:
            return True

        # Check if the coordinator indicates this is an expected offline state
        if (
            hasattr(self.coordinator, "is_expected_offline")
            and self.coordinator.is_expected_offline
        ):
            # For SYS (status) sensor, always remain available to show offline status
            if self.sensor_key == "SYS":
                return True
            # For other sensors during expected offline periods, become unavailable
            return False

        # Check if it's night time for backward compatibility
        is_night = self.coordinator.is_night_time

        # For SYS (status) sensor, always remain available to show offline status
        if self.sensor_key == "SYS":
            return True

        # For all other sensors during night time, become unavailable
        # when inverter is not reachable (expected behavior)
        if is_night:
            return False

        # During day time, check consecutive failures
        if hasattr(self.coordinator, "consecutive_failures"):
            # If we have many consecutive failures during day, sensors become unavailable
            # This helps indicate there's a real problem vs temporary network hiccup
            if self.coordinator.consecutive_failures > 5:
                return False

        # During day time, if coordinator update failed, still show as available
        # but sensors will show their last known values or None
        return True
