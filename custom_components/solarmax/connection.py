"""Connection primitives and transport for the SolarMax MaxComm link.

The inverter announces its own shutdown (SYS status 20002, DC power dropping
to a 1-2W residual) before it leaves the network. Arming reflects the
evidence seen on the LAST successful poll; a disconnect while armed (or with
the sun below the twilight threshold) is expected rather than a fault.

The state-machine primitives below (EngineState, ArmingTracker,
classify_disconnect, EngineDiagnostics, EngineSnapshot) are pure — no
sockets, no I/O. SolarmaxLink is the async transport added on top of them;
it owns the one real TCP connection to the device. Later tasks add
orchestration (ConnectionEngine) to this same module; do not rename or
restructure the names defined here.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from .protocol import (
    DEVICE_FIELDS,
    HOT_FIELDS,
    STATIC_FIELDS,
    ProtocolError,
    RetryableProtocolError,
    build_request,
    parse_response,
)

_LOGGER = logging.getLogger(__name__)

LOW_PDC_WATTS = 25
SHUTDOWN_ANNOUNCE_SYS = 20002
STARTUP_GRACE_SECONDS = 150.0
POLL_BUDGET_SECONDS = 10.0


class EngineState(StrEnum):
    """Observed connection state, derived from poll evidence only."""

    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE_EXPECTED = "offline_expected"
    OFFLINE_FAULT = "offline_fault"


class ArmingTracker:
    """Single-poll arming from the two observational indicators (spec)."""

    def __init__(self, low_pdc_watts: float = LOW_PDC_WATTS) -> None:
        self.low_pdc_watts = low_pdc_watts
        self.armed = False

    def observe(self, values: dict[str, dict[str, float | int]]) -> None:
        evidence = False
        armed = False
        if "SYS" in values:
            evidence = True
            armed = armed or values["SYS"]["raw_value"] == SHUTDOWN_ANNOUNCE_SYS
        if "PDC" in values:
            evidence = True
            armed = armed or values["PDC"]["value"] < self.low_pdc_watts
        if evidence:
            self.armed = armed


def classify_disconnect(armed: bool, sun_below: bool) -> EngineState:
    """Classify a disconnect as expected (announced, or after dark) or a fault."""
    if armed or sun_below:
        return EngineState.OFFLINE_EXPECTED
    return EngineState.OFFLINE_FAULT


@dataclass
class EngineDiagnostics:
    """Poll/connection counters and the most recent state transitions."""

    connection_attempts: int = 0
    reconnects: int = 0
    timeouts: int = 0
    polls_ok: int = 0
    last_successful_poll: datetime | None = None
    last_shutdown_announcement: datetime | None = None
    transitions: list[tuple[str, str, str]] = field(default_factory=list)

    def record_transition(self, from_state: str, to_state: str) -> None:
        """Append an (iso-ts, from, to) transition, capped at the last 20."""
        self.transitions.append((datetime.now(UTC).isoformat(), from_state, to_state))
        del self.transitions[:-20]


@dataclass(frozen=True)
class EngineSnapshot:
    """Immutable result of a single poll cycle."""

    state: EngineState
    values: dict[str, dict[str, float | int]]
    shutdown_announced: bool
    reconnecting: bool
    expected_outside_twilight: bool
    fault_since: datetime | None
    # HA notifies listeners on `previous_data != self.data`; per-poll counter
    # churn in diagnostics must not defeat `always_update=False`, so it is
    # excluded from equality/hash comparison.
    diagnostics: dict[str, object] = field(compare=False)


class LinkTimeout(Exception):
    """No answer within the connect/response timeout budget (lockout/dark)."""


class LinkClosed(Exception):
    """Peer closed the connection (FIN/reset/EPIPE) and no recovery was possible."""


class _PeerClosed(Exception):
    """Internal signal: peer closed the socket — triggers one reconnect+resend."""


class SolarmaxLink:
    """Persistent async TCP transport to a single SolarMax inverter.

    The device serves exactly one TCP client and FINs idle connections at
    ~100 s. `request()` reuses one connection across calls, transparently
    reconnecting-and-resending once if the peer has closed it; any timeout
    (connect or response) raises `LinkTimeout` with no internal retry. No
    raw `OSError` is ever allowed to cross this boundary — an escaped
    exception would flip HA's `last_update_success` incorrectly.
    """

    def __init__(
        self,
        host: str,
        port: int,
        connect_timeout: float = 3.0,
        response_timeout: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.response_timeout = response_timeout
        self.connected = False
        self.attempts = 0
        self.reconnects = 0
        self.timeouts = 0
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._closing = False

    async def request(self, payload: str) -> str:
        """Send `payload` and return the response, reusing the connection."""
        self._closing = False  # a fresh request IS the re-open
        if not self.connected:
            await self._connect()
        try:
            return await self._send_receive(payload)
        except _PeerClosed as err:
            await self._close_transport()
            if self._closing:  # closed underneath us — do NOT reopen
                raise LinkClosed(
                    f"{self.host}:{self.port}: closed during poll"
                ) from err
            self.reconnects += 1
            await self._connect()
            try:
                return await self._send_receive(payload)
            except _PeerClosed as err2:
                await self._close_transport()
                raise LinkClosed(
                    f"peer at {self.host}:{self.port} closed the connection"
                ) from err2

    async def close(self) -> None:
        """Idempotent, deterministic close; always leaves `connected` False.

        Sets `_closing` before the transport actually tears down, so a
        `request()` racing this close() on another task (e.g. an in-flight
        poll during HA unload) sees it in its `_PeerClosed` handler and does
        not resurrect the connection. Never cleared here: `request()` clears
        it on its own next entry instead, since a fresh request IS the
        intentional re-open — including the one `ConnectionEngine._on_failure`
        makes on every OFFLINE_EXPECTED entry, which closes the link on
        purpose and must still be able to reconnect at dawn.
        """
        self._closing = True
        await self._close_transport()

    async def _connect(self) -> None:
        self.attempts += 1
        try:
            async with asyncio.timeout(self.connect_timeout):
                reader, writer = await asyncio.open_connection(self.host, self.port)
        except TimeoutError as err:
            self.timeouts += 1
            self._abort_transport()
            raise LinkTimeout(f"connect to {self.host}:{self.port} timed out") from err
        except OSError as err:
            self._abort_transport()
            raise LinkClosed(
                f"connect to {self.host}:{self.port} failed: {err}"
            ) from err

        # Assign before setsockopt so a failure below leaves a live writer
        # reachable by `_abort_transport` — never an orphaned open socket.
        self._reader = reader
        self._writer = writer
        self.connected = True

        try:
            sock = writer.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError as err:
            self._abort_transport()
            raise LinkClosed(
                f"connect to {self.host}:{self.port} failed: {err}"
            ) from err

    async def _send_receive(self, payload: str) -> str:
        reader, writer = self._reader, self._writer
        if reader is None or writer is None:
            raise LinkClosed(f"{self.host}:{self.port}: transport is not connected")
        try:
            async with asyncio.timeout(self.response_timeout):
                writer.write(payload.encode())
                await writer.drain()
                buf = b""
                while not buf.endswith(b"}"):
                    chunk = await reader.read(4096)
                    if not chunk:
                        raise _PeerClosed("peer closed the connection (EOF)")
                    buf += chunk
                return buf.decode(errors="ignore")
        except TimeoutError as err:
            self.timeouts += 1
            self._abort_transport()
            raise LinkTimeout(
                f"no response from {self.host}:{self.port} "
                f"within {self.response_timeout}s"
            ) from err
        except (ConnectionResetError, BrokenPipeError) as err:
            raise _PeerClosed(str(err)) from err
        except OSError as err:
            await self._close_transport()
            raise LinkClosed(f"{self.host}:{self.port}: {err}") from err
        except asyncio.CancelledError:
            # External cancellation (e.g. an outer asyncio.timeout wrapping a
            # poll, or HA cancelling a coordinator refresh on unload) can land
            # here mid-read. Abort synchronously — no `await` — so an
            # in-flight response can never be left on the wire for the NEXT
            # request() to read as a stale frame.
            self._abort_transport()
            raise

    def _abort_transport(self) -> None:
        """Synchronous, non-blocking transport teardown.

        `writer.close()` + `await writer.wait_closed()` is a graceful
        shutdown that can block if the peer has stopped reading (the
        measured silent-hang lockout). `transport.abort()` tears the socket
        down immediately and has no `await`, so it is also safe to call
        while unwinding a `CancelledError`.
        """
        writer = self._writer
        self._writer = None
        self._reader = None
        self.connected = False
        if writer is not None:
            writer.transport.abort()

    async def _close_transport(self) -> None:
        writer = self._writer
        self._writer = None
        self._reader = None
        self.connected = False
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass


class ConnectionEngine:
    """Composes the codec, the state machine, and the link into poll().

    Every `poll()` call returns an `EngineSnapshot` classified from what
    that poll (and, for arming, the LAST successful poll) actually
    observed — never from elapsed time or assumptions about why a request
    failed. `EngineState`'s own docstring is the invariant this class
    exists to uphold: state is derived from poll evidence only.
    """

    def __init__(
        self,
        link: SolarmaxLink,
        address: int,
        sun_below: Callable[[], bool],
        verify_checksum: bool = True,
        low_pdc_watts: float = LOW_PDC_WATTS,
        grace_seconds: float = STARTUP_GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._link = link
        self._address = address
        self._sun_below = sun_below
        self._verify_checksum = verify_checksum
        self._grace_seconds = grace_seconds
        self._clock = clock
        self._tracker = ArmingTracker(low_pdc_watts)
        self._diagnostics = EngineDiagnostics()
        self._values: dict[str, dict[str, float | int]] = {}
        self._statics_loaded = False
        self._state = EngineState.UNKNOWN
        self._fault_since: datetime | None = None
        # Anchors "how long have we been unable to reach a good state":
        # set at construction (covers the startup grace below), cleared on
        # every successful poll, and re-anchored to "now" on the FIRST
        # failure after a success (covers the post-ONLINE reconnecting
        # grace). Both grace windows share this one anchor.
        self._disconnected_since: float | None = self._clock()

    async def poll(self) -> EngineSnapshot:
        try:
            async with asyncio.timeout(POLL_BUDGET_SECONDS):  # spec: poll budget < 10s
                return await self._poll_inner()
        except TimeoutError:
            return await self._on_failure()

    async def close(self) -> None:
        await self._link.close()

    async def _poll_inner(self) -> EngineSnapshot:
        try:
            if not self._statics_loaded:
                static_raw = await self._request_with_retry(
                    build_request(self._address, STATIC_FIELDS + DEVICE_FIELDS)
                )
                static = parse_response(static_raw, self._verify_checksum)
                self._values.update(static)
                # An empty/short frame (e.g. inject("empty_data")) parses to
                # {} with no exception; `bool(static)` would latch "loaded"
                # on that (or on any non-empty-but-still-fieldless reply)
                # and lose TYP/PIN/etc. for the life of the entry. Gate on
                # the device-info keys actually landing instead. The
                # tradeoff: an inverter that never reports them re-fetches
                # statics on every poll forever (doubled traffic) rather
                # than once — accepted deliberately, since silently losing
                # device info is worse than the extra request.
                self._statics_loaded = any(k in static for k in DEVICE_FIELDS)
            raw = await self._request_with_retry(
                build_request(self._address, HOT_FIELDS)
            )
            values = parse_response(raw, self._verify_checksum)
        except (LinkTimeout, LinkClosed, RetryableProtocolError):
            return await self._on_failure()
        except ProtocolError:
            return await self._on_failure()  # IPR/IPN: no data either way
        return self._on_success(values)

    async def _request_with_retry(self, payload: str) -> str:
        """Fetch `payload`, retrying once if the response fails to parse.

        Only `RetryableProtocolError` (checksum/frame corruption — line
        noise) triggers the retry. `LinkClosed` is already retried
        transparently inside `SolarmaxLink`; `LinkTimeout` is deliberately
        NOT retried here — a dark device fails fast by design, and
        retrying a timeout would double the poll budget for the one case
        where the honest answer is "no response".
        """
        raw = await self._link.request(payload)
        try:
            parse_response(raw, self._verify_checksum)
        except RetryableProtocolError:
            raw = await self._link.request(payload)
        return raw

    def _on_success(self, values: dict[str, dict[str, float | int]]) -> EngineSnapshot:
        # Absent keys keep their last reading (Q15) — never drop a value
        # just because this poll's frame didn't repeat it.
        self._values.update(values)

        was_armed = self._tracker.armed
        self._tracker.observe(values)
        if self._tracker.armed and not was_armed:
            self._diagnostics.last_shutdown_announcement = datetime.now(UTC)

        previous_state = self._state
        self._state = EngineState.ONLINE
        if previous_state is not self._state:
            self._diagnostics.record_transition(previous_state, self._state)
        self._diagnostics.polls_ok += 1
        self._diagnostics.last_successful_poll = datetime.now(UTC)

        self._fault_since = None
        self._disconnected_since = None

        return self._snapshot(reconnecting=False, expected_outside_twilight=False)

    async def _on_failure(self) -> EngineSnapshot:
        previous_state = self._state
        armed = self._tracker.armed
        try:
            sun_below = self._sun_below()
        except Exception:
            # An unknown sun position must never suppress a real fault, so
            # a broken callback falls back to "not below the threshold"
            # (the conservative reading) rather than crossing poll()'s
            # "never raises" boundary.
            _LOGGER.warning(
                "sun_below callback raised; assuming sun is up", exc_info=True
            )
            sun_below = False

        if armed or sun_below:
            new_state = EngineState.OFFLINE_EXPECTED
            expected_outside_twilight = not sun_below and armed
            reconnecting = False
            # Deliberate deviation: re-fetch statics on OFFLINE_EXPECTED
            # entry rather than on every transparent Link reconnect. The
            # spec's "once per connection establishment" is read loosely
            # here — statics cannot change mid-day, so paying for a
            # re-fetch only at dusk/dawn is enough.
            await self._link.close()
            self._statics_loaded = False
        else:
            expected_outside_twilight = False
            if self._disconnected_since is None:
                self._disconnected_since = self._clock()
            reconnecting = (
                self._clock() - self._disconnected_since
            ) < self._grace_seconds
            if previous_state is EngineState.UNKNOWN and reconnecting:
                # Startup grace covers UNKNOWN only (spec).
                new_state = EngineState.UNKNOWN
            else:
                # Honest FAULT on the first failed poll; grace only
                # softens `reconnecting`/logging, never `state`, and never
                # delays `fault_since` (spec Q19(b)).
                new_state = EngineState.OFFLINE_FAULT
                if self._fault_since is None:
                    self._fault_since = datetime.now(UTC)

        self._state = new_state
        if previous_state is not new_state:
            self._diagnostics.record_transition(previous_state, new_state)

        return self._snapshot(
            reconnecting=reconnecting,
            expected_outside_twilight=expected_outside_twilight,
        )

    def _snapshot(
        self, *, reconnecting: bool, expected_outside_twilight: bool
    ) -> EngineSnapshot:
        # Every snapshot rebuilds diagnostics from the link's live
        # counters so they never go stale/zero (Task 7 serialises these).
        self._diagnostics.connection_attempts = self._link.attempts
        self._diagnostics.reconnects = self._link.reconnects
        self._diagnostics.timeouts = self._link.timeouts
        return EngineSnapshot(
            state=self._state,
            values=dict(self._values),  # fresh copy every snapshot
            shutdown_announced=self._tracker.armed,
            reconnecting=reconnecting,
            expected_outside_twilight=expected_outside_twilight,
            fault_since=self._fault_since,
            diagnostics=asdict(self._diagnostics),
        )
