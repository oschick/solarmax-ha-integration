#!/usr/bin/env python3
"""Quick test to verify the MaxComm protocol implementation."""

import importlib.util

# Load solarmax_api directly to avoid importing homeassistant
spec = importlib.util.spec_from_file_location(
    "solarmax_api",
    "custom_components/solarmax/solarmax_api.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SolarmaxAPI = mod.SolarmaxAPI
FIELD_MAP_INVERTER = mod.FIELD_MAP_INVERTER
PROTO_STX = mod.PROTO_STX
PROTO_ETX = mod.PROTO_ETX
PROTO_PORT_DATA = mod.PROTO_PORT_DATA

api = SolarmaxAPI("192.168.1.1", 12345, address=1)

# Test checksum calculation
cs = api.calculate_checksum("FB;01;17|64:PAC|")
print(f"Checksum test: {cs}")

# Test build_request
req = api.build_request({"PAC": "AC_Power", "UDC": "DC_Voltage"})
print(f"Built request: {req}")
assert req[0] == "{" and req[-1] == "}"
print("Request structure OK")

# Test response parsing with valid checksum
resp_data = "01;FB;1A|64:PAC=1F4;UDC=BB8|"
crc = api.calculate_checksum(resp_data)
mock_resp = "{" + resp_data + crc + "}"
print(f"Mock response: {mock_resp}")

result = api.convert_to_json(FIELD_MAP_INVERTER, mock_resp)
print(f"Parsed PAC: {result['PAC']['value']}W (raw: 0x{result['PAC']['raw_value']:X})")
print(f"Parsed UDC: {result['UDC']['value']}V (raw: 0x{result['UDC']['raw_value']:X})")

# Verify scaling per MaxComm network variables
assert result["PAC"]["value"] == 500 / 2  # Leistung: 0.5 W/digit
assert result["UDC"]["value"] == 3000 / 10  # Spannung_2: 0.1 V/digit
print("Scaling verification: PASS")

# Test checksum verification
assert api._verify_response_checksum(mock_resp) is True
print("Checksum verification: PASS")

# Test bad checksum detection
bad_resp = "{01;FB;1A|64:PAC=1F4;UDC=BB8|0000}"
assert api._verify_response_checksum(bad_resp) is False
print("Bad checksum detection: PASS")

# Test SYS value parsing (STATUS,0 format)
sys_resp_data = "01;FB;15|64:SYS=4E24,0|"
sys_crc = api.calculate_checksum(sys_resp_data)
sys_mock = "{" + sys_resp_data + sys_crc + "}"
sys_result = api.convert_to_json(FIELD_MAP_INVERTER, sys_mock)
assert sys_result["SYS"]["value"] == 0x4E24  # 20004 decimal = mpp_operation
print(f"SYS parsing: {sys_result['SYS']['value']} (0x4E24 = 20004 = mpp_operation)")

# Test TYP and SWV parsing (device identification)
typ_resp_data = "01;FB;17|64:TYP=50AA;SWV=28|"
typ_crc = api.calculate_checksum(typ_resp_data)
typ_mock = "{" + typ_resp_data + typ_crc + "}"
typ_result = api.convert_to_json(FIELD_MAP_INVERTER, typ_mock)
assert typ_result["TYP"]["raw_value"] == 20650  # SolarMax 7TP2
assert typ_result["SWV"]["raw_value"] == 40  # Firmware v40
print(f"TYP/SWV parsing: TYP={typ_result['TYP']['raw_value']} SWV={typ_result['SWV']['raw_value']} PASS")

# Test "not applicable" key handling (key returned without value)
na_resp_data = "01;FB;12|64:PAC=1F4;FRT|"
na_crc = api.calculate_checksum(na_resp_data)
na_mock = "{" + na_resp_data + na_crc + "}"
na_result = api.convert_to_json(FIELD_MAP_INVERTER, na_mock)
assert "FRT" not in na_result  # Not applicable keys are skipped
assert "PAC" in na_result
print("Not-applicable key handling: PASS")

# Test full field map request
full_req = api.build_request(FIELD_MAP_INVERTER)
print(f"\nFull request ({len(FIELD_MAP_INVERTER)} keys):")
print(f"  {full_req}")
print(f"  Length: {len(full_req)} bytes")

print(f"\nFIELD_MAP_INVERTER: {len(FIELD_MAP_INVERTER)} keys")
print(f"Protocol constants: STX={PROTO_STX!r} ETX={PROTO_ETX!r} PORT_DATA=0x{PROTO_PORT_DATA:X}")
print("\nAll MaxComm protocol tests PASSED!")
