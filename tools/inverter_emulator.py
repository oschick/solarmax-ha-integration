#!/usr/bin/env python3
"""Solarmax Inverter Emulator.

A TCP server that emulates a Solarmax inverter for testing the HA integration
when the real inverter is offline.

Usage:
    python3 tools/inverter_emulator.py [--port 12345] [--address 1] [--scenario day]

Scenarios:
    day          - Normal daytime operation (default)
    night        - Nighttime / no irradiation
    starting     - Inverter starting up
    alarm        - Active alarm condition
    multi_alarm  - Multiple alarms active
    max_power    - Running at maximum power
    custom       - Interactive mode: set values manually

Examples:
    # Run with defaults (daytime operation on port 12345)
    python3 tools/inverter_emulator.py

    # Simulate nighttime
    python3 tools/inverter_emulator.py --scenario night

    # Run on a different port
    python3 tools/inverter_emulator.py --port 12346

    # Interactive mode - change values at runtime
    python3 tools/inverter_emulator.py --scenario custom
"""

from __future__ import annotations

import argparse
import logging
import random
import socket
import sys
import threading
import time
from dataclasses import dataclass, field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_LOGGER = logging.getLogger("solarmax_emulator")


@dataclass
class InverterState:
    """Holds the current emulated inverter state."""

    # Status (SYS) - raw integer code
    sys: int = 20004  # MPP operation

    # Alarm (SAL) - bitmask
    sal: int = 0  # No error

    # Power values (raw values before division)
    pac: int = 3000  # AC Power: 3000/2 = 1500W
    pdc: int = 3200  # DC Power: 3200/2 = 1600W
    pd01: int = 1600  # DC Power String 1: 1600/2 = 800W
    pd02: int = 1600  # DC Power String 2: 1600/2 = 800W

    # Voltage values (raw values before /10)
    ul1: int = 2300  # AC Voltage Phase 1: 2300/10 = 230.0V
    ul2: int = 2310  # AC Voltage Phase 2: 2310/10 = 231.0V
    ul3: int = 2295  # AC Voltage Phase 3: 2295/10 = 229.5V
    ud01: int = 3500  # DC Voltage String 1: 3500/10 = 350.0V
    ud02: int = 3480  # DC Voltage String 2: 3480/10 = 348.0V

    # Current values (raw values before /100)
    idc: int = 450  # DC Current: 450/100 = 4.50A
    id01: int = 230  # DC Current String 1: 230/100 = 2.30A
    id02: int = 220  # DC Current String 2: 220/100 = 2.20A
    il1: int = 220  # AC Current Phase 1: 220/100 = 2.20A
    il2: int = 215  # AC Current Phase 2: 215/100 = 2.15A
    il3: int = 218  # AC Current Phase 3: 218/100 = 2.18A

    # Energy values (raw)
    kdy: int = 85  # Energy Day: 85/10 = 8.5 kWh
    kmt: int = 350  # Energy Month: 350 kWh
    kyr: int = 4200  # Energy Year: 4200 kWh
    kt0: int = 28500  # Energy Total: 28500 kWh

    # Other
    tkk: int = 42  # Temperature: 42°C
    khr: int = 15230  # Power On Hours
    cac: int = 1847  # Startups

    # Simulation settings
    add_noise: bool = True  # Add small random variations


def get_scenario_state(scenario: str) -> InverterState:
    """Get inverter state for a predefined scenario."""
    if scenario == "night":
        return InverterState(
            sys=20000,  # No communication
            sal=0,
            pac=0, pdc=0, pd01=0, pd02=0,
            ul1=0, ul2=0, ul3=0,
            ud01=0, ud02=0,
            idc=0, id01=0, id02=0,
            il1=0, il2=0, il3=0,
            kdy=85, kmt=350, kyr=4200, kt0=28500,
            tkk=18, khr=15230, cac=1847,
            add_noise=False,
        )
    elif scenario == "starting":
        return InverterState(
            sys=20003,  # Starting up
            sal=0,
            pac=0, pdc=100, pd01=50, pd02=50,
            ul1=2300, ul2=2310, ul3=2295,
            ud01=2800, ud02=2750,
            idc=10, id01=5, id02=5,
            il1=0, il2=0, il3=0,
            kdy=0, kmt=350, kyr=4200, kt0=28500,
            tkk=22, khr=15230, cac=1848,
            add_noise=False,
        )
    elif scenario == "alarm":
        return InverterState(
            sys=20001,  # In operation
            sal=2,  # Insulation fault DC side
            pac=500, pdc=600, pd01=300, pd02=300,
            ul1=2300, ul2=2310, ul3=2295,
            ud01=3200, ud02=3180,
            idc=200, id01=100, id02=100,
            il1=75, il2=72, il3=73,
            kdy=30, kmt=350, kyr=4200, kt0=28500,
            tkk=38, khr=15230, cac=1847,
        )
    elif scenario == "multi_alarm":
        return InverterState(
            sys=20001,  # In operation
            sal=5,  # External fault 1 (1) + Earth fault current (4) = 5
            pac=200, pdc=250, pd01=125, pd02=125,
            ul1=2280, ul2=2290, ul3=2275,
            ud01=3000, ud02=2980,
            idc=80, id01=40, id02=40,
            il1=30, il2=28, il3=29,
            kdy=15, kmt=350, kyr=4200, kt0=28500,
            tkk=45, khr=15230, cac=1847,
        )
    elif scenario == "max_power":
        return InverterState(
            sys=20006,  # Max power operation
            sal=0,
            pac=10000, pdc=10500, pd01=5250, pd02=5250,
            ul1=2350, ul2=2360, ul3=2345,
            ud01=5800, ud02=5750,
            idc=1800, id01=900, id02=900,
            il1=1450, il2=1440, il3=1445,
            kdy=250, kmt=1200, kyr=4800, kt0=29000,
            tkk=58, khr=15230, cac=1847,
        )
    elif scenario == "low_irradiation":
        return InverterState(
            sys=20002,  # Low irradiation
            sal=0,
            pac=100, pdc=150, pd01=75, pd02=75,
            ul1=2300, ul2=2310, ul3=2295,
            ud01=2200, ud02=2150,
            idc=30, id01=15, id02=15,
            il1=15, il2=14, il3=14,
            kdy=5, kmt=350, kyr=4200, kt0=28500,
            tkk=25, khr=15230, cac=1847,
        )
    else:
        # Default: day / normal MPP operation
        return InverterState()


