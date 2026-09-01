"""Test repairs for Solarmax integration."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from custom_components.solarmax.const import SYS_OPTIONS
from custom_components.solarmax.repairs import (
    SolarmaxConfigurationRepairFlow,
    SolarmaxConnectionRepairFlow,
    async_create_fix_flow,
)

_INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "solarmax"
)
_TRANSLATION_PATHS = [
    _INTEGRATION_DIR / "strings.json",
    _INTEGRATION_DIR / "translations" / "en.json",
    _INTEGRATION_DIR / "translations" / "de.json",
    _INTEGRATION_DIR / "translations" / "fr.json",
]


def _load_translation(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _leaf_key_paths(node: object, prefix: str = "") -> set[str]:
    """Return dotted paths to every leaf value in a nested dict.

    Comparing leaf paths (not just top-level keys) catches a missing
    `fix_flow` block, not just a missing `issues.<id>` entry.
    """
    if not isinstance(node, dict):
        return {prefix}
    paths: set[str] = set()
    for key, value in node.items():
        full = f"{prefix}.{key}" if prefix else key
        paths |= _leaf_key_paths(value, full)
    return paths


@pytest.mark.asyncio
async def test_connection_repair_flow():
    """Test connection repair flow."""
    data = {"host": "192.168.1.100", "port": 12345, "minutes": "5"}

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
    assert "5" in str(result["description_placeholders"]["minutes"])

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


@pytest.mark.asyncio
async def test_connection_repair_flow_survives_null_data():
    """HA overwrites flow.data from issue.data after construction.

    homeassistant/components/repairs/issue_handler.py assigns `flow.data =
    issue.data` after async_create_fix_flow returns, so the `data or {}` guard
    there does not protect us — a None reaches _placeholders() and used to
    raise AttributeError, surfacing as a 500 when the user opened the repair.
    """
    flow = SolarmaxConnectionRepairFlow({})
    flow.data = None

    placeholders = flow._placeholders()

    assert placeholders["host"] == "unknown"
    assert placeholders["port"] == "unknown"
    assert placeholders["minutes"] == "?"


@pytest.mark.asyncio
async def test_configuration_repair_flow_survives_null_data():
    """Same null-data path for the configuration repair flow."""
    flow = SolarmaxConfigurationRepairFlow({})
    flow.data = None

    placeholders = flow._placeholders()

    assert placeholders["host"] == "unknown"


@pytest.mark.asyncio
async def test_connection_repair_fix_flow_renders_confirm_step():
    """strings.json's fix_flow confirm step must exist and reference every
    placeholder the flow actually supplies.

    Home Assistant renders the repair dialog from
    `issues.connection_issues.fix_flow.step.confirm` using the flow's
    `description_placeholders` -- a missing block or a stale placeholder
    name renders a literal '{minutes}' (or a blank dialog) to the user.
    """
    data = {"host": "192.168.1.100", "port": 12345, "minutes": "7"}
    flow = SolarmaxConnectionRepairFlow(data)

    result = await flow.async_step_confirm()

    assert result["type"] == "form"
    assert result["step_id"] == "confirm"

    strings = _load_translation(_INTEGRATION_DIR / "strings.json")
    confirm = strings["issues"]["connection_issues"]["fix_flow"]["step"]["confirm"]
    assert confirm["title"]
    for placeholder in result["description_placeholders"]:
        assert f"{{{placeholder}}}" in confirm["description"]


def test_translation_files_share_issues_and_sys_state_keys():
    """strings.json and every translations/*.json must declare identical
    keys under `issues` and `entity.sensor.sys.state`.

    A missing `issues` key breaks the repair dialog for that language; a
    missing `entity.sensor.sys.state` key means Home Assistant rejects the
    enum state entirely (`SYS_OPTIONS` in const.py must also stay in sync,
    checked separately below).
    """
    loaded = {path.name: _load_translation(path) for path in _TRANSLATION_PATHS}

    reference = next(iter(loaded.values()))
    reference_issue_keys = _leaf_key_paths(reference["issues"])
    reference_sys_state_keys = set(reference["entity"]["sensor"]["sys"]["state"])

    for name, content in loaded.items():
        assert _leaf_key_paths(content["issues"]) == reference_issue_keys, name
        assert (
            set(content["entity"]["sensor"]["sys"]["state"]) == reference_sys_state_keys
        ), name


def test_sys_state_keys_match_sys_options():
    """Every translation file's `entity.sensor.sys.state` keys must equal
    `SYS_OPTIONS` -- Home Assistant rejects an enum state whose option
    isn't declared in every translation file."""
    for path in _TRANSLATION_PATHS:
        content = _load_translation(path)
        sys_state_keys = set(content["entity"]["sensor"]["sys"]["state"])
        assert sys_state_keys == set(SYS_OPTIONS), path.name
