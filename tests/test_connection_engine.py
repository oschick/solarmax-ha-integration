"""Engine orchestration against the emulator — the spec's success criteria."""

import asyncio

from custom_components.solarmax.connection import (
    ConnectionEngine,
    EngineState,
    SolarmaxLink,
)


def _engine(emulator, *, sun_below=lambda: False, grace=0.0, timeout=0.5):
    # grace=0.0 disables the startup window so classification is tested directly;
    # the two grace tests pass an explicit grace to exercise the window itself.
    link = SolarmaxLink(*emulator.addr, response_timeout=timeout)
    return ConnectionEngine(link, address=1, sun_below=sun_below, grace_seconds=grace)


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
