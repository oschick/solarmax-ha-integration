"""Observed state-machine primitives for connection tracking (pure, no I/O).

The inverter announces its own shutdown (SYS status 20002, DC power dropping
to a 1-2W residual) before it leaves the network. Arming reflects the
evidence seen on the LAST successful poll; a disconnect while armed (or with
the sun below the twilight threshold) is expected rather than a fault.

This module is pure — no sockets, no I/O. Later tasks add the async
transport (SolarmaxLink) and orchestration (ConnectionEngine) to this same
module; do not rename or restructure the names defined here.
"""

from __future__ import annotations

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
