"""Test the Solarmax coordinator."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarmax.connection import (
    ConnectionEngine,
    EngineSnapshot,
    EngineState,
)
from custom_components.solarmax.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_UPDATE_INTERVAL,
    DAWN_POLL_SECONDS,
    DOMAIN,
    FAULT_REPAIR_SECONDS,
    NIGHT_POLL_SECONDS,
)
from custom_components.solarmax.coordinator import SolarmaxCoordinator


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


def _snap(
    state: EngineState,
    *,
    fault_since: datetime | None = None,
    values: dict[str, dict[str, float | int]] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> EngineSnapshot:
    """Build a minimal EngineSnapshot for coordinator-level tests."""
    return EngineSnapshot(
        state=state,
        values=values or {},
        shutdown_announced=False,
        reconnecting=False,
        expected_outside_twilight=False,
        fault_since=fault_since,
        diagnostics=diagnostics or {},
    )


class _StubEngine:
    """Stand-in for ConnectionEngine: returns a prepared snapshot, or raises.

    The real ConnectionEngine has its own emulator-driven coverage
    (test_connection_engine.py); the coordinator is tested against this
    stub so it only needs to trust the engine's documented contract.
    """

    def __init__(
        self,
        state: EngineState = EngineState.ONLINE,
        *,
        fault_since: datetime | None = None,
        values: dict[str, dict[str, float | int]] | None = None,
        diagnostics: dict[str, object] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._snapshot = _snap(
            state, fault_since=fault_since, values=values, diagnostics=diagnostics
        )
        self._exc = exc

    async def poll(self) -> EngineSnapshot:
        if self._exc is not None:
            raise self._exc
        return self._snapshot

    async def close(self) -> None:
        """No-op close, matching ConnectionEngine.close()'s signature."""


# --- Task-5 brief: verbatim skeleton tests ----------------------------------


async def test_update_returns_snapshot_and_never_raises(hass, mock_config_entry):
    """A poll that returns OFFLINE_FAULT must not raise UpdateFailed."""
    coordinator = SolarmaxCoordinator(hass, mock_config_entry)
    coordinator._engine = _StubEngine(state=EngineState.OFFLINE_FAULT)
    snapshot = await coordinator._async_update_data()  # no UpdateFailed
    assert snapshot.state is EngineState.OFFLINE_FAULT


async def test_interval_follows_state(hass, mock_config_entry):
    """Polling cadence only slows down for OFFLINE_EXPECTED, and only then
    depends on whether the sun is below the twilight threshold."""
    coordinator = SolarmaxCoordinator(hass, mock_config_entry)
    assert coordinator._interval_for(_snap(EngineState.ONLINE)) == timedelta(seconds=30)
    with patch.object(coordinator, "sun_below_threshold", return_value=True):
        assert coordinator._interval_for(
            _snap(EngineState.OFFLINE_EXPECTED)
        ) == timedelta(seconds=NIGHT_POLL_SECONDS)
    with patch.object(coordinator, "sun_below_threshold", return_value=False):
        assert coordinator._interval_for(
            _snap(EngineState.OFFLINE_EXPECTED)
        ) == timedelta(seconds=DAWN_POLL_SECONDS)
    # OFFLINE_FAULT keeps normal cadence regardless of the (unmocked) sun —
    # a genuine daytime fault should not be polled any slower than usual.
    assert coordinator._interval_for(_snap(EngineState.OFFLINE_FAULT)) == timedelta(
        seconds=30
    )


async def test_repair_raised_after_sustained_fault_and_cleared(hass, mock_config_entry):
    """A fault older than FAULT_REPAIR_SECONDS raises the repair issue;
    recovering to ONLINE clears it."""
    coordinator = SolarmaxCoordinator(hass, mock_config_entry)
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 1)
    await coordinator._async_handle_snapshot(
        _snap(EngineState.OFFLINE_FAULT, fault_since=old)
    )
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert issue.data["host"] == "192.168.1.100"  # dialog payload guaranteed

    await coordinator._async_handle_snapshot(_snap(EngineState.ONLINE))
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id) is None
    )


# --- Repair issue: additional coverage --------------------------------------


async def test_repair_not_raised_before_sustained_threshold(coordinator, hass):
    """A fault younger than FAULT_REPAIR_SECONDS does not raise the issue."""
    recent = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS - 1)
    await coordinator._async_handle_snapshot(
        _snap(EngineState.OFFLINE_FAULT, fault_since=recent)
    )
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id) is None
    )


async def test_repair_issue_payload_has_host_port_minutes(coordinator, hass):
    """data and translation_placeholders carry exactly host/port/minutes —
    the old {failures} placeholder no longer exists."""
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 60)
    await coordinator._async_handle_snapshot(
        _snap(EngineState.OFFLINE_FAULT, fault_since=old)
    )
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert set(issue.data) == {"host", "port", "minutes"}
    assert issue.translation_placeholders == issue.data
    assert issue.data["port"] == "12345"
    assert issue.data["minutes"] == "6"  # (300 + 60) // 60


