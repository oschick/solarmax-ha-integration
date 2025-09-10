"""Test diagnostics for Solarmax integration."""

import pytest
from unittest.mock import AsyncMock, Mock

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.solarmax.diagnostics import async_get_config_entry_diagnostics
from custom_components.solarmax.coordinator import SolarmaxCoordinator


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics():
    """Test diagnostics data collection."""
    hass = Mock(spec=HomeAssistant)
    hass.config.as_dict.return_value = {"version": "2024.1.0"}

    # Mock config entry
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.version = 1
    entry.minor_version = 0
    entry.domain = "solarmax"
    entry.title = "Test Inverter"
    entry.data = {
        "host": "192.168.1.100",
        "port": 12345,
        "device_name": "Test Inverter",
    }
    entry.options = {"update_interval": 30}
    entry.source = "user"
    entry.state = Mock()
    entry.state.value = "loaded"

    # Mock coordinator
    coordinator = Mock(spec=SolarmaxCoordinator)
    coordinator.last_update_success = True
    coordinator.last_exception = None
    coordinator.update_interval = Mock()
    coordinator.update_interval.__str__ = Mock(return_value="0:00:30")
    coordinator.data = {
        "PAC": {"value": 1500, "raw_value": "1500", "timestamp": "2024-01-01T12:00:00"},
        "SYS": {
            "value": "Feed-in operation",
            "raw_value": "20019",
            "timestamp": "2024-01-01T12:00:00",
        },
    }
    coordinator.consecutive_failures = 0
    coordinator.last_successful_update = Mock()
    coordinator.last_successful_update.isoformat.return_value = "2024-01-01T12:00:00"
    coordinator.is_expected_offline = False

    # Mock API
    coordinator.api = Mock()
    coordinator.api.last_successful_connection = Mock()
    coordinator.api.last_successful_connection.isoformat.return_value = (
        "2024-01-01T12:00:00"
    )
    coordinator.api.connection_attempts = 1
    coordinator.api.timeout_errors = 0

    entry.runtime_data = coordinator

    # Call diagnostics
    result = await async_get_config_entry_diagnostics(hass, entry)

    # Verify structure
    assert "config_entry" in result
    assert "coordinator" in result
    assert "api_connection" in result
    assert "sensor_data" in result
    assert "device_info" in result
    assert "system_info" in result

    # Verify config entry data
    assert result["config_entry"]["entry_id"] == "test_entry_id"
    assert result["config_entry"]["domain"] == "solarmax"
    assert "host" not in result["config_entry"]["data"]  # Should be redacted
    assert result["config_entry"]["data"]["port"] == 12345

    # Verify coordinator data
    assert result["coordinator"]["last_update_success"] is True
    assert result["coordinator"]["data_available"] is True
    assert "PAC" in result["coordinator"]["data_keys"]
    assert "SYS" in result["coordinator"]["data_keys"]

    # Verify sensor data
    assert "PAC" in result["sensor_data"]
    assert result["sensor_data"]["PAC"]["value"] == 1500
    assert "SYS" in result["sensor_data"]

    # Verify system info
    assert result["system_info"]["ha_version"] == "2024.1.0"
    assert result["system_info"]["integration_version"] == "1.0.3"


@pytest.mark.asyncio
async def test_diagnostics_with_failures():
    """Test diagnostics when there are connection failures."""
    hass = Mock(spec=HomeAssistant)
    hass.config.as_dict.return_value = {"version": "2024.1.0"}

    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.version = 1
    entry.minor_version = 0
    entry.domain = "solarmax"
    entry.title = "Test Inverter"
    entry.data = {"host": "192.168.1.100", "port": 12345}
    entry.options = {}
    entry.source = "user"
    entry.state = Mock()
    entry.state.value = "loaded"

    # Mock coordinator with failures
    coordinator = Mock(spec=SolarmaxCoordinator)
    coordinator.last_update_success = False
    coordinator.last_exception = Exception("Connection failed")
    coordinator.update_interval = Mock()
    coordinator.update_interval.__str__ = Mock(return_value="0:00:30")
    coordinator.data = None
    coordinator.consecutive_failures = 5
    coordinator.is_expected_offline = False

    # Mock API with no successful connection
    coordinator.api = Mock()

    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, entry)

    # Verify failure data is captured
    assert result["coordinator"]["last_update_success"] is False
    assert result["coordinator"]["last_exception"] == "Connection failed"
    assert result["coordinator"]["data_available"] is False
    assert result["coordinator"]["consecutive_failures"] == 5


@pytest.mark.asyncio
async def test_diagnostics_minimal_data():
    """Test diagnostics with minimal coordinator data."""
    hass = Mock(spec=HomeAssistant)
    hass.config.as_dict.return_value = {"version": "2024.1.0"}

    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.version = 1
    entry.minor_version = 0
    entry.domain = "solarmax"
    entry.title = "Test Inverter"
    entry.data = {"host": "192.168.1.100", "port": 12345}
    entry.options = {}
    entry.source = "user"
    entry.state = Mock()
    entry.state.value = "loaded"

    # Mock coordinator with minimal data
    coordinator = Mock(spec=SolarmaxCoordinator)
    coordinator.last_update_success = True
    coordinator.last_exception = None
    coordinator.update_interval = Mock()
    coordinator.update_interval.__str__ = Mock(return_value="0:00:30")
    coordinator.data = {}

    # Mock API with minimal data
    coordinator.api = Mock()

    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, entry)

    # Should work with minimal data
    assert result["coordinator"]["data_available"] is True
    assert result["coordinator"]["data_keys"] == []
    assert result["sensor_data"] == {}
