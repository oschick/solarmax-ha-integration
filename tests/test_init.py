"""Test the Solarmax integration initialization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarmax import async_setup_entry, async_unload_entry
from custom_components.solarmax.const import (
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_NIGHT_KEEP_VALUES,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
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
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
        entry_id="test_entry",
        unique_id="192.168.1.100:12345",
    )


@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_success(
    mock_coordinator_class, hass: HomeAssistant, mock_config_entry
):
    """Test successful setup of config entry."""
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator_class.return_value = mock_coordinator

    with patch.object(
        hass.config_entries, "async_forward_entry_setups"
    ) as mock_forward:
        result = await async_setup_entry(hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.runtime_data == mock_coordinator
        mock_coordinator.async_config_entry_first_refresh.assert_called_once()
        mock_forward.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


@patch("custom_components.solarmax.async_track_time_change")
@patch("custom_components.solarmax.SolarmaxCoordinator")
async def test_setup_entry_registers_midnight_listener_when_night_keep_values_enabled(
    mock_coordinator_class, mock_track_time_change, hass: HomeAssistant
):
    """night_keep_values=True must register the local-midnight callback."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Inverter",
        data={
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
            CONF_NIGHT_KEEP_VALUES: True,
        },
        entry_id="test_entry_night_keep_values",
        unique_id="192.168.1.100:12345:night",
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
    """Test successful unload of config entry: engine closes, platforms unload."""
    mock_coordinator = MagicMock()
    mock_coordinator.engine.close = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=True
    ) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)

        assert result is True
        mock_coordinator.engine.close.assert_awaited_once()
        mock_unload.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


async def test_unload_entry_failed(hass: HomeAssistant, mock_config_entry):
    """Test failed unload of config entry: engine still closes first."""
    mock_coordinator = MagicMock()
    mock_coordinator.engine.close = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)

        assert result is False
        mock_coordinator.engine.close.assert_awaited_once()
        mock_unload.assert_called_once_with(mock_config_entry, [Platform.SENSOR])


async def test_unload_closes_engine_before_platform_teardown(
    hass: HomeAssistant, mock_config_entry
):
    """Spec: engine.close() must complete before platform teardown begins.

    Close precedes task cancellation — otherwise an in-flight poll can
    survive entity teardown and hold the single-client inverter's one TCP
    slot open after the integration is gone.
    """
    call_order: list[str] = []

    mock_coordinator = MagicMock()

    async def _close() -> None:
        call_order.append("engine_close")

    mock_coordinator.engine.close = AsyncMock(side_effect=_close)
    mock_config_entry.runtime_data = mock_coordinator

    async def _unload_platforms(*args, **kwargs):
        call_order.append("platform_teardown")
        return True

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        side_effect=_unload_platforms,
    ):
        await async_unload_entry(hass, mock_config_entry)

    assert call_order == ["engine_close", "platform_teardown"]


async def test_setup_while_dark_creates_entities(hass, emulator):
    """Spec criterion 3: restart at night -> entities exist, OFFLINE_EXPECTED.

    The plan's only true end-to-end test: real coordinator + real engine +
    real entities over the emulator — the composition seam nothing else
    covers. Setup against a dark inverter must NOT raise ConfigEntryNotReady.
    """
    emulator.dark = True
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "127.0.0.1",
            "port": emulator.addr[1],
            "device_name": "E2E Inverter",
            "update_interval": 30,
        },
        unique_id="e2e",
    )
    entry.add_to_hass(hass)
    with patch.object(SolarmaxCoordinator, "sun_below_threshold", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        status = hass.states.get("sensor.e2e_inverter_sys")
        assert status is not None
        assert status.state == "offline_expected"


async def test_device_registry_updates_when_statics_arrive_later(hass, emulator):
    """Finding 9: setup while the device withholds TYP/SWV/DIN/BDN bakes the
    "Inverter" placeholder into the device registry at construction time.
    Once a later poll's statics arrive, the registry entry must be
    refreshed to the real model/firmware/serial rather than keeping the
    placeholder for the device's whole life.
    """
    from homeassistant.helpers import device_registry as dr

    emulator.respond_only(["PAC", "PDC", "SYS", "SAL", "KDY"])  # withhold device info
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "127.0.0.1",
            "port": emulator.addr[1],
            "device_name": "E2E Inverter",
            "update_interval": 30,
        },
        unique_id="e2e-device-info",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.model == "Inverter"  # placeholder: statics never arrived

    emulator.respond_only(None)  # statics now available
    coordinator: SolarmaxCoordinator = entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.model == "SolarMax 7TP2"

    # Unload before the emulator fixture tears down: an unclosed connection
    # would leave the emulator's client-handling thread alive past teardown.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
