"""Sensor platform for Solarmax integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_NAME,
    CONF_NIGHT_KEEP_VALUES,
    DAYTIME_FAILURE_GRACE,
    DEFAULT_NIGHT_KEEP_VALUES,
    DOMAIN,
    NIGHT_POLICY,
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
    NightPolicy,
)
from .coordinator import SolarmaxConfigEntry, SolarmaxCoordinator

_LOGGER = logging.getLogger(__name__)

# Limit parallel updates to prevent overwhelming the inverter
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarmaxConfigEntry,
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
        entry: SolarmaxConfigEntry,
        description: SensorEntityDescription,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.sensor_key = description.key

        # Snapshot the option: an options-flow change reloads the entry, so a
        # value read at construction time can never go stale.
        self._night_keep_values: bool = entry.data.get(
            CONF_NIGHT_KEEP_VALUES, DEFAULT_NIGHT_KEEP_VALUES
        )

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
    def _night_policy(self) -> NightPolicy | None:
        """Return the night policy in force right now, else None.

        None means "fall through to the original behaviour" — the coordinator
        is healthy, the option is off, it is not night, or this sensor has no
        honest night-time value.
        """
        if self.coordinator.last_update_success:
            return None
        if not self._night_keep_values:
            return None
        if not (self.coordinator.is_expected_offline or self.coordinator.is_night_time):
            return None
        policy = NIGHT_POLICY.get(self.sensor_key, NightPolicy.UNAVAILABLE)
        return None if policy is NightPolicy.UNAVAILABLE else policy

    def _night_value_source(self, policy: NightPolicy) -> str:
        """Resolve a policy in force to the value it produces right now."""
        if policy is NightPolicy.ZERO:
            return "zero"
        if policy is NightPolicy.HOLD_UNTIL_MIDNIGHT and self._is_new_day():
            return "zero"
        return "hold"

    def _is_new_day(self) -> bool:
        """True when the last successful poll fell on an earlier local day.

        Stateless and restart-safe: derived from the timestamp rather than a
        latch, so it cannot drift out of sync with the wall clock.
        """
        last = self.coordinator.last_successful_update
        if last is None:
            return False
        return last.date() != dt_util.now().date()

    def _held_value(self) -> Any:
        """Return the value retained from the last successful poll, if any.

        The coordinator keeps its last successful payload across failed polls,
        but a key the inverter never reported is simply absent — there is then
        nothing to hold and the sensor must go unavailable rather than sit
        available reporting `unknown`.
        """
        if not self.coordinator.data:
            return None
        sensor_data = self.coordinator.data.get(self.sensor_key)
        if sensor_data is None:
            return None
        return sensor_data.get("value")

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the sensor."""
        is_status = self.sensor_key == SENSOR_TYPE_STATUS

        # Status sensor reports the offline reason when the coordinator fails.
        if is_status and not self.coordinator.last_update_success:
            if self.coordinator.is_expected_offline:
                return SYS_STATE_OFFLINE_NIGHT
            return SYS_STATE_CONNECTION_FAILED

        # A resolved "zero" is synthetic and needs no history; "hold" falls
        # through to coordinator.data, which retains the last successful poll.
        policy = self._night_policy
        if policy is not None and self._night_value_source(policy) == "zero":
            return 0

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

        # A synthesised zero has no underlying poll data, so it must be built
        # here — the empty-data guards below would otherwise return None.
        night_source = None
        if (policy := self._night_policy) is not None:
            night_source = self._night_value_source(policy)
            if night_source == "zero":
                # Do not advertise the stale raw_value behind a synthetic 0.
                return {"raw_value": 0, "night_value_source": "zero"}

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

        # Flag held values so automations can tell them from live readings.
        if night_source is not None:
            attributes["night_value_source"] = night_source

        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.coordinator.last_update_success:
            return True

        # The status sensor stays available so it can report the offline state.
        if self.sensor_key == SENSOR_TYPE_STATUS:
            return True

        # A sensor with a night policy stays available to report it — except a
        # HOLD sensor with nothing held, which has no value to offer.
        policy = self._night_policy
        if policy is not None:
            if self._night_value_source(policy) == "zero":
                return True
            return self._held_value() is not None

        # Other sensors go unavailable when the inverter is expectedly offline
        # (night) or after a sustained run of day-time failures.
        if self.coordinator.is_expected_offline or self.coordinator.is_night_time:
            return False

        return self.coordinator.consecutive_failures <= DAYTIME_FAILURE_GRACE
