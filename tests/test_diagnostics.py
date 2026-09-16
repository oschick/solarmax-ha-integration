"""Test diagnostics functionality."""

import json
import pathlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.solarmax.connection import EngineSnapshot, EngineState
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from custom_components.solarmax.diagnostics import async_get_config_entry_diagnostics
from tests.helpers import endpoint_entry

MANIFEST = json.loads(
    (
        pathlib.Path(__file__).parent.parent
        / "custom_components"
        / "solarmax"
        / "manifest.json"
    ).read_text()
)


def _snapshot(**overrides) -> EngineSnapshot:
    """A real EngineSnapshot, matching the shape the engine actually produces."""
    defaults: dict = {
        "state": EngineState.ONLINE,
        "values": {
            "PAC": {"value": 1000, "raw_value": 1000},
            "PDC": {"value": 1050, "raw_value": 1050},
        },
        "shutdown_announced": False,
        "reconnecting": False,
        "expected_outside_twilight": False,
        "fault_since": None,
        "diagnostics": {
            "polls_ok": 10,
            "last_successful_poll": datetime(2025, 9, 11, 10, 0, tzinfo=UTC),
            "last_shutdown_announcement": None,
            "transitions": [],
        },
    }
    defaults.update(overrides)
    return EngineSnapshot(**defaults)


def _mock_coordinator(**attrs) -> MagicMock:
    """A coordinator mock spec'd against the real class.

    `spec=SolarmaxCoordinator` makes an access to a removed attribute (e.g.
    the old `is_expected_offline`/`consecutive_failures`/`api`) raise
    AttributeError immediately, the way it would in production — this is
    what would have caught diagnostics.py's live AttributeError before it
    shipped.
    """
    coordinator = MagicMock(spec=SolarmaxCoordinator)
    coordinator.last_update_success = True
    coordinator.last_exception = None
    coordinator.update_interval.total_seconds.return_value = 30
    coordinator.sun_source = "sun.sun"
    coordinator.data = {"sub1": _snapshot()}
    coordinator.subentry_ids.return_value = ["sub1"]
    coordinator.subentry_title.return_value = "Roof"
    coordinator.device_model_for.return_value = "SolarMax 7TP2"
    coordinator.last_successful_update_for.return_value = None
    coordinator.link = MagicMock(attempts=5, reconnects=1, timeouts=0)
    for key, value in attrs.items():
        setattr(coordinator, key, value)
    return coordinator


@pytest.mark.asyncio
async def test_config_entry_diagnostics(hass: HomeAssistant):
    """Test config entry diagnostics."""
    mock_config_entry = endpoint_entry(host="192.168.1.100", port=12345)
    mock_coordinator = _mock_coordinator()
    mock_config_entry.runtime_data = mock_coordinator

    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # Verify diagnostics structure
    assert "config_entry" in diagnostics
    assert "coordinator" in diagnostics
    assert "inverters" in diagnostics
    assert "system_info" in diagnostics

    # Verify config entry data
    config_data = diagnostics["config_entry"]
    assert config_data["domain"] == "solarmax"
    assert config_data["data"]["host"] == "**REDACTED**"
    assert "port" in config_data["data"]

    # Verify coordinator data (update_interval, sun_source, shared-link counters)
    coordinator_data = diagnostics["coordinator"]
    assert coordinator_data["sun_source"] == "sun.sun"
    assert "update_interval" in coordinator_data
    # The shared link's counters are reported once at coordinator level.
    assert coordinator_data["link"] == {"attempts": 5, "reconnects": 1, "timeouts": 0}

    # Verify per-inverter diagnostics structure
    inverter_data = diagnostics["inverters"]["sub1"]
    assert inverter_data["state"] == EngineState.ONLINE
    assert inverter_data["reconnecting"] is False
    assert inverter_data["fault_since"] is None

    # Per-engine diagnostics no longer copy the shared link's counters.
    connection_data = inverter_data["connection"]
    assert "connection_attempts" not in connection_data
    assert "reconnects" not in connection_data
    assert "timeouts" not in connection_data
    assert connection_data["transitions"] == []

    # Verify sensor data
    sensor_data = inverter_data["sensor_data"]
    assert "PAC" in sensor_data
    assert sensor_data["PAC"]["value"] == 1000
    assert "PDC" in sensor_data
    assert sensor_data["PDC"]["value"] == 1050

    # Verify system info
    system_info = diagnostics["system_info"]
    assert system_info["ha_version"] == "2024.1.0"
    # Compare against the manifest so this assertion never goes stale
    assert system_info["integration_version"] == MANIFEST["version"]

    # Verify device info uses JSON-serializable identifier tuples and the
    # detected model
    device_info = inverter_data["device_info"]
    assert device_info["identifiers"] == [("solarmax", "sub1")]
    assert device_info["model"] == "SolarMax 7TP2"


