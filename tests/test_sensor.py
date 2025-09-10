"""Test the Solarmax sensor functionality."""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solarmax.sensor import SolarmaxSensor
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from custom_components.solarmax.const import SENSOR_TYPES


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = Mock(spec=SolarmaxCoordinator)
    coordinator.data = {
        "SYS": {"value": 20019, "raw_value": 20019},
        "PAC": {"value": 1500.0, "raw_value": 3000},
    }
    coordinator.last_update_success = True
    coordinator.hass = Mock(spec=HomeAssistant)
    coordinator.hass.config.language = "en"
    coordinator.hass.states.get.return_value = None  # No sun component
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.data = {
        "host": "192.168.1.100",
        "port": 12345,
        "device_name": "Test Inverter",
    }
    return entry


def test_sensor_available_when_coordinator_success(mock_coordinator, mock_config_entry):
    """Test sensor is available when coordinator update succeeds."""
    sensor = SolarmaxSensor(
        coordinator=mock_coordinator,
        entry=mock_config_entry,
        sensor_key="PAC",
        sensor_config=SENSOR_TYPES["PAC"],
        device_name="Test Inverter",
    )

    assert sensor.available is True


def test_sys_sensor_available_when_coordinator_fails(
    mock_coordinator, mock_config_entry
):
    """Test SYS sensor remains available when coordinator update fails."""
    mock_coordinator.last_update_success = False

    sensor = SolarmaxSensor(
        coordinator=mock_coordinator,
        entry=mock_config_entry,
        sensor_key="SYS",
        sensor_config=SENSOR_TYPES["SYS"],
        device_name="Test Inverter",
    )

    assert sensor.available is True


@patch("custom_components.solarmax.sensor.dt_util.now")
def test_other_sensor_unavailable_during_night_when_coordinator_fails(
    mock_now, mock_coordinator, mock_config_entry
):
    """Test other sensors become unavailable during night when coordinator fails."""
    # Mock night time (22:00)
    mock_now.return_value = datetime(2024, 1, 1, 22, 0, 0)
    mock_coordinator.last_update_success = False

    sensor = SolarmaxSensor(
        coordinator=mock_coordinator,
        entry=mock_config_entry,
        sensor_key="PAC",
        sensor_config=SENSOR_TYPES["PAC"],
        device_name="Test Inverter",
    )

    assert sensor.available is False


@patch("custom_components.solarmax.sensor.dt_util.now")
def test_other_sensor_available_during_day_when_coordinator_fails(
    mock_now, mock_coordinator, mock_config_entry
):
    """Test other sensors remain available during day when coordinator fails."""
    # Mock day time (12:00)
    mock_now.return_value = datetime(2024, 1, 1, 12, 0, 0)
    mock_coordinator.last_update_success = False

    sensor = SolarmaxSensor(
        coordinator=mock_coordinator,
        entry=mock_config_entry,
        sensor_key="PAC",
        sensor_config=SENSOR_TYPES["PAC"],
        device_name="Test Inverter",
    )

    assert sensor.available is True


def test_sys_sensor_shows_offline_when_coordinator_fails(
    mock_coordinator, mock_config_entry
):
    """Test SYS sensor shows offline status when coordinator update fails."""
    mock_coordinator.last_update_success = False

    sensor = SolarmaxSensor(
        coordinator=mock_coordinator,
        entry=mock_config_entry,
        sensor_key="SYS",
        sensor_config=SENSOR_TYPES["SYS"],
        device_name="Test Inverter",
    )

    assert sensor.native_value == "Offline"


def test_sys_sensor_offline_attributes(mock_coordinator, mock_config_entry):
    """Test SYS sensor shows offline attributes when coordinator update fails."""
    mock_coordinator.last_update_success = False

    sensor = SolarmaxSensor(
        coordinator=mock_coordinator,
        entry=mock_config_entry,
        sensor_key="SYS",
        sensor_config=SENSOR_TYPES["SYS"],
        device_name="Test Inverter",
    )

    attributes = sensor.extra_state_attributes
    assert attributes["raw_value"] == "offline"
    assert attributes["code"] == "offline"


def test_normal_sensor_operation(mock_coordinator, mock_config_entry):
    """Test normal sensor operation when coordinator succeeds."""
    sensor = SolarmaxSensor(
        coordinator=mock_coordinator,
        entry=mock_config_entry,
        sensor_key="SYS",
        sensor_config=SENSOR_TYPES["SYS"],
        device_name="Test Inverter",
    )

    # Should show translated status
    assert sensor.native_value == "Feed-in operation"

    # Should show normal attributes
    attributes = sensor.extra_state_attributes
    assert attributes["raw_value"] == 20019
    assert attributes["code"] == 20019
