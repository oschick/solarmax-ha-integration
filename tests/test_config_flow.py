"""Test the Solarmax config flow."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

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


async def test_form(hass: HomeAssistant) -> None:
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_form_successful_connection(mock_api, hass: HomeAssistant) -> None:
    """Test successful config flow."""
    mock_api.return_value.test_connection.return_value = True

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


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_verify_checksum_passed_to_api(mock_api, hass: HomeAssistant) -> None:
    """Test that the verify_checksum option is passed to the API for validation."""
    mock_api.return_value.test_connection.return_value = True

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
            CONF_VERIFY_CHECKSUM: False,
        },
    )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    mock_api.assert_called_once_with("192.168.1.100", 12345, 1, verify_checksum=False)


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_update_interval_out_of_range(mock_api, hass: HomeAssistant) -> None:
    """Test that an out-of-range update interval is rejected by the schema."""
    mock_api.return_value.test_connection.return_value = True

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


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_form_cannot_connect(mock_api, hass: HomeAssistant) -> None:
    """Test we handle cannot connect error."""
    mock_api.return_value.test_connection.return_value = False

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


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_form_unexpected_exception(mock_api, hass: HomeAssistant) -> None:
    """Test we handle unexpected exceptions."""
    mock_api.return_value.test_connection.side_effect = Exception("Test exception")

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


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_duplicate_entry_prevention(mock_api, hass: HomeAssistant) -> None:
    """Test that duplicate entries are prevented."""
    mock_api.return_value.test_connection.return_value = True

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


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_options_flow(mock_api, hass: HomeAssistant) -> None:
    """Test options flow."""
    mock_api.return_value.test_connection.return_value = True

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


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_options_flow_connection_error(mock_api, hass: HomeAssistant) -> None:
    """Test options flow with connection error."""
    mock_api.return_value.test_connection.return_value = False

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
