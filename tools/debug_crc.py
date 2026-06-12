#!/usr/bin/env python3
"""Debug script to test the fixed multi-frame handling against a real inverter."""

import os
import sys

# Add the project root to path so we can import the API
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "solarmax_api",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "custom_components",
        "solarmax",
        "solarmax_api.py",
    ),
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SolarmaxAPI = mod.SolarmaxAPI

api = SolarmaxAPI(host="10.0.5.15", port=12345, address=1, timeout=5)

print("Testing full get_data() against real inverter at 10.0.5.15...")

# First, let's manually test the recv and frame splitting
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
sock.connect(("10.0.5.15", 12345))

request = api.build_request(mod.FIELD_MAP_INVERTER)
print(f"Request: {repr(request[:50])}...")
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
frames = api._split_response_frames(response)
print(f"Frames found: {len(frames)}")
for i, f in enumerate(frames):
    valid = api._verify_response_checksum(f)
    print(
        f"  Frame {i + 1}: {len(f)} bytes, CRC valid: {valid}, ends with: {repr(f[-1])}"
    )

# Test full parsing
try:
    data = api.convert_to_json(response)
    print(f"\nSuccess! Parsed {len(data)} fields:")
    for key, val in sorted(data.items()):
        print(f"  {key:6s} = {val['value']} (raw: 0x{val['raw_value']:X})")
except Exception as e:
    print(f"\nFailed: {type(e).__name__}: {e}")
