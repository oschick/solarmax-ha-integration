"""Reconfiguration handoff tests against the single-client emulator."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solarmax import async_setup_entry
from custom_components.solarmax.configuration import validate_connection
from custom_components.solarmax.connection import (
    ConnectionEngine,
    EngineState,
    SolarmaxLink,
)
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from custom_components.solarmax.protocol import build_request, parse_response
from tests.emulator import EmulatorHandle
from tests.test_config_flow import _configured_endpoint_entry, _submit_reconfigure
from tests.test_repairs import (
    _connection_issue,
    _create_connection_issue,
    _submit_repair,
)


@pytest.fixture
def proposed_emulator(socket_enabled):
    handle = EmulatorHandle()
    handle.start()
    yield handle
    handle.stop()


async def _loaded_entry(hass, emulator):
    host, port = emulator.addr
    entry = _configured_endpoint_entry(host=host, port=port, address=1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert (await entry.runtime_data.engine.poll()).state is EngineState.ONLINE
    return entry


async def test_reconfigure_emulator_success(hass, emulator, proposed_emulator):
    """Real HA unload and setup transfer the connection to the proposed endpoint."""
    entry = await _loaded_entry(hass, emulator)
    old_engine = entry.runtime_data.engine
    host, port = proposed_emulator.addr
    try:
        result = await asyncio.wait_for(
            _submit_reconfigure(hass, entry, host=host, port=port), 5
        )
        assert result["type"] is FlowResultType.ABORT
        assert entry.data["port"] == port
        assert entry.runtime_data.engine is not old_engine
        assert (await entry.runtime_data.engine.poll()).state is EngineState.ONLINE
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_emulator_probe_failure(hass, emulator, proposed_emulator):
    """Rejected probe leaves the original engine able to reconnect."""
    entry = await _loaded_entry(hass, emulator)
    old_engine = entry.runtime_data.engine
    proposed_emulator.inject("corrupt_crc")
    host, port = proposed_emulator.addr
    try:
        result = await _submit_reconfigure(hass, entry, host=host, port=port)
        assert result["errors"] == {"base": "cannot_connect"}
        assert entry.data["port"] == emulator.addr[1]
        assert entry.runtime_data.engine is old_engine
        assert (await old_engine.poll()).state is EngineState.ONLINE
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_emulator_cancel_validation(
    hass, emulator, proposed_emulator
):
    """Cancelling while the old engine is handed off releases its polling lock."""
    entry = await _loaded_entry(hass, emulator)
    old_engine = entry.runtime_data.engine
    validated = asyncio.Event()

    async def blocked_probe(**kwargs):
        await validate_connection(**kwargs)
        validated.set()
        await asyncio.Event().wait()

    host, port = proposed_emulator.addr
    try:
        with patch(
            "custom_components.solarmax.config_flow.validate_connection",
            side_effect=blocked_probe,
        ):
            submit = asyncio.create_task(
                _submit_reconfigure(hass, entry, host=host, port=port)
            )
            await asyncio.wait_for(validated.wait(), 5)
            submit.cancel()
            with pytest.raises(asyncio.CancelledError):
                await submit
        assert entry.data["port"] == emulator.addr[1]
        assert (await old_engine.poll()).state is EngineState.ONLINE
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_emulator_cancel_failed_activation_restores(
    hass, emulator, proposed_emulator
):
    """After actual unload, cancelled setup failure restores a usable old endpoint."""
    entry = await _loaded_entry(hass, emulator)
    old_runtime = entry.runtime_data
    activation_started, release_activation = asyncio.Event(), asyncio.Event()
    restoration_started, release_restoration = asyncio.Event(), asyncio.Event()
    host, port = proposed_emulator.addr

    async def setup(hass, entry):
        if entry.data["port"] == port:
            assert getattr(entry, "runtime_data", None) is not old_runtime
            activation_started.set()
            await release_activation.wait()
            return False
        restoration_started.set()
        await release_restoration.wait()
        return await async_setup_entry(hass, entry)

    try:
        with patch("custom_components.solarmax.async_setup_entry", side_effect=setup):
            submit = asyncio.create_task(
                _submit_reconfigure(hass, entry, host=host, port=port)
            )
            await asyncio.wait_for(activation_started.wait(), 5)
            submit.cancel()
            await asyncio.sleep(0)
            submit.cancel()
            release_activation.set()
            await asyncio.wait_for(restoration_started.wait(), 5)
            submit.cancel()
            await asyncio.sleep(0)
            submit.cancel()
            release_restoration.set()
            with pytest.raises(asyncio.CancelledError):
                await submit
        assert entry.data["port"] == emulator.addr[1]
        assert entry.runtime_data is not old_runtime
        assert (await entry.runtime_data.engine.poll()).state is EngineState.ONLINE
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_validation_handoff_releases_single_client_slot(emulator):
    """A validation client owns the sole socket slot only during handoff."""
    host, port = emulator.addr
    link = SolarmaxLink(host, port)
    engine = ConnectionEngine(link, address=1, sun_below=lambda: False)
    assert (await engine.poll()).state is EngineState.ONLINE

    async with engine.validation_handoff():
        probe = SolarmaxLink(host, port)
        try:
            raw = await probe.request(build_request(1, ["PAC"]))
            assert parse_response(raw, verify_checksum=True)["PAC"]["value"] >= 0
        finally:
            await probe.close()

    assert (await engine.poll()).state is EngineState.ONLINE
    await engine.close()


@pytest.mark.parametrize("changed", [False, True])
async def test_repair_emulator_waits_for_full_poll(
    hass, emulator, proposed_emulator, changed
):
    """Changed and unchanged repairs retain the issue until a real full poll."""
    entry = await _loaded_entry(hass, emulator)
    _create_connection_issue(hass, entry)
    before_poll, release_poll = asyncio.Event(), asyncio.Event()
    original_update = SolarmaxCoordinator._async_update_data

    async def gated_update(coordinator):
        before_poll.set()
        await release_poll.wait()
        return await original_update(coordinator)

    host, port = (proposed_emulator if changed else emulator).addr
    try:
        with patch.object(SolarmaxCoordinator, "_async_update_data", gated_update):
            task = asyncio.create_task(
                _submit_repair(hass, entry, host=host, port=port)
            )
            await asyncio.wait_for(before_poll.wait(), 5)
            assert _connection_issue(hass, entry).data["verification_pending"] == 1
            release_poll.set()
            result = await asyncio.wait_for(task, 5)
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert entry.data["port"] == port
        assert entry.runtime_data.data.state is EngineState.ONLINE
        assert _connection_issue(hass, entry) is None
    finally:
        release_poll.set()
        await hass.config_entries.async_unload(entry.entry_id)


async def test_repair_emulator_unreachable_endpoint_stays_open(
    hass, emulator, unused_tcp_port
):
    """A refused probe preserves the entry; only its recovered full poll clears."""
    entry = await _loaded_entry(hass, emulator)
    _create_connection_issue(hass, entry)
    old_runtime = entry.runtime_data
    try:
        result = await _submit_repair(
            hass, entry, host="127.0.0.1", port=unused_tcp_port
        )
        assert result["errors"] == {"base": "cannot_connect"}
        assert entry.data["port"] == emulator.addr[1]
        assert entry.runtime_data is old_runtime
        assert _connection_issue(hass, entry) is not None
        await entry.runtime_data.async_refresh()
        assert entry.runtime_data.data.state is EngineState.ONLINE
        assert _connection_issue(hass, entry) is None
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_repair_emulator_activation_rollback_full_poll_clears(
    hass, emulator, proposed_emulator
):
    """Rollback's successful full poll verifies recovery and must stay cleared."""
    entry = await _loaded_entry(hass, emulator)
    _create_connection_issue(hass, entry)
    before_restore, release_restore = asyncio.Event(), asyncio.Event()
    host, port = proposed_emulator.addr

    async def setup(hass, entry):
        if entry.data["port"] == port:
            return False
        before_restore.set()
        await release_restore.wait()
        return await async_setup_entry(hass, entry)

    try:
        with patch("custom_components.solarmax.async_setup_entry", side_effect=setup):
            task = asyncio.create_task(
                _submit_repair(hass, entry, host=host, port=port)
            )
            await asyncio.wait_for(before_restore.wait(), 5)
            assert _connection_issue(hass, entry).data["verification_pending"] == 1
            release_restore.set()
            result = await asyncio.wait_for(task, 5)
        assert result["errors"] == {"base": "reload_failed"}
        assert entry.data["port"] == emulator.addr[1]
        assert entry.runtime_data.data.state is EngineState.ONLINE
        assert _connection_issue(hass, entry) is None
    finally:
        release_restore.set()
        await hass.config_entries.async_unload(entry.entry_id)


async def test_disabled_repair_emulator_waits_until_enabled(hass, emulator):
    """A disabled repaired entry stays pending until enabled and polled."""
    host, port = emulator.addr
    entry = _configured_endpoint_entry(host="192.0.2.10", port=12345, address=1)
    entry.add_to_hass(hass)
    object.__setattr__(entry, "disabled_by", ConfigEntryDisabler.USER)
    _create_connection_issue(hass, entry)
    result = await _submit_repair(hass, entry, host=host, port=port)
    assert result["reason"] == "repair_pending_verification"
    assert entry.disabled_by is ConfigEntryDisabler.USER
    assert getattr(entry, "runtime_data", None) is None
    assert _connection_issue(hass, entry).data["verification_pending"] == 1
    object.__setattr__(entry, "disabled_by", None)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert entry.runtime_data.data.state is EngineState.ONLINE
        assert _connection_issue(hass, entry) is None
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
