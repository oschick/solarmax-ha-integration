"""Test the Solarmax integration initialization."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarmax import (
    _migrate_v2_to_v3,
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.solarmax.configuration import inverter_fingerprint
from custom_components.solarmax.const import (
    CONF_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_NIGHT_KEEP_VALUES,
    CONF_PORT,
    CONF_RESPONSE_TIMEOUT,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    DEFAULT_RESPONSE_TIMEOUT,
    DOMAIN,
)
from custom_components.solarmax.coordinator import SolarmaxCoordinator
from custom_components.solarmax.sensor import _make_device_registry_updater
from tests.helpers import endpoint_entry, inverter_subentry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock version 3 endpoint entry with a single inverter."""
    return endpoint_entry(host="192.168.1.100", port=12345, entry_id="test_entry")


def _legacy_entry(
    *,
    version: int = 1,
    minor_version: int = 1,
    data_update: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    data = {
        CONF_HOST: "192.0.2.10",
        CONF_PORT: 12345,
        CONF_DEVICE_NAME: "Roof",
        CONF_UPDATE_INTERVAL: 30,
    }
    data.update(data_update or {})
    return MockConfigEntry(
        domain=DOMAIN,
        version=version,
        minor_version=minor_version,
        title="Roof",
        unique_id="192.0.2.10:12345",
        data=data,
        options=options or {},
    )


def _v2_entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=1,
        title="Roof",
        unique_id="192.0.2.10:12345:1",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 12345,
            CONF_ADDRESS: 1,
            CONF_DEVICE_NAME: "Roof",
        },
        options={
            CONF_UPDATE_INTERVAL: 30,
            CONF_VERIFY_CHECKSUM: True,
            CONF_TWILIGHT_ELEVATION_THRESHOLD: 7,
            CONF_NIGHT_KEEP_VALUES: True,
            **options,
        },
    )


