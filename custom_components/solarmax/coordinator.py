"""DataUpdateCoordinator for Solarmax."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    DEVICE_TYPE_MAP,
    DOMAIN,
)
from .solarmax_api import SolarmaxAPI, SolarmaxConnectionError, SolarmaxTimeoutError

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

        # Device identification (populated on first successful data fetch)
        self._device_model: str | None = None
        self._sw_version: str | None = None
        self._serial_number: str | None = None

    def _is_night_time(self) -> bool:
        """Check if it's currently night time (when inverter is expected to be offline)."""
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

            if not data:
                raise UpdateFailed("No data received from inverter")

            # Reset failure tracking on successful update
            if self._consecutive_failures > 0:
                _LOGGER.info(
                    "Connection restored after %d failed attempts",
                    self._consecutive_failures,
                )
            self._consecutive_failures = 0
            self._last_successful_update = datetime.now()
            self._is_expected_offline = False

            # Fetch device identification once (separate query for static keys)
            if self._device_model is None:
                await self._async_fetch_device_info()

            _LOGGER.debug("Successfully updated data from inverter")
            return data

        except (SolarmaxConnectionError, SolarmaxTimeoutError) as err:
            self._consecutive_failures += 1
            is_night = self._is_night_time()

            # Enhanced error handling based on context
            if is_night:
                # During night time, connection failures are expected
                self._is_expected_offline = True
                _LOGGER.debug("Inverter offline during night time (expected): %s", err)
                raise UpdateFailed(f"Inverter offline (night time): {err}") from err

            elif self._consecutive_failures == 1:
                # First failure during day - could be temporary, log as warning
                _LOGGER.warning("First connection failure during day time: %s", err)
                raise UpdateFailed(f"Connection failed (attempt 1): {err}") from err

            elif self._consecutive_failures <= 3:
                # Multiple failures but not too many - could be inverter restart
                _LOGGER.warning(
                    "Connection failure #%d during day time: %s",
                    self._consecutive_failures,
                    err,
                )
                raise UpdateFailed(
                    f"Connection failed (attempt {self._consecutive_failures}): {err}"
                ) from err

            else:
                # Many consecutive failures during day - something is wrong
                if (
                    self._consecutive_failures == 4
                ):  # Log once when becoming persistently unavailable
                    _LOGGER.error(
                        "Inverter persistently unavailable after %d attempts during day time",
                        self._consecutive_failures,
                    )
                else:
                    _LOGGER.debug(
                        "Persistent connection failure (#%d) during day time: %s",
                        self._consecutive_failures,
                        err,
                    )
                raise UpdateFailed(f"Persistent connection failure: {err}") from err

        except Exception as err:
            self._consecutive_failures += 1
            _LOGGER.error("Unexpected error communicating with inverter: %s", err)
            raise UpdateFailed(f"Unexpected error: {err}") from err

    @property
    def is_expected_offline(self) -> bool:
        """Return if the inverter is expected to be offline (e.g., night time)."""
        return self._is_expected_offline

    async def _async_fetch_device_info(self) -> None:
        """Fetch static device identification keys (one-time query)."""
        try:
            info = await self.hass.async_add_executor_job(self.api.get_device_info)

            if "TYP" in info:
                typ_value = info["TYP"].get("raw_value")
                if typ_value is not None:
                    self._device_model = DEVICE_TYPE_MAP.get(
                        typ_value, f"Unknown ({typ_value})"
                    )
                    _LOGGER.info("Detected inverter type: %s", self._device_model)

            if "SWV" in info:
                swv_value = info["SWV"].get("raw_value")
                if swv_value is not None:
                    bdn_value = info.get("BDN", {}).get("raw_value")
                    if bdn_value is not None:
                        self._sw_version = f"{swv_value} (build {bdn_value})"
                    else:
                        self._sw_version = str(swv_value)
                    _LOGGER.debug("Detected firmware version: %s", self._sw_version)

            if "DIN" in info:
                din_value = info["DIN"].get("raw_value")
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
