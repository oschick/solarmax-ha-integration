"""Test the Solarmax config flow."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarmax import async_update_listener
from custom_components.solarmax.configuration import (
    OPTION_DEFAULTS,
    CannotConnect,
    endpoint_unique_id,
    split_entry_input,
    validate_connection,
)
from custom_components.solarmax.connection import LinkClosed, LinkTimeout, SolarmaxLink
from custom_components.solarmax.const import (
    CONF_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_NIGHT_KEEP_VALUES,
    CONF_PORT,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    DOMAIN,
)
from custom_components.solarmax.protocol import build_request, calculate_checksum

_LINK_REQUEST = "custom_components.solarmax.configuration.SolarmaxLink.request"
_LINK_CLOSE = "custom_components.solarmax.configuration.SolarmaxLink.close"


def test_split_entry_input_separates_connection_data_from_options() -> None:
    """Config entry values are partitioned by their canonical ownership."""
    data, options = split_entry_input(
        {
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 12345,
            CONF_ADDRESS: 7,
            CONF_DEVICE_NAME: "Roof",
            CONF_UPDATE_INTERVAL: 45,
            CONF_VERIFY_CHECKSUM: False,
            CONF_TWILIGHT_ELEVATION_THRESHOLD: 4.5,
            CONF_NIGHT_KEEP_VALUES: True,
        }
    )

    assert data == {
        CONF_HOST: "192.0.2.10",
        CONF_PORT: 12345,
        CONF_ADDRESS: 7,
        CONF_DEVICE_NAME: "Roof",
    }
    assert options == {
        CONF_UPDATE_INTERVAL: 45,
        CONF_VERIFY_CHECKSUM: False,
        CONF_TWILIGHT_ELEVATION_THRESHOLD: 4.5,
        CONF_NIGHT_KEEP_VALUES: True,
    }


def _response(data: str, *, checksum: str | None = None) -> str:
    """Build one structurally valid MaxComm response frame."""
    response = "{01;FB;!!|64:" + data + "|$$$$}"
    response = response.replace("!!", format(len(response), "02X"))
    checksum_data = response[1:-5]
    return response.replace("$$$$", checksum or calculate_checksum(checksum_data))


def _configured_endpoint_entry(
    *, host: str, port: int, address: int
) -> MockConfigEntry:
    """Create a current-version entry for one inverter endpoint."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Existing inverter",
        data={
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_ADDRESS: address,
            CONF_DEVICE_NAME: "Existing inverter",
        },
        options=dict(OPTION_DEFAULTS),
        unique_id=endpoint_unique_id(host, port, address),
        version=2,
        minor_version=1,
    )


async def _submit_user_flow(
    hass: HomeAssistant, *, host: str, port: int, address: int
) -> ConfigFlowResult:
    """Submit one complete initial setup flow."""
    form = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        form["flow_id"],
        {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_ADDRESS: address,
            CONF_DEVICE_NAME: "New inverter",
            **OPTION_DEFAULTS,
        },
    )


@patch.object(SolarmaxLink, "request", new_callable=AsyncMock)
async def test_setup_rejects_same_endpoint_with_different_address(
    mock_request: AsyncMock, hass: HomeAssistant
) -> None:
    """Only one config entry may claim an inverter TCP endpoint."""
    mock_request.return_value = _response("PAC=03E8")
    existing = _configured_endpoint_entry(host="192.0.2.5", port=12345, address=1)
    existing.add_to_hass(hass)

    result = await _submit_user_flow(hass, host="192.0.2.5", port=12345, address=2)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@patch.object(SolarmaxLink, "request", new_callable=AsyncMock)
async def test_setup_uses_address_aware_unique_id(
    mock_request: AsyncMock, hass: HomeAssistant
) -> None:
    """The inverter address participates in config entry identity."""
    mock_request.return_value = _response("PAC=03E8")

    result = await _submit_user_flow(hass, host="192.0.2.6", port=12345, address=7)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "192.0.2.6:12345:7"


@patch.object(SolarmaxLink, "request", new_callable=AsyncMock)
async def test_setup_creates_split_data_and_options(
    mock_request: AsyncMock, hass: HomeAssistant
) -> None:
    """Connection identity and preferences use their canonical stores."""
    mock_request.return_value = _response("PAC=03E8")

    result = await _submit_user_flow(hass, host="192.0.2.7", port=12345, address=3)

    assert result["data"] == {
        CONF_HOST: "192.0.2.7",
        CONF_PORT: 12345,
        CONF_ADDRESS: 3,
        CONF_DEVICE_NAME: "New inverter",
    }
    assert result["options"] == OPTION_DEFAULTS


