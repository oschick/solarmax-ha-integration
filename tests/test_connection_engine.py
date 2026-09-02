"""Engine orchestration against the emulator — the spec's success criteria."""

import asyncio

from custom_components.solarmax.connection import (
    ARMED_ESCALATION_MIN_FAILURES,
    ARMED_ESCALATION_SECONDS,
    POLL_BUDGET_SECONDS,
    ConnectionEngine,
    EngineState,
    SolarmaxLink,
)


class _FakeClock:
    """Deterministic stand-in for `time.monotonic` — advanced explicitly so
    escalation-window tests never need a real hour-long sleep."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _engine(emulator, *, sun_below=lambda: False, grace=0.0, timeout=0.5, clock=None):
    # grace=0.0 disables the startup window so classification is tested directly;
    # the two grace tests pass an explicit grace to exercise the window itself.
    link = SolarmaxLink(*emulator.addr, response_timeout=timeout)
    kwargs = {} if clock is None else {"clock": clock}
    return ConnectionEngine(
        link, address=1, sun_below=sun_below, grace_seconds=grace, **kwargs
    )


async def test_online_poll_returns_values_and_statics(emulator):
    emulator.set_noise(False)  # PAC jitters +-2% otherwise
    engine = _engine(emulator)
    try:
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE
        assert snapshot.values["PAC"]["value"] == 1500.0
        assert snapshot.values["PIN"]["raw_value"] > 0  # statics fetched
        assert snapshot.values["TYP"]["raw_value"] == 20650
    finally:
        await engine.close()


async def test_dusk_sequence_classifies_expected(emulator):
    """Success criterion 1: announced dusk -> OFFLINE_EXPECTED, armed."""
    engine = _engine(emulator)
    try:
        await engine.poll()
        emulator.begin_dusk(announce_seconds=0.4)
        snapshot = await engine.poll()  # sees 20002 + PDC residual
        assert snapshot.shutdown_announced is True
        await asyncio.sleep(0.6)  # device goes dark
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.OFFLINE_EXPECTED
        assert snapshot.values["KDY"]["raw_value"] >= 0  # last values retained
    finally:
        await engine.close()


async def test_announcement_slip_covered_by_pdc(emulator):
    """The 20002 frame can slip between polls; low PDC still arms."""
    engine = _engine(emulator)
    try:
        await engine.poll()
        emulator.begin_dusk(announce_seconds=0.4)
        emulator.respond_only(["PAC", "PDC", "KDY"])  # SYS withheld: PDC path alone
        await engine.poll()  # PDC residual 1.5W < 25W must arm without SYS
        await asyncio.sleep(0.6)
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.OFFLINE_EXPECTED
    finally:
        await engine.close()


async def test_unannounced_drop_at_noon_is_fault(emulator):
    """Success criterion 2: healthy -> dark with sun up = FAULT, fault_since set."""
    engine = _engine(emulator)
    try:
        await engine.poll()
        emulator.dark = True  # sudden death, no announcement
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.OFFLINE_FAULT
        assert snapshot.fault_since is not None
    finally:
        await engine.close()


async def test_sun_fallback_for_non_announcing_inverter(emulator):
    """Success criterion 4: no announcement, sun below -> EXPECTED."""
    engine = _engine(emulator, sun_below=lambda: True)
    try:
        await engine.poll()
        emulator.dark = True
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.OFFLINE_EXPECTED
    finally:
        await engine.close()


async def test_online_drop_is_fault_immediately_with_reconnecting_flag(emulator):
    """Q19(b): honest FAULT on first failed poll; grace only softens attributes."""
    engine = _engine(emulator, grace=60.0)
    try:
        await engine.poll()
        emulator.dark = True
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.OFFLINE_FAULT
        assert snapshot.reconnecting is True
        assert snapshot.fault_since is not None
    finally:
        await engine.close()


async def test_startup_grace_keeps_unknown(emulator):
    """From UNKNOWN, timeouts within the grace stay UNKNOWN, not FAULT."""
    emulator.dark = True
    engine = _engine(emulator, grace=60.0)
    try:
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.UNKNOWN
        assert snapshot.reconnecting is True
    finally:
        await engine.close()


async def test_partial_frame_is_online_and_can_arm(emulator):
    """Q15(c): a device that answers is online; SYS in a dying frame arms."""
    emulator.begin_dusk(announce_seconds=None)  # announce-only, no dark timer
    emulator.respond_only(["SYS"])
    engine = _engine(emulator)
    try:
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE
        assert snapshot.shutdown_announced is True
    finally:
        await engine.close()


async def test_expected_outside_twilight_flag(emulator):
    """Q22: noon DC-trip -> EXPECTED but flagged anomalous.

    NOTE: the brief's version of this test called `begin_dusk(announce_seconds=0)`
    with no intervening poll before the device went dark, which cannot arm the
    tracker (armed is only set by ArmingTracker.observe() on a *successful* poll,
    and a LinkTimeout carries no protocol data by construction — see Task 3).
    That is inconsistent with `EngineState`'s own "derived from poll evidence
    only" invariant and with `test_unannounced_drop_at_noon_is_fault`, which
    requires the identical (armed=False, sun_below=False) case to be FAULT.
    Fixed here, matching the shape of `test_dusk_sequence_classifies_expected`,
    by giving the tracker the one arming poll it needs. Confirmed with advisor
    review; the engine's `_on_failure` algorithm is unchanged from the brief.
    """
    engine = _engine(emulator, sun_below=lambda: False)
    try:
        await engine.poll()
        emulator.begin_dusk(announce_seconds=0.4)
        await engine.poll()  # observes SYS 20002 / PDC residual -> arms
        await asyncio.sleep(0.6)
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.OFFLINE_EXPECTED
        assert snapshot.expected_outside_twilight is True
    finally:
        await engine.close()


async def test_corrupt_crc_is_retried_within_the_poll(emulator):
    """One in-poll retry on RetryableProtocolError: line noise never fails a cycle."""
    engine = _engine(emulator)
    try:
        await engine.poll()
        emulator.inject("corrupt_crc")  # poisons exactly one response
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE
    finally:
        await engine.close()


async def test_truncated_frame_retried(emulator):
    engine = _engine(emulator)
    try:
        await engine.poll()
        emulator.inject("truncate")
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE
    finally:
        await engine.close()


async def test_empty_data_frame_does_not_crash(emulator):
    """Empty payload parses to zero values: still an answering device."""
    engine = _engine(emulator)
    try:
        await engine.poll()
        emulator.inject("empty_data")
        snapshot = await engine.poll()
        assert snapshot.state in (EngineState.ONLINE,)
        assert snapshot.values["PAC"]["value"] is not None  # held from poll 1
    finally:
        await engine.close()


async def test_recovery_clears_everything(emulator):
    # wake may first drain a stale backlogged socket
    engine = _engine(emulator, timeout=1.0)
    try:
        await engine.poll()
        emulator.begin_dusk(announce_seconds=0.4)
        await engine.poll()  # observes SYS 20002 / PDC residual -> arms
        await asyncio.sleep(0.6)
        assert (await engine.poll()).state is EngineState.OFFLINE_EXPECTED
        emulator.wake()
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE
        assert snapshot.shutdown_announced is False
        assert snapshot.fault_since is None
    finally:
        await engine.close()


async def test_statics_retried_within_the_poll(emulator):
    """The statics frame gets the same one-shot retry as the hot frame.

    Review fix: `_poll_inner` used to fetch statics via a bare
    `self._link.request(...)`, bypassing `_request_with_retry` entirely —
    a single CRC glitch on the statics frame failed the whole poll. Since
    `_statics_loaded` resets on every OFFLINE_EXPECTED entry, that
    unretried request is exactly the dawn poll after every dusk.
    """
    engine = _engine(emulator)
    try:
        emulator.inject("corrupt_crc")  # poisons the *statics* frame (first request)
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE
        assert "PIN" in snapshot.values
    finally:
        await engine.close()


async def test_sun_below_callback_exception_does_not_escape_poll(emulator):
    """A broken sun_below callback must not cross poll()'s "never raises" boundary.

    Review fix: `_on_failure` called `self._sun_below()` unguarded; an
    exception from a HA sun-integration callback raised straight out of
    poll(). Falls back to sun_below=False — the conservative reading, so
    an unknown sun position never suppresses a real fault.
    """

    def _raising_sun_below() -> bool:
        raise RuntimeError("boom")

    engine = _engine(emulator, sun_below=_raising_sun_below)
    try:
        await engine.poll()
        emulator.dark = True
        snapshot = await engine.poll()  # must not raise
        assert snapshot.state is EngineState.OFFLINE_FAULT
    finally:
        await engine.close()


async def test_dawn_recovery_after_on_failure_closed_link(emulator):
    """Final-review finding #1 regression guard.

    `ConnectionEngine._on_failure` calls `self._link.close()` on every
    OFFLINE_EXPECTED entry (so statics get re-fetched on the next connect,
    see the comment in `_on_failure`). The close()-vs-in-flight-poll race
    fix must NOT make `SolarmaxLink._closing` sticky: if it were never
    cleared, this routine close() at dusk would permanently refuse to
    reconnect and the integration would stay dark forever after the first
    night. `request()` clearing `_closing` on its own next entry is what
    keeps this dusk -> dawn recovery working.
    """
    engine = _engine(emulator, sun_below=lambda: True)
    try:
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE

        emulator.dark = True
        snapshot = await engine.poll()  # -> OFFLINE_EXPECTED, engine closes link
        assert snapshot.state is EngineState.OFFLINE_EXPECTED

        emulator.wake()
        snapshot = await engine.poll()  # dawn: link must be able to reconnect
        assert snapshot.state is EngineState.ONLINE
    finally:
        await engine.close()


async def test_empty_first_statics_frame_is_refetched(emulator):
    """Final-review finding #4: an empty statics frame must not latch
    `_statics_loaded`.

    `inject("empty_data")` poisons exactly the next response, which is the
    very first request a fresh engine sends (statics + device fields). That
    parses cleanly to `{}` — no exception — so before the fix
    `_statics_loaded` was set True unconditionally and TYP/PIN never
    arrived for the life of the entry. The fix gates on the device-info
    keys actually landing, so the next poll must re-fetch and succeed.
    """
    emulator.inject("empty_data")
    engine = _engine(emulator)
    try:
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE
        assert "TYP" not in snapshot.values
        assert "PIN" not in snapshot.values

        snapshot = await engine.poll()  # must re-fetch statics this time
        assert "TYP" in snapshot.values
        assert "PIN" in snapshot.values
    finally:
        await engine.close()


# --- Review-fix-wave: fault_since / armed escalation / closed / retry / lock ---


async def test_fault_since_is_not_backdated_across_a_night(emulator):
    """G16: fault_since must not survive an OFFLINE_EXPECTED window — a fault
    reclassified back to FAULT at dawn must get a fresh timestamp, not the
    one from before dusk (which would make the repair issue fire instantly,
    counting the whole night as part of the fault)."""
    sun_below = False  # noon
    engine = _engine(emulator, sun_below=lambda: sun_below, grace=0.0)
    try:
        await engine.poll()
        emulator.dark = True  # sudden daytime fault at "14:00", sun still up
        fault_snapshot = await engine.poll()
        assert fault_snapshot.state is EngineState.OFFLINE_FAULT
        assert fault_snapshot.fault_since is not None

        sun_below = True  # dusk falls; the same unresolved outage now reads EXPECTED
        expected_snapshot = await engine.poll()
        assert expected_snapshot.state is EngineState.OFFLINE_EXPECTED
        assert expected_snapshot.fault_since is None  # G16: cleared on entry

        sun_below = False  # dawn: sun is back up, device still not responding
        dawn_snapshot = await engine.poll()
        assert dawn_snapshot.state is EngineState.OFFLINE_FAULT
        assert dawn_snapshot.fault_since is not None
        assert dawn_snapshot.fault_since > fault_snapshot.fault_since  # fresh
    finally:
        await engine.close()


async def test_armed_escalates_to_fault_after_sustained_anomaly(emulator):
    """Q24: armed OFFLINE_EXPECTED with the sun staying up for >=1h and
    >=10 failed probes (zero successes) escalates to OFFLINE_FAULT; arming
    clears and fault_since stamps fresh at escalation.

    Drives `_on_failure()` directly for the repeated-failure steps (rather
    than `poll()` against a dark emulator) to avoid ~20 real connect/timeout
    cycles for what is purely internal counting/threshold logic; the wiring
    from `poll()` into `_on_failure()` on every failure path is already
    covered by every other test in this module.
    """
    clock = _FakeClock()
    engine = _engine(emulator, sun_below=lambda: False, clock=clock)
    try:
        await engine.poll()
        emulator.begin_dusk(announce_seconds=0.4)
        armed_snapshot = await engine.poll()  # sees SYS 20002 + low PDC -> arms
        assert armed_snapshot.shutdown_announced is True

        for _ in range(9):  # below the 10-failure floor: no escalation yet
            snapshot = await engine._on_failure()
        assert snapshot.state is EngineState.OFFLINE_EXPECTED
        assert snapshot.expected_outside_twilight is True
        assert snapshot.shutdown_announced is True

        clock.advance(ARMED_ESCALATION_SECONDS + 1)
        snapshot = await engine._on_failure()  # 10th failed probe, window elapsed
        assert snapshot.state is EngineState.OFFLINE_FAULT
        assert snapshot.shutdown_announced is False  # armed cleared on escalation
        assert snapshot.expected_outside_twilight is False
        assert snapshot.fault_since is not None
    finally:
        await engine.close()


async def test_armed_anomaly_below_window_stays_expected(emulator):
    """Q24: >=10 failures with the elapsed window still short must not
    escalate — both thresholds are required together."""
    clock = _FakeClock()
    engine = _engine(emulator, sun_below=lambda: False, clock=clock)
    try:
        await engine.poll()
        emulator.begin_dusk(announce_seconds=0.4)
        await engine.poll()  # arms

        clock.advance(100.0)  # well under ARMED_ESCALATION_SECONDS
        snapshot = None
        for _ in range(ARMED_ESCALATION_MIN_FAILURES + 5):
            snapshot = await engine._on_failure()
        assert snapshot.state is EngineState.OFFLINE_EXPECTED
        assert snapshot.expected_outside_twilight is True
    finally:
        await engine.close()


async def test_armed_with_sun_below_needs_no_escalation(emulator):
    """Q24: a sun-classified (non-anomalous) EXPECTED never escalates, no
    matter how long it persists or how many probes fail."""
    clock = _FakeClock()
    engine = _engine(emulator, sun_below=lambda: True, clock=clock)
    try:
        await engine.poll()
        emulator.begin_dusk(announce_seconds=0.4)
        await engine.poll()  # arms, but sun is already below threshold

        clock.advance(ARMED_ESCALATION_SECONDS * 2)
        snapshot = None
        for _ in range(ARMED_ESCALATION_MIN_FAILURES + 5):
            snapshot = await engine._on_failure()
        assert snapshot.state is EngineState.OFFLINE_EXPECTED
        assert snapshot.expected_outside_twilight is False
    finally:
        await engine.close()


async def test_poll_after_close_never_touches_link(emulator):
    """Engine-level closed flag: once close() has run, poll() must return
    without ever calling into the link again — no reconnect, no request.

    This is what closes the reload leak: a scheduled refresh racing HA
    unload used to reach `SolarmaxLink.request()`, whose first line clears
    `_closing` (a fresh request IS the intentional re-open) and resurrects
    the connection behind close()'s back.
    """
    link = SolarmaxLink(*emulator.addr, response_timeout=0.5)
    engine = ConnectionEngine(
        link, address=1, sun_below=lambda: False, grace_seconds=0.0
    )
    online_snapshot = await engine.poll()
    assert online_snapshot.state is EngineState.ONLINE
    attempts_before = link.attempts

    await engine.close()
    snapshot = await engine.poll()

    assert link.attempts == attempts_before
    assert snapshot.state is EngineState.ONLINE  # previous snapshot, not touched


async def test_timeout_is_retried_once_within_the_poll(emulator):
    """Q26: a single dropped response is retried once in-poll, same as line
    noise — the poll still comes back ONLINE rather than failing."""
    engine = _engine(emulator, timeout=1.0)
    try:
        await engine.poll()  # baseline: statics loaded
        emulator.inject("drop")  # swallow exactly the next request, no reply
        snapshot = await engine.poll()
        assert snapshot.state is EngineState.ONLINE
    finally:
        await engine.close()


async def test_concurrent_polls_are_serialized(emulator):
    """Poll lock: HA's debouncer can run a refresh concurrently with a
    scheduled one; without serialising, two `poll()`s racing the same
    `SolarmaxLink` corrupt each other's connect/request sequencing."""
    link = SolarmaxLink(*emulator.addr)
    engine = ConnectionEngine(
        link, address=1, sun_below=lambda: False, grace_seconds=0.0
    )
    try:
        results = await asyncio.gather(engine.poll(), engine.poll())
        assert all(s.state is EngineState.ONLINE for s in results)
        assert link.attempts == 1  # one connection served both polls, serially
    finally:
        await engine.close()


def test_timeouts_widened_per_q27():
    """Q27: response timeout 2.0 -> 3.5s, POLL_BUDGET 10 -> 15s."""
    link = SolarmaxLink("127.0.0.1", 1)
    assert link.response_timeout == 3.5
    assert POLL_BUDGET_SECONDS == 15.0
