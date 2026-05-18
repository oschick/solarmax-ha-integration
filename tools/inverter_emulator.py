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

    # Device identification (per MaxComm protocol Section 2.3/2.4)
    typ: int = 20650  # Device Type: SolarMax 7TP2
    swv: int = 40  # Software Version: 40 (0x28)
    din: int = 118767  # Serial Number (DIN)
    bdn: int = 1851  # Build/Release Number (BDN)

    # Power values (raw values before division)
    pac: int = 3000  # AC Power: 3000/2 = 1500W
    pdc: int = 3200  # DC Power: 3200/2 = 1600W
    pd01: int = 1600  # DC Power String 1: 1600/2 = 800W
    pd02: int = 1600  # DC Power String 2: 1600/2 = 800W

    # Voltage values (raw values before /10)
    ul1: int = 2300  # AC Voltage Phase 1: 2300/10 = 230.0V
    ul2: int = 2310  # AC Voltage Phase 2: 2310/10 = 231.0V
    ul3: int = 2295  # AC Voltage Phase 3: 2295/10 = 229.5V
    udc: int = 3490  # DC Voltage: 3490/10 = 349.0V
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

    # String 3 (for 3-string inverters)
    pd03: int = 0  # DC Power String 3: 0W (not all models have string 3)
    ud03: int = 0  # DC Voltage String 3: 0V
    id03: int = 0  # DC Current String 3: 0A

    # Energy history
    kdl: int = 72  # Energy Yesterday: 72/10 = 7.2 kWh
    klm: int = 320  # Energy Last Month: 320 kWh
    kly: int = 3800  # Energy Last Year: 3800 kWh

    # Other
    tkk: int = 42  # Temperature: 42°C
    tk2: int = 38  # Temperature 2: 38°C
    tk3: int = 35  # Temperature 3: 35°C
    khr: int = 15230  # Power On Hours
    cac: int = 1847  # Startups
    prl: int = 45  # Relative Power: 45%
    pin: int = 14000  # Installed Power: 14000/2 = 7000W
    tnf: int = 500  # Grid Frequency: 500/10 = 50.0 Hz

    # Grid monitoring configuration (raw values)
    ulh: int = 2640  # Grid Voltage Upper Limit: 2640/10 = 264.0V
    ull: int = 1960  # Grid Voltage Lower Limit: 1960/10 = 196.0V
    tnh: int = 5050  # Grid Frequency Upper Limit: 5050/100 = 50.50Hz
    tnl: int = 4950  # Grid Frequency Lower Limit: 4950/100 = 49.50Hz

    # Simulation settings
    add_noise: bool = True  # Add small random variations


