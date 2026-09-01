"""DataUpdateCoordinator for Solarmax."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .connection import ConnectionEngine, EngineSnapshot, EngineState, SolarmaxLink
from .const import (
    CONF_ADDRESS,
    CONF_HOST,
    CONF_PORT,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    DAWN_POLL_SECONDS,
    DEFAULT_ADDRESS,
    DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VERIFY_CHECKSUM,
    DEVICE_KEY_BUILD,
    DEVICE_KEY_FIRMWARE,
    DEVICE_KEY_SERIAL,
    DEVICE_KEY_TYPE,
    DEVICE_TYPE_MAP,
    DOMAIN,
    FAULT_REPAIR_SECONDS,
    NIGHT_POLL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class SolarmaxCoordinator(DataUpdateCoordinator[EngineSnapshot]):
    """Poll a Solarmax inverter through a ConnectionEngine.

    Every poll cycle produces an EngineSnapshot, never an exception — this
    is what makes the coordinator a thin *always-succeed* adapter. HA's
    DataUpdateCoordinator suppresses async_update_listeners() while polls
    are failing (last_update_success is False); since _async_update_data
    never raises, that suppression path can never engage, which is exactly
    what closes the dusk/dawn listener-starvation bug this redesign fixes.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self._entry = entry

        link = SolarmaxLink(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
        )
        self._engine = ConnectionEngine(
            link,
            address=entry.data.get(CONF_ADDRESS, DEFAULT_ADDRESS),
            sun_below=self.sun_below_threshold,
            verify_checksum=entry.data.get(
                CONF_VERIFY_CHECKSUM, DEFAULT_VERIFY_CHECKSUM
            ),
        )

        self._configured_interval = timedelta(
            seconds=entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._configured_interval,
            always_update=False,  # Only notify listeners when data changes
        )

        self._repair_issue_id = f"connection_issues_{entry.entry_id}"

    @property
    def engine(self) -> ConnectionEngine:
        """Return the underlying connection engine."""
        return self._engine

    @property
    def _twilight_elevation_threshold(self) -> float:
        """Return the configured twilight elevation threshold in degrees."""
        return float(
            self._entry.data.get(
                CONF_TWILIGHT_ELEVATION_THRESHOLD,
                DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
            )
        )

    def sun_below_threshold(self) -> bool:
        """Return True when the sun is below the configured twilight threshold.

        Passed to ConnectionEngine as its `sun_below` callback, and also
        used by the coordinator itself to decide how slowly it can poll
        while OFFLINE_EXPECTED. Falls back to a fixed 20:00-06:00 clock
        window when no `sun.sun` entity is available.
        """
        try:
            sun_component = self.hass.states.get("sun.sun")
            if sun_component:
                if sun_component.state == "below_horizon":
                    return True
                elevation = sun_component.attributes.get("elevation")
                if (
                    elevation is not None
                    and elevation < self._twilight_elevation_threshold
                ):
                    return True
                return False

            current_hour = dt_util.now().hour
            return current_hour >= 20 or current_hour < 6

        except Exception as e:  # noqa: BLE001 - defensive, must not fail a poll
            _LOGGER.debug("Error checking sun position: %s", e)
            current_hour = dt_util.now().hour
            return current_hour >= 20 or current_hour < 6

    @property
    def is_night_time(self) -> bool:
        """Alias for sun_below_threshold(), kept for sensor.py compatibility."""
        return self.sun_below_threshold()

    @callback
    def async_handle_midnight(self, now: datetime) -> None:
        """Force a listener refresh at local midnight for Energy Day sensors.

        The base coordinator skips async_update_listeners() while polls are
        consecutively failing, so nothing re-reads native_value between dusk
        and dawn. Energy Day depends on noticing midnight, so we push one
        update ourselves.

        That also makes this the *only* state write between dusk and dawn,
        which is what keeps the night policy safe. In the dawn gap — after
        the sun clears the twilight threshold but before the inverter
        answers a poll — the engine's snapshot classification moves off
        OFFLINE_EXPECTED (to UNKNOWN/OFFLINE_FAULT), so the night policy
        disengages and native_value falls through to the stale value still
        sitting in coordinator.data. If state were written in that window,
        a HOLD_UNTIL_MIDNIGHT sensor like KDY would jump from the midnight 0
        back up to yesterday's total, and HA reads that rise on a
        TOTAL_INCREASING sensor as real growth — injecting a phantom day's
        energy into the Energy dashboard every morning. It cannot happen
        today only because nothing else writes state there. Any future
        change that adds a second state-write path in that window — a
        forced homeassistant.update_entity call, an
        always_update/availability-polling change, or RestoreSensor work —
        reopens this hole and needs the same care.
        """
        self.async_update_listeners()

    async def _async_update_data(self) -> EngineSnapshot:
        """Poll the engine and hand back a snapshot. Never raises."""
        try:
            snapshot = await self._engine.poll()
        except Exception:  # noqa: BLE001 - belt-and-braces, see class docstring
            _LOGGER.exception(
                "Unexpected error polling the inverter; treating as a fault"
            )
            snapshot = self._restate_as_fault()

        await self._async_handle_snapshot(snapshot)
        self.update_interval = self._interval_for(snapshot)
        return snapshot

    def _restate_as_fault(self) -> EngineSnapshot:
        """Build a fault snapshot after an unexpected exception from poll().

        ConnectionEngine.poll() is documented to never raise; this only
        guards against an unforeseen bug so _async_update_data can still
        provably never raise.
        """
        previous = self.data
        if previous is None:
            return EngineSnapshot(
                state=EngineState.OFFLINE_FAULT,
                values={},
                shutdown_announced=False,
                reconnecting=False,
                expected_outside_twilight=False,
                fault_since=dt_util.utcnow(),
                diagnostics={},
            )
        return replace(
            previous,
            state=EngineState.OFFLINE_FAULT,
            fault_since=previous.fault_since or dt_util.utcnow(),
        )

    def _interval_for(self, snapshot: EngineSnapshot) -> timedelta:
        """Slow down polling while expectedly offline; keep cadence otherwise."""
        if snapshot.state is EngineState.OFFLINE_EXPECTED:
            if self.sun_below_threshold():
                return timedelta(seconds=NIGHT_POLL_SECONDS)
            return timedelta(seconds=DAWN_POLL_SECONDS)
        return self._configured_interval

    async def _async_handle_snapshot(self, snapshot: EngineSnapshot) -> None:
        """Log state transitions and create/clear the connection repair issue.

        `self.data` is still the *previous* snapshot here — the base class
        only assigns `self.data = await self._async_update_data()` after
        this whole method has returned — so comparing against it gives the
        actual state transition, not a comparison against itself.
        """
        previous_state = self.data.state if self.data else None
        if snapshot.state is not previous_state:
            if snapshot.state is EngineState.OFFLINE_FAULT:
                _LOGGER.warning("Inverter unreachable during daytime (fault)")
            else:
                _LOGGER.info(
                    "Connection state %s -> %s", previous_state, snapshot.state
                )

        if snapshot.state is EngineState.OFFLINE_FAULT and snapshot.fault_since:
            fault_seconds = (dt_util.utcnow() - snapshot.fault_since).total_seconds()
            if fault_seconds >= FAULT_REPAIR_SECONDS:
                # No "already raised" guard: `minutes` must keep refreshing
                # for the life of the fault. async_create_issue no-ops (no
                # new update event) when the replacement issue is identical
                # to the one already registered, so recomputing every poll
                # is cheap and only actually updates the dialog when the
                # minute count ticks over.
                issue_context: dict[str, str] = {
                    "host": self._entry.data[CONF_HOST],
                    "port": str(self._entry.data[CONF_PORT]),
                    "minutes": str(int(fault_seconds // 60)),
                }
                async_create_issue(
                    self.hass,
                    DOMAIN,
                    self._repair_issue_id,
                    is_fixable=True,
                    is_persistent=False,
                    severity=IssueSeverity.ERROR,
                    translation_key="connection_issues",
                    translation_placeholders=issue_context,
                    # async_create_issue's `data` param is typed broader
                    # (dict[str, str | int | float | None]) than
                    # translation_placeholders' dict[str, str]; mypy
                    # treats dict as invariant, so a plain dict[str, str]
                    # isn't accepted for `data` without this cast even
                    # though every value here is already a str.
                    data=cast("dict[str, str | int | float | None]", issue_context),
                )
                return

        async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)

    def _static_raw(self, key: str) -> Any:
        """Return the raw_value for a static device-info key, or None."""
        if self.data is None:
            return None
        return self.data.values.get(key, {}).get("raw_value")

    @property
    def device_model(self) -> str | None:
        """Return the detected inverter model, from the latest snapshot."""
        typ_value = self._static_raw(DEVICE_KEY_TYPE)
        if typ_value is None:
            return None
        return DEVICE_TYPE_MAP.get(typ_value, f"Unknown ({typ_value})")

    @property
    def sw_version(self) -> str | None:
        """Return the detected firmware version, from the latest snapshot."""
        swv_value = self._static_raw(DEVICE_KEY_FIRMWARE)
        if swv_value is None:
            return None
        bdn_value = self._static_raw(DEVICE_KEY_BUILD)
        if bdn_value is not None:
            return f"{swv_value} (build {bdn_value})"
        return str(swv_value)

    @property
    def serial_number(self) -> str | None:
        """Return the detected serial number, from the latest snapshot."""
        din_value = self._static_raw(DEVICE_KEY_SERIAL)
        if din_value is None:
            return None
        return str(din_value)

    @property
    def last_successful_update(self) -> datetime | None:
        """Return the local-time timestamp of the last successful poll.

        Converted to local time because sensor._is_new_day() compares
        .date() against dt_util.now().date() — a raw UTC value would shift
        the KDY midnight rollover by the timezone offset.
        """
        if self.data is None:
            return None
        last = self.data.diagnostics.get("last_successful_poll")
        if not isinstance(last, datetime):
            return None
        return dt_util.as_local(last)


# Typed config entry: gives `entry.runtime_data` a real type instead of Any,
# so mypy can actually check every coordinator access through it.
# Plain assignment rather than PEP 695 `type` — pyproject targets >=3.11.
SolarmaxConfigEntry = ConfigEntry[SolarmaxCoordinator]
