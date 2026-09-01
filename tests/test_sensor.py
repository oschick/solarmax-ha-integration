"""Test the Solarmax sensor functionality."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from custom_components.solarmax.const import SENSOR_TYPES
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from custom_components.solarmax.sensor import SolarmaxSensor

_SENSOR_BY_KEY = {description.key: description for description in SENSOR_TYPES}


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
        coordinator,
        entry,
        _SENSOR_BY_KEY[sensor_key],
        "Test Inverter",
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


def test_description_metadata_flows_through(mock_coordinator, mock_config_entry):
    """A main sensor exposes its description's unit/class/state metadata."""
    sensor = _make_sensor(mock_coordinator, mock_config_entry, "PAC")

    assert sensor.native_unit_of_measurement == "W"
    assert sensor.device_class == SensorDeviceClass.POWER
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert sensor.translation_key == "pac"
    assert sensor.entity_registry_enabled_default is True
    assert sensor.entity_category is None


def test_diagnostic_sensor_disabled_by_default(mock_coordinator, mock_config_entry):
    """A diagnostic sensor is opt-in and categorized as diagnostic."""
    sensor = _make_sensor(mock_coordinator, mock_config_entry, "UL1")

    assert sensor.entity_registry_enabled_default is False
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC


def test_unique_id_and_entity_id_scheme(mock_coordinator, mock_config_entry):
    """unique_id and forced entity_id keep the pre-migration scheme."""
    sensor = _make_sensor(mock_coordinator, mock_config_entry, "PAC")

    assert sensor.unique_id == "test_entry_id-pac"
    assert sensor.entity_id == "sensor.test_inverter_pac"


def test_enum_sensor_description(mock_coordinator, mock_config_entry):
    """The status sensor is an enum with options sourced from the description."""
    sensor = _make_sensor(mock_coordinator, mock_config_entry, "SYS")

    assert sensor.device_class == SensorDeviceClass.ENUM
    assert sensor.options
    assert "mpp_operation" in sensor.options


def test_no_invalid_device_state_class_combinations():
    """Guard against device_class/state_class combos HA rejects.

    Energy sensors must not use MEASUREMENT (only TOTAL/TOTAL_INCREASING or
    None); enum sensors must have no state_class and no unit. This catches the
    KLD/KLM/KLY regression where energy + measurement was invalid.
    """
    valid_energy_state_classes = {
        None,
        SensorStateClass.TOTAL,
        SensorStateClass.TOTAL_INCREASING,
    }
    for description in SENSOR_TYPES:
        if description.device_class == SensorDeviceClass.ENERGY:
            assert description.state_class in valid_energy_state_classes, (
                f"{description.key}: invalid energy state_class "
                f"{description.state_class}"
            )
        if description.device_class == SensorDeviceClass.ENUM:
            assert description.state_class is None, f"{description.key}: enum + state"
            assert description.native_unit_of_measurement is None, (
                f"{description.key}: enum sensors must not have a unit"
            )


@pytest.fixture
def night_entry(mock_config_entry):
    """A config entry with the night-keep-values option enabled."""
    mock_config_entry.data = {**mock_config_entry.data, "night_keep_values": True}
    return mock_config_entry


def _set_night(coordinator):
    coordinator.last_update_success = False
    coordinator.is_night_time = True
    coordinator.is_expected_offline = True


def test_zero_policy_sensor_reads_zero_at_night(mock_coordinator, night_entry):
    """PAC is available and reads 0 at night when the option is on."""
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "PAC")

    assert sensor.available is True
    assert sensor.native_value == 0


def test_zero_policy_sensor_reads_zero_without_prior_data(
    mock_coordinator, night_entry
):
    """A zero needs no history — it is true whether or not we ever polled."""
    mock_coordinator.data = {}
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "PAC")

    assert sensor.available is True
    assert sensor.native_value == 0


def test_hold_policy_sensor_keeps_last_value_at_night(mock_coordinator, night_entry):
    """KT0 holds the last successful reading rather than going unavailable."""
    mock_coordinator.data["KT0"] = {"value": 12345, "raw_value": 12345}
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "KT0")

    assert sensor.available is True
    assert sensor.native_value == 12345


def test_hold_policy_sensor_survives_midnight(mock_coordinator, night_entry):
    """Only KDY resets at midnight; lifetime totals keep holding."""
    mock_coordinator.data["KT0"] = {"value": 12345, "raw_value": 12345}
    mock_coordinator.last_successful_update = dt_util.now() - timedelta(days=1)
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "KT0")

    assert sensor.native_value == 12345


def test_hold_policy_sensor_unavailable_with_nothing_to_hold(
    mock_coordinator, night_entry
):
    """An available sensor reporting `unknown` is worse than an absent one.

    Happens for real when the inverter model does not support the key, so its
    value never appears in coordinator.data.
    """
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "KLM")

    assert sensor.available is False


def test_unavailable_policy_sensor_still_unavailable_at_night(
    mock_coordinator, night_entry
):
    """AC grid voltage has no honest night value, so it stays unavailable."""
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "UL1")

    assert sensor.available is False


def test_night_policy_ignored_during_daytime_outage(mock_coordinator, night_entry):
    """A daytime failure is a real fault and must not be smoothed over."""
    mock_coordinator.last_update_success = False
    mock_coordinator.is_night_time = False
    mock_coordinator.is_expected_offline = False
    mock_coordinator.consecutive_failures = 9

    sensor = _make_sensor(mock_coordinator, night_entry, "PAC")

    assert sensor.available is False


def test_night_policy_ignored_when_option_disabled(mock_coordinator, mock_config_entry):
    """Default-off installs keep the original behaviour exactly."""
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, mock_config_entry, "PAC")

    assert sensor.available is False


def test_kdy_holds_before_midnight(mock_coordinator, night_entry):
    """Same local day as the last poll: the day's total still stands."""
    mock_coordinator.data["KDY"] = {"value": 24.5, "raw_value": 245}
    mock_coordinator.last_successful_update = dt_util.now()
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "KDY")

    assert sensor.available is True
    assert sensor.native_value == 24.5


def test_kdy_reads_zero_after_midnight(mock_coordinator, night_entry):
    """Last poll was an earlier local day: today's total is 0."""
    mock_coordinator.data["KDY"] = {"value": 24.5, "raw_value": 245}
    mock_coordinator.last_successful_update = dt_util.now() - timedelta(days=1)
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "KDY")

    assert sensor.available is True
    assert sensor.native_value == 0


def test_kdy_after_midnight_needs_no_held_value(mock_coordinator, night_entry):
    """Once the day has rolled over the 0 is synthetic, not derived."""
    mock_coordinator.data = {}
    mock_coordinator.last_successful_update = dt_util.now() - timedelta(days=1)
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "KDY")

    assert sensor.available is True
    assert sensor.native_value == 0


def test_kdy_unavailable_when_never_polled(mock_coordinator, night_entry):
    """No successful poll ever: nothing to hold and no day boundary crossed."""
    mock_coordinator.data = {}
    mock_coordinator.last_successful_update = None
    _set_night(mock_coordinator)

    sensor = _make_sensor(mock_coordinator, night_entry, "KDY")

    assert sensor.available is False
