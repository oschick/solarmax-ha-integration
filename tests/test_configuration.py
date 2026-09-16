"""Entry and subentry helpers."""

from unittest.mock import patch

import pytest

from custom_components.solarmax.configuration import (
    CannotConnect,
    endpoint_unique_id,
    find_address_conflict,
    inverter_fingerprint,
    inverter_subentries,
    validate_endpoint,
)
from custom_components.solarmax.connection import EngineState
from tests.helpers import endpoint_entry


def test_endpoint_unique_id_is_host_and_port():
    assert endpoint_unique_id("192.0.2.10", 12345) == "192.0.2.10:12345"


def test_inverter_subentries_returns_only_inverters(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    subentries = inverter_subentries(entry)
    assert sorted(sub.data["address"] for sub in subentries.values()) == [1, 2]
    assert all(sub.subentry_type == "inverter" for sub in subentries.values())


def test_fingerprint_ignores_device_name(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1,))
    entry.add_to_hass(hass)
    before = inverter_fingerprint(entry)
    subentry = next(iter(inverter_subentries(entry).values()))
    hass.config_entries.async_update_subentry(entry, subentry, title="Renamed")
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, "device_name": "Renamed"}
    )
    assert inverter_fingerprint(entry) == before
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, "twilight_elevation_threshold": 9}
    )
    assert inverter_fingerprint(entry) != before


def test_find_address_conflict(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    two = find_address_conflict(entry, 2)
    assert two is not None and two.data["address"] == 2
    assert find_address_conflict(entry, 2, exclude_subentry_id=two.subentry_id) is None
    assert find_address_conflict(entry, 3) is None


def _runtime_with_states(entry, states: dict[int, EngineState]) -> None:
    """Attach a runtime whose data maps each inverter address to a state."""
    from types import SimpleNamespace

    by_address = {int(s.data["address"]): sid for sid, s in entry.subentries.items()}
    data = {
        by_address[address]: SimpleNamespace(state=state)
        for address, state in states.items()
    }
    online = {sid for sid, snap in data.items() if snap.state is EngineState.ONLINE}
    entry.runtime_data = SimpleNamespace(data=data, online_subentry_ids=lambda: online)


def _probe(**answers: bool):
    """Patch probe_addresses to report a fixed answer per address."""
    return patch(
        "custom_components.solarmax.configuration.probe_addresses",
        return_value={int(address): value for address, value in answers.items()},
    )


async def test_validate_endpoint_requires_every_online_inverter(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    _runtime_with_states(entry, {1: EngineState.ONLINE, 2: EngineState.ONLINE})
    with _probe(**{"1": True, "2": False}), pytest.raises(CannotConnect):
        await validate_endpoint(entry, "192.0.2.20", 12345)


async def test_validate_endpoint_tolerates_a_faulted_inverter(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    _runtime_with_states(entry, {1: EngineState.ONLINE, 2: EngineState.OFFLINE_FAULT})
    with _probe(**{"1": True, "2": False}) as probe:
        await validate_endpoint(entry, "192.0.2.20", 12345)
    # A single link probes every address in one pass.
    assert probe.await_count == 1
    assert sorted(probe.await_args.args[1]) == [1, 2]


async def test_validate_endpoint_tolerates_expected_offline_sibling(hass):
    """An OFFLINE_EXPECTED sibling may stay silent while a faulted one answers."""
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    _runtime_with_states(
        entry, {1: EngineState.OFFLINE_EXPECTED, 2: EngineState.OFFLINE_FAULT}
    )
    with _probe(**{"1": False, "2": True}):
        await validate_endpoint(entry, "192.0.2.20", 12345)


async def test_validate_endpoint_requires_a_silent_online_sibling(hass):
    """An ONLINE sibling that stays silent fails the probe."""
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    _runtime_with_states(entry, {1: EngineState.ONLINE, 2: EngineState.OFFLINE_FAULT})
    with _probe(**{"1": False, "2": True}), pytest.raises(CannotConnect):
        await validate_endpoint(entry, "192.0.2.20", 12345)


async def test_validate_endpoint_needs_one_answer_when_all_faulted(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    _runtime_with_states(
        entry, {1: EngineState.OFFLINE_FAULT, 2: EngineState.OFFLINE_FAULT}
    )
    with _probe(**{"1": False, "2": True}):
        await validate_endpoint(entry, "192.0.2.20", 12345)
    with _probe(**{"1": False, "2": False}), pytest.raises(CannotConnect):
        await validate_endpoint(entry, "192.0.2.20", 12345)


async def test_validate_endpoint_without_runtime_needs_one_answer(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=(1, 2))
    entry.add_to_hass(hass)
    with _probe(**{"1": True, "2": False}):
        await validate_endpoint(entry, "192.0.2.20", 12345)
    with _probe(**{"1": False, "2": False}), pytest.raises(CannotConnect):
        await validate_endpoint(entry, "192.0.2.20", 12345)