async def test_repair_minutes_refreshes_across_polls(coordinator, hass):
    """`minutes` must keep refreshing for the life of the fault, not freeze
    at whatever value was computed when the issue was first raised — a
    2-hour outage should not still show the created-at value."""
    fault_since = dt_util.utcnow() - timedelta(seconds=310)
    await coordinator._async_handle_snapshot(
        _snap(EngineState.OFFLINE_FAULT, fault_since=fault_since)
    )
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert issue.data["minutes"] == "5"  # 310 // 60

    # Same fault, further aged: the coordinator must recompute, not reuse
    # the value captured on the first call.
    fault_since = dt_util.utcnow() - timedelta(seconds=7300)
    await coordinator._async_handle_snapshot(
        _snap(EngineState.OFFLINE_FAULT, fault_since=fault_since)
    )
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert issue.data["minutes"] == "121"  # 7300 // 60


# --- state-transition logging: the replacement for the old ERROR spew -----


async def test_state_transition_logging(coordinator, caplog):
    """Entering FAULT logs exactly one WARNING; any other transition logs
    INFO; a repeated same-state snapshot logs nothing. This is now the only
    trail of connection state changes, since _async_handle_snapshot never
    raises."""
    logger_name = "custom_components.solarmax.coordinator"
    caplog.set_level(logging.INFO, logger=logger_name)

    def records() -> list[logging.LogRecord]:
        return [r for r in caplog.records if r.name == logger_name]

    # No previous data (fresh coordinator) -> OFFLINE_FAULT: one WARNING.
    assert coordinator.data is None
    await coordinator._async_handle_snapshot(_snap(EngineState.OFFLINE_FAULT))
    assert len(records()) == 1
    assert records()[0].levelname == "WARNING"
    coordinator.data = _snap(EngineState.OFFLINE_FAULT)
    caplog.clear()

    # OFFLINE_FAULT -> OFFLINE_EXPECTED: one INFO.
    await coordinator._async_handle_snapshot(_snap(EngineState.OFFLINE_EXPECTED))
    assert len(records()) == 1
    assert records()[0].levelname == "INFO"
    coordinator.data = _snap(EngineState.OFFLINE_EXPECTED)
    caplog.clear()

    # OFFLINE_EXPECTED -> OFFLINE_EXPECTED (no change): nothing logged.
    await coordinator._async_handle_snapshot(_snap(EngineState.OFFLINE_EXPECTED))
    assert records() == []


# --- last_successful_update: local-time semantics (KDY midnight reset) -----


async def test_last_successful_update_returns_local_time(coordinator, hass):
    """Ruling: last_successful_update must convert the engine's UTC
    diagnostics timestamp to local time, since sensor._is_new_day() compares
    against dt_util.now().date(). Pin a non-UTC zone so this actually fails
    if `as_local()` is dropped — under the default test TZ (UTC), local and
    UTC are indistinguishable and the assertion would pass either way."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    utc_now = dt_util.utcnow()
    coordinator.data = _snap(
        EngineState.ONLINE, diagnostics={"last_successful_poll": utc_now}
    )
    result = coordinator.last_successful_update
    assert result == dt_util.as_local(utc_now)
    assert result.utcoffset() != timedelta(0)


async def test_last_successful_update_none_when_unavailable(coordinator):
    """No data yet, or a snapshot without the diagnostics key, both read as
    None rather than raising."""
    assert coordinator.last_successful_update is None

    coordinator.data = _snap(EngineState.ONLINE, diagnostics={})
    assert coordinator.last_successful_update is None


# --- _async_update_data belt-and-braces: provably never raises -------------


async def test_engine_exception_restates_previous_snapshot_as_fault(coordinator):
    """An unexpected exception from the engine must not escape
    _async_update_data; the previous snapshot's values are preserved."""
    coordinator.data = _snap(
        EngineState.ONLINE, values={"PAC": {"value": 1500.0, "raw_value": 3000}}
    )
    coordinator._engine = _StubEngine(exc=RuntimeError("boom"))

    snapshot = await coordinator._async_update_data()

    assert snapshot.state is EngineState.OFFLINE_FAULT
    assert snapshot.values == {"PAC": {"value": 1500.0, "raw_value": 3000}}
    assert snapshot.fault_since is not None