def get_scenario_state(scenario: str) -> InverterState:
    """Get inverter state for a predefined scenario."""
    if scenario == "night":
        return InverterState(
            sys=20000,  # No communication
            sal=0,
            pac=0,
            pdc=0,
            pd01=0,
            pd02=0,
            pd03=0,
            ul1=0,
            ul2=0,
            ul3=0,
            ud01=0,
            ud02=0,
            ud03=0,
            idc=0,
            id01=0,
            id02=0,
            id03=0,
            il1=0,
            il2=0,
            il3=0,
            kdy=85,
            kmt=350,
            kyr=4200,
            kt0=28500,
            kdl=72,
            klm=320,
            kly=3800,
            tkk=18,
            tk2=16,
            tk3=15,
            khr=15230,
            cac=1847,
            prl=0,
            pin=14000,
            tnf=0,
            add_noise=False,
        )
    elif scenario == "starting":
        return InverterState(
            sys=20003,  # Starting up
            sal=0,
            pac=0,
            pdc=100,
            pd01=50,
            pd02=50,
            pd03=0,
            ul1=2300,
            ul2=2310,
            ul3=2295,
            ud01=2800,
            ud02=2750,
            ud03=0,
            idc=10,
            id01=5,
            id02=5,
            id03=0,
            il1=0,
            il2=0,
            il3=0,
            kdy=0,
            kmt=350,
            kyr=4200,
            kt0=28500,
            kdl=72,
            klm=320,
            kly=3800,
            tkk=22,
            tk2=20,
            tk3=19,
            khr=15230,
            cac=1848,
            prl=0,
            pin=14000,
            tnf=500,
            add_noise=False,
        )
    elif scenario == "alarm":
        return InverterState(
            sys=20001,  # In operation
            sal=2,  # Insulation fault DC side
            pac=500,
            pdc=600,
            pd01=300,
            pd02=300,
            pd03=0,
            ul1=2300,
            ul2=2310,
            ul3=2295,
            ud01=3200,
            ud02=3180,
            ud03=0,
            idc=200,
            id01=100,
            id02=100,
            id03=0,
            il1=75,
            il2=72,
            il3=73,
            kdy=30,
            kmt=350,
            kyr=4200,
            kt0=28500,
            kdl=72,
            klm=320,
            kly=3800,
            tkk=38,
            tk2=35,
            tk3=33,
            khr=15230,
            cac=1847,
            prl=7,
            pin=14000,
            tnf=500,
        )
    elif scenario == "multi_alarm":
        return InverterState(
            sys=20001,  # In operation
            sal=5,  # External fault 1 (1) + Earth fault current (4) = 5
            pac=200,
            pdc=250,
            pd01=125,
            pd02=125,
            pd03=0,
            ul1=2280,
            ul2=2290,
            ul3=2275,
            ud01=3000,
            ud02=2980,
            ud03=0,
            idc=80,
            id01=40,
            id02=40,
            id03=0,
            il1=30,
            il2=28,
            il3=29,
            kdy=15,
            kmt=350,
            kyr=4200,
            kt0=28500,
            kdl=72,
            klm=320,
            kly=3800,
            tkk=45,
            tk2=42,
            tk3=40,
            khr=15230,
            cac=1847,
            prl=3,
            pin=14000,
            tnf=500,
        )
    elif scenario == "max_power":
        return InverterState(
            sys=20006,  # Max power operation
            sal=0,
            pac=10000,
            pdc=10500,
            pd01=5250,
            pd02=5250,
            pd03=0,
            ul1=2350,
            ul2=2360,
            ul3=2345,
            ud01=5800,
            ud02=5750,
            ud03=0,
            idc=1800,
            id01=900,
            id02=900,
            id03=0,
            il1=1450,
            il2=1440,
            il3=1445,
            kdy=250,
            kmt=1200,
            kyr=4800,
            kt0=29000,
            kdl=240,
            klm=1100,
            kly=4500,
            tkk=58,
            tk2=55,
            tk3=52,
            khr=15230,
            cac=1847,
            prl=100,
            pin=10000,
            tnf=500,
        )
    elif scenario == "low_irradiation":
        return InverterState(
            sys=20002,  # Low irradiation
            sal=0,
            pac=100,
            pdc=150,
            pd01=75,
            pd02=75,
            pd03=0,
            ul1=2300,
            ul2=2310,
            ul3=2295,
            ud01=2200,
            ud02=2150,
            ud03=0,
            idc=30,
            id01=15,
            id02=15,
            id03=0,
            il1=15,
            il2=14,
            il3=14,
            kdy=5,
            kmt=350,
            kyr=4200,
            kt0=28500,
            kdl=72,
            klm=320,
            kly=3800,
            tkk=25,
            tk2=23,
            tk3=22,
            khr=15230,
            cac=1847,
            prl=1,
            pin=14000,
            tnf=500,
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
        if (
            self.state.add_noise
            and raw > 0
            and field
            not in (
                "SYS",
                "SAL",
                "KT0",
                "KHR",
                "CAC",
                "TYP",
                "SWV",
                "DIN",
                "BDN",
                "PIN",
                "TNF",
                "ULH",
                "ULL",
                "TNH",
                "TNL",
            )
        ):
            noise = random.randint(-max(1, raw // 50), max(1, raw // 50))
            raw = max(0, raw + noise)

        if field == "SYS":
            # SYS uses special format: value,0
            return f"{raw:X},0"
        else:
            return format(raw, "X")

    def build_response(self, requested_fields: list[str]) -> str:
        """Build a response message for the requested fields.

        Mimics real inverter behavior: if the response exceeds 255 bytes,
        it is split into multiple frames. Non-final frames use ')' as ETX,
        the final frame uses '}'. Field names may be split at frame boundaries.
        """
        MAX_FRAME = 255
        addr_hex = format(self.address, "02X")

        # Build field responses
        field_responses = []
        for f in requested_fields:
            val = self.get_field_value(f)
            field_responses.append(f"{f}={val}")

        fields_str = ";".join(field_responses)

        # Check if single frame suffices
        # Template: {ADR;FB;LEN|64:FIELDS|CHECKSUM}
        # With placeholders: 1({) + header + fields + 1(|) + 4(CRC) + 1(}) = total
        header = f"{addr_hex};FB;!!|64:"
        single_frame_len = 1 + len(header) + len(fields_str) + 1 + 4 + 1

        if single_frame_len <= MAX_FRAME:
            # Single frame — current behavior
            response = "{" + header + fields_str + "|$$$$}"
            response = response.replace("!!", format(len(response), "02X"))
            checksum_data = response[1:-5]
            response = response.replace("$$$$", self.calculate_checksum(checksum_data))
            return response

        # Multi-frame response: split data across frames
        frames = []
        remaining = fields_str

        # First frame includes port prefix "64:"
        first_header = f"{addr_hex};FB;FF|64:"
        # Available space for data: MAX_FRAME - { - header - | - CRC(4) - )
        max_data_first = MAX_FRAME - 1 - len(first_header) - 1 - 4 - 1
        first_data = remaining[:max_data_first]
        remaining = remaining[max_data_first:]

        # Build first frame (continuation: ends with ')')
        crc_content = first_header + first_data + "|"
        crc = self.calculate_checksum(crc_content)
        frames.append("{" + crc_content + crc + ")")

        # Continuation frames (no port prefix, just data)
        while remaining:
            # Header placeholder for length calculation
            cont_header = f"{addr_hex};FB;!!|"
            # Available data space
            max_data_cont = MAX_FRAME - 1 - len(cont_header) - 1 - 4 - 1
            cont_data = remaining[:max_data_cont]
            remaining = remaining[max_data_cont:]

            etx = ")" if remaining else "}"
            frame = "{" + cont_header + cont_data + "|$$$$" + etx
            frame = frame.replace("!!", format(len(frame), "02X"))
            checksum_data = frame[1:-5]
            frame = frame.replace("$$$$", self.calculate_checksum(checksum_data))
            frames.append(frame)

        return "".join(frames)

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
                    _LOGGER.info(
                        f"  Request:  {len(fields)} fields: {', '.join(fields)}"
                    )
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
            print(
                "  scenario <name>       - day, night, starting, alarm, multi_alarm, max_power, low_irradiation"
            )
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
            print(f"  TK2 (temp 2):    {s.tk2}°C")
            print(f"  TK3 (temp 3):    {s.tk3}°C")
            print(f"  TNF (freq):      {s.tnf} raw -> {s.tnf / 10} Hz")
            print(f"  PRL (rel power): {s.prl}%")
            print(f"  PIN (installed): {s.pin} raw -> {s.pin / 2}W")
            print(f"  KDY (day):       {s.kdy} raw -> {s.kdy / 10} kWh")
            print(f"  KDL (yesterday): {s.kdl} raw -> {s.kdl / 10} kWh")
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
        choices=[
            "day",
            "night",
            "starting",
            "alarm",
            "multi_alarm",
            "max_power",
            "low_irradiation",
            "custom",
        ],
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
