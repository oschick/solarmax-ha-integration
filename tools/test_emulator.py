#!/usr/bin/env python3
"""Quick test to verify the inverter emulator works correctly."""

import socket
import sys
import threading
import time

sys.path.insert(0, ".")
from tools.inverter_emulator import SolarmaxEmulator, get_scenario_state


def calculate_checksum(data: str) -> str:
    return format(sum(ord(c) for c in data), "04X")


def build_request(fields_str: str) -> str:
    """Build a request like the real SolarmaxAPI does."""
    req = "{FB;01;!!|64:" + fields_str + "|$$$$}"
    req = req.replace("!!", format(len(req), "02X"))
    req = req.replace("$$$$", calculate_checksum(req[1:-5]))
    return req


def test_emulator():
    """Test the emulator with a raw socket client."""
    # Start emulator
    emu = SolarmaxEmulator(port=12347)
    emu.state = get_scenario_state("day")
    t = threading.Thread(target=emu.start, daemon=True)
    t.start()
    time.sleep(0.5)

    try:
        # Build request
        fields = "PAC;PDC;SYS;SAL;UL1;KDY;TKK"
        req = build_request(fields)
        print(f"Request:  {req}")

        # Send request via TCP
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("127.0.0.1", 12347))
        sock.send(req.encode())
        resp = sock.recv(1024).decode()
        sock.close()
        print(f"Response: {resp}")

        # Parse response like the API does
        data_split = resp.split(":")[1].split("|")[0].split(";")
        print(f"\nParsed {len(data_split)} fields:")
        for item in data_split:
            if "=" not in item:
                continue
            field, val = item.split("=", 1)
            if field == "SYS":
                value = int(val.split(",")[0], 16)
            else:
                value = int(val, 16)
            print(f"  {field} = {value} (hex: {val})")

        # Verify key fields
        assert len(data_split) == 7, f"Expected 7 fields, got {len(data_split)}"

        # Test scenario switching
        print("\n--- Testing 'night' scenario ---")
        emu.state = get_scenario_state("night")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("127.0.0.1", 12347))
        sock.send(build_request("PAC;SYS").encode())
        resp = sock.recv(1024).decode()
        sock.close()
        print(f"Response: {resp}")

        data_split = resp.split(":")[1].split("|")[0].split(";")
        for item in data_split:
            if "=" not in item:
                continue
            field, val = item.split("=", 1)
            if field == "SYS":
                value = int(val.split(",")[0], 16)
                assert value == 20000, f"Expected SYS=20000, got {value}"
                print(f"  SYS = {value} (no communication) ✓")
            elif field == "PAC":
                value = int(val, 16)
                assert value == 0, f"Expected PAC=0, got {value}"
                print(f"  PAC = {value} (no power) ✓")

        print("\n✓ All emulator tests PASSED")

    finally:
        emu.stop()


if __name__ == "__main__":
    test_emulator()