async def test_engine_exception_with_no_previous_data_builds_empty_fault(
    coordinator,
):
    """If the very first poll raises, there is no previous snapshot to
    restate — fall back to an empty OFFLINE_FAULT snapshot."""
    assert coordinator.data is None
    coordinator._engine = _StubEngine(exc=RuntimeError("boom"))

    snapshot = await coordinator._async_update_data()

    assert snapshot.state is EngineState.OFFLINE_FAULT
    assert snapshot.values == {}
    assert snapshot.fault_since is not None


async def test_engine_exception_preserves_existing_fault_since(coordinator):
    """A second unrelated exception while already faulted must not push
    fault_since forward."""
    original_fault_since = dt_util.utcnow() - timedelta(seconds=120)
    coordinator.data = _snap(
        EngineState.OFFLINE_FAULT, fault_since=original_fault_since
    )
    coordinator._engine = _StubEngine(exc=RuntimeError("boom again"))

    snapshot = await coordinator._async_update_data()

    assert snapshot.fault_since == original_fault_since


# --- sun_below_threshold: ported from the removed _is_night_time -----------


async def test_sun_below_threshold_with_sun_component(coordinator):
    """Test threshold detection with sun component."""
    coordinator.hass.states.async_set("sun.sun", "below_horizon")
    assert coordinator.sun_below_threshold() is True

    coordinator.hass.states.async_set("sun.sun", "above_horizon")
    assert coordinator.sun_below_threshold() is False


async def test_sun_below_threshold_dusk_twilight(coordinator):
    """Test that low sun elevation above the horizon is treated as below-threshold."""
    coordinator.hass.states.async_set("sun.sun", "above_horizon", {"elevation": 2.0})
    assert coordinator.sun_below_threshold() is True

    coordinator.hass.states.async_set("sun.sun", "above_horizon", {"elevation": 30.0})
    assert coordinator.sun_below_threshold() is False

    coordinator.hass.states.async_set("sun.sun", "above_horizon", {})
    assert coordinator.sun_below_threshold() is False


async def test_sun_below_threshold_configurable_twilight_threshold(
    hass: HomeAssistant,
):
    """Test that the twilight elevation threshold is configurable."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Inverter",
        data={
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_UPDATE_INTERVAL: 30,
            CONF_TWILIGHT_ELEVATION_THRESHOLD: 10,
        },
        entry_id="test_entry_custom_threshold",
        unique_id="192.168.1.100:12345:custom",
    )
    custom_coordinator = SolarmaxCoordinator(hass, entry)

    hass.states.async_set("sun.sun", "above_horizon", {"elevation": 7.0})
    assert custom_coordinator.sun_below_threshold() is True

    hass.states.async_set("sun.sun", "above_horizon", {"elevation": 15.0})
    assert custom_coordinator.sun_below_threshold() is False


def test_sun_below_threshold_fallback(coordinator):
    """Test the clock-based fallback used when no sun component exists."""
    with patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now:
        mock_time = MagicMock()
        mock_time.hour = 22
        mock_now.return_value = mock_time
        assert coordinator.sun_below_threshold() is True

        mock_time.hour = 14
        assert coordinator.sun_below_threshold() is False

        mock_time.hour = 5
        assert coordinator.sun_below_threshold() is True


# --- device-info properties, read from snapshot.values ----------------------


async def test_device_info_props_from_snapshot_values(coordinator):
    """device_model/sw_version/serial_number read from the latest
    snapshot's values via DEVICE_TYPE_MAP, with no separate fetch step."""
    coordinator.data = _snap(
        EngineState.ONLINE,
        values={
            "TYP": {"value": 20650, "raw_value": 20650},
            "SWV": {"value": 314, "raw_value": 314},
            "BDN": {"value": 5, "raw_value": 5},
            "DIN": {"value": 123456, "raw_value": 123456},
        },
    )
    assert coordinator.device_model == "SolarMax 7TP2"
    assert coordinator.sw_version == "314 (build 5)"
    assert coordinator.serial_number == "123456"


async def test_device_info_props_none_without_data(coordinator):
    """Before the first poll, device-info properties read as None."""
    assert coordinator.data is None
    assert coordinator.device_model is None
    assert coordinator.sw_version is None
    assert coordinator.serial_number is None


# --- engine property ---------------------------------------------------------


def test_engine_property_returns_the_connection_engine(coordinator):
    """engine exposes the ConnectionEngine the coordinator polls."""
    assert isinstance(coordinator.engine, ConnectionEngine)
    assert coordinator.engine is coordinator._engine


# --- midnight handler: kept verbatim from the old suite ---------------------


async def test_async_handle_midnight_notifies_listeners(hass, mock_config_entry):
    """The midnight callback must force listeners to re-read native_value."""
    mock_config_entry.add_to_hass(hass)
    coordinator = SolarmaxCoordinator(hass, mock_config_entry)

    with patch.object(coordinator, "async_update_listeners") as notify:
        coordinator.async_handle_midnight(dt_util.now())

    notify.assert_called_once()
