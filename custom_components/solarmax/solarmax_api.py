"""Solarmax Inverter API."""

from __future__ import annotations

import logging
import socket
from datetime import datetime
from typing import Any, Dict, Union

_LOGGER = logging.getLogger(__name__)

# Field mapping for inverter parameters
FIELD_MAP_INVERTER = {
    "KDY": "Energy_Day (Wh)",
    "KMT": "Energy_Month (kWh)",
    "KYR": "Energy_Year (kWh)",
    "KT0": "Energy_Total (kWh)",
    "PDC": "DC_Power (W)",
    "PD01": "DC_Power_String_1 (W)",
    "PD02": "DC_Power_String_2 (W)",
    "UD01": "DC_Voltage_String_1 (V)",
    "UD02": "DC_Voltage_String_2 (V)",
    "IDC": "DC_Current (A)",
    "ID01": "DC_Current_String_1 (A)",
    "ID02": "DC_Current_String_2 (A)",
    "PAC": "AC_Power (W)",
    "UL1": "AC_Voltage_Phase_1 (V)",
    "UL2": "AC_Voltage_Phase_2 (V)",
    "UL3": "AC_Voltage_Phase_3 (V)",
    "IL1": "AC_Current_Phase_1 (A)",
    "IL2": "AC_Current_Phase_2 (A)",
    "IL3": "AC_Current_Phase_3 (A)",
    "CAC": "Startups",
    "KHR": "poweronhours",
    "TKK": "inverter_operating_temp (C)",
    "SAL": "Alarm_Codes",
    "SYS": "status_Code",
}

# Base request template
REQUEST_TEMPLATE = "{FB;01;!!|64:&&|$$$$}"


class SolarmaxAPI:
    """API for communicating with Solarmax inverters."""

    def __init__(self, host: str, port: int = 12345, timeout: int = 10):
        """Initialize the API."""
        self.host = host
        self.port = port
        self.timeout = timeout

    def build_request(self, field_map: Dict[str, str]) -> str:
        """Build the request message for the inverter."""
        fields = ";".join(field_map.keys())
        req = REQUEST_TEMPLATE.replace("&&", fields)
        # Replace !! with length of string in 2-digit hex
        req = req.replace("!!", format(len(req), "02X"))
        # Replace $$$$ with checksum
        req = req.replace("$$$$", self.calculate_checksum((req[1:])[:-5]))
        return req

    def calculate_checksum(self, data: str) -> str:
        """Calculate the checksum for the message."""
        checksum_value = sum(ord(c) for c in data)
        _LOGGER.debug(f"Checksum calculation for '{data}': {checksum_value}")
        return format(checksum_value, "04X")

    def map_data_value(self, field: str, value: int) -> Union[str, float, int]:
        """Convert raw inverter values to useful units."""
        if field == "SYS":
            # Return raw value - translation will be handled at sensor level
            return value
        elif field == "SAL":
            # Return raw value - translation will be handled at sensor level
            return value
        elif field in ["PAC", "PD01", "PD02", "PDC"]:
            return value / 2
        elif field in ["UL1", "UL2", "UL3", "UDC", "UD01", "UD02"]:
            return value / 10.0
        elif field in ["IDC", "ID01", "ID02", "IL1", "IL2", "IL3"]:
            return value / 100.0
        else:
            return value

    def test_connection(self) -> bool:
        """Test if we can connect to the inverter."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))

            # Try to send a minimal request
            request = self.build_request({"PAC": "AC_Power (W)"})
            sock.send(bytes(request, "utf-8"))

            # Try to receive response
            response = ""
            start_time = datetime.now()
            while (datetime.now() - start_time).total_seconds() < 2:
                buf = sock.recv(1024)
                if len(buf) > 0:
                    response += buf.decode("utf-8", errors="ignore")
                    break

            sock.close()
            return len(response) > 0

        except Exception as e:
            _LOGGER.debug(f"Connection test failed: {e}")
            return False

    def get_data(self) -> Dict[str, Any]:
        """Get data from the inverter."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))

            # Build and send request
            request = self.build_request(FIELD_MAP_INVERTER)
            _LOGGER.debug(f"Sending request: {request}")
            sock.send(bytes(request, "utf-8"))

            # Receive response
            response = ""
            start_time = datetime.now()
            data_received = False

            while (
                not data_received and (datetime.now() - start_time).total_seconds() < 2
            ):
                buf = sock.recv(1024)
                if len(buf) > 0:
                    response += buf.decode("utf-8", errors="ignore")
                    data_received = True

            sock.close()
            _LOGGER.debug(f"Received response: {response}")

            if response:
                return self.convert_to_json(FIELD_MAP_INVERTER, response)
            else:
                _LOGGER.warning("No response received from inverter")
                return {}

        except Exception as e:
            _LOGGER.error(f"Error getting data from inverter: {e}")
            # Re-raise the exception instead of returning mock data
            raise

    def convert_to_json(self, field_map: Dict[str, str], data: str) -> Dict[str, Any]:
        """Convert inverter response to JSON format."""
        try:
            data_split = data.split(":")[1].split("|")[0].split(";")
            result_dict = {}

            for item in data_split:
                if "=" not in item:
                    continue

                field, value_str = item.split("=", 1)

                if field == "SYS":
                    # Cut off the ",0" in SYS status
                    value = int(value_str.split(",")[0], 16)
                else:
                    value = int(value_str, 16)

                result_dict[field] = {
                    "value": self.map_data_value(field, value),
                    "raw_value": value,
                }

            _LOGGER.debug(f"Converted data: {result_dict}")
            return result_dict

        except Exception as e:
            _LOGGER.error(f"Error converting data to JSON: {e}")
            return {}
