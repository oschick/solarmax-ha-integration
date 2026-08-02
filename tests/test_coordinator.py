"""Test the Solarmax coordinator."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarmax.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from custom_components.solarmax.solarmax_api import (
    SolarmaxConnectionError,
    SolarmaxProtocolError,
    SolarmaxTimeoutError,
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
            CONF_UPDATE_INTERVAL: 30,
        },
        entry_id="test_entry",
        unique_id="192.168.1.100:12345",
    )


@pytest.fixture
def coordinator(hass: HomeAssistant, mock_config_entry):
    """Create a coordinator instance."""
    return SolarmaxCoordinator(hass, mock_config_entry)


@patch("custom_components.solarmax.coordinator.SolarmaxAPI")
async def test_coordinator_successful_update(mock_api_class, coordinator):
    """Test successful data update."""
    mock_api = MagicMock()
    mock_api.get_data.return_value = {
        "PAC": {"value": 1500.0, "raw_value": 3000},
        "SYS": {"value": 20019, "raw_value": 20019},
    }
    mock_api_class.return_value = mock_api
    coordinator.api = mock_api

    result = await coordinator._async_update_data()

    assert result is not None
    assert "PAC" in result
    assert coordinator.consecutive_failures == 0
    assert coordinator.last_successful_update is not None


@patch("custom_components.solarmax.coordinator.SolarmaxAPI")
async def test_coordinator_connection_error_day(mock_api_class, coordinator):
    """Test connection error during day time."""
    mock_api = MagicMock()
    mock_api.get_data.side_effect = SolarmaxConnectionError("Connection failed")
    mock_api_class.return_value = mock_api
    coordinator.api = mock_api

    # Mock daytime
    with patch.object(coordinator, "_is_night_time", return_value=False):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    assert coordinator.consecutive_failures == 1


@patch("custom_components.solarmax.coordinator.SolarmaxAPI")
async def test_coordinator_connection_error_night(mock_api_class, coordinator):
    """Test connection error during night time."""
    mock_api = MagicMock()
    mock_api.get_data.side_effect = SolarmaxConnectionError("Connection failed")
    mock_api_class.return_value = mock_api
    coordinator.api = mock_api

    # Mock nighttime
    with patch.object(coordinator, "_is_night_time", return_value=True):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    assert coordinator.is_expected_offline is True


@patch("custom_components.solarmax.coordinator.SolarmaxAPI")
async def test_coordinator_timeout_error(mock_api_class, coordinator):
    """Test timeout error."""
    mock_api = MagicMock()
    mock_api.get_data.side_effect = SolarmaxTimeoutError("Timeout")
    mock_api_class.return_value = mock_api
    coordinator.api = mock_api

    with patch.object(coordinator, "_is_night_time", return_value=False):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


async def test_is_night_time_with_sun_component(coordinator):
    """Test night time detection with sun component."""
    # Sun component showing below horizon
    coordinator.hass.states.async_set("sun.sun", "below_horizon")
    assert coordinator._is_night_time() is True

    # Sun component showing above horizon
    coordinator.hass.states.async_set("sun.sun", "above_horizon")
    assert coordinator._is_night_time() is False


def test_is_night_time_fallback(coordinator):
    """Test night time detection fallback logic."""
    # No sun component state exists, so the time-based fallback is used
    with patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now:
        # Test night time (22:00)
        mock_time = MagicMock()
        mock_time.hour = 22
        mock_now.return_value = mock_time
        assert coordinator._is_night_time() is True

        # Test day time (14:00)
        mock_time.hour = 14
        assert coordinator._is_night_time() is False

        # Test early morning (05:00)
        mock_time.hour = 5
        assert coordinator._is_night_time() is True


def test_consecutive_failures_tracking(coordinator):
    """Test consecutive failures tracking."""
    assert coordinator.consecutive_failures == 0

    coordinator._consecutive_failures = 3
    assert coordinator.consecutive_failures == 3


def test_expected_offline_property(coordinator):
    """Test expected offline property."""
    assert coordinator.is_expected_offline is False

    coordinator._is_expected_offline = True
    assert coordinator.is_expected_offline is True


@patch("custom_components.solarmax.coordinator.SolarmaxAPI")
async def test_coordinator_recovery_after_failures(mock_api_class, coordinator):
    """Test recovery after multiple failures."""
    mock_api = MagicMock()
    mock_api_class.return_value = mock_api
    coordinator.api = mock_api

    # Simulate some failures first
    coordinator._consecutive_failures = 3

    # Then successful update
    mock_api.get_data.return_value = {"PAC": {"value": 1500.0, "raw_value": 3000}}

    with patch.object(coordinator, "_is_night_time", return_value=False):
        result = await coordinator._async_update_data()

    assert result is not None
    assert coordinator.consecutive_failures == 0
    assert coordinator.last_successful_update is not None


async def test_daytime_failure_after_night_clears_stale_state(coordinator, caplog):
    """A genuine day-time outage after a night must not stay 'offline_night'."""
    mock_api = MagicMock()
    mock_api.get_data.side_effect = SolarmaxConnectionError("Connection failed")
    mock_api.host = "192.168.1.100"
    mock_api.port = 12345
    coordinator.api = mock_api

    # A full night of expected-offline failures
    with patch.object(coordinator, "_is_night_time", return_value=True):
        for _ in range(10):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    assert coordinator.is_expected_offline is True

    # Morning: the inverter is still down — a real outage, not a night
    with patch.object(coordinator, "_is_night_time", return_value=False):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    assert coordinator.is_expected_offline is False
    assert coordinator.consecutive_failures == 1

    # The escalation starts over and reaches ERROR on the 4th day-time failure
    for _ in range(3):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    assert any(
        "failure #4" in record.message and record.levelno == logging.ERROR
        for record in caplog.records
    )


async def test_empty_data_not_logged_as_unexpected_error(coordinator, caplog):
    """Empty inverter response must not hit the generic 'Unexpected error' path."""
    mock_api = MagicMock()
    mock_api.get_data.return_value = {}
    coordinator.api = mock_api

    with patch.object(coordinator, "_is_night_time", return_value=False):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    assert coordinator.consecutive_failures == 1
    assert not any("Unexpected error" in r.message for r in caplog.records)


async def test_protocol_error_escalates_like_connection_error(coordinator, caplog):
    """Protocol errors must go through the same WARNING/ERROR/DEBUG escalation."""
    mock_api = MagicMock()
    mock_api.get_data.side_effect = SolarmaxProtocolError("Checksum mismatch")
    mock_api.host = "192.168.1.100"
    mock_api.port = 12345
    coordinator.api = mock_api

    with patch.object(coordinator, "_is_night_time", return_value=False):
        for _ in range(4):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    assert coordinator.consecutive_failures == 4
    assert any(
        "failure #4" in record.message and record.levelno == logging.ERROR
        for record in caplog.records
    )
    assert not any("Unexpected error" in r.message for r in caplog.records)


async def test_repair_issue_created_after_sustained_daytime_failures(coordinator, hass):
    """A repair issue is raised after 4 consecutive day-time failures."""
    from homeassistant.helpers.issue_registry import async_get

    mock_api = MagicMock()
    mock_api.get_data.side_effect = SolarmaxConnectionError("Connection failed")
    mock_api.host = "192.168.1.100"
    mock_api.port = 12345
    coordinator.api = mock_api

    with patch.object(coordinator, "_is_night_time", return_value=False):
        for _ in range(4):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    issue = async_get(hass).async_get_issue(DOMAIN, "connection_issues_test_entry")
    assert issue is not None
    assert issue.translation_key == "connection_issues"
    assert issue.translation_placeholders == {
        "host": "192.168.1.100",
        "port": "12345",
        "failures": "4",
    }


async def test_repair_issue_deleted_after_recovery(coordinator, hass):
    """A raised repair issue is cleared once the connection is restored."""
    from homeassistant.helpers.issue_registry import async_get

    mock_api = MagicMock()
    mock_api.get_data.side_effect = SolarmaxConnectionError("Connection failed")
    mock_api.host = "192.168.1.100"
    mock_api.port = 12345
    coordinator.api = mock_api

    with patch.object(coordinator, "_is_night_time", return_value=False):
        for _ in range(4):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    assert (
        async_get(hass).async_get_issue(DOMAIN, "connection_issues_test_entry")
        is not None
    )

    mock_api.get_data.side_effect = None
    mock_api.get_data.return_value = {"PAC": {"value": 1500.0, "raw_value": 3000}}
    with patch.object(coordinator, "_is_night_time", return_value=False):
        await coordinator._async_update_data()

    assert (
        async_get(hass).async_get_issue(DOMAIN, "connection_issues_test_entry") is None
    )


async def test_repair_issue_deleted_when_night_failures_start(coordinator, hass):
    """A repair issue is cleared once the night-time offline period starts."""
    from homeassistant.helpers.issue_registry import async_get

    mock_api = MagicMock()
    mock_api.get_data.side_effect = SolarmaxConnectionError("Connection failed")
    mock_api.host = "192.168.1.100"
    mock_api.port = 12345
    coordinator.api = mock_api

    with patch.object(coordinator, "_is_night_time", return_value=False):
        for _ in range(4):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    assert (
        async_get(hass).async_get_issue(DOMAIN, "connection_issues_test_entry")
        is not None
    )

    with patch.object(coordinator, "_is_night_time", return_value=True):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    assert (
        async_get(hass).async_get_issue(DOMAIN, "connection_issues_test_entry") is None
    )
