"""Test the Solarmax config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarmax.config_flow import CannotConnect, validate_input
from custom_components.solarmax.connection import LinkClosed, LinkTimeout
from custom_components.solarmax.const import (
    CONF_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_NIGHT_KEEP_VALUES,
    CONF_PORT,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    DEFAULT_NIGHT_KEEP_VALUES,
    DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    DOMAIN,
)
from custom_components.solarmax.protocol import build_request

_LINK_REQUEST = "custom_components.solarmax.config_flow.SolarmaxLink.request"
_LINK_CLOSE = "custom_components.solarmax.config_flow.SolarmaxLink.close"


async def test_form(hass: HomeAssistant) -> None:
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_form_successful_connection(mock_request, hass: HomeAssistant) -> None:
    """Test successful config flow."""
    mock_request.return_value = "{FB;01;10|64:PAC=03E8,0|1234}"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_ADDRESS: 1,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
    )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Test Inverter"
    assert result2["data"] == {
        CONF_HOST: "192.168.1.100",
        CONF_PORT: 12345,
        CONF_ADDRESS: 1,
        CONF_DEVICE_NAME: "Test Inverter",
        CONF_UPDATE_INTERVAL: 30,
        CONF_VERIFY_CHECKSUM: True,
        CONF_NIGHT_KEEP_VALUES: DEFAULT_NIGHT_KEEP_VALUES,
        CONF_TWILIGHT_ELEVATION_THRESHOLD: DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    }


@patch(_LINK_CLOSE, new_callable=AsyncMock)
@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_validate_input_closes_probe_link_on_success(
    mock_request, mock_close, hass: HomeAssistant
) -> None:
    """The `finally: await link.close()` is a hard invariant (spec: a leaked
    probe socket locks the single-client inverter out for ~128s and would
    fail the very next setup attempt) — must run even when the probe
    succeeds. Also pins that the configured address reaches the PAC probe.
    """
    mock_request.return_value = "{FB;01;10|64:PAC=03E8,0|1234}"

    await validate_input(
        hass,
        {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_ADDRESS: 2,
            CONF_DEVICE_NAME: "Test Inverter",
        },
    )

    mock_close.assert_awaited_once()
    mock_request.assert_awaited_once_with(build_request(2, ["PAC"]))


@patch(_LINK_CLOSE, new_callable=AsyncMock)
@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_validate_input_closes_probe_link_on_failure(
    mock_request, mock_close, hass: HomeAssistant
) -> None:
    """Same invariant on the failure path — and covers the LinkClosed arm of
    the except tuple, which no other test exercises.
    """
    mock_request.side_effect = LinkClosed("peer closed the connection")

    with pytest.raises(CannotConnect):
        await validate_input(
            hass,
            {
                CONF_HOST: "192.168.1.100",
                CONF_PORT: 12345,
                CONF_DEVICE_NAME: "Test Inverter",
            },
        )

    mock_close.assert_awaited_once()


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_update_interval_out_of_range(mock_request, hass: HomeAssistant) -> None:
    """Test that an out-of-range update interval is rejected by the schema."""
    mock_request.return_value = "{FB;01;10|64:PAC=03E8,0|1234}"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with pytest.raises(data_entry_flow.InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.1.100",
                CONF_PORT: 12345,
                CONF_UPDATE_INTERVAL: 0,
            },
        )


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_form_cannot_connect(mock_request, hass: HomeAssistant) -> None:
    """Test we handle cannot connect error (LinkTimeout -> cannot_connect)."""
    mock_request.side_effect = LinkTimeout("no response")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_form_unexpected_exception(mock_request, hass: HomeAssistant) -> None:
    """Test we handle unexpected exceptions."""
    mock_request.side_effect = Exception("Test exception")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "unknown"}


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_duplicate_entry_prevention(mock_request, hass: HomeAssistant) -> None:
    """Test that duplicate entries are prevented."""
    mock_request.return_value = "{FB;01;10|64:PAC=03E8,0|1234}"

    # Create first entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_ADDRESS: 1,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY

    # Try to create duplicate entry
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_ADDRESS: 1,
            CONF_DEVICE_NAME: "Test Inverter 2",
            CONF_UPDATE_INTERVAL: 60,
        },
    )

    assert result4["type"] == FlowResultType.ABORT
    assert result4["reason"] == "already_configured"


def _make_entry() -> MockConfigEntry:
    """Create a mock config entry for options flow tests."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Inverter",
        data={
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_ADDRESS: 1,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
        unique_id="192.168.1.100:12345",
    )


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_options_flow(mock_request, hass: HomeAssistant) -> None:
    """Test options flow."""
    mock_request.return_value = "{FB;01;10|64:PAC=03E8,0|1234}"

    entry = _make_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_HOST: "192.168.1.101",
                CONF_PORT: 12346,
                CONF_ADDRESS: 2,
                CONF_DEVICE_NAME: "Updated Inverter",
                CONF_UPDATE_INTERVAL: 60,
            },
        )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_HOST] == "192.168.1.101"
    assert entry.data[CONF_UPDATE_INTERVAL] == 60


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_options_flow_connection_error(mock_request, hass: HomeAssistant) -> None:
    """Test options flow with connection error."""
    mock_request.side_effect = LinkTimeout("no response")

    entry = _make_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "192.168.1.101",
            CONF_PORT: 12345,
            CONF_ADDRESS: 1,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_night_keep_values_defaults_to_disabled(hass):
    """The new option must not change behaviour for anyone who ignores it."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Read the default off the vol.Optional marker rather than validating
    # an empty dict — the schema has vol.Required("host"), so schema({})
    # raises MultipleInvalid instead of applying defaults.
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    assert "night_keep_values" in schema_keys
    assert schema_keys["night_keep_values"].default() is False
