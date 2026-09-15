"""DataUpdateCoordinator for Solarmax: one endpoint, many inverters."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State, callback
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

from .configuration import (
    endpoint_unique_id,
    entry_option,
    inverter_fingerprint,
    inverter_subentries,
    subentry_option,
)
from .connection import (
    ConnectionEngine,
    EngineSnapshot,
    EngineState,
    LinkClosed,
    LinkFailure,
    SolarmaxLink,
)
from .const import (
    CONF_ADDRESS,
    CONF_HOST,
    CONF_PORT,
    CONF_RESPONSE_TIMEOUT,
    CONF_TWILIGHT_ELEVATION_THRESHOLD,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_CHECKSUM,
    DAWN_POLL_SECONDS,
    DEFAULT_RESPONSE_TIMEOUT,
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
    NO_INVERTER_ISSUE,
    REPAIR_PENDING,
    REPAIR_PENDING_ENDPOINT,
    REPAIR_PENDING_INVERTERS,
)

_LOGGER = logging.getLogger(__name__)

_DAWN_ELEVATION_THRESHOLD = -6.0
_CLOCK_DAWN_HOUR = 5
_CLOCK_NIGHT_HOUR = 20

SnapshotMap = dict[str, EngineSnapshot]


class SolarmaxCoordinator(DataUpdateCoordinator[SnapshotMap]):
    """Poll every inverter behind one endpoint through one shared link.

    Every cycle produces a mapping of subentry ID to EngineSnapshot, never an
    exception. Cycles are serialized by `_cycle_lock`, which the validation
    handoff and shutdown also take, so requests from two cycles can never
    interleave on the half-duplex bus.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize link, engines, and scheduling state from the entry."""
        self._entry = entry
        self._endpoint_unique_id = endpoint_unique_id(
            entry.data[CONF_HOST], entry.data[CONF_PORT]
        )
        self._subentries: dict[str, ConfigSubentry] = inverter_subentries(entry)
        self.fingerprint = inverter_fingerprint(entry)
        self._thresholds: dict[str, float] = {
            subentry_id: float(
                subentry_option(
                    subentry,
                    CONF_TWILIGHT_ELEVATION_THRESHOLD,
                    DEFAULT_TWILIGHT_ELEVATION_THRESHOLD,
                )
            )
            for subentry_id, subentry in self._subentries.items()
        }

        self.link: SolarmaxLink | None = None
        self.engines: dict[str, ConnectionEngine] = {}
        if self._subentries:
            self.link = SolarmaxLink(
                host=entry.data[CONF_HOST],
                port=entry.data[CONF_PORT],
                response_timeout=float(
                    entry_option(entry, CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT)
                ),
            )
            verify_checksum = entry_option(
                entry, CONF_VERIFY_CHECKSUM, DEFAULT_VERIFY_CHECKSUM
            )
            for subentry_id, subentry in self._subentries.items():
                self.engines[subentry_id] = ConnectionEngine(
                    self.link,
                    address=int(subentry.data[CONF_ADDRESS]),
                    sun_below=self._sun_below_callback(self._thresholds[subentry_id]),
                    verify_checksum=verify_checksum,
                    today=lambda: dt_util.now().date(),
                )

        self._configured_interval = timedelta(
            seconds=entry_option(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        self._sun_source = "unknown"
        self._sun_fallback_warned = False
        self.sensor_setup_complete = False
        self._cycle_lock = asyncio.Lock()
        self._shutdown = False
        # Subentries that completed an ONLINE poll since this coordinator started.
        self._verified_online: set[str] = set()

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._configured_interval,
            always_update=False,  # Only notify listeners when data changes
        )

        self._repair_issue_id = f"connection_issues_{entry.entry_id}"
        self._no_inverter_issue_id = f"{NO_INVERTER_ISSUE}_{entry.entry_id}"
        if self.engines:
            async_delete_issue(hass, DOMAIN, self._no_inverter_issue_id)
        else:
            async_delete_issue(hass, DOMAIN, self._repair_issue_id)

    # --- identity -----------------------------------------------------------

    def subentry_ids(self) -> list[str]:
        """Return the inverter subentry IDs in polling order."""
        return list(self._subentries)

    def subentry_title(self, subentry_id: str) -> str:
        """Return the current display name of an inverter."""
        subentry = self._entry.subentries.get(subentry_id)
        if subentry is None:
            subentry = self._subentries.get(subentry_id)
        return subentry.title if subentry is not None else subentry_id

    @property
    def sun_source(self) -> str:
        """Return the source used by the most recent sun check."""
        return self._sun_source

    # --- sun ----------------------------------------------------------------

    def _sun_below_callback(self, threshold: float) -> Callable[[], bool]:
        return lambda: self.sun_below_threshold(threshold)

    def sun_below_threshold(self, threshold: float) -> bool:
        """Return True when the sun is below the given twilight threshold.

        Falls back to a fixed 20:00-06:00 clock window without `sun.sun`.
        """
        sun_component = self._sun_component()
        if sun_component is not None:
            try:
                if sun_component.state == "below_horizon":
                    return True
                elevation = sun_component.attributes.get("elevation")
                if elevation is not None and elevation < threshold:
                    return True
                return False
            except Exception as e:  # noqa: BLE001 - defensive, must not fail a poll
                _LOGGER.debug("Error checking sun position: %s", e)

        current_hour = self._clock_fallback_hour()
        return current_hour >= 20 or current_hour < 6

    def _sun_component(self) -> State | None:
        """Return the sun entity and remember when it is available."""
        try:
            sun_component = self.hass.states.get("sun.sun")
        except Exception as e:  # noqa: BLE001 - defensive, must not fail a poll
            _LOGGER.debug("Error reading sun.sun: %s", e)
            return None
        if sun_component is not None and sun_component.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            self._sun_source = "sun.sun"
            return sun_component
        return None

    def _clock_fallback_hour(self) -> int:
        """Return the current hour and record use of the clock fallback."""
        self._sun_source = "clock_fallback"
        if not self._sun_fallback_warned:
            _LOGGER.warning(
                "sun.sun is unavailable; using the 20:00-06:00 clock "
                "fallback with fast polling from 05:00"
            )
            self._sun_fallback_warned = True
        return dt_util.now().hour

    def _fast_expected_polling(self, threshold: float) -> bool:
        """Return whether an expected outage needs the recovery cadence."""
        sun_component = self._sun_component()
        if sun_component is not None:
            try:
                elevation = sun_component.attributes.get("elevation")
                if elevation is None:
                    return sun_component.state != "below_horizon"
                return elevation >= threshold or (
                    sun_component.attributes.get("rising") is True
                    and elevation >= _DAWN_ELEVATION_THRESHOLD
                )
            except Exception as e:  # noqa: BLE001 - defensive, must not fail a poll
                _LOGGER.debug("Error checking sun position: %s", e)

        current_hour = self._clock_fallback_hour()
        return _CLOCK_DAWN_HOUR <= current_hour < _CLOCK_NIGHT_HOUR

    @callback
    def async_handle_midnight(self, now: datetime) -> None:
        """Force a listener refresh at local midnight for Energy Day sensors.

        `coordinator.data` is reassigned every poll regardless — the engine
        never raises, so that assignment always runs. What's suppressed is
        `async_update_listeners()`, and the mechanism is `always_update=False`
        plus `EngineSnapshot` equality (its `diagnostics` field is
        `compare=False` for exactly this reason): HA only notifies listeners
        when the new snapshot differs from the last one it notified with;
        `coordinator.data` is now a mapping of one snapshot per inverter,
        compared as a whole, so this invariant holds per inverter.
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

    # --- polling ------------------------------------------------------------

    async def _async_update_data(self) -> SnapshotMap:
        """Run one bus cycle and hand back every snapshot. Never raises."""
        if not self.engines:
            # Nothing can be in fault without an inverter; drop any leftover
            # connection issue, pending or not, and ask for an inverter.
            self._clear_repair_issue()
            self._create_no_inverter_issue()
            return {}
        async with self._cycle_lock:
            snapshots = await self._poll_cycle()
        await self._async_handle_snapshots(snapshots)
        self.update_interval = self._interval_for(snapshots)
        return snapshots

    async def _poll_cycle(self) -> SnapshotMap:
        """Poll engines in order; a connect failure fails the rest without I/O."""
        snapshots: SnapshotMap = {}
        bus_down = False
        for subentry_id, engine in self.engines.items():
            if bus_down:
                snapshot = await engine.record_bus_failure()
            else:
                try:
                    snapshot = await engine.poll()
                except Exception:  # noqa: BLE001 - the coordinator contract never raises
                    _LOGGER.exception(
                        "Unexpected error polling %s; treating as a fault",
                        self.subentry_title(subentry_id),
                    )
                    snapshot = self._restate_as_fault(subentry_id)
                bus_down = snapshot.link_failure is LinkFailure.CONNECT
            snapshots[subentry_id] = snapshot
        if self.link is not None and all(
            snapshot.state is EngineState.OFFLINE_EXPECTED
            for snapshot in snapshots.values()
        ):
            # Every inverter announced or is in darkness: free the client slot
            # until dawn. Engines never touch the shared socket themselves.
            await self.link.disconnect()
        return snapshots

    def _restate_as_fault(self, subentry_id: str) -> EngineSnapshot:
        """Build a fault snapshot after an unexpected exception from poll()."""
        previous = (self.data or {}).get(subentry_id)
        if previous is None:
            return EngineSnapshot(
                state=EngineState.OFFLINE_FAULT,
                values={},
                shutdown_announced=False,
                reconnecting=False,
                expected_outside_twilight=False,
                fault_since=dt_util.utcnow(),
                diagnostics={},
                link_failure=LinkFailure.EXCHANGE,
            )
        return replace(
            previous,
            state=EngineState.OFFLINE_FAULT,
            fault_since=previous.fault_since or dt_util.utcnow(),
            link_failure=LinkFailure.EXCHANGE,
        )

    def _interval_for(self, snapshots: SnapshotMap) -> timedelta:
        """The fastest cadence any inverter asks for."""
        if not snapshots:
            return self._configured_interval
        return min(
            self._interval_for_one(subentry_id, snapshot)
            for subentry_id, snapshot in snapshots.items()
        )

    def _interval_for_one(
        self, subentry_id: str, snapshot: EngineSnapshot
    ) -> timedelta:
        if snapshot.state is EngineState.OFFLINE_EXPECTED:
            threshold = self._thresholds.get(
                subentry_id, float(DEFAULT_TWILIGHT_ELEVATION_THRESHOLD)
            )
            interval = (
                DAWN_POLL_SECONDS
                if self._fast_expected_polling(threshold)
                else NIGHT_POLL_SECONDS
            )
            return timedelta(seconds=interval)
        if snapshot.state is EngineState.OFFLINE_FAULT or (
            snapshot.state is EngineState.UNKNOWN and snapshot.reconnecting
        ):
            return min(self._configured_interval, timedelta(seconds=FAULT_POLL_SECONDS))
        return self._configured_interval

    # --- handoff and shutdown ----------------------------------------------

    @asynccontextmanager
    async def validation_handoff(self) -> AsyncIterator[None]:
        """Pause polling and release the client slot for a short-lived probe."""
        async with self._cycle_lock:
            if self._shutdown:
                raise LinkClosed("coordinator is shut down")
            if self.link is not None:
                await self.link.disconnect()
            yield

    async def async_shutdown(self) -> None:
        """Stop scheduling, close every engine, then close the link exactly once.

        Home Assistant registers this on entry unload as well, so a second
        call must be a no-op.
        """
        await super().async_shutdown()  # idempotent in core; safe to repeat
        async with self._cycle_lock:
            # Keep this guard inside the lock: the once-only link close that
            # test_shutdown_closes_engines_and_link_exactly_once asserts
            # depends on it.
            if self._shutdown:
                return
            self._shutdown = True
            for engine in self.engines.values():
                await engine.close()
            if self.link is not None:
                await self.link.close()

    # --- repairs ------------------------------------------------------------

    async def _async_handle_snapshots(self, snapshots: SnapshotMap) -> None:
        """Log transitions and synchronize the endpoint's repair issue."""
        self._log_state_transitions(snapshots)
        for subentry_id, snapshot in snapshots.items():
            if snapshot.state is EngineState.ONLINE:
                self._verified_online.add(subentry_id)

        issue = async_get_issue_registry(self.hass).async_get_issue(
            DOMAIN, self._repair_issue_id
        )
        issue_data = issue.data or {} if issue is not None else {}
        if issue_data.get(REPAIR_PENDING) == 1:
            if self._pending_repair_verified(issue_data):
                self._clear_repair_issue()
            return
        faulted = self._faulted(snapshots)
        if not faulted:
            self._clear_repair_issue()
            return
        self._create_repair_issue(faulted)

    def _pending_repair_verified(self, issue_data: dict[str, Any]) -> bool:
        pending_endpoint = issue_data.get(REPAIR_PENDING_ENDPOINT)
        current_endpoint = endpoint_unique_id(
            self._entry.data[CONF_HOST], self._entry.data[CONF_PORT]
        )
        endpoint_ok = (
            pending_endpoint is None
            or pending_endpoint == self._endpoint_unique_id
            or self._endpoint_unique_id == current_endpoint
        )
        raw = issue_data.get(REPAIR_PENDING_INVERTERS)
        if isinstance(raw, str) and raw:
            required = {sid for sid in raw.split(",") if sid in self.engines}
        else:
            required = set(self.engines)
        return endpoint_ok and required <= self._verified_online

    def _faulted(self, snapshots: SnapshotMap) -> dict[str, float]:
        """Subentry IDs in a repair-worthy fault, with the fault age in seconds."""
        faulted: dict[str, float] = {}
        for subentry_id, snapshot in snapshots.items():
            seconds = self._repairable_fault_seconds(snapshot)
            if seconds is not None:
                faulted[subentry_id] = seconds
        return faulted

    def _log_state_transitions(self, snapshots: SnapshotMap) -> None:
        previous_map = self.data or {}
        for subentry_id, snapshot in snapshots.items():
            previous = previous_map.get(subentry_id)
            previous_state = previous.state if previous else None
            if snapshot.state is previous_state:
                continue
            if snapshot.state is EngineState.OFFLINE_FAULT:
                _LOGGER.warning(
                    "Inverter %s at %s:%s unreachable (fault)",
                    self.subentry_title(subentry_id),
                    self._entry.data[CONF_HOST],
                    self._entry.data[CONF_PORT],
                )
                continue
            _LOGGER.info(
                "Inverter %s connection state %s -> %s",
                self.subentry_title(subentry_id),
                previous_state,
                snapshot.state,
            )

    @staticmethod
    def _repairable_fault_seconds(snapshot: EngineSnapshot) -> float | None:
        """Return the age of a sustained fault that warrants a repair issue."""
        if (
            snapshot.state is not EngineState.OFFLINE_FAULT
            or snapshot.fault_since is None
        ):
            return None
        fault_seconds = (dt_util.utcnow() - snapshot.fault_since).total_seconds()
        return fault_seconds if fault_seconds >= FAULT_REPAIR_SECONDS else None

    def _create_repair_issue(self, faulted: dict[str, float]) -> None:
        """Create or refresh the endpoint's repair issue for the faulted set."""
        issue_context: dict[str, str] = {
            "host": self._entry.data[CONF_HOST],
            "port": str(self._entry.data[CONF_PORT]),
            "minutes": str(int(max(faulted.values()) // 60)),
            "inverters": ", ".join(self.subentry_title(sid) for sid in faulted),
        }
        # `inverter_ids` lets a later rename re-render the names.
        data: dict[str, str] = {**issue_context, "inverter_ids": ",".join(faulted)}
        async_create_issue(
            self.hass,
            DOMAIN,
            self._repair_issue_id,
            is_fixable=True,
            is_persistent=False,
            severity=IssueSeverity.ERROR,
            translation_key="connection_issues",
            translation_placeholders=issue_context,
            # The repair API's mutable data mapping has a broader value type.
            data=cast("dict[str, str | int | float | None]", data),
        )

    @callback
    def async_refresh_repair_issue(self) -> None:
        """Re-render the connection issue's inverter names after a rename.

        Works for a normal and a pending issue alike: every other data key,
        including the pending marker, is preserved.
        """
        issue = async_get_issue_registry(self.hass).async_get_issue(
            DOMAIN, self._repair_issue_id
        )
        if issue is None:
            return
        data = dict(issue.data or {})
        ids = [sid for sid in str(data.get("inverter_ids", "")).split(",") if sid]
        names = ", ".join(self.subentry_title(sid) for sid in ids)
        placeholders = {**(issue.translation_placeholders or {}), "inverters": names}
        data["inverters"] = names
        async_create_issue(
            self.hass,
            DOMAIN,
            self._repair_issue_id,
            breaks_in_ha_version=issue.breaks_in_ha_version,
            data=data,
            is_fixable=True,
            is_persistent=issue.is_persistent,
            issue_domain=issue.issue_domain,
            learn_more_url=issue.learn_more_url,
            severity=issue.severity or IssueSeverity.ERROR,
            translation_key=issue.translation_key or "connection_issues",
            translation_placeholders=placeholders,
        )

    def _clear_repair_issue(self) -> None:
        """End repair bookkeeping for a recovered or reclassified episode."""
        async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)

    def _create_no_inverter_issue(self) -> None:
        async_create_issue(
            self.hass,
            DOMAIN,
            self._no_inverter_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key=NO_INVERTER_ISSUE,
            translation_placeholders={"title": self._entry.title},
        )

    # --- per-inverter metadata ---------------------------------------------

    def _static_raw(self, subentry_id: str, key: str) -> Any:
        snapshot = (self.data or {}).get(subentry_id)
        if snapshot is None:
            return None
        return snapshot.values.get(key, {}).get("raw_value")

    def device_model_for(self, subentry_id: str) -> str | None:
        """Return the detected inverter model, from the latest snapshot."""
        typ_value = self._static_raw(subentry_id, DEVICE_KEY_TYPE)
        if typ_value is None:
            return None
        return DEVICE_TYPE_MAP.get(typ_value, f"Unknown ({typ_value})")

    def sw_version_for(self, subentry_id: str) -> str | None:
        """Return the detected firmware version, from the latest snapshot."""
        swv_value = self._static_raw(subentry_id, DEVICE_KEY_FIRMWARE)
        if swv_value is None:
            return None
        bdn_value = self._static_raw(subentry_id, DEVICE_KEY_BUILD)
        if bdn_value is not None:
            return f"{swv_value} (build {bdn_value})"
        return str(swv_value)

    def serial_number_for(self, subentry_id: str) -> str | None:
        """Return the detected serial number, from the latest snapshot."""
        din_value = self._static_raw(subentry_id, DEVICE_KEY_SERIAL)
        if din_value is None:
            return None
        return str(din_value)

    def last_successful_update_for(self, subentry_id: str) -> datetime | None:
        """Local-time timestamp of the inverter's last successful poll.

        Local time because sensor._is_new_day() compares .date() against
        dt_util.now().date(); a raw UTC value would shift the KDY rollover.
        """
        snapshot = (self.data or {}).get(subentry_id)
        if snapshot is None:
            return None
        last = snapshot.diagnostics.get("last_successful_poll")
        if not isinstance(last, datetime):
            return None
        return dt_util.as_local(last)


# Typed config entry: gives `entry.runtime_data` a real type instead of Any.
SolarmaxConfigEntry = ConfigEntry[SolarmaxCoordinator]
