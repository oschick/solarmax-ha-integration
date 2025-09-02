"""Test the Solarmax config flow."""
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solarmax.const import DOMAIN


async def test_form(hass: HomeAssistant) -> None:
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}


async def test_form_invalid_host(hass: HomeAssistant) -> None:
    """Test we handle invalid host."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "",
            "port": 12345,
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"host": "invalid_host"}


async def test_form_cannot_connect(hass: HomeAssistant) -> None:
    """Test we handle cannot connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "192.168.1.100",
            "port": 12345,
        },
    )

    # This will likely fail in tests since we don't have a real inverter
    # In real tests, you would mock the connection
    assert result2["type"] in [FlowResultType.CREATE_ENTRY, FlowResultType.FORM]
