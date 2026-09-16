"""Add and reconfigure inverter subentries."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from custom_components.solarmax.configuration import CannotConnect
from custom_components.solarmax.const import DOMAIN
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from tests.helpers import endpoint_entry

INVERTER_INPUT = {
    "address": 2,
    "device_name": "Garage",
    "twilight_elevation_threshold": 5,
    "night_keep_values": False,
}


@pytest.fixture
def loaded_entry(hass: HomeAssistant):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1,))
    entry.add_to_hass(hass)
    runtime = MagicMock()
    runtime.validation_handoff = MagicMock()
    runtime.validation_handoff.return_value.__aenter__ = AsyncMock()
    runtime.validation_handoff.return_value.__aexit__ = AsyncMock(return_value=False)
    runtime.async_refresh_repair_issue = MagicMock()
    entry.runtime_data = runtime
    entry.mock_state(hass, config_entries.ConfigEntryState.LOADED)
    return entry


async def _start(hass, entry, source="user", subentry_id=None):
    context = {"source": source}
    if subentry_id is not None:
        context["subentry_id"] = subentry_id
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "inverter"), context=context
    )


async def test_add_inverter_probes_through_handoff_and_creates_subentry(
    hass, loaded_entry
):
    result = await _start(hass, loaded_entry)
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.solarmax.config_flow.validate_connection") as probe:
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], INVERTER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    probe.assert_awaited_once()
    assert probe.await_args.kwargs["address"] == 2
    assert probe.await_args.kwargs["response_timeout"] == 3.5
    loaded_entry.runtime_data.validation_handoff.assert_called_once()
    added = [s for s in loaded_entry.subentries.values() if s.unique_id == "2"]
    assert len(added) == 1 and added[0].title == "Garage"


async def test_add_inverter_refuses_failed_probe(hass, loaded_entry):
    result = await _start(hass, loaded_entry)
    with patch(
        "custom_components.solarmax.config_flow.validate_connection",
        side_effect=CannotConnect,
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], INVERTER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert all(s.unique_id != "2" for s in loaded_entry.subentries.values())


async def test_add_inverter_rejects_duplicate_address(hass, loaded_entry):
    result = await _start(hass, loaded_entry)
    with patch("custom_components.solarmax.config_flow.validate_connection") as probe:
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**INVERTER_INPUT, "address": 1}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    probe.assert_not_awaited()


async def test_add_inverter_schedules_reload_when_entry_not_loaded(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=())
    entry.add_to_hass(hass)
    entry.mock_state(hass, config_entries.ConfigEntryState.NOT_LOADED)
    result = await _start(hass, entry)
    with (
        patch("custom_components.solarmax.config_flow.validate_connection"),
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], INVERTER_INPUT
        )
        # The reload is deferred until the manager commits the subentry.
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    reload.assert_called_once_with(entry.entry_id)


async def test_add_inverter_reload_sees_committed_subentry_when_not_loaded(hass):
    """A1: the deferred reload runs after the new subentry is committed, so the
    rebuilt coordinator polls every inverter and exactly one reload runs."""
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1,))
    entry.add_to_hass(hass)
    entry.mock_state(hass, config_entries.ConfigEntryState.NOT_LOADED)

    built = asyncio.Event()
    release = asyncio.Event()
    engines_at_build: dict[str, set[str]] = {}

    async def first_refresh(coordinator):
        engines_at_build["ids"] = set(coordinator.engines)
        coordinator.sensor_setup_complete = True
        built.set()
        await release.wait()

    result = await _start(hass, entry)
    with (
        patch("custom_components.solarmax.config_flow.validate_connection"),
        patch.object(
            SolarmaxCoordinator, "async_config_entry_first_refresh", first_refresh
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
        patch.object(
            hass.config_entries,
            "async_schedule_reload",
            wraps=hass.config_entries.async_schedule_reload,
        ) as reload,
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], INVERTER_INPUT
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await asyncio.wait_for(built.wait(), 5)
        release.set()
        await hass.async_block_till_done()

    reload.assert_called_once_with(entry.entry_id)
    # Both address 1 and the newly added address 2 are present when the reload
    # builds the coordinator: the subentry was committed first.
    assert len(engines_at_build["ids"]) == 2


async def test_reconfigure_address_schedules_reload_when_entry_not_loaded(hass):
    """A7: an address change on an idle entry reloads through the same path."""
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1,))
    entry.add_to_hass(hass)
    entry.mock_state(hass, config_entries.ConfigEntryState.NOT_LOADED)
    sub = next(iter(entry.subentries.values()))
    result = await _start(hass, entry, "reconfigure", sub.subentry_id)
    with (
        patch("custom_components.solarmax.config_flow.validate_connection"),
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**dict(sub.data), "address": 5}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    reload.assert_called_once_with(entry.entry_id)


async def test_reconfigure_name_only_updates_title_and_device(hass, loaded_entry):
    sub = next(iter(loaded_entry.subentries.values()))
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=loaded_entry.entry_id,
        config_subentry_id=sub.subentry_id,
        identifiers={(DOMAIN, sub.subentry_id)},
        name="Existing inverter",
    )
    result = await _start(hass, loaded_entry, "reconfigure", sub.subentry_id)
    with patch("custom_components.solarmax.config_flow.validate_connection") as probe:
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**dict(sub.data), "device_name": "Roof"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    probe.assert_not_awaited()
    assert loaded_entry.subentries[sub.subentry_id].title == "Roof"
    assert dr.async_get(hass).async_get(device.id).name == "Roof"
    loaded_entry.runtime_data.async_refresh_repair_issue.assert_called_once()


async def test_reconfigure_address_probes_and_updates_unique_id(hass, loaded_entry):
    sub = next(iter(loaded_entry.subentries.values()))
    result = await _start(hass, loaded_entry, "reconfigure", sub.subentry_id)
    with patch("custom_components.solarmax.config_flow.validate_connection") as probe:
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**dict(sub.data), "address": 5}
        )
    assert result["reason"] == "reconfigure_successful"
    probe.assert_awaited_once()
    updated = loaded_entry.subentries[sub.subentry_id]
    assert updated.unique_id == "5" and updated.data["address"] == 5


async def test_reconfigure_address_conflict_aborts(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    entry.mock_state(hass, config_entries.ConfigEntryState.LOADED)
    first = next(s for s in entry.subentries.values() if s.unique_id == "1")
    result = await _start(hass, entry, "reconfigure", first.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**dict(first.data), "address": 2}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
