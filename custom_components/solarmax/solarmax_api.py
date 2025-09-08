"""Solarmax Inverter API."""

from __future__ import annotations

import logging
import socket
import time
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


class SolarmaxConnectionError(Exception):
    """Exception raised when connection to inverter fails."""
    pass


class SolarmaxTimeoutError(SolarmaxConnectionError):
    """Exception raised when connection times out."""
    pass


class SolarmaxAPI:
    """API for communicating with Solarmax inverters."""

    def __init__(self, host: str, port: int = 12345, timeout: int = 10):
        """Initialize the API."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self._last_successful_connection = None

    def _create_socket_connection(self, retries: int = 3) -> socket.socket:
        """Create a socket connection with retry logic."""
        last_exception = None
        
        for attempt in range(retries):
            sock = None
            try:
                _LOGGER.debug(f"Attempting connection to {self.host}:{self.port} (attempt {attempt + 1}/{retries})")
                
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                
                # Set socket options to help with connection reuse
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                
                # Connect with timeout
                sock.connect((self.host, self.port))
                
                _LOGGER.debug(f"Successfully connected to {self.host}:{self.port}")
                return sock
                
            except socket.timeout as e:
                last_exception = SolarmaxTimeoutError(f"Connection timeout to {self.host}:{self.port}")
                _LOGGER.debug(f"Connection attempt {attempt + 1} timed out: {e}")
            except ConnectionRefusedError as e:
                last_exception = SolarmaxConnectionError(f"Connection refused by {self.host}:{self.port}")
                _LOGGER.debug(f"Connection attempt {attempt + 1} refused: {e}")
            except socket.error as e:
                last_exception = SolarmaxConnectionError(f"Socket error: {e}")
                _LOGGER.debug(f"Connection attempt {attempt + 1} failed with socket error: {e}")
            except Exception as e:
                last_exception = SolarmaxConnectionError(f"Unexpected error: {e}")
                _LOGGER.debug(f"Connection attempt {attempt + 1} failed with unexpected error: {e}")
            
            # Clean up failed socket
            if sock:
                try:
                    sock.close()
                except:
                    pass
            
            # Wait before retry (except on last attempt)
            if attempt < retries - 1:
                wait_time = 1 + attempt  # Exponential backoff: 1s, 2s, 3s
                _LOGGER.debug(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
        
        # All attempts failed
        _LOGGER.error(f"Failed to connect to {self.host}:{self.port} after {retries} attempts")
        if last_exception:
            raise last_exception
        else:
            raise SolarmaxConnectionError(f"Failed to connect to {self.host}:{self.port}")

    def _send_request_and_receive_response(self, sock: socket.socket, request: str) -> str:
        """Send request and receive response with proper timeout handling."""
        try:
            # Send request
            _LOGGER.debug(f"Sending request: {request}")
            sock.send(bytes(request, "utf-8"))

            # Receive response with consistent timeout
            response = ""
            start_time = time.time()
            
            # Use the same timeout as socket connection for consistency
            while (time.time() - start_time) < self.timeout:
                try:
                    sock.settimeout(1.0)  # Short timeout for recv to allow checking overall timeout
                    buf = sock.recv(1024)
                    if len(buf) > 0:
                        response += buf.decode("utf-8", errors="ignore")
                        break
                except socket.timeout:
                    # Continue loop to check overall timeout
                    continue
                except socket.error as e:
                    raise SolarmaxConnectionError(f"Error receiving data: {e}")

            if not response:
                raise SolarmaxTimeoutError("No response received within timeout period")
                
            _LOGGER.debug(f"Received response: {response}")
            return response
            
        except socket.timeout:
            raise SolarmaxTimeoutError("Request/response timeout")
        except socket.error as e:
            raise SolarmaxConnectionError(f"Socket error during communication: {e}")

    @property
    def last_successful_connection(self) -> datetime | None:
        """Return the timestamp of the last successful connection."""
        return self._last_successful_connection

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
            sock = self._create_socket_connection(retries=1)
            try:
                # Try to send a minimal request
                request = self.build_request({"PAC": "AC_Power (W)"})
                response = self._send_request_and_receive_response(sock, request)
                return len(response) > 0
            finally:
                sock.close()
                
        except Exception as e:
            _LOGGER.debug(f"Connection test failed: {e}")
            return False

    def get_data(self) -> Dict[str, Any]:
        """Get data from the inverter with retry logic."""
        retries = 3
        last_exception = None
        
        for attempt in range(retries):
            sock = None
            try:
                _LOGGER.debug(f"Getting data from inverter (attempt {attempt + 1}/{retries})")
                
                # Create connection with retry logic
                sock = self._create_socket_connection(retries=2)  # 2 retries per attempt
                
                # Build and send request, receive response
                request = self.build_request(FIELD_MAP_INVERTER)
                response = self._send_request_and_receive_response(sock, request)
                
                if response:
                    # Mark successful connection
                    self._last_successful_connection = datetime.now()
                    data = self.convert_to_json(FIELD_MAP_INVERTER, response)
                    _LOGGER.debug(f"Successfully retrieved data from inverter")
                    return data
                else:
                    raise SolarmaxTimeoutError("Empty response received")
                    
            except (SolarmaxConnectionError, SolarmaxTimeoutError) as e:
                last_exception = e
                _LOGGER.debug(f"Data retrieval attempt {attempt + 1} failed: {e}")
            except Exception as e:
                last_exception = SolarmaxConnectionError(f"Unexpected error: {e}")
                _LOGGER.debug(f"Data retrieval attempt {attempt + 1} failed with unexpected error: {e}")
            finally:
                # Always clean up socket
                if sock:
                    try:
                        sock.close()
                    except:
                        pass
            
            # Wait before retry (except on last attempt)
            if attempt < retries - 1:
                wait_time = 2 + attempt  # 2s, 3s wait between attempts
                _LOGGER.debug(f"Waiting {wait_time}s before retrying data retrieval...")
                time.sleep(wait_time)
        
        # All attempts failed
        _LOGGER.error(f"Failed to get data from inverter after {retries} attempts")
        if last_exception:
            raise last_exception
        else:
            raise SolarmaxConnectionError("Failed to get data from inverter")

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
