"""Sensor platform for Solarmax integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import generate_entity_id

from .const import (
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
    SENSOR_TYPES,
)
from .coordinator import SolarmaxCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solarmax sensor platform."""
    coordinator: SolarmaxCoordinator = hass.data[DOMAIN][entry.entry_id]
    
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
        
        # Get language from Home Assistant (use 'en' as fallback)
        try:
            self._language = coordinator.hass.config.language or 'en'
        except AttributeError:
            self._language = 'en'
        
        # Use descriptive name from sensor config or a meaningful fallback
        # We'll load the translated name in the name property to avoid blocking I/O here
        self._base_name = self.sensor_config.get("name", self.sensor_key.upper())
        self._translation_key = self.sensor_config.get("translation_key", self.sensor_key.lower())
        
        # Override the translation_key to enable HA's translation system for display names
        self._attr_translation_key = self._translation_key
        
        # Enable HA's translation system for entity names
        self._attr_has_entity_name = True
        
        # Remove debug logging now that we've verified the logic works
        # _LOGGER.warning(f"DEBUG Solarmax Sensor Init: sensor_key={sensor_key}, device_name='{device_name}', device_name_normalized='{device_name_normalized}', unique_id='{self._attr_unique_id}', suggested_object_id='{self._attr_suggested_object_id}'")
        
        # Ensure entity is enabled by default
        self._attr_entity_registry_enabled_default = True
        
        # Force the exact entity ID we want using generate_entity_id
        desired_object_id = f"{device_name_normalized}_{sensor_type}"
        self.entity_id = generate_entity_id("sensor.{}", desired_object_id, hass=coordinator.hass)
        
        # Set sensor properties
        if "unit" in sensor_config:
            self._attr_native_unit_of_measurement = sensor_config["unit"]
        if "device_class" in sensor_config:
            self._attr_device_class = sensor_config["device_class"]
        if "state_class" in sensor_config:
            self._attr_state_class = sensor_config["state_class"]
        if "icon" in sensor_config:
            self._attr_icon = sensor_config["icon"]
            
        # Device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": device_name,
            "manufacturer": "Solarmax",
            "model": "Inverter",
            "sw_version": "1.0.0",
        }

    @property
    def translation_key(self) -> str:
        """Return the translation key for this entity."""
        return self._translation_key

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
            
        sensor_data = self.coordinator.data.get(self.sensor_key)
        if sensor_data is None:
            return None
            
        value = sensor_data.get("value")
        
        # Translate status and alarm codes inline (no file I/O, non-blocking)
        if self.sensor_key == "SYS" and isinstance(value, int):
            status_translations = {
                20019: "Feed-in operation" if self._language == "en" else "Einspeisebetrieb",
                20018: "Starting up" if self._language == "en" else "Hochfahren", 
                20000: "Standby" if self._language == "en" else "Bereitschaft",
                20017: "Shutdown" if self._language == "en" else "Herunterfahren",
                20001: "Off" if self._language == "en" else "Aus",
                20002: "Grid monitoring" if self._language == "en" else "Netzüberwachung",
            }
            return status_translations.get(value, f"Status Code: {value}")
            
        elif self.sensor_key == "SAL" and isinstance(value, int):
            alarm_translations = {
                0: "No alarms" if self._language == "en" else "Keine Alarme",
                1: "Grid failure" if self._language == "en" else "Netzfehler",
                2: "DC overvoltage" if self._language == "en" else "DC Überspannung",
                3: "DC undervoltage" if self._language == "en" else "DC Unterspannung",
                4: "Temperature too high" if self._language == "en" else "Temperatur zu hoch",
                5: "Insulation error" if self._language == "en" else "Isolationsfehler",
            }
            return alarm_translations.get(value, f"Alarm Code: {value}")
        
        # For all other sensors, return raw value
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
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
            
        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
