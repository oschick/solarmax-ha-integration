"""Test the Solarmax integration initialization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarmax import async_setup_entry, async_unload_entry
from custom_components.solarmax.const import (
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_NIGHT_KEEP_VALUES,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Inverter",
        data={
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
        entry_id="test_entry",
        unique_id="192.168.1.100:12345",
    )


@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_success(
    mock_coordinator_class, hass: HomeAssistant, mock_config_entry
):
    """Test successful setup of config entry."""
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_class.return_value = mock_coordinator

    with patch.object(
        hass.config_entries, "async_forward_entry_setups"
    ) as mock_forward:
        result = await async_setup_entry(hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.runtime_data == mock_coordinator
        mock_coordinator.async_config_entry_first_refresh.assert_called_once()
        mock_forward.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_connection_failed(
    mock_coordinator_class, hass: HomeAssistant, mock_config_entry
):
    """Test setup failure due to connection error."""
    mock_coordinator = MagicMock()
    mock_coordinator.is_night_time = False
    mock_coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=Exception("Connection failed")
    )
    mock_coordinator_class.return_value = mock_coordinator

    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, mock_config_entry)


@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_connection_failed_logs_error_by_day(
    mock_coordinator_class, hass: HomeAssistant, mock_config_entry, caplog
):
    """Test setup failure during the day logs at ERROR level."""
    caplog.set_level("DEBUG", logger="custom_components.solarmax")
    mock_coordinator = MagicMock()
    mock_coordinator.is_night_time = False
    mock_coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=Exception("Connection failed")
    )
    mock_coordinator_class.return_value = mock_coordinator

    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, mock_config_entry)

    assert any(
        record.levelname == "ERROR"
        and "Failed to connect to inverter during setup" in record.message
        for record in caplog.records
    )


@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_connection_failed_logs_debug_at_night(
    mock_coordinator_class, hass: HomeAssistant, mock_config_entry, caplog
):
    """Test setup failure at night logs at DEBUG level, not ERROR."""
    mock_coordinator = MagicMock()
    mock_coordinator.is_night_time = True
    mock_coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=Exception("Inverter offline (night time): Host is unreachable")
    )
    mock_coordinator_class.return_value = mock_coordinator

    with caplog.at_level("DEBUG"):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry)

    assert not any(
        record.levelname == "ERROR"
        and "Failed to connect to inverter during setup" in record.message
        for record in caplog.records
    )
    assert any(
        record.levelname == "DEBUG"
        and "Failed to connect to inverter during setup" in record.message
        for record in caplog.records
    )


@patch("custom_components.solarmax.async_track_time_change")
@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_registers_midnight_listener_when_night_keep_values_enabled(
    mock_coordinator_class, mock_track_time_change, hass: HomeAssistant
):
    """night_keep_values=True must register the local-midnight callback."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Inverter",
        data={
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
            CONF_NIGHT_KEEP_VALUES: True,
        },
        entry_id="test_entry_night_keep_values",
        unique_id="192.168.1.100:12345:night",
    )
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_class.return_value = mock_coordinator

    with patch.object(hass.config_entries, "async_forward_entry_setups"):
        await async_setup_entry(hass, entry)

    mock_track_time_change.assert_called_once_with(
        hass, mock_coordinator.async_handle_midnight, hour=0, minute=0, second=0
    )


@patch("custom_components.solarmax.async_track_time_change")
@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_skips_midnight_listener_by_default(
    mock_coordinator_class,
    mock_track_time_change,
    hass: HomeAssistant,
    mock_config_entry,
):
    """night_keep_values absent (default False) must not register the callback."""
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_class.return_value = mock_coordinator

    with patch.object(hass.config_entries, "async_forward_entry_setups"):
        await async_setup_entry(hass, mock_config_entry)

    mock_track_time_change.assert_not_called()


async def test_unload_entry_success(hass: HomeAssistant, mock_config_entry):
    """Test successful unload of config entry."""
    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=True
    ) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)

        assert result is True
        mock_unload.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


async def test_unload_entry_failed(hass: HomeAssistant, mock_config_entry):
    """Test failed unload of config entry."""
    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)

        assert result is False
        mock_unload.assert_called_once_with(mock_config_entry, [Platform.SENSOR])