async def test_setup_serializes_concurrent_claims_for_endpoint(
    hass: HomeAssistant,
) -> None:
    """Concurrent flows cannot both claim the same TCP endpoint."""
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def blocked_probe(**kwargs: Any) -> None:
        probe_started.set()
        await release_probe.wait()

    with patch(
        "custom_components.solarmax.config_flow.validate_connection",
        side_effect=blocked_probe,
    ):
        first_submission = asyncio.create_task(
            _submit_user_flow(hass, host="192.0.2.8", port=12345, address=1)
        )
        await probe_started.wait()
        second_submission = asyncio.create_task(
            _submit_user_flow(hass, host="192.0.2.8", port=12345, address=2)
        )
        await asyncio.sleep(0)
        assert not second_submission.done()
        release_probe.set()
        first, second = await asyncio.gather(first_submission, second_submission)

    assert sorted(result["type"] for result in (first, second)) == [
        FlowResultType.ABORT,
        FlowResultType.CREATE_ENTRY,
    ]
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


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
    mock_request.return_value = _response("PAC=03E8")

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
    }
    assert result2["options"] == OPTION_DEFAULTS


@patch(_LINK_CLOSE, new_callable=AsyncMock)
@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_validate_connection_closes_probe_link_on_success(
    mock_request, mock_close
) -> None:
    """The `finally: await link.close()` is a hard invariant (spec: a leaked
    probe socket locks the single-client inverter out for ~128s and would
    fail the very next setup attempt) — must run even when the probe
    succeeds. Also pins that the configured address reaches the PAC probe.
    """
    mock_request.return_value = _response("PAC=03E8")

    await validate_connection(
        host="192.168.1.100",
        port=12345,
        address=2,
        verify_checksum=True,
    )

    mock_close.assert_awaited_once()
    mock_request.assert_awaited_once_with(build_request(2, ["PAC"]))


@patch(_LINK_CLOSE, new_callable=AsyncMock)
@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_validate_connection_closes_probe_link_on_failure(
    mock_request, mock_close
) -> None:
    """Same invariant on the failure path — and covers the LinkClosed arm of
    the except tuple, which no other test exercises.
    """
    mock_request.side_effect = LinkClosed("peer closed the connection")

    with pytest.raises(CannotConnect):
        await validate_connection(
            host="192.168.1.100",
            port=12345,
            address=1,
            verify_checksum=True,
        )

    mock_close.assert_awaited_once()


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_validate_connection_rejects_non_maxcomm_response(mock_request) -> None:
    """A TCP service that merely terminates with `}` is not an inverter."""
    mock_request.return_value = "not-a-maxcomm-frame}"

    with pytest.raises(CannotConnect):
        await validate_connection(
            host="192.168.1.100",
            port=12345,
            address=1,
            verify_checksum=True,
        )


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_validate_connection_rejects_invalid_checksum(
    mock_request,
) -> None:
    """Checksum-enabled setup validation rejects corrupted MaxComm frames."""
    mock_request.return_value = _response("PAC=03E8", checksum="0000")

    with pytest.raises(CannotConnect):
        await validate_connection(
            host="192.168.1.100",
            port=12345,
            address=1,
            verify_checksum=True,
        )


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_validate_connection_honors_disabled_checksum(
    mock_request,
) -> None:
    """The user's ignore-checksum choice also applies to the setup probe."""
    mock_request.return_value = _response("PAC=03E8", checksum="0000")

    await validate_connection(
        host="192.168.1.100",
        port=12345,
        address=1,
        verify_checksum=False,
    )


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_validate_connection_accepts_not_applicable_pac(
    mock_request,
) -> None:
    """A valid inverter may report PAC as unavailable while not producing."""
    mock_request.return_value = _response("PAC")

    await validate_connection(
        host="192.168.1.100",
        port=12345,
        address=1,
        verify_checksum=True,
    )


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_update_interval_out_of_range(mock_request, hass: HomeAssistant) -> None:
    """Test that an out-of-range update interval is rejected by the schema."""
    mock_request.return_value = _response("PAC=03E8")

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
    mock_request.return_value = _response("PAC=03E8")

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
    """Test options flow saves without probing the inverter (finding 1/13):
    the running engine already holds the device's single client slot, so a
    second connection here always fails — cannot_connect at any time of
    day, or always at night. The options flow validates the schema only."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    entry.add_update_listener(async_update_listener)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload_entry:
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
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_HOST] == "192.168.1.101"
    assert entry.data[CONF_UPDATE_INTERVAL] == 60
    reload_entry.assert_awaited_once_with(entry.entry_id)
    mock_request.assert_not_awaited()  # no live probe was ever attempted


@patch(_LINK_REQUEST, new_callable=AsyncMock)
async def test_options_flow_saves_even_when_a_probe_would_fail(
    mock_request, hass: HomeAssistant
) -> None:
    """Saving options must not compete for the inverter's client slot."""
    mock_request.side_effect = LinkTimeout("no response")

    entry = _make_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    with patch.object(hass.config_entries, "async_reload", return_value=True):
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

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    mock_request.assert_not_awaited()


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
