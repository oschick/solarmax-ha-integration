"""Test the Solarmax sensor functionality."""

from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntry

from custom_components.solarmax.const import SENSOR_TYPES
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from custom_components.solarmax.sensor import SolarmaxSensor


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = Mock(spec=SolarmaxCoordinator)
    coordinator.data = {
        "SYS": {"value": 20004, "raw_value": 20004},
        "PAC": {"value": 1500.0, "raw_value": 3000},
    }
    coordinator.last_update_success = True
    # Explicit values for the properties the sensor consults; a bare Mock
    # attribute would be truthy and silently flip the logic under test
    coordinator.is_expected_offline = False
    coordinator.is_night_time = False
    coordinator.consecutive_failures = 0
    coordinator.last_successful_update = None
    coordinator.api = Mock()
    coordinator.api.last_successful_connection = None
    # Plain Mock: hass.config/hass.states are instance attributes and thus
    # not visible to a spec'd Mock
    coordinator.hass = Mock()
    coordinator.hass.config.language = "en"
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


def _make_sensor(coordinator, entry, sensor_key):
    return SolarmaxSensor(
        coordinator=coordinator,
        entry=entry,
        sensor_key=sensor_key,
        sensor_config=SENSOR_TYPES[sensor_key],
        device_name="Test Inverter",
    )


def test_sensor_available_when_coordinator_success(mock_coordinator, mock_config_entry):
    """Test sensor is available when coordinator update succeeds."""
    sensor = _make_sensor(mock_coordinator, mock_config_entry, "PAC")

    assert sensor.available is True


def test_sys_sensor_available_when_coordinator_fails(
    mock_coordinator, mock_config_entry
):
    """Test SYS sensor remains available when coordinator update fails."""
    mock_coordinator.last_update_success = False

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "SYS")

    assert sensor.available is True


def test_other_sensor_unavailable_during_night_when_coordinator_fails(
    mock_coordinator, mock_config_entry
):
    """Test other sensors become unavailable during night when coordinator fails."""
    mock_coordinator.last_update_success = False
    mock_coordinator.is_night_time = True

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "PAC")

    assert sensor.available is False


def test_other_sensor_available_during_day_when_coordinator_fails(
    mock_coordinator, mock_config_entry
):
    """Test other sensors remain available during day when coordinator fails."""
    mock_coordinator.last_update_success = False

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "PAC")

    assert sensor.available is True


def test_other_sensor_unavailable_when_expected_offline(
    mock_coordinator, mock_config_entry
):
    """Test other sensors become unavailable when coordinator expects offline."""
    mock_coordinator.last_update_success = False
    mock_coordinator.is_expected_offline = True

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "PAC")

    assert sensor.available is False


def test_other_sensor_unavailable_after_many_failures(
    mock_coordinator, mock_config_entry
):
    """Test other sensors become unavailable after many day-time failures."""
    mock_coordinator.last_update_success = False
    mock_coordinator.consecutive_failures = 6

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "PAC")

    assert sensor.available is False


def test_sys_sensor_shows_connection_failed_when_coordinator_fails(
    mock_coordinator, mock_config_entry
):
    """Test SYS sensor shows connection_failed when coordinator update fails."""
    mock_coordinator.last_update_success = False

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "SYS")

    assert sensor.native_value == "connection_failed"


def test_sys_sensor_shows_offline_night_when_expected_offline(
    mock_coordinator, mock_config_entry
):
    """Test SYS sensor shows offline_night when the inverter is expected offline."""
    mock_coordinator.last_update_success = False
    mock_coordinator.is_expected_offline = True

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "SYS")

    assert sensor.native_value == "offline_night"


def test_sys_sensor_offline_attributes(mock_coordinator, mock_config_entry):
    """Test SYS sensor shows offline attributes when coordinator update fails."""
    mock_coordinator.last_update_success = False

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "SYS")

    attributes = sensor.extra_state_attributes
    assert attributes["raw_value"] == "offline"
    assert attributes["code"] == "offline"


def test_normal_sensor_operation(mock_coordinator, mock_config_entry):
    """Test normal sensor operation when coordinator succeeds."""
    sensor = _make_sensor(mock_coordinator, mock_config_entry, "SYS")

    # Should show enum option key (HA handles translation)
    assert sensor.native_value == "mpp_operation"

    # Should show normal attributes
    attributes = sensor.extra_state_attributes
    assert attributes["raw_value"] == 20004
    assert attributes["code"] == 20004
