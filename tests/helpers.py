"""Builders shared by flow, setup, repair, and emulator tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VERIFY_CHECKSUM,
    DOMAIN,
    SUBENTRY_TYPE_INVERTER,
)

GLOBAL_OPTION_DEFAULTS: dict[str, Any] = {
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM: DEFAULT_VERIFY_CHECKSUM,
    CONF_RESPONSE_TIMEOUT: DEFAULT_RESPONSE_TIMEOUT,
}


def inverter_subentry(
    address: int = 1,
    name: str = "Existing inverter",
    twilight: float = 5,
    night_keep: bool = False,
) -> ConfigSubentryData:
    """Subentry payload for one inverter, as stored on a version 3 entry."""
    return ConfigSubentryData(
        data={
            CONF_ADDRESS: address,
            CONF_DEVICE_NAME: name,
            CONF_TWILIGHT_ELEVATION_THRESHOLD: twilight,
            CONF_NIGHT_KEEP_VALUES: night_keep,
        },
        subentry_type=SUBENTRY_TYPE_INVERTER,
        title=name,
        unique_id=str(address),
    )


def endpoint_entry(
    *,
    host: str,
    port: int,
    inverters: Sequence[int] = (1,),
    title: str = "Existing inverter",
    options: dict[str, Any] | None = None,
    entry_id: str | None = None,
) -> MockConfigEntry:
    """A version 3 endpoint entry with one inverter subentry per address."""
    names = [
        "Existing inverter" if index == 0 else f"Inverter {address}"
        for index, address in enumerate(inverters)
    ]
    kwargs: dict[str, Any] = {}
    if entry_id is not None:
        kwargs["entry_id"] = entry_id
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data={CONF_HOST: host, CONF_PORT: port},
        options=dict(GLOBAL_OPTION_DEFAULTS) | (options or {}),
        unique_id=f"{host}:{port}",
        version=3,
        minor_version=1,
        subentries_data=[
            inverter_subentry(address, name)
            for address, name in zip(inverters, names, strict=True)
        ],
        **kwargs,
    )
