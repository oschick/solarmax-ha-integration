"""SolarmaxLink transport tests — real sockets against the emulator."""

import asyncio
import time

import pytest

from custom_components.solarmax.connection import LinkTimeout, SolarmaxLink
from custom_components.solarmax.protocol import build_request


async def test_persistent_connection_reused(emulator):
    link = SolarmaxLink(*emulator.addr)
    try:
        for _ in range(3):
            response = await link.request(build_request(1, ["PAC"]))
            assert "PAC=" in response
        assert link.attempts == 1  # one TCP connect served all three
    finally:
        await link.close()


async def test_peer_fin_reconnects_transparently(emulator):
    """Idle FIN between polls is routine, not an error (measured behaviour)."""
    emulator.idle_timeout = 0.5
    link = SolarmaxLink(*emulator.addr)
    try:
        await link.request(build_request(1, ["PAC"]))
        await asyncio.sleep(0.9)  # emulator FINs us
        response = await link.request(build_request(1, ["PAC"]))
        assert "PAC=" in response
        assert link.reconnects == 1
    finally:
        await link.close()


async def test_dark_device_times_out_within_budget(emulator):
    """Dark = swallowed requests; must raise LinkTimeout inside response_timeout."""
    link = SolarmaxLink(*emulator.addr, response_timeout=0.5)
    try:
        await link.request(build_request(1, ["PAC"]))
        emulator.begin_dusk(announce_seconds=0)
        await asyncio.sleep(0.3)
        start = time.monotonic()
        with pytest.raises(LinkTimeout):
            await link.request(build_request(1, ["PAC"]))
        assert time.monotonic() - start < 2.0
    finally:
        await link.close()


async def test_refused_connection_raises_link_closed(emulator):
    """Connect-side OSErrors must surface as LinkClosed, never escape raw."""
    import pytest as _pytest

    from custom_components.solarmax.connection import LinkClosed

    dead_port_link = SolarmaxLink("127.0.0.1", 1)  # nothing listens on port 1
    with _pytest.raises(LinkClosed):
        await dead_port_link.request(build_request(1, ["PAC"]))
    await dead_port_link.close()


async def test_close_is_idempotent_and_deterministic(emulator):
    link = SolarmaxLink(*emulator.addr)
    await link.request(build_request(1, ["PAC"]))
    await link.close()
    await link.close()
    assert link.connected is False