class SolarmaxEmulator:
    """TCP server emulating a Solarmax inverter."""

    def __init__(self, host: str = "0.0.0.0", port: int = 12345, address: int = 1):
        """Initialize the emulator."""
        self.host = host
        self.port = port
        self.address = address
        self.state = InverterState()
        self.running = False
        self._server_socket: socket.socket | None = None
        self._lock = threading.Lock()

    def calculate_checksum(self, data: str) -> str:
        """Calculate the Solarmax protocol checksum."""
        checksum_value = sum(ord(c) for c in data)
        return format(checksum_value, "04X")

    def get_field_value(self, field: str) -> str:
        """Get the hex-encoded value for a field, with optional noise."""
        with self._lock:
            raw = getattr(self.state, field.lower(), 0)

        # Add small random noise for realism
        if self.state.add_noise and raw > 0 and field not in ("SYS", "SAL", "KT0", "KHR", "CAC"):
            noise = random.randint(-max(1, raw // 50), max(1, raw // 50))
            raw = max(0, raw + noise)

        if field == "SYS":
            # SYS uses special format: value,0
            return f"{raw:X},0"
        else:
            return format(raw, "X")

    def build_response(self, requested_fields: list[str]) -> str:
        """Build a response message for the requested fields."""
        # Response format: {ADR;FB;LEN|64:FIELD1=VAL1;FIELD2=VAL2|CHECKSUM}
        addr_hex = format(self.address, "02X")

        # Build field responses
        field_responses = []
        for f in requested_fields:
            val = self.get_field_value(f)
            field_responses.append(f"{f}={val}")

        fields_str = ";".join(field_responses)

        # Build response without length and checksum first
        # Format: {ADR;FB;LEN|64:FIELDS|CHECKSUM}
        response_body = f"FB;{addr_hex};!!|64:{fields_str}|$$$$"
        response = "{" + response_body + "}"

        # Calculate and insert length
        response = response.replace("!!", format(len(response), "02X"))

        # Calculate and insert checksum
        checksum_data = response[1:-5]  # Between { and |$$$$}
        response = response.replace("$$$$", self.calculate_checksum(checksum_data))

        return response

    def parse_request(self, data: str) -> list[str]:
        """Parse incoming request and extract requested field names."""
        try:
            # Format: {FB;ADR;LEN|64:FIELD1;FIELD2;...|CHECKSUM}
            # Extract fields between : and |
            parts = data.split(":")
            if len(parts) < 2:
                return []
            fields_part = parts[1].split("|")[0]
            fields = [f.strip() for f in fields_part.split(";") if f.strip()]
            return fields
        except (IndexError, ValueError) as e:
            _LOGGER.warning(f"Failed to parse request: {data!r} - {e}")
            return []

    def handle_client(self, client_socket: socket.socket, client_addr: tuple):
        """Handle a single client connection."""
        _LOGGER.info(f"Client connected: {client_addr[0]}:{client_addr[1]}")
        try:
            client_socket.settimeout(10.0)
            data = client_socket.recv(1024).decode("utf-8", errors="ignore")

            if data:
                _LOGGER.debug(f"Received: {data}")
                fields = self.parse_request(data)

                if fields:
                    response = self.build_response(fields)
                    _LOGGER.info(f"  Request:  {len(fields)} fields: {', '.join(fields)}")
                    _LOGGER.debug(f"  Response: {response}")
                    client_socket.send(response.encode("utf-8"))
                else:
                    _LOGGER.warning(f"  Could not parse request: {data!r}")
        except socket.timeout:
            _LOGGER.debug(f"Client {client_addr} timed out")
        except Exception as e:
            _LOGGER.error(f"Error handling client {client_addr}: {e}")
        finally:
            client_socket.close()

    def start(self):
        """Start the emulator server."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)

        try:
            self._server_socket.bind((self.host, self.port))
        except OSError as e:
            _LOGGER.error(f"Cannot bind to {self.host}:{self.port} - {e}")
            sys.exit(1)

        self._server_socket.listen(5)
        self.running = True

        _LOGGER.info("=" * 60)
        _LOGGER.info("  Solarmax Inverter Emulator")
        _LOGGER.info("=" * 60)
        _LOGGER.info(f"  Listening on {self.host}:{self.port}")
        _LOGGER.info(f"  Inverter address: {self.address}")
        _LOGGER.info(f"  Status: {self.state.sys} | Alarm: {self.state.sal}")
        _LOGGER.info(f"  AC Power (raw): {self.state.pac} -> {self.state.pac / 2}W")
        _LOGGER.info("=" * 60)
        _LOGGER.info("  Waiting for connections...")
        _LOGGER.info("")

        while self.running:
            try:
                client_socket, client_addr = self._server_socket.accept()
                thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, client_addr),
                    daemon=True,
                )
                thread.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self):
        """Stop the emulator server."""
        self.running = False
        if self._server_socket:
            self._server_socket.close()
        _LOGGER.info("Emulator stopped.")

    def update_state(self, **kwargs):
        """Thread-safe state update."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, value)


def interactive_loop(emulator: SolarmaxEmulator):
    """Run an interactive command loop for changing emulator state."""
    print("\nInteractive mode. Commands:")
    print("  set <field> <value>   - Set a field value (e.g., 'set pac 5000')")
    print("  scenario <name>       - Load a scenario (day/night/starting/alarm/...)")
    print("  status                - Show current state")
    print("  help                  - Show this help")
    print("  quit                  - Stop emulator")
    print("")

    while emulator.running:
        try:
            cmd = input("emulator> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue

        parts = cmd.split()
        command = parts[0].lower()

        if command == "quit" or command == "exit":
            break
        elif command == "help":
            print("Commands:")
            print("  set <field> <value>   - Set a field (pac, pdc, sys, sal, etc.)")
            print("  scenario <name>       - day, night, starting, alarm, multi_alarm, max_power, low_irradiation")
            print("  status                - Show current state")
            print("  quit                  - Stop emulator")
        elif command == "status":
            s = emulator.state
            print(f"\n  SYS (status):    {s.sys}")
            print(f"  SAL (alarm):     {s.sal}")
            print(f"  PAC (AC power):  {s.pac} raw -> {s.pac / 2}W")
            print(f"  PDC (DC power):  {s.pdc} raw -> {s.pdc / 2}W")
            print(f"  UL1 (voltage):   {s.ul1} raw -> {s.ul1 / 10}V")
            print(f"  TKK (temp):      {s.tkk}°C")
            print(f"  KDY (day):       {s.kdy} raw -> {s.kdy / 10} kWh")
            print(f"  KT0 (total):     {s.kt0} kWh")
            print(f"  Noise: {'on' if s.add_noise else 'off'}")
            print("")
        elif command == "set" and len(parts) >= 3:
            field_name = parts[1].lower()
            try:
                value = int(parts[2])
                if hasattr(emulator.state, field_name):
                    emulator.update_state(**{field_name: value})
                    print(f"  {field_name} = {value}")
                else:
                    print(f"  Unknown field: {field_name}")
            except ValueError:
                if parts[2].lower() in ("true", "false"):
                    emulator.update_state(**{field_name: parts[2].lower() == "true"})
                    print(f"  {field_name} = {parts[2].lower() == 'true'}")
                else:
                    print(f"  Invalid value: {parts[2]}")
        elif command == "scenario" and len(parts) >= 2:
            scenario_name = parts[1].lower()
            try:
                new_state = get_scenario_state(scenario_name)
                with emulator._lock:
                    emulator.state = new_state
                print(f"  Loaded scenario: {scenario_name}")
            except Exception as e:
                print(f"  Error loading scenario: {e}")
        elif command == "noise":
            emulator.state.add_noise = not emulator.state.add_noise
            print(f"  Noise: {'on' if emulator.state.add_noise else 'off'}")
        else:
            print(f"  Unknown command: {cmd}")

    emulator.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Solarmax Inverter Emulator for testing the HA integration"
    )
    parser.add_argument(
        "--port", type=int, default=12345, help="TCP port to listen on (default: 12345)"
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--address", type=int, default=1, help="Inverter address 1-249 (default: 1)"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="day",
        choices=["day", "night", "starting", "alarm", "multi_alarm", "max_power", "low_irradiation", "custom"],
        help="Simulation scenario (default: day)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    emulator = SolarmaxEmulator(host=args.host, port=args.port, address=args.address)
    emulator.state = get_scenario_state(args.scenario)

    # Start server in a thread
    server_thread = threading.Thread(target=emulator.start, daemon=True)
    server_thread.start()

    # Small delay to let server start
    time.sleep(0.3)

    if args.scenario == "custom":
        interactive_loop(emulator)
    else:
        print(f"\nScenario '{args.scenario}' active. Press Ctrl+C to stop.\n")
        try:
            while emulator.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        emulator.stop()


if __name__ == "__main__":
    main()
