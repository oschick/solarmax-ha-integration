"""Coordinator: shared link, one engine per inverter subentry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.solarmax.connection import (
    EngineSnapshot,
    EngineState,
    LinkFailure,
)
from custom_components.solarmax.const import (
    CONF_UPDATE_INTERVAL,
    DAWN_POLL_SECONDS,
    DOMAIN,
    FAULT_POLL_SECONDS,
    FAULT_REPAIR_SECONDS,
    NIGHT_POLL_SECONDS,
    NO_INVERTER_ISSUE,
    REPAIR_PENDING,
    REPAIR_PENDING_ENDPOINT,
    REPAIR_PENDING_INVERTERS,
)
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from tests.helpers import endpoint_entry


def _snap(
    state: EngineState,
    *,
    fault_since: datetime | None = None,
    values: dict | None = None,
    diagnostics: dict | None = None,
    reconnecting: bool = False,
    link_failure: LinkFailure | None = None,
) -> EngineSnapshot:
    return EngineSnapshot(
        state=state,
        values=values or {},
        shutdown_announced=False,
        reconnecting=reconnecting,
        expected_outside_twilight=False,
        fault_since=fault_since,
        diagnostics=diagnostics or {},
        link_failure=link_failure,
    )


class _StubEngine:
    """Returns scripted snapshots; records how it was driven."""

    def __init__(self, *snapshots: EngineSnapshot, exc: Exception | None = None):
        self._snapshots = list(snapshots)
        self._exc = exc
        self.polls = 0
        self.bus_failures = 0
        self.closed = False

    async def poll(self) -> EngineSnapshot:
        self.polls += 1
        if self._exc is not None:
            raise self._exc
        return (
            self._snapshots.pop(0) if len(self._snapshots) > 1 else self._snapshots[0]
        )

    async def record_bus_failure(self) -> EngineSnapshot:
        self.bus_failures += 1
        return _snap(EngineState.OFFLINE_FAULT, link_failure=LinkFailure.CONNECT)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def entry(hass: HomeAssistant):
    # 120 s so the 60 s fault cap is visible in interval assertions.
    entry = endpoint_entry(
        host="192.0.2.10",
        port=12345,
        inverters=(1, 2),
        options={CONF_UPDATE_INTERVAL: 120},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def coordinator(hass: HomeAssistant, entry):
    coordinator = SolarmaxCoordinator(hass, entry)
    coordinator.link = MagicMock()
    coordinator.link.disconnect = AsyncMock()
    coordinator.link.close = AsyncMock()
    return coordinator


def _ids(coordinator):
    return coordinator.subentry_ids()


async def test_cycle_polls_every_engine_in_order(coordinator):
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    data = await coordinator._async_update_data()
    assert set(data) == {first, second}
    assert coordinator.engines[first].polls == 1
    assert coordinator.engines[second].polls == 1


async def test_connect_failure_fails_the_rest_of_the_cycle(coordinator):
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(
            _snap(EngineState.OFFLINE_FAULT, link_failure=LinkFailure.CONNECT)
        ),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    data = await coordinator._async_update_data()
    assert coordinator.engines[second].polls == 0
    assert coordinator.engines[second].bus_failures == 1
    assert data[second].link_failure is LinkFailure.CONNECT


async def test_exchange_failure_only_affects_its_engine(coordinator):
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(
            _snap(EngineState.OFFLINE_FAULT, link_failure=LinkFailure.EXCHANGE)
        ),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    data = await coordinator._async_update_data()
    assert coordinator.engines[second].polls == 1
    assert data[second].state is EngineState.ONLINE


async def test_link_disconnects_only_when_all_expected_offline(coordinator):
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_EXPECTED)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    coordinator.link.disconnect.assert_not_awaited()
    coordinator.engines[second] = _StubEngine(_snap(EngineState.OFFLINE_EXPECTED))
    await coordinator._async_update_data()
    coordinator.link.disconnect.assert_awaited_once()


async def test_cycles_never_interleave(coordinator):
    first, second = _ids(coordinator)
    started = asyncio.Event()
    release = asyncio.Event()

    class _Slow(_StubEngine):
        async def poll(self):
            started.set()
            await release.wait()
            return await super().poll()

    coordinator.engines = {
        first: _Slow(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    cycle_one = asyncio.create_task(coordinator._async_update_data())
    await started.wait()
    cycle_two = asyncio.create_task(coordinator._async_update_data())
    await asyncio.sleep(0)
    assert coordinator.engines[second].polls == 0
    release.set()
    await asyncio.gather(cycle_one, cycle_two)
    assert coordinator.engines[first].polls == 2
    assert coordinator.engines[second].polls == 2


def _night(hass: HomeAssistant) -> None:
    """Pin the sun so expected-offline cadence is the 900 s night value."""
    hass.states.async_set(
        "sun.sun", "below_horizon", {"elevation": -12.0, "rising": False}
    )


async def test_interval_is_minimum_across_inverters(hass, coordinator):
    _night(hass)
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.OFFLINE_EXPECTED)),
    }
    await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(seconds=120)
    coordinator.engines[first] = _StubEngine(
        _snap(EngineState.OFFLINE_FAULT, fault_since=dt_util.utcnow())
    )
    await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(seconds=FAULT_POLL_SECONDS)


async def test_night_cadence_uses_per_inverter_dawn_check(coordinator):
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_EXPECTED)),
        second: _StubEngine(_snap(EngineState.OFFLINE_EXPECTED)),
    }
    with patch.object(
        SolarmaxCoordinator, "_fast_expected_polling", side_effect=[False, True]
    ):
        await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(seconds=DAWN_POLL_SECONDS)
    with patch.object(
        SolarmaxCoordinator, "_fast_expected_polling", return_value=False
    ):
        await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(seconds=NIGHT_POLL_SECONDS)


async def test_repair_issue_lists_faulted_inverters(hass, coordinator):
    first, second = _ids(coordinator)
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 60)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=old)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"connection_issues_{coordinator.config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["inverters"] == "Existing inverter"
    coordinator.engines[first] = _StubEngine(_snap(EngineState.ONLINE))
    await coordinator._async_update_data()
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"connection_issues_{coordinator.config_entry.entry_id}"
        )
        is None
    )


async def test_pending_repair_clears_after_every_pending_inverter_polls_online(
    hass, coordinator
):
    first, second = _ids(coordinator)
    issue_id = f"connection_issues_{coordinator.config_entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="connection_issues",
        data={
            REPAIR_PENDING: 1,
            REPAIR_PENDING_ENDPOINT: "192.0.2.10:12345",
            REPAIR_PENDING_INVERTERS: f"{first},{second}",
        },
    )
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(
            _snap(EngineState.OFFLINE_FAULT, link_failure=LinkFailure.EXCHANGE)
        ),
    }
    await coordinator._async_update_data()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    coordinator.engines[second] = _StubEngine(_snap(EngineState.ONLINE))
    await coordinator._async_update_data()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.parametrize("pending", [False, True])
async def test_refresh_repair_issue_re_renders_names(hass, coordinator, pending):
    first, second = _ids(coordinator)
    issue_id = f"connection_issues_{coordinator.config_entry.entry_id}"
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 60)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=old)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    registry = ir.async_get(hass)
    if pending:
        issue = registry.async_get_issue(DOMAIN, issue_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="connection_issues",
            translation_placeholders=issue.translation_placeholders,
            data={
                **(issue.data or {}),
                REPAIR_PENDING: 1,
                REPAIR_PENDING_ENDPOINT: "192.0.2.10:12345",
                REPAIR_PENDING_INVERTERS: first,
            },
        )
    subentry = coordinator.config_entry.subentries[first]
    hass.config_entries.async_update_subentry(
        coordinator.config_entry, subentry, title="Garage"
    )
    coordinator.async_refresh_repair_issue()
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue.translation_placeholders["inverters"] == "Garage"
    assert issue.data["inverters"] == "Garage"
    assert (issue.data.get(REPAIR_PENDING) == 1) is pending
    if pending:
        assert issue.data[REPAIR_PENDING_INVERTERS] == first


@pytest.mark.parametrize("pending", [False, True])
async def test_empty_entry_clears_stale_connection_issue(hass, pending):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=())
    entry.add_to_hass(hass)
    issue_id = f"connection_issues_{entry.entry_id}"
    data = {"host": "192.0.2.10", "port": "12345", "minutes": "7", "inverters": "Roof"}
    if pending:
        data |= {REPAIR_PENDING: 1, REPAIR_PENDING_ENDPOINT: "192.0.2.10:12345"}
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="connection_issues",
        translation_placeholders=data,
        data=data,
    )
    coordinator = SolarmaxCoordinator(hass, entry)
    assert await coordinator._async_update_data() == {}
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_empty_entry_is_idle_with_no_inverter_issue(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=())
    entry.add_to_hass(hass)
    coordinator = SolarmaxCoordinator(hass, entry)
    assert coordinator.link is None
    assert coordinator.engines == {}
    assert await coordinator._async_update_data() == {}
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{NO_INVERTER_ISSUE}_{entry.entry_id}"
    )
    assert issue is not None and issue.is_fixable is False


async def test_shutdown_closes_engines_and_link_exactly_once(coordinator):
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator.async_shutdown()
    await coordinator.async_shutdown()  # HA calls it again on entry unload
    assert all(engine.closed for engine in coordinator.engines.values())
    # A6: the link is closed once before the lock (to abort an in-flight poll)
    # and once inside it (the once-only slot-free guarantee); the second
    # shutdown is a no-op, so the count stays at two.
    assert coordinator.link.close.await_count == 2


async def test_handoff_disconnects_link_and_blocks_cycles(coordinator):
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    async with coordinator.validation_handoff():
        # A6: disconnect runs once before the lock (aborting any in-flight
        # exchange) and once inside it (guaranteeing the slot is free).
        assert coordinator.link.disconnect.await_count == 2
        cycle = asyncio.create_task(coordinator._async_update_data())
        await asyncio.sleep(0)
        assert coordinator.engines[first].polls == 0
    await cycle
    assert coordinator.engines[first].polls == 1


# --- Ported: snapshot contract, intervals, and options ----------------------


async def test_update_returns_snapshot_and_never_raises(coordinator):
    """A cycle where every engine faults returns a dict and never raises."""
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT)),
        second: _StubEngine(_snap(EngineState.OFFLINE_FAULT)),
    }
    data = await coordinator._async_update_data()  # no UpdateFailed
    assert set(data) == {first, second}
    assert data[first].state is EngineState.OFFLINE_FAULT


async def test_interval_follows_state(coordinator):
    """Online polling uses the configured cadence; faults retain their cap."""
    first, second = _ids(coordinator)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(seconds=120)

    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT)),
        second: _StubEngine(_snap(EngineState.OFFLINE_FAULT)),
    }
    await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(seconds=FAULT_POLL_SECONDS)


async def test_runtime_option_overrides_legacy_update_interval(hass: HomeAssistant):
    """A migrated option must take precedence over legacy entry data."""
    entry = endpoint_entry(
        host="192.0.2.10",
        port=12345,
        inverters=(1, 2),
        options={CONF_UPDATE_INTERVAL: 45},
    )
    entry.add_to_hass(hass)
    # Legacy data key that a stale entry might still carry.
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_UPDATE_INTERVAL: 30}
    )
    coordinator = SolarmaxCoordinator(hass, entry)
    first, second = coordinator.subentry_ids()
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(seconds=45)


@pytest.mark.parametrize(
    ("state", "elevation", "rising", "expected_seconds"),
    [
        ("below_horizon", -6.1, True, NIGHT_POLL_SECONDS),
        ("below_horizon", -6.0, True, DAWN_POLL_SECONDS),
        ("above_horizon", 4.0, True, DAWN_POLL_SECONDS),
        ("above_horizon", None, True, DAWN_POLL_SECONDS),
        ("below_horizon", -5.0, False, NIGHT_POLL_SECONDS),
        ("above_horizon", 6.0, False, DAWN_POLL_SECONDS),
    ],
)
def test_expected_offline_interval_tracks_dawn_and_daytime(
    coordinator, state, elevation, rising, expected_seconds
):
    """Fast polling starts at civil dawn and remains active in daytime."""
    first, _second = _ids(coordinator)
    coordinator.hass.states.async_set(
        "sun.sun",
        state,
        {"elevation": elevation, "rising": rising},
    )

    assert coordinator._interval_for(
        {first: _snap(EngineState.OFFLINE_EXPECTED)}
    ) == timedelta(seconds=expected_seconds)


@pytest.mark.parametrize(
    ("hour", "expected_seconds"),
    [
        (4, NIGHT_POLL_SECONDS),
        (5, DAWN_POLL_SECONDS),
        (19, DAWN_POLL_SECONDS),
        (20, NIGHT_POLL_SECONDS),
    ],
)
def test_expected_offline_interval_uses_clock_dawn_fallback(
    coordinator, hour, expected_seconds
):
    """The clock fallback starts recovery polling an hour before daytime."""
    first, _second = _ids(coordinator)
    with patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now:
        mock_now.return_value.hour = hour

        assert coordinator._interval_for(
            {first: _snap(EngineState.OFFLINE_EXPECTED)}
        ) == timedelta(seconds=expected_seconds)


def test_fault_interval_is_capped_at_one_minute(coordinator):
    """A long configured interval must not delay fault recovery detection."""
    first, _second = _ids(coordinator)
    coordinator._configured_interval = timedelta(hours=1)

    assert coordinator._interval_for(
        {first: _snap(EngineState.OFFLINE_FAULT)}
    ) == timedelta(seconds=60)


def test_reconnecting_unknown_interval_is_capped_at_one_minute(coordinator):
    """Daytime startup failures need the same recovery cadence during grace."""
    first, _second = _ids(coordinator)
    coordinator._configured_interval = timedelta(hours=1)

    assert coordinator._interval_for(
        {first: _snap(EngineState.UNKNOWN, reconnecting=True)}
    ) == timedelta(seconds=60)


# --- Ported: repair issue coverage ------------------------------------------


async def test_repair_raised_after_sustained_fault_and_cleared(hass, coordinator):
    """A fault older than FAULT_REPAIR_SECONDS raises the repair issue;
    recovering to ONLINE clears it."""
    first, second = _ids(coordinator)
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 1)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=old)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert issue.data["host"] == "192.0.2.10"  # dialog payload guaranteed

    coordinator.engines[first] = _StubEngine(_snap(EngineState.ONLINE))
    await coordinator._async_update_data()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id) is None
    )


async def test_repair_not_raised_before_sustained_threshold(coordinator, hass):
    """A fault younger than FAULT_REPAIR_SECONDS does not raise the issue."""
    first, second = _ids(coordinator)
    recent = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS - 1)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=recent)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id) is None
    )


async def test_repair_issue_payload_has_host_port_minutes_and_inverters(
    coordinator, hass
):
    """data and translation_placeholders carry host/port/minutes/inverters, and
    data additionally carries inverter_ids for later name refreshes."""
    first, second = _ids(coordinator)
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 60)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=old)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert set(issue.data) == {"host", "port", "minutes", "inverters", "inverter_ids"}
    assert set(issue.translation_placeholders) == {
        "host",
        "port",
        "minutes",
        "inverters",
    }
    assert issue.data["port"] == "12345"
    assert issue.data["minutes"] == "6"  # (300 + 60) // 60
    assert issue.data["inverters"] == "Existing inverter"


async def test_repair_minutes_refresh_for_fault_episode(coordinator, hass):
    """An existing issue reflects the ongoing fault duration."""
    first, second = _ids(coordinator)
    fault_since = dt_util.utcnow() - timedelta(seconds=310)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=fault_since)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert issue.data["minutes"] == "5"  # 310 // 60

    fault_since = dt_util.utcnow() - timedelta(seconds=7300)
    coordinator.engines[first] = _StubEngine(
        _snap(EngineState.OFFLINE_FAULT, fault_since=fault_since)
    )
    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert issue.data["minutes"] == "121"


# --- Ported: state-transition logging ---------------------------------------


async def test_state_transition_logging(coordinator, caplog):
    """Entering FAULT logs exactly one WARNING per inverter, naming it. This
    is now the only trail of connection state changes, since the cycle never
    raises."""
    first, second = _ids(coordinator)
    logger_name = "custom_components.solarmax.coordinator"
    caplog.set_level(logging.INFO, logger=logger_name)

    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT)),
        second: _StubEngine(_snap(EngineState.OFFLINE_FAULT)),
    }
    await coordinator._async_update_data()

    warnings = [
        record
        for record in caplog.records
        if record.name == logger_name and record.levelname == "WARNING"
    ]
    assert len(warnings) == 2
    messages = " ".join(record.getMessage() for record in warnings)
    assert coordinator.subentry_title(first) in messages
    assert coordinator.subentry_title(second) in messages


# --- Ported: last_successful_update local-time semantics --------------------


async def test_last_successful_update_returns_local_time(coordinator, hass):
    """Convert engine timestamps to local time for midnight policies."""
    first, _second = _ids(coordinator)
    await hass.config.async_set_time_zone("Europe/Berlin")
    utc_now = dt_util.utcnow()
    coordinator.data = {
        first: _snap(EngineState.ONLINE, diagnostics={"last_successful_poll": utc_now})
    }
    result = coordinator.last_successful_update_for(first)
    assert result == dt_util.as_local(utc_now)
    assert result.utcoffset() != timedelta(0)


async def test_last_successful_update_none_when_unavailable(coordinator):
    """No data yet, or a snapshot without the diagnostics key, both read as
    None rather than raising."""
    first, _second = _ids(coordinator)
    assert coordinator.last_successful_update_for(first) is None

    coordinator.data = {first: _snap(EngineState.ONLINE, diagnostics={})}
    assert coordinator.last_successful_update_for(first) is None


# --- Ported: unexpected engine errors ---------------------------------------


async def test_engine_exception_restates_previous_snapshot_as_fault(coordinator):
    """An unexpected exception from one engine must not escape the cycle; that
    inverter's previous values are preserved and the rest of the bus is
    unaffected."""
    first, second = _ids(coordinator)
    coordinator.data = {
        first: _snap(
            EngineState.ONLINE, values={"PAC": {"value": 1500.0, "raw_value": 3000}}
        )
    }
    coordinator.engines = {
        first: _StubEngine(exc=RuntimeError("boom")),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }

    data = await coordinator._async_update_data()

    assert data[first].state is EngineState.OFFLINE_FAULT
    assert data[first].values == {"PAC": {"value": 1500.0, "raw_value": 3000}}
    assert data[first].fault_since is not None
    assert data[first].link_failure is LinkFailure.EXCHANGE
    assert data[second].state is EngineState.ONLINE


async def test_engine_exception_with_no_previous_data_builds_empty_fault(coordinator):
    """If the very first poll raises, there is no previous snapshot to
    restate — fall back to an empty OFFLINE_FAULT snapshot."""
    first, second = _ids(coordinator)
    assert coordinator.data is None
    coordinator.engines = {
        first: _StubEngine(exc=RuntimeError("boom")),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }

    data = await coordinator._async_update_data()

    assert data[first].state is EngineState.OFFLINE_FAULT
    assert data[first].values == {}
    assert data[first].fault_since is not None
    assert data[first].link_failure is LinkFailure.EXCHANGE
    assert data[second].state is EngineState.ONLINE


async def test_engine_exception_preserves_existing_fault_since(coordinator):
    """A second unrelated exception while already faulted must not push
    fault_since forward."""
    first, second = _ids(coordinator)
    original_fault_since = dt_util.utcnow() - timedelta(seconds=120)
    coordinator.data = {
        first: _snap(EngineState.OFFLINE_FAULT, fault_since=original_fault_since)
    }
    coordinator.engines = {
        first: _StubEngine(exc=RuntimeError("boom again")),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }

    data = await coordinator._async_update_data()

    assert data[first].fault_since == original_fault_since


# --- Ported: sun_below_threshold --------------------------------------------


async def test_sun_below_threshold_with_sun_component(coordinator):
    """Test threshold detection with sun component."""
    coordinator.hass.states.async_set("sun.sun", "below_horizon")
    assert coordinator.sun_below_threshold(5.0) is True

    coordinator.hass.states.async_set("sun.sun", "above_horizon")
    assert coordinator.sun_below_threshold(5.0) is False


async def test_sun_below_threshold_dusk_twilight(coordinator):
    """Test that low sun elevation above the horizon is treated as below-threshold."""
    coordinator.hass.states.async_set("sun.sun", "above_horizon", {"elevation": 2.0})
    assert coordinator.sun_below_threshold(5.0) is True

    coordinator.hass.states.async_set("sun.sun", "above_horizon", {"elevation": 30.0})
    assert coordinator.sun_below_threshold(5.0) is False

    coordinator.hass.states.async_set("sun.sun", "above_horizon", {})
    assert coordinator.sun_below_threshold(5.0) is False


def test_sun_below_threshold_configurable_twilight_threshold(coordinator):
    """The twilight elevation threshold is a per-call argument."""
    coordinator.hass.states.async_set("sun.sun", "above_horizon", {"elevation": 7.0})
    assert coordinator.sun_below_threshold(9.0) is True
    assert coordinator.sun_below_threshold(2.0) is False


def test_sun_below_threshold_fallback(coordinator):
    """Test the clock-based fallback used when no sun component exists."""
    with patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now:
        mock_time = MagicMock()
        mock_time.hour = 22
        mock_now.return_value = mock_time
        assert coordinator.sun_below_threshold(5.0) is True

        mock_time.hour = 14
        assert coordinator.sun_below_threshold(5.0) is False

        mock_time.hour = 5
        assert coordinator.sun_below_threshold(5.0) is True


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
def test_unavailable_sun_state_uses_clock_fallback(coordinator, state):
    """An unusable sun entity must not suppress the clock fallback."""
    coordinator.hass.states.async_set("sun.sun", state, {})

    with patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now:
        mock_now.return_value.hour = 22
        assert coordinator.sun_below_threshold(5.0) is True
        assert coordinator._fast_expected_polling(5.0) is False

    assert coordinator.sun_source == "clock_fallback"


def test_invalid_sun_elevation_uses_clock_fallback(coordinator):
    """Malformed sun attributes must not break classification or scheduling."""
    first, _second = _ids(coordinator)
    coordinator.hass.states.async_set(
        "sun.sun",
        "above_horizon",
        {"elevation": "invalid", "rising": True},
    )

    with patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now:
        mock_now.return_value.hour = 5
        assert coordinator.sun_below_threshold(5.0) is True
        assert coordinator._interval_for(
            {first: _snap(EngineState.OFFLINE_EXPECTED)}
        ) == timedelta(seconds=DAWN_POLL_SECONDS)


def test_sun_read_error_uses_clock_fallback(coordinator):
    """A failed state lookup must use the safe clock fallback."""
    with (
        patch.object(
            type(coordinator.hass.states),
            "get",
            side_effect=RuntimeError("state machine unavailable"),
        ),
        patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now,
    ):
        mock_now.return_value.hour = 22
        assert coordinator.sun_below_threshold(5.0) is True

    assert coordinator.sun_source == "clock_fallback"


def test_sun_source_tracks_active_input(coordinator):
    """Support diagnostics report the source used by the last sun check."""
    assert coordinator.sun_source == "unknown"

    with patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now:
        mock_now.return_value.hour = 22
        coordinator.sun_below_threshold(5.0)
    assert coordinator.sun_source == "clock_fallback"

    coordinator.hass.states.async_set(
        "sun.sun",
        "above_horizon",
        {"elevation": 20.0, "rising": True},
    )
    coordinator.sun_below_threshold(5.0)
    assert coordinator.sun_source == "sun.sun"


def test_clock_fallback_logs_one_warning(coordinator, caplog):
    """Repeated sun checks must not repeat the missing-entity warning."""
    first, _second = _ids(coordinator)
    with (
        patch("custom_components.solarmax.coordinator.dt_util.now") as mock_now,
        caplog.at_level(
            logging.WARNING,
            logger="custom_components.solarmax.coordinator",
        ),
    ):
        mock_now.return_value.hour = 5
        coordinator.sun_below_threshold(5.0)
        coordinator._interval_for({first: _snap(EngineState.OFFLINE_EXPECTED)})

    warnings = [
        record
        for record in caplog.records
        if record.name == "custom_components.solarmax.coordinator"
        and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1


# --- Ported: device-info properties, read from snapshot.values --------------


async def test_device_info_props_from_snapshot_values(coordinator):
    """device_model/sw_version/serial_number read from the latest
    snapshot's values via DEVICE_TYPE_MAP, with no separate fetch step."""
    first, _second = _ids(coordinator)
    coordinator.data = {
        first: _snap(
            EngineState.ONLINE,
            values={
                "TYP": {"value": 20650, "raw_value": 20650},
                "SWV": {"value": 314, "raw_value": 314},
                "BDN": {"value": 5, "raw_value": 5},
                "DIN": {"value": 123456, "raw_value": 123456},
            },
        )
    }
    assert coordinator.device_model_for(first) == "SolarMax 7TP2"
    assert coordinator.sw_version_for(first) == "314 (build 5)"
    assert coordinator.serial_number_for(first) == "123456"


