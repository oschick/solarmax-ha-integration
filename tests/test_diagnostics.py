"""Test diagnostics functionality."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solarmax.diagnostics import async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_config_entry_diagnostics(hass: HomeAssistant, mock_config_entry):
    """Test config entry diagnostics."""
    # Mock coordinator
    mock_coordinator = AsyncMock()
    mock_coordinator.last_update_success = True
    mock_coordinator.last_exception = None
    mock_coordinator.update_interval.total_seconds.return_value = 30
    mock_coordinator.data = {
        "PAC": {"value": 1000, "raw_value": "1000", "timestamp": "2025-09-11T10:00:00"},
        "PDC": {"value": 1050, "raw_value": "1050", "timestamp": "2025-09-11T10:00:00"},
    }
    mock_coordinator.consecutive_failures = 0
    mock_coordinator.last_successful_update = None
    mock_coordinator.is_expected_offline = False

    # Mock API
    mock_api = AsyncMock()
    mock_api.last_successful_connection = None
    mock_api.connection_attempts = 5
    mock_api.timeout_errors = 0
    mock_coordinator.api = mock_api

    # Set up config entry
    mock_config_entry.runtime_data = mock_coordinator

    # Mock hass version
    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # Verify diagnostics structure
    assert "config_entry" in diagnostics
    assert "coordinator" in diagnostics
    assert "api_connection" in diagnostics
    assert "sensor_data" in diagnostics
    assert "system_info" in diagnostics
    assert "device_info" in diagnostics

    # Verify config entry data
    config_data = diagnostics["config_entry"]
    assert config_data["domain"] == "solarmax"
    assert config_data["title"] == "Test Solarmax"
    assert "host" not in config_data["data"]  # Should be redacted
    assert "port" in config_data["data"]

    # Verify coordinator data
    coordinator_data = diagnostics["coordinator"]
    assert coordinator_data["last_update_success"] is True
    assert coordinator_data["data_available"] is True
    assert "PAC" in coordinator_data["data_keys"]
    assert "PDC" in coordinator_data["data_keys"]

    # Verify sensor data
    sensor_data = diagnostics["sensor_data"]
    assert "PAC" in sensor_data
    assert sensor_data["PAC"]["value"] == 1000
    assert "PDC" in sensor_data
    assert sensor_data["PDC"]["value"] == 1050

    # Verify system info
    system_info = diagnostics["system_info"]
    assert system_info["ha_version"] == "2024.1.0"
    assert system_info["integration_version"] == "1.0.5"


@pytest.mark.asyncio
async def test_diagnostics_with_no_data(hass: HomeAssistant, mock_config_entry):
    """Test diagnostics when coordinator has no data."""
    # Mock coordinator with no data
    mock_coordinator = AsyncMock()
    mock_coordinator.last_update_success = False
    mock_coordinator.last_exception = Exception("Connection failed")
    mock_coordinator.update_interval.total_seconds.return_value = 30
    mock_coordinator.data = None

    # Mock API
    mock_api = AsyncMock()
    mock_coordinator.api = mock_api

    # Set up config entry
    mock_config_entry.runtime_data = mock_coordinator

    # Mock hass version
    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # Verify basic structure still exists
    assert "config_entry" in diagnostics
    assert "coordinator" in diagnostics
    assert "sensor_data" in diagnostics

    # Verify no data handling
    coordinator_data = diagnostics["coordinator"]
    assert coordinator_data["last_update_success"] is False
    assert coordinator_data["data_available"] is False
    assert coordinator_data["data_keys"] == []
    assert "Connection failed" in coordinator_data["last_exception"]

    # Verify empty sensor data
    assert diagnostics["sensor_data"] == {}


@pytest.mark.asyncio
async def test_diagnostics_redacts_sensitive_data(
    hass: HomeAssistant, mock_config_entry
):
    """Test that sensitive data is properly redacted."""
    # Mock coordinator
    mock_coordinator = AsyncMock()
    mock_coordinator.data = {}
    mock_coordinator.api = AsyncMock()

    # Set up config entry with host data
    mock_config_entry.runtime_data = mock_coordinator
    mock_config_entry.data = {
        "host": "192.168.1.100",  # Should be redacted
        "port": 12345,  # Should not be redacted
        "device_name": "Test Inverter",
    }

    # Mock hass version
    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # Verify sensitive data is redacted
    config_data = diagnostics["config_entry"]["data"]
    assert config_data["host"] == "**REDACTED**"
    assert config_data["port"] == 12345
    assert config_data["device_name"] == "Test Inverter"
