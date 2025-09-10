"""Test repairs for Solarmax integration."""

import pytest
from unittest.mock import Mock

from custom_components.solarmax.repairs import (
    SolarmaxConnectionRepairFlow,
    SolarmaxConfigurationRepairFlow,
    async_create_fix_flow,
)


@pytest.mark.asyncio
async def test_connection_repair_flow():
    """Test connection repair flow."""
    data = {"host": "192.168.1.100", "port": 12345, "failures": 5}

    flow = SolarmaxConnectionRepairFlow(data)

    # Test initial step
    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert result["step_id"] == "confirm"

    # Test confirm step
    result = await flow.async_step_confirm()
    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert "192.168.1.100" in str(result["description_placeholders"]["host"])
    assert "12345" in str(result["description_placeholders"]["port"])
    assert "5" in str(result["description_placeholders"]["failures"])

    # Test confirm with user input
    result = await flow.async_step_confirm({"confirm": True})
    assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_configuration_repair_flow():
    """Test configuration repair flow."""
    data = {"host": "192.168.1.100", "issue": "Invalid port configuration"}

    flow = SolarmaxConfigurationRepairFlow(data)

    # Test initial step
    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert result["step_id"] == "confirm"

    # Test confirm step
    result = await flow.async_step_confirm()
    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert "192.168.1.100" in str(result["description_placeholders"]["host"])
    assert "Invalid port configuration" in str(
        result["description_placeholders"]["issue"]
    )


@pytest.mark.asyncio
async def test_async_create_fix_flow():
    """Test fix flow creation."""
    hass = Mock()

    # Test connection issue flow
    flow = await async_create_fix_flow(hass, "connection_issues_test", {"host": "test"})
    assert isinstance(flow, SolarmaxConnectionRepairFlow)

    # Test configuration issue flow
    flow = await async_create_fix_flow(
        hass, "configuration_issue_test", {"issue": "test"}
    )
    assert isinstance(flow, SolarmaxConfigurationRepairFlow)

    # Test unknown issue (fallback)
    flow = await async_create_fix_flow(hass, "unknown_issue", {})
    assert flow is not None  # Should return ConfirmRepairFlow
