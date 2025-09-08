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
    CONF_HOST,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
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
        )

        update_interval = timedelta(seconds=entry.data.get(CONF_UPDATE_INTERVAL, 30))

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

        # Track connection state for better error handling
        self._consecutive_failures = 0
        self._last_successful_update = None
        self._is_expected_offline = False

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
            _LOGGER.debug(f"Error checking night time: {e}")
            # Fallback: simple time-based check
            current_hour = dt_util.now().hour
            return current_hour >= 20 or current_hour < 6

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the inverter with intelligent error handling."""
        try:
            data = await self.hass.async_add_executor_job(self.api.get_data)

            if not data:
                raise UpdateFailed("No data received from inverter")

            # Reset failure tracking on successful update
            self._consecutive_failures = 0
            self._last_successful_update = datetime.now()
            self._is_expected_offline = False

            _LOGGER.debug("Successfully updated data from inverter")
            return data

        except (SolarmaxConnectionError, SolarmaxTimeoutError) as err:
            self._consecutive_failures += 1
            is_night = self._is_night_time()

            # Enhanced error handling based on context
            if is_night:
                # During night time, connection failures are expected
                self._is_expected_offline = True
                _LOGGER.debug(f"Inverter offline during night time (expected): {err}")
                raise UpdateFailed(f"Inverter offline (night time): {err}") from err

            elif self._consecutive_failures == 1:
                # First failure during day - could be temporary, log as warning
                _LOGGER.warning(f"First connection failure during day time: {err}")
                raise UpdateFailed(f"Connection failed (attempt 1): {err}") from err

            elif self._consecutive_failures <= 3:
                # Multiple failures but not too many - could be inverter restart
                _LOGGER.warning(
                    f"Connection failure #{self._consecutive_failures} during day time: {err}"
                )
                raise UpdateFailed(
                    f"Connection failed (attempt {self._consecutive_failures}): {err}"
                ) from err

            else:
                # Many consecutive failures during day - something is wrong
                _LOGGER.error(
                    f"Persistent connection failure (#{self._consecutive_failures}) during day time: {err}"
                )
                raise UpdateFailed(f"Persistent connection failure: {err}") from err

        except Exception as err:
            self._consecutive_failures += 1
            _LOGGER.error(f"Unexpected error communicating with inverter: {err}")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    @property
    def is_expected_offline(self) -> bool:
        """Return if the inverter is expected to be offline (e.g., night time)."""
        return self._is_expected_offline

    @property
    def consecutive_failures(self) -> int:
        """Return the number of consecutive update failures."""
        return self._consecutive_failures

    @property
    def last_successful_update(self) -> datetime | None:
        """Return the timestamp of the last successful update."""
        return self._last_successful_update