def _seed_registry(hass, entry):
    """Create the device and two entities exactly as 1.4.0 registered them."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Roof",
    )
    entity_registry = er.async_get(hass)
    pac = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}-pac",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="roof_pac",
    )
    kt0 = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}-kt0",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="roof_kt0",
    )
    return device, pac, kt0


def _assert_migrated(
    hass, entry, device, pac, kt0, *, twilight: float = 7, night_keep: bool = True
):
    subentries = [
        sub for sub in entry.subentries.values() if sub.subentry_type == "inverter"
    ]
    assert len(subentries) == 1
    sub = subentries[0]
    assert sub.unique_id == "1"
    assert sub.title == "Roof"
    assert dict(sub.data) == {
        CONF_ADDRESS: 1,
        CONF_DEVICE_NAME: "Roof",
        CONF_TWILIGHT_ELEVATION_THRESHOLD: twilight,
        CONF_NIGHT_KEEP_VALUES: night_keep,
    }
    assert entry.version == 3 and entry.minor_version == 1
    assert entry.unique_id == "192.0.2.10:12345"
    assert dict(entry.data) == {CONF_HOST: "192.0.2.10", CONF_PORT: 12345}
    assert dict(entry.options) == {
        CONF_UPDATE_INTERVAL: 30,
        CONF_VERIFY_CHECKSUM: True,
        CONF_RESPONSE_TIMEOUT: DEFAULT_RESPONSE_TIMEOUT,
    }
    assert entry.title == "Roof"
    entity_registry = er.async_get(hass)
    for original, key in ((pac, "pac"), (kt0, "kt0")):
        migrated = entity_registry.async_get(original.entity_id)
        assert migrated is not None
        assert migrated.unique_id == f"{sub.subentry_id}-{key}"
        assert migrated.config_subentry_id == sub.subentry_id
    migrated_device = dr.async_get(hass).async_get(device.id)
    assert migrated_device is not None
    assert migrated_device.identifiers == {(DOMAIN, sub.subentry_id)}
    assert migrated_device.config_subentry_id == sub.subentry_id


async def test_migrate_v1_splits_connection_data_and_options(hass):
    entry = _legacy_entry()
    entry.add_to_hass(hass)
    device, pac, kt0 = _seed_registry(hass, entry)
    assert await async_migrate_entry(hass, entry)
    _assert_migrated(hass, entry, device, pac, kt0, twilight=5, night_keep=False)


async def test_migrate_v1_keeps_existing_option_value(hass):
    entry = _legacy_entry(
        data_update={CONF_UPDATE_INTERVAL: 30},
        options={CONF_UPDATE_INTERVAL: 45},
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.options[CONF_UPDATE_INTERVAL] == 45


async def test_migrate_v2_creates_subentry_and_moves_registry_records(hass):
    entry = _v2_entry()
    entry.add_to_hass(hass)
    device, pac, kt0 = _seed_registry(hass, entry)
    assert await async_migrate_entry(hass, entry)
    _assert_migrated(hass, entry, device, pac, kt0)


async def test_migrate_v1_reaches_v3_in_one_call(hass):
    entry = _legacy_entry(
        data_update={
            CONF_TWILIGHT_ELEVATION_THRESHOLD: 7,
            CONF_NIGHT_KEEP_VALUES: True,
        }
    )
    entry.add_to_hass(hass)
    device, pac, kt0 = _seed_registry(hass, entry)
    assert await async_migrate_entry(hass, entry)
    _assert_migrated(hass, entry, device, pac, kt0)


@pytest.mark.parametrize(
    "failing", ["_reconcile_entities", "_reconcile_device", "final_update"]
)
async def test_migrate_v2_retries_after_partial_failure(hass, failing):
    """A crash after any persistent step converges on the next attempt."""
    entry = _v2_entry()
    entry.add_to_hass(hass)
    device, pac, kt0 = _seed_registry(hass, entry)
    import custom_components.solarmax as component

    if failing == "final_update":
        # Subentry created, registry moved, then the version-3 write fails.
        target = patch.object(
            hass.config_entries, "async_update_entry", side_effect=RuntimeError("boom")
        )
    else:
        target = patch.object(component, failing, side_effect=RuntimeError("boom"))
    with target, pytest.raises(RuntimeError):
        await async_migrate_entry(hass, entry)
    assert entry.version == 2  # the version bump never ran
    if failing == "final_update":
        # Only the new device identifier remains; nothing is left to reconcile.
        sub = next(iter(entry.subentries.values()))
        assert dr.async_get(hass).async_get(device.id).identifiers == {
            (DOMAIN, sub.subentry_id)
        }
    assert await async_migrate_entry(hass, entry)
    _assert_migrated(hass, entry, device, pac, kt0)


async def test_migrate_is_idempotent_on_a_migrated_entry(hass):
    entry = _v2_entry()
    entry.add_to_hass(hass)
    device, pac, kt0 = _seed_registry(hass, entry)
    assert await async_migrate_entry(hass, entry)
    hass.config_entries.async_update_entry(entry, version=2)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_ADDRESS: 1, CONF_DEVICE_NAME: "Roof"}
    )
    # Re-run the reconciliation step directly; it must converge, not duplicate.
    _migrate_v2_to_v3(hass, entry)
    _assert_migrated(hass, entry, device, pac, kt0)


async def test_migrate_future_major_version_is_rejected(hass):
    entry = _legacy_entry(version=4)
    entry.add_to_hass(hass)
    assert not await async_migrate_entry(hass, entry)


async def test_migrate_future_minor_version_is_rejected(hass):
    entry = _legacy_entry(version=3, minor_version=2)
    entry.add_to_hass(hass)
    assert not await async_migrate_entry(hass, entry)
    assert (entry.version, entry.minor_version) == (3, 2)


async def test_subentry_change_reloads_entry(hass, emulator):
    host, port = emulator.addr
    entry = endpoint_entry(host=host, port=port, inverters=(1,))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    sub = next(iter(entry.subentries.values()))
    try:
        with patch.object(hass.config_entries, "async_schedule_reload") as reload:
            hass.config_entries.async_update_subentry(entry, sub, title="Renamed")
            await hass.async_block_till_done()
            reload.assert_not_called()
            hass.config_entries.async_update_subentry(
                entry, sub, data={**sub.data, CONF_TWILIGHT_ELEVATION_THRESHOLD: 9}
            )
            await hass.async_block_till_done()
            reload.assert_called_once_with(entry.entry_id)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_with_no_inverters_loads_idle(hass):
    entry = endpoint_entry(host="192.0.2.10", port=12345, inverters=())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.engines == {}


async def test_setup_entry_success(hass: HomeAssistant, emulator):
    """Real setup over the emulator builds one engine and its entities."""
    host, port = emulator.addr
    entry = endpoint_entry(host=host, port=port)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(entry.runtime_data.engines) == 1
    assert hass.states.get("sensor.existing_inverter_pac") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_entry_update_does_not_reload_implicitly(
    mock_coordinator_class, hass, mock_config_entry
):
    """Submitting flows own reloads, so a title update cannot trigger a second one."""
    mock_config_entry.add_to_hass(hass)
    coordinator = mock_coordinator_class.return_value
    coordinator.async_config_entry_first_refresh = AsyncMock()
    # A title update leaves the inverter fingerprint unchanged.
    coordinator.fingerprint = inverter_fingerprint(mock_config_entry)
    with (
        patch.object(hass.config_entries, "async_forward_entry_setups"),
        patch.object(hass.config_entries, "async_reload") as reload,
    ):
        await async_setup_entry(hass, mock_config_entry)
        hass.config_entries.async_update_entry(mock_config_entry, title="Garage")
        await hass.async_block_till_done()
    assert mock_config_entry.title == "Garage"
    reload.assert_not_awaited()


@patch("custom_components.solarmax.async_track_time_change")
@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_registers_midnight_listener_when_night_keep_values_enabled(
    mock_coordinator_class, mock_track_time_change, hass: HomeAssistant
):
    """A subentry with night_keep_values=True must register the midnight callback."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Roof",
        data={CONF_HOST: "192.168.1.100", CONF_PORT: 12345},
        options={CONF_UPDATE_INTERVAL: 30},
        unique_id="192.168.1.100:12345:night",
        version=3,
        minor_version=1,
        subentries_data=[inverter_subentry(1, "Roof", night_keep=True)],
    )
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_class.return_value = mock_coordinator

    with patch.object(hass.config_entries, "async_forward_entry_setups"):
        await async_setup_entry(hass, entry)

    mock_track_time_change.assert_called_once_with(
        hass, mock_coordinator.async_handle_midnight, hour=0, minute=0, second=0
    )


