"""Reconfiguration handoff tests against the single-client emulator."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solarmax import async_setup_entry
from custom_components.solarmax.configuration import validate_connection
from custom_components.solarmax.connection import (
    ConnectionEngine,
    EngineState,
    SolarmaxLink,
)
from custom_components.solarmax.protocol import build_request, parse_response
from tests.emulator import EmulatorHandle
from tests.test_config_flow import _configured_endpoint_entry, _submit_reconfigure


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
