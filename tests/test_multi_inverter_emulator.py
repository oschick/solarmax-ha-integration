"""Two inverters on one emulated endpoint through the real integration."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.solarmax.connection import EngineState, LinkFailure
from custom_components.solarmax.const import DOMAIN, FAULT_POLL_SECONDS
from tests.helpers import endpoint_entry


def _daytime(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sun.sun", "above_horizon", {"elevation": 45.0, "rising": False}
    )


def _night(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sun.sun", "below_horizon", {"elevation": -12.0, "rising": False}
    )


async def _loaded(hass: HomeAssistant, emulator, inverters=(1, 2), **options):
    host, port = emulator.addr
    entry = endpoint_entry(host=host, port=port, inverters=inverters, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_two_inverters_get_two_devices_and_entity_sets(hass, dual_emulator):
    dual_emulator.set_noise(False)
    dual_emulator.state_for(2).pac = 1234
    entry = await _loaded(hass, dual_emulator)
    coordinator = entry.runtime_data
    first, second = coordinator.subentry_ids()
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert {d.config_subentry_id for d in devices} == {first, second}
    assert hass.states.get("sensor.existing_inverter_pac").state == "1500.0"
    assert hass.states.get("sensor.inverter_2_pac").state == "617.0"
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {e.config_subentry_id for e in entities} == {first, second}


async def test_silent_inverter_leaves_the_other_online(hass, dual_emulator):
    _daytime(hass)
    entry = await _loaded(hass, dual_emulator, update_interval=120)
    coordinator = entry.runtime_data
    first, second = coordinator.subentry_ids()
    dual_emulator.set_dark(2, True)
    snapshots = await coordinator._async_update_data()
    assert snapshots[first].state is EngineState.ONLINE
    # Daytime silence: startup-grace reconnecting first, fault after 150 s.
    assert snapshots[second].state in (EngineState.UNKNOWN, EngineState.OFFLINE_FAULT)
    assert (
        snapshots[second].state is EngineState.OFFLINE_FAULT
        or snapshots[second].reconnecting
    )
    assert snapshots[second].link_failure is LinkFailure.EXCHANGE
    assert coordinator.update_interval == timedelta(seconds=FAULT_POLL_SECONDS)


async def test_unreachable_endpoint_fails_both_without_extra_attempts(
    hass, dual_emulator
):
    _daytime(hass)
    entry = await _loaded(hass, dual_emulator)
    coordinator = entry.runtime_data
    await coordinator.link.disconnect()
    attempts_before = coordinator.link.attempts
    with patch("asyncio.open_connection", side_effect=ConnectionRefusedError()):
        snapshots = await coordinator._async_update_data()
    assert all(s.link_failure is LinkFailure.CONNECT for s in snapshots.values())
    # A refused connect is not retried and the second engine never connects.
    assert coordinator.link.attempts - attempts_before == 1


async def test_removing_a_subentry_reloads_and_drops_its_entities(hass, dual_emulator):
    entry = await _loaded(hass, dual_emulator)
    second = next(s for s in entry.subentries.values() if s.unique_id == "2")
    hass.config_entries.async_remove_subentry(entry, second.subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert list(entry.runtime_data.engines) == [
        s.subentry_id for s in entry.subentries.values()
    ]
    assert hass.states.get("sensor.inverter_2_pac") is None


async def test_removing_last_inverter_raises_issue_and_adding_one_clears_it(
    hass, emulator
):
    entry = await _loaded(hass, emulator, inverters=(1,))
    only = next(iter(entry.subentries.values()))
    hass.config_entries.async_remove_subentry(entry, only.subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"no_inverter_{entry.entry_id}")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "inverter"), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "address": 1,
            "device_name": "Roof",
            "twilight_elevation_threshold": 5,
            "night_keep_values": False,
        },
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"].value == "create_entry"
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"no_inverter_{entry.entry_id}")
        is None
    )
    assert hass.states.get("sensor.roof_pac") is not None


async def test_night_policy_and_midnight_rollover_are_per_inverter(hass, dual_emulator):
    """One inverter keeps values overnight, its neighbour does not."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from tests.helpers import GLOBAL_OPTION_DEFAULTS, inverter_subentry

    dual_emulator.set_noise(False)
    host, port = dual_emulator.addr
    # Setup, polling, and the night assertions all run in real time: freezing
    # time here would freeze the event loop clock that asyncio.timeout() uses
    # for the emulator's TCP I/O, hanging the poll once an address is dark.
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=host,
        data={"host": host, "port": port},
        options=dict(GLOBAL_OPTION_DEFAULTS),
        unique_id=f"{host}:{port}",
        version=3,
        minor_version=1,
        subentries_data=[
            inverter_subentry(1, "Keep", night_keep=True),
            inverter_subentry(2, "Drop", night_keep=False),
        ],
    )
    entry.add_to_hass(hass)
    _daytime(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.keep_kdy").state == "8.5"
    assert hass.states.get("sensor.drop_kdy").state == "8.5"

    _night(hass)
    dual_emulator.dark = True
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.keep_kdy").state == "8.5"
    assert hass.states.get("sensor.keep_pac").state == "0"
    assert hass.states.get("sensor.drop_kdy").state == "unavailable"
    assert hass.states.get("sensor.drop_pac").state == "unavailable"

    # No socket traffic happens inside this block, so freezing time is safe.
    tomorrow = (dt_util.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=1, microsecond=0
    )
    with freeze_time(tomorrow):
        coordinator.async_handle_midnight(dt_util.now())
        await hass.async_block_till_done()
        assert hass.states.get("sensor.keep_kdy").state == "0"
        assert hass.states.get("sensor.keep_kt0").state == "28500"
        assert hass.states.get("sensor.drop_kdy").state == "unavailable"


async def test_single_inverter_migrated_entry_keeps_entity_ids(hass, emulator):
    """A 1.4.0 entry loads on 1.5.0 with the same entity IDs and device."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    emulator.set_noise(False)
    host, port = emulator.addr
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=1,
        title="Roof",
        unique_id=f"{host}:{port}:1",
        data={"host": host, "port": port, "address": 1, "device_name": "Roof"},
        options={
            "update_interval": 30,
            "verify_checksum": True,
            "twilight_elevation_threshold": 5,
            "night_keep_values": False,
        },
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Roof",
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}-pac",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="roof_pac",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 3
    assert hass.states.get("sensor.roof_pac").state == "1500.0"
    migrated = dr.async_get(hass).async_get(device.id)
    sub = next(iter(entry.subentries.values()))
    assert migrated.identifiers == {(DOMAIN, sub.subentry_id)}
