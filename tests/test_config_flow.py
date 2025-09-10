"""Test the Solarmax config flow."""

import pytest
from unittest.mock import patch, AsyncMock

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solarmax.config_flow import CannotConnect, InvalidAuth
from custom_components.solarmax.const import DOMAIN, CONF_HOST, CONF_PORT, CONF_DEVICE_NAME, CONF_UPDATE_INTERVAL


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
    mock_api.return_value.test_connection = AsyncMock(return_value=True)
    
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
    )
    
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Test Inverter"
    assert result2["data"] == {
        CONF_HOST: "192.168.1.100",
        CONF_PORT: 12345,
        CONF_DEVICE_NAME: "Test Inverter",
        CONF_UPDATE_INTERVAL: 30,
    }


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_form_cannot_connect(mock_api, hass: HomeAssistant) -> None:
    """Test we handle cannot connect error."""
    mock_api.return_value.test_connection = AsyncMock(return_value=False)
    
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
    mock_api.return_value.test_connection = AsyncMock(side_effect=Exception("Test exception"))
    
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
    mock_api.return_value.test_connection = AsyncMock(return_value=True)
    
    # Create first entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
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
            CONF_DEVICE_NAME: "Test Inverter 2",
            CONF_UPDATE_INTERVAL: 60,
        },
    )
    
    assert result4["type"] == FlowResultType.ABORT
    assert result4["reason"] == "already_configured"


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_options_flow(mock_api, hass: HomeAssistant) -> None:
    """Test options flow."""
    mock_api.return_value.test_connection = AsyncMock(return_value=True)
    
    # Create config entry
    entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Test Inverter",
        data={
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
        source=config_entries.SOURCE_USER,
        entry_id="test_entry",
        unique_id="192.168.1.100:12345",
    )
    
    # Test options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "192.168.1.101",
            CONF_PORT: 12346,
            CONF_DEVICE_NAME: "Updated Inverter",
            CONF_UPDATE_INTERVAL: 60,
        },
    )
    
    assert result2["type"] == FlowResultType.CREATE_ENTRY


@patch("custom_components.solarmax.config_flow.SolarmaxAPI")
async def test_options_flow_connection_error(mock_api, hass: HomeAssistant) -> None:
    """Test options flow with connection error."""
    mock_api.return_value.test_connection = AsyncMock(return_value=False)
    
    # Create config entry
    entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Test Inverter",
        data={
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 12345,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
        source=config_entries.SOURCE_USER,
        entry_id="test_entry",
        unique_id="192.168.1.100:12345",
    )
    
    # Test options flow with connection error
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "192.168.1.999",  # Invalid IP
            CONF_PORT: 12345,
            CONF_DEVICE_NAME: "Test Inverter",
            CONF_UPDATE_INTERVAL: 30,
        },
    )
    
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}

    # This will likely fail in tests since we don't have a real inverter
    # In real tests, you would mock the connection
    assert result2["type"] in [FlowResultType.CREATE_ENTRY, FlowResultType.FORM]
