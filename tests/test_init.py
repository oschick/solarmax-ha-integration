"""Test the Solarmax integration initialization."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.solarmax import async_setup_entry, async_unload_entry
from custom_components.solarmax.const import DOMAIN, CONF_HOST, CONF_PORT, CONF_DEVICE_NAME, CONF_UPDATE_INTERVAL


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Test Inverter",
        data={
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
        source="user",
        entry_id="test_entry",
        unique_id="192.168.1.100:12345",
    )


@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_success(mock_coordinator_class, hass: HomeAssistant, mock_config_entry):
    """Test successful setup of config entry."""
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_class.return_value = mock_coordinator
    
    with patch.object(hass.config_entries, "async_forward_entry_setups") as mock_forward:
        result = await async_setup_entry(hass, mock_config_entry)
        
        assert result is True
        assert mock_config_entry.runtime_data == mock_coordinator
        mock_coordinator.async_config_entry_first_refresh.assert_called_once()
        mock_forward.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_connection_failed(mock_coordinator_class, hass: HomeAssistant, mock_config_entry):
    """Test setup failure due to connection error."""
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock(side_effect=Exception("Connection failed"))
    mock_coordinator_class.return_value = mock_coordinator
    
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, mock_config_entry)


async def test_unload_entry_success(hass: HomeAssistant, mock_config_entry):
    """Test successful unload of config entry."""
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)
        
        assert result is True
        mock_unload.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


async def test_unload_entry_failed(hass: HomeAssistant, mock_config_entry):
    """Test failed unload of config entry."""
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=False) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)
        
        assert result is False
        mock_unload.assert_called_once_with(mock_config_entry, [Platform.SENSOR])
