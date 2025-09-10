"""Test configuration for Solarmax integration."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarmax.const import DOMAIN


@pytest.fixture
def mock_config_entry():
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "port": 12345,
            "device_name": "Test Inverter",
            "update_interval": 30,
        },
        unique_id="test_inverter",
    )


@pytest.fixture
async def mock_solarmax_setup(hass: HomeAssistant):
    """Set up the Solarmax integration."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