async def test_device_info_props_none_without_data(coordinator):
    """Before the first poll, device-info properties read as None."""
    first, _second = _ids(coordinator)
    assert coordinator.data is None
    assert coordinator.device_model_for(first) is None
    assert coordinator.sw_version_for(first) is None
    assert coordinator.serial_number_for(first) is None


# --- Ported: engines are keyed by subentry id -------------------------------


def test_engines_are_keyed_by_subentry_id(hass, entry):
    """A real coordinator builds one engine per subentry and a shared link."""
    coordinator = SolarmaxCoordinator(hass, entry)
    assert set(coordinator.engines) == set(entry.subentries)
    assert coordinator.link is not None


# --- Ported: midnight handler -----------------------------------------------


async def test_async_handle_midnight_notifies_listeners(hass, entry):
    """The midnight callback must force listeners to re-read native_value."""
    coordinator = SolarmaxCoordinator(hass, entry)

    with patch.object(coordinator, "async_update_listeners") as notify:
        coordinator.async_handle_midnight(dt_util.now())

    notify.assert_called_once()


# --- Ported: repair-issue episodes and the dismissal window -----------------


async def test_ignored_fault_issue_stays_ignored_when_refreshed(coordinator, hass):
    """Native Ignore persists when the same stable issue is refreshed."""
    first, second = _ids(coordinator)
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 60)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=old)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
        is not None
    )

    ir.async_get(hass).async_ignore(DOMAIN, coordinator._repair_issue_id, True)

    # Same fault, further aged, on the next poll.
    older = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 120)
    coordinator.engines[first] = _StubEngine(
        _snap(EngineState.OFFLINE_FAULT, fault_since=older)
    )
    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert issue.dismissed_version is not None