@pytest.mark.asyncio
async def test_diagnostics_with_no_data(hass: HomeAssistant):
    """Test diagnostics when the coordinator has not completed a poll yet."""
    mock_config_entry = endpoint_entry(host="192.168.1.100", port=12345)
    mock_coordinator = _mock_coordinator(data={})
    mock_config_entry.runtime_data = mock_coordinator

    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # Verify basic structure still exists
    assert "config_entry" in diagnostics
    assert "coordinator" in diagnostics
    assert "inverters" in diagnostics

    # Verify no-snapshot handling for subentry
    inverter_data = diagnostics["inverters"]["sub1"]
    assert inverter_data["state"] is None
    assert inverter_data["reconnecting"] is None
    assert inverter_data["fault_since"] is None

    # Verify empty sensor/connection data
    assert inverter_data["sensor_data"] == {}
    assert inverter_data["connection"] == {}


@pytest.mark.asyncio
async def test_diagnostics_reports_fault_since_and_reconnecting(
    hass: HomeAssistant,
):
    """A live fault must surface fault_since/reconnecting for support triage."""
    mock_config_entry = endpoint_entry(host="192.168.1.100", port=12345)
    fault_since = datetime(2025, 9, 11, 9, 30, tzinfo=UTC)
    mock_coordinator = _mock_coordinator(
        data={
            "sub1": _snapshot(
                state=EngineState.OFFLINE_FAULT,
                reconnecting=True,
                fault_since=fault_since,
            )
        }
    )
    mock_config_entry.runtime_data = mock_coordinator

    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    inverter_data = diagnostics["inverters"]["sub1"]
    assert inverter_data["state"] == EngineState.OFFLINE_FAULT
    assert inverter_data["reconnecting"] is True
    assert inverter_data["fault_since"] == fault_since.isoformat()


@pytest.mark.asyncio
async def test_diagnostics_redacts_sensitive_data(
    hass: HomeAssistant,
):
    """Test that sensitive data is properly redacted."""
    mock_config_entry = endpoint_entry(host="192.168.1.100", port=12345)
    mock_coordinator = _mock_coordinator(data={"sub1": _snapshot(values={})})
    mock_config_entry.runtime_data = mock_coordinator

    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # Verify sensitive data is redacted
    config_data = diagnostics["config_entry"]["data"]
    assert config_data["host"] == "**REDACTED**"
    assert config_data["port"] == 12345


@pytest.mark.asyncio
async def test_diagnostics_redacts_serial_number_in_sensor_data(
    hass: HomeAssistant,
):
    """Diagnostics must redact the inverter serial number."""
    mock_config_entry = endpoint_entry(host="192.168.1.100", port=12345)
    mock_coordinator = _mock_coordinator(
        data={
            "sub1": _snapshot(
                values={
                    "PAC": {"value": 1000, "raw_value": 1000},
                    "DIN": {"value": 123456789, "raw_value": 123456789},
                }
            )
        }
    )
    mock_config_entry.runtime_data = mock_coordinator

    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert "123456789" not in str(diagnostics)  # no raw DIN value anywhere
    sensor_data = diagnostics["inverters"]["sub1"]["sensor_data"]
    assert sensor_data["DIN"] == "**REDACTED**"
    assert sensor_data["PAC"]["value"] == 1000  # unrelated data intact


@pytest.mark.asyncio
async def test_diagnostics_lists_subentries(
    hass: HomeAssistant,
):
    """Test that diagnostics list all inverter subentries."""
    mock_config_entry = endpoint_entry(host="192.168.1.100", port=12345)
    mock_coordinator = _mock_coordinator()
    mock_config_entry.runtime_data = mock_coordinator

    with patch.object(hass.config, "as_dict", return_value={"version": "2024.1.0"}):
        diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # Verify subentries are listed in config_entry
    subentries = diagnostics["config_entry"]["subentries"]
    assert len(subentries) == 1
    assert "subentry_id" in subentries[0]
    assert "title" in subentries[0]
    assert "data" in subentries[0]
    assert subentries[0]["title"] == "Existing inverter"
    # host must not be in subentries
    assert "host" not in str(subentries)
