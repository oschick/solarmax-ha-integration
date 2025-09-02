"""DataUpdateCoordinator for Solarmax."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from .solarmax_api import SolarmaxAPI

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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the inverter."""
        try:
            data = await self.hass.async_add_executor_job(self.api.get_data)
            if not data:
                raise UpdateFailed("No data received from inverter")
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with inverter: {err}") from err
