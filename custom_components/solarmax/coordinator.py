"""DataUpdateCoordinator for Solarmax."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ADDRESS,
    CONF_HOST,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    DEFAULT_ADDRESS,
    DEFAULT_VERIFY_CHECKSUM,
    DEVICE_KEY_BUILD,
    DEVICE_KEY_FIRMWARE,
    DEVICE_KEY_SERIAL,
    DEVICE_KEY_TYPE,
    DEVICE_TYPE_MAP,
    DOMAIN,
)
from .solarmax_api import (
    SolarmaxAPI,
    SolarmaxConnectionError,
    SolarmaxProtocolError,
    SolarmaxTimeoutError,
)

_LOGGER = logging.getLogger(__name__)


class SolarmaxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Solarmax data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.api = SolarmaxAPI(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            address=entry.data.get(CONF_ADDRESS, DEFAULT_ADDRESS),
            verify_checksum=entry.data.get(
                CONF_VERIFY_CHECKSUM, DEFAULT_VERIFY_CHECKSUM
            ),
        )

        update_interval = timedelta(seconds=entry.data.get(CONF_UPDATE_INTERVAL, 30))

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,  # Only update when data changes
        )

        # Track connection state for better error handling
        self._consecutive_failures = 0
        self._last_successful_update = None
        self._is_expected_offline = False

        # Repair issue tracking (one issue per config entry)
        self._repair_issue_id = f"connection_issues_{entry.entry_id}"
        self._repair_issue_raised = False

        # Device identification (populated on first successful data fetch)
        self._device_model: str | None = None
        self._sw_version: str | None = None
        self._serial_number: str | None = None

    def _is_night_time(self) -> bool:
        """Check if it's currently night (when the inverter is expected offline)."""
        try:
            now = dt_util.now()

            # Get sun component if available
            sun_component = self.hass.states.get("sun.sun")
            if sun_component:
                return sun_component.state == "below_horizon"

            # Fallback: simple time-based check (between 20:00 and 06:00)
            current_hour = now.hour
            return current_hour >= 20 or current_hour < 6

        except Exception as e:
            _LOGGER.debug("Error checking night time: %s", e)
            # Fallback: simple time-based check
            current_hour = dt_util.now().hour
            return current_hour >= 20 or current_hour < 6

    @property
    def is_night_time(self) -> bool:
        """Return True if it is currently night time."""
        return self._is_night_time()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the inverter with intelligent error handling."""
        try:
            data = await self.hass.async_add_executor_job(self.api.get_data)
        except (
            SolarmaxConnectionError,
            SolarmaxTimeoutError,
            SolarmaxProtocolError,
        ) as err:
            raise self._handle_poll_failure(err) from err

        if not data:
            # Valid response without parseable values (e.g. all keys returned
            # as "not applicable"). Nothing to report — treat like a failed
            # poll, not an unexpected error.
            raise self._handle_poll_failure(
                SolarmaxTimeoutError("No data received from inverter")
            )

        # Reset failure tracking on successful update
        if self._consecutive_failures > 0:
            _LOGGER.info(
                "Connection restored after %d failed attempts",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._last_successful_update = dt_util.now()
        self._is_expected_offline = False

        # Delete unconditionally (no-op if absent): a stale issue may exist
        # even when the in-memory flag is False (e.g. after a restart).
        async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)
        self._repair_issue_raised = False

        # Fetch device identification once (separate query for static keys)
        if self._device_model is None:
            await self._async_fetch_device_info()

        _LOGGER.debug("Successfully updated data from inverter")
        return data

    def _handle_poll_failure(self, err: Exception) -> UpdateFailed:
        """Count a failed poll and return the UpdateFailed to raise.

        Night-time failures are expected (the inverter powers down) and stay
        quiet. The first day-time failure after a night clears the stale
        night state so a genuine day-time outage escalates (WARNING → ERROR →
        DEBUG) from scratch.
        """
        if not self._is_night_time():
            if self._is_expected_offline:
                _LOGGER.info(
                    "Inverter offline during day time after expected night-time "
                    "offline — resetting failure tracking"
                )
                self._is_expected_offline = False
                self._consecutive_failures = 0

            self._consecutive_failures += 1
            failures = self._consecutive_failures

            # Day-time failures escalate: warn while it may be transient, raise to
            # error once when it looks persistent, then drop to debug to avoid spam.
            if failures <= 3:
                level = logging.WARNING
            elif failures == 4:
                level = logging.ERROR
            else:
                level = logging.DEBUG
            _LOGGER.log(
                level,
                "Inverter connection failure #%d during day time: %s",
                failures,
                err,
            )

            if failures == 4 and not self._repair_issue_raised:
                async_create_issue(
                    self.hass,
                    DOMAIN,
                    self._repair_issue_id,
                    is_fixable=True,
                    is_persistent=False,
                    severity=IssueSeverity.ERROR,
                    translation_key="connection_issues",
                    translation_placeholders={
                        "host": self.api.host,
                        "port": str(self.api.port),
                        "failures": str(failures),
                    },
                )
                self._repair_issue_raised = True

            if isinstance(err, SolarmaxProtocolError):
                failure_type = "Protocol error"
            elif isinstance(err, SolarmaxTimeoutError):
                failure_type = "Timeout"
            else:
                failure_type = "Connection failed"
            return UpdateFailed(f"{failure_type} (attempt {failures}): {err}")

        # Night time: the inverter powers down, so failures are expected.
        # Delete unconditionally (no-op if absent), like in the success path.
        async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)
        self._repair_issue_raised = False
        self._is_expected_offline = True
        _LOGGER.debug("Inverter offline during night time (expected): %s", err)
        return UpdateFailed(f"Inverter offline (night time): {err}")

    @property
    def is_expected_offline(self) -> bool:
        """Return if the inverter is expected to be offline (e.g., night time)."""
        return self._is_expected_offline

    async def _async_fetch_device_info(self) -> None:
        """Fetch static device identification keys (one-time query)."""
        try:
            info = await self.hass.async_add_executor_job(self.api.get_device_info)

            def raw(key: str) -> Any:
                """Return the raw_value for a device-info key, or None if absent."""
                return info.get(key, {}).get("raw_value")

            typ_value = raw(DEVICE_KEY_TYPE)
            if typ_value is not None:
                self._device_model = DEVICE_TYPE_MAP.get(
                    typ_value, f"Unknown ({typ_value})"
                )
                _LOGGER.info("Detected inverter type: %s", self._device_model)

            swv_value = raw(DEVICE_KEY_FIRMWARE)
            if swv_value is not None:
                bdn_value = raw(DEVICE_KEY_BUILD)
                self._sw_version = (
                    f"{swv_value} (build {bdn_value})"
                    if bdn_value is not None
                    else str(swv_value)
                )
                _LOGGER.debug("Detected firmware version: %s", self._sw_version)

            din_value = raw(DEVICE_KEY_SERIAL)
            if din_value is not None:
                self._serial_number = str(din_value)
                _LOGGER.debug("Detected serial number: %s", self._serial_number)

        except Exception as err:
            _LOGGER.debug("Failed to fetch device info: %s", err)
            # Non-fatal — will retry on next successful data poll

    @property
    def consecutive_failures(self) -> int:
        """Return the number of consecutive update failures."""
        return self._consecutive_failures

    @property
    def last_successful_update(self) -> datetime | None:
        """Return the timestamp of the last successful update."""
        return self._last_successful_update

    @property
    def device_model(self) -> str | None:
        """Return the detected inverter model name (from TYP key)."""
        return self._device_model

    @property
    def sw_version(self) -> str | None:
        """Return the detected firmware version (from SWV key)."""
        return self._sw_version

    @property
    def serial_number(self) -> str | None:
        """Return the detected serial number (from DIN key)."""
        return self._serial_number
