"""Reconfiguration handoff tests against the single-client emulator."""

from custom_components.solarmax.connection import (
    ConnectionEngine,
    EngineState,
    SolarmaxLink,
)
from custom_components.solarmax.protocol import build_request, parse_response


async def test_validation_handoff_releases_single_client_slot(emulator):
    """A validation client owns the sole socket slot only during handoff."""
    host, port = emulator.addr
    link = SolarmaxLink(host, port)
    engine = ConnectionEngine(link, address=1, sun_below=lambda: False)
    assert (await engine.poll()).state is EngineState.ONLINE

    async with engine.validation_handoff():
        probe = SolarmaxLink(host, port)
        try:
            raw = await probe.request(build_request(1, ["PAC"]))
            assert parse_response(raw, verify_checksum=True)["PAC"]["value"] >= 0
        finally:
            await probe.close()

    assert (await engine.poll()).state is EngineState.ONLINE
    await engine.close()