async def test_deleted_issue_is_recreated_without_custom_suppression(coordinator, hass):
    """Deletion is not a substitute for native Ignore."""
    first, second = _ids(coordinator)
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 60)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=old)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    ir.async_delete_issue(hass, DOMAIN, coordinator._repair_issue_id)

    await coordinator._async_update_data()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
        is not None
    )


async def test_repair_new_episode_after_recovery_recreates_immediately(
    coordinator, hass
):
    """Recovery ends the ignored episode and the next fault is visible."""
    first, second = _ids(coordinator)
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 60)
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.OFFLINE_FAULT, fault_since=old)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    ir.async_get(hass).async_ignore(DOMAIN, coordinator._repair_issue_id, True)

    # Recovery ends the episode and clears the dismissal anchor.
    coordinator.engines[first] = _StubEngine(_snap(EngineState.ONLINE))
    await coordinator._async_update_data()

    # A brand-new fault raises immediately, with no 24h suppression left over.
    new_old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 10)
    coordinator.engines[first] = _StubEngine(
        _snap(EngineState.OFFLINE_FAULT, fault_since=new_old)
    )
    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    assert issue is not None
    assert issue.dismissed_version is None


@pytest.mark.parametrize("state", list(EngineState))
async def test_pending_repair_clears_only_on_online_snapshot(coordinator, hass, state):
    """A PAC probe cannot clear the issue before a full ONLINE snapshot."""
    first, second = _ids(coordinator)
    ir.async_create_issue(
        hass,
        DOMAIN,
        coordinator._repair_issue_id,
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="connection_issues",
        data={
            REPAIR_PENDING: 1,
            REPAIR_PENDING_ENDPOINT: "192.0.2.10:12345",
            REPAIR_PENDING_INVERTERS: first,
        },
    )
    coordinator.engines = {
        first: _StubEngine(_snap(state)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, coordinator._repair_issue_id)
    if state is EngineState.ONLINE:
        assert issue is None
    else:
        assert issue is not None
        assert issue.data[REPAIR_PENDING] == 1


async def test_pending_repair_ignores_online_polls_before_the_marker(hass, coordinator):
    """A2: only ONLINE polls after the pending marker was written verify it.

    An inverter that polled ONLINE earlier, then faulted, must not have that
    stale online history clear a same-endpoint pending repair while it is
    still faulted.
    """
    first, second = _ids(coordinator)
    issue_id = coordinator._repair_issue_id
    old = dt_util.utcnow() - timedelta(seconds=FAULT_REPAIR_SECONDS + 60)

    # 1. `first` polls ONLINE, landing in the pre-marker online history.
    coordinator.engines = {
        first: _StubEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }
    coordinator.async_set_updated_data(await coordinator._async_update_data())

    # 2. `first` faults long enough to raise the (non-pending) repair issue.
    coordinator.engines[first] = _StubEngine(
        _snap(EngineState.OFFLINE_FAULT, fault_since=old)
    )
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None

    # 3. A fix flow for the same endpoint writes the pending marker for `first`.
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="connection_issues",
        translation_placeholders=issue.translation_placeholders,
        data={
            **(issue.data or {}),
            REPAIR_PENDING: 1,
            REPAIR_PENDING_ENDPOINT: "192.0.2.10:12345",
            REPAIR_PENDING_INVERTERS: first,
        },
    )

    # 4. `first` still faulted -> the pre-marker ONLINE must not clear it.
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    # 5. `first` polls ONLINE after the marker -> the issue clears.
    coordinator.engines[first] = _StubEngine(_snap(EngineState.ONLINE))
    await coordinator._async_update_data()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_shutdown_aborts_in_flight_poll_before_taking_the_lock(coordinator):
    """A6: closing the link must abort the in-flight poll so shutdown never
    waits for the cycle lock through a whole poll budget."""
    first, second = _ids(coordinator)
    poll_started = asyncio.Event()
    released = asyncio.Event()

    class _BlockingEngine(_StubEngine):
        async def poll(self) -> EngineSnapshot:
            poll_started.set()
            # Stuck on the wire until the link is closed under us.
            await asyncio.wait_for(released.wait(), timeout=5)
            return _snap(EngineState.ONLINE)

    coordinator.link.close = AsyncMock(side_effect=lambda: released.set())
    coordinator.engines = {
        first: _BlockingEngine(_snap(EngineState.ONLINE)),
        second: _StubEngine(_snap(EngineState.ONLINE)),
    }

    cycle = asyncio.create_task(coordinator._async_update_data())
    await asyncio.wait_for(poll_started.wait(), timeout=1)
    # If shutdown took the lock first, it would wait behind the blocked poll.
    await asyncio.wait_for(coordinator.async_shutdown(), timeout=1)
    await cycle
    assert coordinator.link.close.await_count == 2
