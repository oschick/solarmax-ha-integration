"""Lifecycle tests for the hardware-free inverter emulator."""

from __future__ import annotations

import socket
import threading
import time

from tests import emulator as emulator_support

SolarmaxEmulator = emulator_support.SolarmaxEmulator


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition was not met before timeout")
        time.sleep(0.01)


def test_stop_waits_for_every_client_handler(socket_enabled) -> None:
    """Replacing the latest handler reference must not leak an older thread."""
    emulator = SolarmaxEmulator(host="127.0.0.1", port=0)
    server_thread = threading.Thread(target=emulator.start, daemon=True)
    handlers: list[threading.Thread] = []
    original_handle_client = emulator.handle_client

    def lingering_handle_client(client_socket, client_addr) -> None:
        original_handle_client(client_socket, client_addr)
        handlers.append(threading.current_thread())
        time.sleep(1.0 if len(handlers) == 1 else 0.05)

    emulator.handle_client = lingering_handle_client
    server_thread.start()

    try:
        _wait_until(lambda: emulator.bound_port is not None)
        address = ("127.0.0.1", emulator.bound_port)

        for expected_handlers in (1, 2):
            with socket.create_connection(address, timeout=1):
                pass
            _wait_until(lambda expected=expected_handlers: len(handlers) == expected)

        emulator.stop()

        assert all(not thread.is_alive() for thread in handlers)
    finally:
        emulator.stop()
        server_thread.join(timeout=2)
        for thread in handlers:
            thread.join(timeout=2)


def test_interactive_set_command_updates_state(capsys) -> None:
    """The interactive set command must update a known emulator field."""
    emulator = SolarmaxEmulator()

    keep_running = emulator_support._mod.execute_interactive_command(
        emulator, "set pac 42"
    )

    assert keep_running is True
    assert emulator.state.pac == 42
    assert "pac = 42" in capsys.readouterr().out


def test_interactive_scenario_command_replaces_state(capsys) -> None:
    """The scenario command must load the requested predefined state."""
    emulator = SolarmaxEmulator()

    keep_running = emulator_support._mod.execute_interactive_command(
        emulator, "scenario night"
    )

    assert keep_running is True
    assert emulator.state.sys == 20000
    assert "Loaded scenario: night" in capsys.readouterr().out


def test_interactive_quit_command_stops_the_loop() -> None:
    """Quit and exit commands must tell the interactive loop to stop."""
    emulator = SolarmaxEmulator()

    assert emulator_support._mod.execute_interactive_command(emulator, "quit") is False
    assert emulator_support._mod.execute_interactive_command(emulator, "exit") is False
