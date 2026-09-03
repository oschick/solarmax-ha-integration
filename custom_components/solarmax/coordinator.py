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
from homeassistant.helpers.issue_registry import (
    async_get as async_get_issue_registry,
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
    FAULT_POLL_SECONDS,
    FAULT_REPAIR_SECONDS,
    NIGHT_POLL_SECONDS,
    REPAIR_DISMISS_SUPPRESS_SECONDS,
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
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._configured_interval,
            always_update=False,  # Only notify listeners when data changes
        )

        self._repair_issue_id = f"connection_issues_{entry.entry_id}"
        # Q28b: repair-issue episode tracking. `_issue_raised` is True once
        # this fault episode has actually created the issue; `_dismissed_at`
        # is set when the user completes the fix flow (issue deleted) while
        # the fault is still ongoing, and suppresses re-creation for
        # REPAIR_DISMISS_SUPPRESS_SECONDS. In-memory only — an HA restart
        # mid-fault forgets the dismissal (accepted by the ruling). Both
        # reset on a new episode (recovery to ONLINE or reclassification to
        # OFFLINE_EXPECTED).
        self._issue_raised = False
        self._dismissed_at: datetime | None = None

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

    @callback
    def async_handle_midnight(self, now: datetime) -> None:
        """Force a listener refresh at local midnight for Energy Day sensors.

        `coordinator.data` is reassigned every poll regardless — the engine
        never raises, so that assignment always runs. What's suppressed is
        `async_update_listeners()`, and the mechanism is `always_update=False`
        plus `EngineSnapshot` equality (its `diagnostics` field is
        `compare=False` for exactly this reason): HA only notifies listeners
        when the new snapshot differs from the last one it notified with.
        Not `last_update_success` — that stays True all night, since
        `_async_update_data` never raises. Two consecutive OFFLINE_EXPECTED
        snapshots overnight compare equal, so nothing re-reads native_value
        between dusk and dawn. Energy Day depends on noticing midnight, so
        we push one update ourselves, bypassing the equality check.

        That also makes this the *only* state write between dusk and dawn
        along the *armed* path — the inverter announced its own shutdown
        (SYS 20002 or low PDC) before going dark, so ArmingTracker.armed
        stays True all night and, per `armed or sun_below`, classification
        holds OFFLINE_EXPECTED straight through the dawn gap (sun already
        above the twilight threshold, inverter not yet answering) with no
        write at all — which is what keeps the night policy safe there. The
        *sun-fallback* path (no shutdown announcement was ever observed, so
        armed never latched) has no such protection: once the sun clears the
        threshold, `armed or sun_below` goes False and the snapshot moves off
        OFFLINE_EXPECTED (to UNKNOWN/OFFLINE_FAULT) — a real change, so this
        one *does* notify. But `_night_policy` requires state ==
        OFFLINE_EXPECTED, so that write only ever produces `unavailable`,
        never a numeric value — and a TOTAL_INCREASING sensor going
        unavailable is not read as a rise. If state were written with a
        *numeric* value in that window instead, a HOLD_UNTIL_MIDNIGHT sensor
        like KDY would jump from the midnight 0 back up to yesterday's
        total, and HA reads that rise on a TOTAL_INCREASING sensor as real
        growth — injecting a phantom day's energy into the Energy dashboard
        every morning. Any future change that adds a second state-write path
        in that window — a forced homeassistant.update_entity call, an
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
        """Adapt cadence for expected outages and active daytime failures."""
        if snapshot.state is EngineState.OFFLINE_EXPECTED:
            if self.sun_below_threshold():
                return timedelta(seconds=NIGHT_POLL_SECONDS)
            return timedelta(seconds=DAWN_POLL_SECONDS)
        if snapshot.state is EngineState.OFFLINE_FAULT or (
            snapshot.state is EngineState.UNKNOWN and snapshot.reconnecting
        ):
            return min(
                self._configured_interval,
                timedelta(seconds=FAULT_POLL_SECONDS),
            )
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
                _LOGGER.warning(
                    "Inverter %s:%s unreachable (fault)",
                    self._entry.data[CONF_HOST],
                    self._entry.data[CONF_PORT],
                )
            else:
                _LOGGER.info(
                    "Connection state %s -> %s", previous_state, snapshot.state
                )

        if snapshot.state is EngineState.OFFLINE_FAULT and snapshot.fault_since:
            fault_seconds = (dt_util.utcnow() - snapshot.fault_since).total_seconds()
            if fault_seconds >= FAULT_REPAIR_SECONDS:
                if self._issue_raised and (
                    async_get_issue_registry(self.hass).async_get_issue(
                        DOMAIN, self._repair_issue_id
                    )
                    is None
                ):
                    # The user completed the fix flow (issue deleted) while
                    # the fault is still ongoing — do not immediately
                    # re-raise it under them.
                    self._issue_raised = False
                    self._dismissed_at = dt_util.utcnow()

                if self._dismissed_at is not None:
                    dismissed_seconds = (
                        dt_util.utcnow() - self._dismissed_at
                    ).total_seconds()
                    if dismissed_seconds < REPAIR_DISMISS_SUPPRESS_SECONDS:
                        return
                    self._dismissed_at = None

                # No "already raised" guard beyond the above: `minutes` must
                # keep refreshing for the life of the fault. async_create_issue
                # no-ops (no new update event) when the replacement issue is
                # identical to the one already registered, so recomputing
                # every poll is cheap and only actually updates the dialog
                # when the minute count ticks over.
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
                self._issue_raised = True
                return

        # Any state that is not a sustained fault ends the current episode.
        self._issue_raised = False
        self._dismissed_at = None
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
