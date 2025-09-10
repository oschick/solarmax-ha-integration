"""Repair platform for Solarmax integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class SolarmaxConnectionRepairFlow(RepairsFlow):
    """Handler for Solarmax connection repair flow."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialize the repair flow."""
        super().__init__()
        self.data = data

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the initial step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Confirm the repair."""
        if user_input is not None:
            # The user confirmed the repair suggestion
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "host": self.data.get("host", "unknown"),
                "port": str(self.data.get("port", "unknown")),
                "failures": str(self.data.get("failures", 0)),
            },
        )


class SolarmaxConfigurationRepairFlow(RepairsFlow):
    """Handler for Solarmax configuration repair flow."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialize the repair flow."""
        super().__init__()
        self.data = data

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the initial step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Confirm the repair."""
        if user_input is not None:
            # The user confirmed the repair suggestion
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "host": self.data.get("host", "unknown"),
                "issue": self.data.get("issue", "configuration issue"),
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create flow."""
    if issue_id.startswith("connection_issues"):
        return SolarmaxConnectionRepairFlow(data or {})
    elif issue_id.startswith("configuration_issue"):
        return SolarmaxConfigurationRepairFlow(data or {})

    # Fallback to confirm repair flow
    return ConfirmRepairFlow()
