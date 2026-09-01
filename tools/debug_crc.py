#!/usr/bin/env python3
"""Debug script to test the fixed multi-frame handling against a real inverter."""

import importlib.util
import os
import socket
import sys

# Add the project root to path so we can import the API
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

spec = importlib.util.spec_from_file_location(
    "protocol",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "custom_components",
        "solarmax",
        "protocol.py",
    ),
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

HOST = "10.0.5.15"
PORT = 12345
ADDRESS = 1

request = mod.build_request(ADDRESS, list(mod.FIELD_MAP_INVERTER))
print(f"Request: {request[:50]!r}...")


def main() -> None:
    """Connect to the real inverter and exercise the full parse pipeline."""
    print(f"Testing full get_data() against real inverter at {HOST}...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect((HOST, PORT))

    sock.send(request.encode("utf-8"))

    # Read all data
    response = ""
    while True:
        try:
            sock.settimeout(1.0)
            buf = sock.recv(4096)
            if len(buf) > 0:
                chunk = buf.decode("utf-8", errors="ignore")
                response += chunk
                sock.settimeout(0.5)
            else:
                break
        except TimeoutError:
            if response:
                break
    sock.close()

    print(f"Response: {len(response)} bytes")

    # Test frame splitting
    frames = mod.split_frames(response)
    print(f"Frames found: {len(frames)}")
    for i, f in enumerate(frames):
        valid = mod.verify_frame_checksum(f)
        print(
            f"  Frame {i + 1}: {len(f)} bytes, CRC valid: {valid}, ends with: {repr(f[-1])}"
        )

    # Test full parsing
    try:
        data = mod.parse_response(response)
        print(f"\nSuccess! Parsed {len(data)} fields:")
        for key, val in sorted(data.items()):
            print(f"  {key:6s} = {val['value']} (raw: 0x{val['raw_value']:X})")
    except Exception as e:
        print(f"\nFailed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