@patch("custom_components.solarmax.async_track_time_change")
@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_failed_setup_does_not_register_midnight_listener(
    mock_coordinator_class, mock_track_time_change, hass: HomeAssistant
):
    """A failed platform setup must not leave a midnight callback behind."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Roof",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 12345},
        options={CONF_UPDATE_INTERVAL: 30},
        unique_id="192.0.2.10:12345",
        version=3,
        minor_version=1,
        subentries_data=[inverter_subentry(1, "Roof", night_keep=True)],
    )
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator.async_shutdown = AsyncMock()
    mock_coordinator_class.return_value = mock_coordinator

    with (
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=RuntimeError("platform setup failed"),
        ),
        pytest.raises(RuntimeError, match="platform setup failed"),
    ):
        await async_setup_entry(hass, entry)

    mock_track_time_change.assert_not_called()


@patch("custom_components.solarmax.async_track_time_change")
@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_skips_midnight_listener_by_default(
    mock_coordinator_class,
    mock_track_time_change,
    hass: HomeAssistant,
    mock_config_entry,
):
    """night_keep_values absent (default False) must not register the callback."""
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_class.return_value = mock_coordinator

    with patch.object(hass.config_entries, "async_forward_entry_setups"):
        await async_setup_entry(hass, mock_config_entry)

    mock_track_time_change.assert_not_called()


async def test_unload_entry_success(hass: HomeAssistant, mock_config_entry):
    """Successful unload shuts the coordinator down once and unloads platforms."""
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=True
    ) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)

    assert result is True
    coordinator.async_shutdown.assert_awaited_once()
    mock_unload.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


async def test_unload_entry_failed(hass: HomeAssistant, mock_config_entry):
    """A failed platform unload leaves the still-loaded coordinator usable."""
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)

    assert result is False
    coordinator.async_shutdown.assert_not_awaited()
    mock_unload.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


async def test_unload_closes_engine_after_platform_teardown(
    hass: HomeAssistant, mock_config_entry
):
    """Terminal shutdown happens only after platform teardown succeeds."""
    call_order: list[str] = []

    coordinator = MagicMock()

    async def _shutdown() -> None:
        call_order.append("engine_close")

    coordinator.async_shutdown = AsyncMock(side_effect=_shutdown)
    mock_config_entry.runtime_data = coordinator

    async def _unload_platforms(*args, **kwargs):
        call_order.append("platform_teardown")
        return True

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        side_effect=_unload_platforms,
    ):
        await async_unload_entry(hass, mock_config_entry)

    assert call_order == ["platform_teardown", "engine_close"]


async def test_setup_while_dark_creates_entities(hass, emulator):
    """Spec criterion 3: restart at night -> entities exist, OFFLINE_EXPECTED.

    The plan's only true end-to-end test: real coordinator + real engine +
    real entities over the emulator — the composition seam nothing else
    covers. Setup against a dark inverter must NOT raise ConfigEntryNotReady.
    """
    emulator.dark = True
    host, port = emulator.addr
    entry = endpoint_entry(host=host, port=port)
    entry.add_to_hass(hass)
    with patch.object(SolarmaxCoordinator, "sun_below_threshold", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        status = hass.states.get("sensor.existing_inverter_sys")
        assert status is not None
        assert status.state == "offline_expected"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def test_device_registry_updater_uses_config_entry_lookup(
    hass, mock_config_entry
) -> None:
    """Newer HA registries receive the config entry needed for disambiguation."""
    subentry_id = next(iter(mock_config_entry.subentries))

    class FutureDeviceRegistry:
        def __init__(self) -> None:
            self.lookup = None
            self.updated = None

        def async_get_device_by_identifier(self, identifier, config_entry_id):
            self.lookup = (identifier, config_entry_id)
            return SimpleNamespace(id="device-id")

        def async_get_device(self, **_kwargs):
            raise AssertionError("deprecated registry lookup used")

        def async_update_device(self, device_id, **changes):
            self.updated = (device_id, changes)

    registry = FutureDeviceRegistry()
    coordinator = MagicMock()
    coordinator.device_model_for.return_value = "SolarMax 7TP2"
    coordinator.sw_version_for.return_value = "40"
    coordinator.serial_number_for.return_value = "118767"

    with patch("custom_components.solarmax.sensor.dr.async_get", return_value=registry):
        updater = _make_device_registry_updater(
            hass, mock_config_entry, coordinator, subentry_id
        )
        updater()

    assert registry.lookup == (
        (DOMAIN, subentry_id),
        mock_config_entry.entry_id,
    )
    assert registry.updated == (
        "device-id",
        {
            "model": "SolarMax 7TP2",
            "sw_version": "40",
            "serial_number": "118767",
        },
    )


@pytest.mark.parametrize(
    ("sw_version", "serial_number", "expected_metadata"),
    [
        (None, None, {"model": "SolarMax 7TP2"}),
        ("40", None, {"model": "SolarMax 7TP2", "sw_version": "40"}),
        (
            None,
            "118767",
            {"model": "SolarMax 7TP2", "serial_number": "118767"},
        ),
    ],
)
def test_device_registry_updater_omits_unreported_metadata(
    hass,
    mock_config_entry,
    sw_version,
    serial_number,
    expected_metadata,
) -> None:
    """Partial static data must not clear existing device metadata."""
    subentry_id = next(iter(mock_config_entry.subentries))

    class RecordingDeviceRegistry:
        def __init__(self) -> None:
            self.updated = None

        def async_get_device_by_identifier(self, *_args):
            return SimpleNamespace(id="device-id")

        def async_update_device(self, device_id, **changes):
            self.updated = (device_id, changes)

    registry = RecordingDeviceRegistry()
    coordinator = MagicMock()
    coordinator.device_model_for.return_value = "SolarMax 7TP2"
    coordinator.sw_version_for.return_value = sw_version
    coordinator.serial_number_for.return_value = serial_number

    with patch("custom_components.solarmax.sensor.dr.async_get", return_value=registry):
        updater = _make_device_registry_updater(
            hass, mock_config_entry, coordinator, subentry_id
        )
        updater()

    assert registry.updated == ("device-id", expected_metadata)


async def test_device_registry_updates_when_statics_arrive_later(
    hass, emulator, monkeypatch
):
    """Static device data should replace the setup-time placeholder."""
    emulator.respond_only(["PAC", "PDC", "SYS", "SAL", "KDY"])  # withhold device info
    host, port = emulator.addr
    entry = endpoint_entry(host=host, port=port)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = next(iter(entry.subentries))
    registry = dr.async_get(hass)
    get_by_identifier = getattr(registry, "async_get_device_by_identifier", None)

    def get_device():
        if get_by_identifier is not None:
            return get_by_identifier((DOMAIN, subentry_id), entry.entry_id)
        return registry.async_get_device(identifiers={(DOMAIN, subentry_id)})

    device = get_device()
    assert device is not None
    assert device.model == "Inverter"  # placeholder: statics never arrived

    if get_by_identifier is not None:

        def fail_deprecated_lookup(*_args, **_kwargs):
            raise AssertionError("deprecated device lookup used")

        monkeypatch.setattr(
            registry,
            "async_get_device",
            fail_deprecated_lookup,
        )

    emulator.respond_only(None)  # statics now available
    coordinator: SolarmaxCoordinator = entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    device = get_device()
    assert device is not None
    assert device.model == "SolarMax 7TP2"

    # Unload before the emulator fixture tears down: an unclosed connection
    # would leave the emulator's client-handling thread alive past teardown.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
