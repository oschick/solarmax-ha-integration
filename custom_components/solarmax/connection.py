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
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

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

    async def request(self, payload: str) -> str:
        """Send `payload` and return the response, reusing the connection."""
        if not self.connected:
            await self._connect()
        try:
            return await self._send_receive(payload)
        except _PeerClosed:
            await self._close_transport()
            self.reconnects += 1
            await self._connect()
            try:
                return await self._send_receive(payload)
            except _PeerClosed as err:
                await self._close_transport()
                raise LinkClosed(
                    f"peer at {self.host}:{self.port} closed the connection"
                ) from err

    async def close(self) -> None:
        """Idempotent, deterministic close; always leaves `connected` False."""
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
