"""Solarmax Inverter API.

Implements the MaxComm data protocol for communication with SolarMax products.
Protocol reference: "Beschreibung des MaxComm Datenprotokolls" (August 2022)

Protocol structure:
    {<Src-Adr>;<Dest-Adr>;<Length>|<Port>:<Data>|<CRC>}

    STX  = '{'   Start of Text (ASCII 123)
    ETX  = '}'   End of Text (ASCII 125)
    FRS  = '|'   Frame Separator (ASCII 124)
    US   = ':'   Union Separator (ASCII 58)
    FS   = ';'   Field Separator (ASCII 59)

All numeric values are transmitted as ASCII hex characters.
Communication is Master-Slave: devices only respond to requests.
Typical response time: 300ms, maximum timeout: 3000ms.
"""

from __future__ import annotations

import logging
import socket
import time
from datetime import datetime
from typing import Any

_LOGGER = logging.getLogger(__name__)

# =============================================================================
# MaxComm Protocol Constants
# =============================================================================

# Protocol framing characters
PROTO_STX = "{"  # Start of Text (ASCII 123)
PROTO_ETX = "}"  # End of Text (ASCII 125)
PROTO_FRS = "|"  # Frame Separator (ASCII 124)
PROTO_US = ":"  # Union Separator (ASCII 58)
PROTO_FS = ";"  # Field Separator (ASCII 59)

# Retry/timeout tuning
DATA_RETRIES = 3  # attempts per get_data() call
CONNECT_RETRIES = 2  # connection attempts within each data attempt
RECV_INITIAL_TIMEOUT = 1.0  # seconds to wait per recv for the first frame
RECV_CONTINUATION_TIMEOUT = 0.5  # seconds to wait per recv for further frames

# Protocol addressing
PROTO_ADDR_HOST = 0xFB  # 251 - Host address (alternative network master)
PROTO_ADDR_BROADCAST = 0x00  # Broadcast (point-to-point only)
PROTO_ADDR_MASTER = 0xFA  # 250 - Network Master

# Protocol port numbers
PROTO_PORT_DATA = 0x64  # 100 - Data query/response
PROTO_PORT_COMMAND = 0xC8  # 200 - Settings/commands
PROTO_PORT_MESSAGE = 0x3E8  # 1000 - Interface messages (IPR, IPN)

# Protocol timing (milliseconds)
PROTO_TYPICAL_RESPONSE_MS = 300
PROTO_MAX_TIMEOUT_MS = 3000

# Protocol error indicators in responses
PROTO_ERROR_INVALID_PROTOCOL = "IPR"  # Checksum/length error
PROTO_ERROR_INVALID_PORT = "IPN"  # Invalid port number

# =============================================================================
# Network Variable Types (per MaxComm protocol spec)
# Defines the resolution/scaling for each data type.
# =============================================================================
# Spannung_2:         0.1 V/digit    (UDC, UL1, UL2, UL3, UD01, UD02, UD03)
# Strom_positiv_2:    0.01 A/digit   (IDC, ID01, ID02, ID03, IL1, IL2, IL3)
# Leistung:           0.5 W/digit    (PAC, PDC, PD01, PD02, PD03, PIN)
# Energie_1:          0.1 kWh/digit  (KDY, KLD)
# Energie_2:          1 kWh/digit    (KMT, KYR, KT0, KLM, KLY)
# Frequenz:           0.01 Hz/digit  (TNF)
# Temperatur_positiv: 1 °C/digit     (TKK)
# ohne_Einheit_1:     1/digit 32-bit (KHR)
# ohne_Einheit_2:     1/digit 16-bit (SWV, TYP, PRL)
# Register:           1/digit 16-bit (SYS, SAL)

# =============================================================================
# Field Mapping for Inverter Data Queries
# =============================================================================
# Keys documented in the MaxComm protocol specification (Section 2.4):
#   PAC, KHR, KDY, KMT, KYR, KT0, UDC, UL1, UL2, UL3,
#   IDC, IL1, IL2, IL3, TKK, PIN, TNP, ADR, PRL, SWV, TYP, SYS, SAL
#
# Additional keys supported by some models (undocumented/model-specific):
#   PDC, PD01, PD02, UD01, UD02, ID01, ID02, CAC
#
# Per the protocol: "Nicht definierte Keys werden in der Antwort ignoriert"
# (Undefined keys are simply ignored in the response)

FIELD_MAP_INVERTER = {
    # Official MaxComm protocol keys (Section 2.4)
    "PAC": "AC_Power",  # Leistung (0.5 W/digit)
    "UDC": "DC_Voltage",  # Spannung_2 (0.1 V/digit)
    "IDC": "DC_Current",  # Strom_positiv_2 (0.01 A/digit)
    "UL1": "AC_Voltage_Phase_1",  # Spannung_2 (0.1 V/digit)
    "UL2": "AC_Voltage_Phase_2",  # Spannung_2 (0.1 V/digit)
    "UL3": "AC_Voltage_Phase_3",  # Spannung_2 (0.1 V/digit)
    "IL1": "AC_Current_Phase_1",  # Strom_positiv_2 (0.01 A/digit)
    "IL2": "AC_Current_Phase_2",  # Strom_positiv_2 (0.01 A/digit)
    "IL3": "AC_Current_Phase_3",  # Strom_positiv_2 (0.01 A/digit)
    "KDY": "Energy_Day",  # Energie_1 (0.1 kWh/digit)
    "KMT": "Energy_Month",  # Energie_2 (1 kWh/digit)
    "KYR": "Energy_Year",  # Energie_2 (1 kWh/digit)
    "KT0": "Energy_Total",  # Energie_2 (1 kWh/digit)
    "KHR": "Operating_Hours",  # ohne_Einheit_1 (1 h/digit)
    "TKK": "Temperature_Power_Unit",  # Temperatur_positiv (1 °C/digit)
    "TK2": "Temperature_Power_Unit_2",  # Temperatur_positiv (1 °C/digit)
    "TK3": "Temperature_Power_Unit_3",  # Temperatur_positiv (1 °C/digit)
    "SYS": "Status_Code",  # Register
    "SAL": "Alarm_Code",  # Register (bitmask)
    "PIN": "Installed_Power",  # Leistung (0.5 W/digit) — rated inverter power
    "PRL": "Relative_Power",  # ohne_Einheit_2 (1 %/digit) — % of rated power
    # Grid monitoring configuration (read from inverter settings)
    "ULH": "Grid_Voltage_Upper_Limit",  # Spannung_2 (0.1 V/digit)
    "ULL": "Grid_Voltage_Lower_Limit",  # Spannung_2 (0.1 V/digit)
    "TNH": "Grid_Frequency_Upper_Limit",  # Frequenz_2 (0.01 Hz/digit)
    "TNL": "Grid_Frequency_Lower_Limit",  # Frequenz_2 (0.01 Hz/digit)
    # Model-specific keys (not in official MaxComm spec, but supported by some models)
    "PDC": "DC_Power",  # Leistung (0.5 W/digit)
    "PD01": "DC_Power_String_1",  # Leistung (0.5 W/digit)
    "PD02": "DC_Power_String_2",  # Leistung (0.5 W/digit)
    "PD03": "DC_Power_String_3",  # Leistung (0.5 W/digit)
    "UD01": "DC_Voltage_String_1",  # Spannung_2 (0.1 V/digit)
    "UD02": "DC_Voltage_String_2",  # Spannung_2 (0.1 V/digit)
    "UD03": "DC_Voltage_String_3",  # Spannung_2 (0.1 V/digit)
    "ID01": "DC_Current_String_1",  # Strom_positiv_2 (0.01 A/digit)
    "ID02": "DC_Current_String_2",  # Strom_positiv_2 (0.01 A/digit)
    "ID03": "DC_Current_String_3",  # Strom_positiv_2 (0.01 A/digit)
    "KLD": "Energy_Yesterday",  # Energie_1 (0.1 kWh/digit)
    "KLM": "Energy_Last_Month",  # Energie_2 (1 kWh/digit)
    "KLY": "Energy_Last_Year",  # Energie_2 (1 kWh/digit)
    "TNF": "Grid_Frequency",  # Frequenz (0.01 Hz/digit)
    "CAC": "Startups",  # ohne_Einheit_1
}

# Static identification keys — queried once for device info, not on every poll.
# These values do not change during operation.
FIELD_MAP_DEVICE_INFO = {
    "TYP": "Device_Type",  # ohne_Einheit_2 (device type identifier)
    "SWV": "Software_Version",  # ohne_Einheit_2 (firmware version number)
    "DIN": "Serial_Number",  # ohne_Einheit_2 (inverter serial number)
    "BDN": "Build_Number",  # ohne_Einheit_2 (firmware build/release number)
}

# MaxComm request template
# Format: {<Src-Adr>;<Dest-Adr>;<Length>|<Port>:<Keys>|<CRC>}
# - FB (251) = Host address per MaxComm spec Section 1.3
# - ## = Dest-Adr placeholder (device address, 2 hex chars)
# - !! = Length placeholder (total packet length, 2 hex chars)
# - 64 = Port 100 (0x64) for data queries per Section 1.4
# - && = Data keys placeholder (semicolon-separated)
# - $$$$ = CRC placeholder (4 hex chars)
REQUEST_TEMPLATE = "{FB;##;!!|64:&&|$$$$}"

# Value scaling per MaxComm Section 2.2 (Netzwerkvariable): physical = raw / divisor.
# Fields not listed are transmitted 1:1 (Energie_2, Temperatur, unitless values,
# and the SYS/SAL registers, which are decoded at the sensor level).
_SCALE_GROUPS: dict[int, tuple[str, ...]] = {
    2: ("PAC", "PDC", "PD01", "PD02", "PD03", "PIN"),  # Leistung: 0.5 W/digit
    10: (
        "UL1",
        "UL2",
        "UL3",
        "UDC",
        "UD01",
        "UD02",
        "UD03",
        "ULH",
        "ULL",  # 0.1 V
        "KDY",
        "KLD",  # Energie_1: 0.1 kWh/digit
    ),
    100: (
        "IDC",
        "ID01",
        "ID02",
        "ID03",
        "IL1",
        "IL2",
        "IL3",  # Strom: 0.01 A/digit
        "TNH",
        "TNL",
        "TNF",  # Frequenz: 0.01 Hz/digit
    ),
}
_FIELD_DIVISOR: dict[str, int] = {
    field: divisor for divisor, fields in _SCALE_GROUPS.items() for field in fields
}

# Frame layout: {<payload>|<CRC>}  — CRC is 4 hex chars immediately before the ETX.
_CRC_LEN = 4


def _frame_payload(frame: str) -> str:
    """Return the CRC-covered payload: everything between STX and the CRC+ETX."""
    return frame[1 : -(_CRC_LEN + 1)]


def _frame_crc(frame: str) -> str:
    """Return the 4-char CRC stated at the end of a frame (just before the ETX)."""
    return frame[-(_CRC_LEN + 1) : -1]


class SolarmaxConnectionError(Exception):
    """Exception raised when connection to inverter fails."""

    def __init__(
        self, message: str, translation_key: str = "connection_error", **kwargs
    ):
        """Initialize the exception with translation support."""
        super().__init__(message)
        self.translation_key = translation_key
        self.translation_placeholders = kwargs


class SolarmaxTimeoutError(Exception):
    """Exception raised when a timeout occurs."""

    def __init__(self, message: str, translation_key: str = "timeout_error", **kwargs):
        """Initialize the exception with translation support."""
        super().__init__(message)
        self.translation_key = translation_key
        self.translation_placeholders = kwargs


class SolarmaxProtocolError(Exception):
    """Exception raised when protocol communication fails."""

    def __init__(self, message: str, translation_key: str = "protocol_error", **kwargs):
        """Initialize the exception with translation support."""
        super().__init__(message)
        self.translation_key = translation_key
        self.translation_placeholders = kwargs


class SolarmaxProtocolRetryableError(SolarmaxProtocolError):
    """Exception for transient protocol failures (corrupted/truncated responses).

    Unlike deterministic errors (IPR/IPN), these may succeed on retry.
    """


class SolarmaxAPI:
    """API for communicating with Solarmax inverters."""

    def __init__(
        self,
        host: str,
        port: int = 12345,
        address: int = 1,
        timeout: int = 10,
        verify_checksum: bool = True,
    ):
        """Initialize the API."""
        self.host = host
        self.port = port
        self.address = address
        self.timeout = timeout
        self.verify_checksum = verify_checksum
        self._last_successful_connection = None

    def _create_socket_connection(
        self, retries: int = CONNECT_RETRIES
    ) -> socket.socket:
        """Create a socket connection with retry logic."""
        last_exception = None

        for attempt in range(retries):
            sock = None
            try:
                _LOGGER.debug(
                    "Attempting connection to %s:%s (attempt %d/%d)",
                    self.host,
                    self.port,
                    attempt + 1,
                    retries,
                )

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)

                # Set socket options to help with connection reuse
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                # Connect with timeout
                sock.connect((self.host, self.port))

                _LOGGER.debug("Successfully connected to %s:%s", self.host, self.port)
                return sock

            except TimeoutError as e:
                last_exception = SolarmaxTimeoutError(
                    f"Connection timeout to {self.host}:{self.port}"
                )
                _LOGGER.debug("Connection attempt %d timed out: %s", attempt + 1, e)
            except ConnectionRefusedError as e:
                last_exception = SolarmaxConnectionError(
                    f"Connection refused by {self.host}:{self.port}"
                )
                _LOGGER.debug("Connection attempt %d refused: %s", attempt + 1, e)
            except OSError as e:
                last_exception = SolarmaxConnectionError(f"Socket error: {e}")
                _LOGGER.debug(
                    "Connection attempt %d failed with socket error: %s",
                    attempt + 1,
                    e,
                )
            except Exception as e:
                last_exception = SolarmaxConnectionError(f"Unexpected error: {e}")
                _LOGGER.debug(
                    "Connection attempt %d failed with unexpected error: %s",
                    attempt + 1,
                    e,
                )

            # Clean up failed socket
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass

            # Wait before retry (except on last attempt)
            if attempt < retries - 1:
                wait_time = 1 + attempt  # Exponential backoff: 1s, 2s, 3s
                _LOGGER.debug("Waiting %ds before retry...", wait_time)
                time.sleep(wait_time)

        # All attempts failed
        _LOGGER.debug(
            "Failed to connect to %s:%s after %d attempts",
            self.host,
            self.port,
            retries,
        )
        if last_exception:
            raise last_exception
        else:
            raise SolarmaxConnectionError(
                f"Failed to connect to {self.host}:{self.port}"
            )

    def _send_request_and_receive_response(
        self, sock: socket.socket, request: str
    ) -> str:
        """Send request and receive response with proper timeout handling.

        The inverter may split large responses into multiple frames (each max
        255 bytes). We keep reading until no more data arrives.

        Two-tier timeout: each recv waits at most RECV_INITIAL_TIMEOUT (or
        RECV_CONTINUATION_TIMEOUT once data has arrived) so we notice quickly
        when a multi-frame response is complete, while self.timeout bounds
        the total wait for the whole response.
        """
        try:
            # Send request
            _LOGGER.debug("Sending request: %s", request)
            sock.send(bytes(request, "utf-8"))

            # Receive response — read all available data (may be multiple frames)
            response = ""
            start_time = time.time()
            recv_timeout = RECV_INITIAL_TIMEOUT

            while True:
                remaining = self.timeout - (time.time() - start_time)
                if remaining <= 0:
                    break
                try:
                    # Never wait beyond the overall timeout
                    sock.settimeout(min(recv_timeout, remaining))
                    buf = sock.recv(4096)
                    if len(buf) > 0:
                        response += buf.decode("utf-8", errors="ignore")
                        # If the response ends with '}' (final frame ETX),
                        # we have the complete response — no need to wait.
                        # Continuation frames end with ')' instead.
                        if response.endswith(PROTO_ETX):
                            break
                        # Still waiting for more frames, use short timeout
                        recv_timeout = RECV_CONTINUATION_TIMEOUT
                    else:
                        break
                except TimeoutError:
                    # If we already have data, the timeout means no more frames
                    if response:
                        break
                    # Otherwise keep waiting for the first response
                    continue
                except OSError as e:
                    raise SolarmaxConnectionError(f"Error receiving data: {e}") from e

            if not response:
                raise SolarmaxTimeoutError("No response received within timeout period")

            _LOGGER.debug("Received response: %s", response)
            return response

        except TimeoutError as e:
            raise SolarmaxTimeoutError("Request/response timeout") from e
        except OSError as e:
            raise SolarmaxConnectionError(
                f"Socket error during communication: {e}"
            ) from e

    @property
    def last_successful_connection(self) -> datetime | None:
        """Return the timestamp of the last successful connection."""
        return self._last_successful_connection

    def build_request(self, field_map: dict[str, str]) -> str:
        """Build a MaxComm protocol request message.

        Request format per MaxComm spec Section 2.1:
            {<Src>;<Dest>;<Len>|<Port>:<Key1>;<Key2>;...|<CRC>}

        The CRC is the sum of ASCII values of all characters from Src-Adr
        up to and including the FRS before the CRC field (Section 1.1).

        Raises SolarmaxProtocolError if the request exceeds 255 bytes
        (the maximum representable in the 2-hex-char length field).
        """
        fields = PROTO_FS.join(field_map.keys())
        req = REQUEST_TEMPLATE.replace("##", format(self.address, "02X"))
        req = req.replace("&&", fields)

        if len(req) > 255:
            raise SolarmaxProtocolError(
                f"Request too large ({len(req)} bytes, max 255). "
                f"Reduce the number of queried fields."
            )

        # Length = total packet length (including STX/ETX, per protocol spec)
        req = req.replace("!!", format(len(req), "02X"))
        # CRC covers the payload: from Src-Adr to (and including) the FRS before
        # the CRC placeholder, i.e. everything except STX and the "$$$$}" tail.
        req = req.replace("$$$$", self.calculate_checksum(_frame_payload(req)))
        return req

    def calculate_checksum(self, data: str) -> str:
        """Calculate MaxComm CRC: sum of ASCII values, formatted as 4-char hex.

        Per protocol spec Section 1.1: "Summe der ASCII-Werte aller Zeichen
        von Adress bis und mit dem FRS vor Crc"
        """
        checksum_value = sum(ord(c) for c in data)
        return format(checksum_value, "04X")

    def _verify_response_checksum(self, response: str) -> bool:
        """Verify the CRC checksum of a MaxComm response frame.

        Returns True if checksum is valid, False otherwise.
        Per protocol spec: if CRC or Length don't match, the data should be
        considered corrupted (Section 3.1).

        Accepts both '}' (final frame) and ')' (continuation frame) as ETX.
        """
        try:
            if not response or response[0] != PROTO_STX:
                return False
            if response[-1] != PROTO_ETX and response[-1] != ")":
                return False

            # Extract the stated CRC and recompute it over the same payload
            # range used by build_request().
            stated_crc = _frame_crc(response)
            expected_crc = self.calculate_checksum(_frame_payload(response))
            if stated_crc != expected_crc:
                _LOGGER.warning(
                    "MaxComm CRC mismatch: stated=%s, calculated=%s",
                    stated_crc,
                    expected_crc,
                )
                return False
            return True
        except (IndexError, ValueError) as e:
            _LOGGER.debug("CRC verification failed: %s", e)
            return False

    def map_data_value(self, field: str, value: int) -> float | int:
        """Convert raw hex digit value to physical units per MaxComm network variables.

        Scaling factors per MaxComm protocol Section 2.2 (Netzwerkvariable):
        - Leistung (Power):         0.5 W/digit   → value / 2
        - Spannung_2 (Voltage):     0.1 V/digit   → value / 10
        - Strom_positiv_2 (Current): 0.01 A/digit → value / 100
        - Energie_1 (Energy Day):   0.1 kWh/digit → value / 10
        - Energie_2 (Energy M/Y/T): 1 kWh/digit   → no conversion
        - Temperatur_positiv:       1 °C/digit    → no conversion
        - ohne_Einheit (unitless):  1/digit       → no conversion
        - Register (SYS/SAL):       raw value     → decoded at sensor level
        """
        divisor = _FIELD_DIVISOR.get(field)
        if divisor is None:
            # Energie_2, Temperatur, unitless, and SYS/SAL registers: raw 1:1
            # (SYS/SAL are decoded into enums/bitmasks at the sensor level).
            return value
        return value / divisor

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
            _LOGGER.debug("Connection test failed: %s", e)
            return False

    def get_data(self) -> dict[str, Any]:
        """Get data from the inverter with retry logic."""
        retries = DATA_RETRIES
        last_exception = None

        for attempt in range(retries):
            sock = None
            try:
                _LOGGER.debug(
                    "Getting data from inverter (attempt %d/%d)", attempt + 1, retries
                )

                # Create connection with retry logic
                sock = self._create_socket_connection(retries=CONNECT_RETRIES)

                # Build and send request, receive response
                request = self.build_request(FIELD_MAP_INVERTER)
                response = self._send_request_and_receive_response(sock, request)

                if response:
                    # Mark successful connection
                    self._last_successful_connection = datetime.now()
                    data = self.convert_to_json(response)
                    _LOGGER.debug("Successfully retrieved data from inverter")
                    return data
                else:
                    raise SolarmaxTimeoutError("Empty response received")

            except SolarmaxProtocolRetryableError as e:
                # Corrupted/truncated responses may be transient line noise —
                # retry before giving up.
                last_exception = e
                _LOGGER.debug(
                    "Data retrieval attempt %d failed (transient protocol error): %s",
                    attempt + 1,
                    e,
                )
            except SolarmaxProtocolError as e:
                # Protocol errors (IPR/IPN) are deterministic — don't retry
                _LOGGER.debug("Protocol error from inverter: %s", e)
                raise
            except (SolarmaxConnectionError, SolarmaxTimeoutError) as e:
                last_exception = e
                _LOGGER.debug("Data retrieval attempt %d failed: %s", attempt + 1, e)
            except Exception as e:
                last_exception = SolarmaxConnectionError(f"Unexpected error: {e}")
                _LOGGER.debug(
                    "Data retrieval attempt %d failed with unexpected error: %s",
                    attempt + 1,
                    e,
                )
            finally:
                # Always clean up socket
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass

            # Wait before retry (except on last attempt)
            if attempt < retries - 1:
                wait_time = 2 + attempt  # 2s, 3s wait between attempts
                _LOGGER.debug(
                    "Waiting %ds before retrying data retrieval...", wait_time
                )
                time.sleep(wait_time)

        # All attempts failed
        _LOGGER.debug("Failed to get data from inverter after %d attempts", retries)
        if last_exception:
            raise last_exception
        else:
            raise SolarmaxConnectionError("Failed to get data from inverter")

    def get_device_info(self) -> dict[str, Any]:
        """Query static device identification keys (TYP, SWV, DIN, BDN).

        These values do not change during operation and should only be
        queried once (e.g. during setup or first refresh).
        """
        sock = None
        try:
            sock = self._create_socket_connection(retries=CONNECT_RETRIES)
            request = self.build_request(FIELD_MAP_DEVICE_INFO)
            response = self._send_request_and_receive_response(sock, request)

            if response:
                self._last_successful_connection = datetime.now()
                return self.convert_to_json(response)
            else:
                raise SolarmaxTimeoutError("Empty response received")
        finally:
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass

    def _split_response_frames(self, data: str) -> list[str]:
        """Split a multi-frame response into individual frames.

        The inverter splits responses exceeding 255 bytes into multiple
        frames, each with its own {Src;Dest;Len|...|CRC} structure.
        Non-final frames use ')' as ETX, the final frame uses '}'.
        """
        frames = []
        current = ""
        for char in data:
            current += char
            if char == PROTO_ETX or char == ")":
                if current.startswith(PROTO_STX):
                    frames.append(current)
                current = ""
        return frames

    def _extract_data_from_frames(self, frames: list[str]) -> str:
        """Extract and merge data sections from multiple response frames.

        Frame 1 format: {Src;Dest;Len|Port:Data|CRC}  or  {Src;Dest;Len|Port:Data|CRC)
        Continuation frames: {Src;Dest;Len|Data|CRC}

        The inverter may split a field name at the frame boundary, e.g.:
        Frame 1 ends with "...;U" and Frame 2 starts with "D01=D38;..."
        Concatenation reconstructs the full field: "...;UD01=D38;..."
        """
        data_parts = []
        for i, frame in enumerate(frames):
            # Strip STX and (CRC + ETX), leaving "Header|Payload|", then strip
            # the trailing FRS (the '|' before the CRC).
            inner = _frame_payload(frame)
            if inner.endswith(PROTO_FRS):
                inner = inner[:-1]

            # Split on first | to separate header from payload
            pipe_pos = inner.find(PROTO_FRS)
            if pipe_pos < 0:
                continue
            payload = inner[pipe_pos + 1 :]

            if i == 0:
                # First frame has "Port:Data" — extract after the colon
                colon_pos = payload.find(PROTO_US)
                if colon_pos >= 0:
                    data_parts.append(payload[colon_pos + 1 :])
                else:
                    data_parts.append(payload)
            else:
                # Continuation frames have just data (no port prefix)
                data_parts.append(payload)

        # Direct concatenation reconstructs split field names at boundaries
        return "".join(data_parts)

    def convert_to_json(self, data: str) -> dict[str, Any]:
        """Parse a MaxComm protocol response into a dictionary.

        Response format per MaxComm spec Section 2.1:
            {<Src>;<Dest>;<Len>|<Port>:<Key1>=<Val1>;<Key2>=<Val2>|<CRC>}

        Handles multi-frame responses where the inverter splits large responses
        into multiple frames (each max 255 bytes).

        Error cases handled per Section 1.6:
        - Key without '=' → "not applicable" (key known but currently unavailable)
        - Empty data section → "not supported" (unknown key)
        - Port 3E8 responses → interface error messages (IPR, IPN)
        """
        try:
            # Split into individual frames
            frames = self._split_response_frames(data)
            if not frames:
                # Corrupted/truncated response — may succeed on retry
                raise SolarmaxProtocolRetryableError(
                    "No valid MaxComm frames found in response"
                )

            # Verify checksum on each frame (unless disabled)
            if self.verify_checksum:
                for frame in frames:
                    if not self._verify_response_checksum(frame):
                        # Likely line noise — may succeed on retry
                        raise SolarmaxProtocolRetryableError(
                            "MaxComm response checksum verification failed: "
                            "data may be corrupted"
                        )

            # Check for interface error messages (port 0x3E8 = 1000)
            # Only need to check the first frame (error responses are single-frame)
            port_hex = format(PROTO_PORT_MESSAGE, "X")
            port_hex_padded = format(PROTO_PORT_MESSAGE, "04X")
            if (
                f"{PROTO_FRS}{port_hex}{PROTO_US}" in frames[0]
                or f"{PROTO_FRS}{port_hex_padded}{PROTO_US}" in frames[0]
            ):
                error_data = frames[0].split(PROTO_US)[1].split(PROTO_FRS)[0]
                if PROTO_ERROR_INVALID_PROTOCOL in error_data:
                    raise SolarmaxProtocolError(
                        "Inverter reported invalid protocol (IPR): "
                        "checksum or length error in our request"
                    )
                if PROTO_ERROR_INVALID_PORT in error_data:
                    raise SolarmaxProtocolError(
                        "Inverter reported invalid port number (IPN)"
                    )

            # Extract and merge data from all frames
            data_section = self._extract_data_from_frames(frames)
            data_split = data_section.split(PROTO_FS)
            result_dict = {}

            for item in data_split:
                if "=" not in item:
                    # Per Section 1.6.4: key without value means "not applicable"
                    # (key is known but not available in current device state)
                    if item.strip():
                        _LOGGER.debug(
                            "MaxComm: key '%s' returned as not applicable", item
                        )
                    continue

                field, value_str = item.split("=", 1)

                if field == "SYS":
                    # SYS uses format "VALUE,0" (status value with sub-state)
                    value = int(value_str.split(",")[0], 16)
                else:
                    value = int(value_str, 16)

                result_dict[field] = {
                    "value": self.map_data_value(field, value),
                    "raw_value": value,
                }

            _LOGGER.debug("Parsed %d values from inverter response", len(result_dict))
            return result_dict

        except (SolarmaxProtocolError, SolarmaxConnectionError):
            raise
        except Exception as e:
            raise SolarmaxProtocolRetryableError(
                f"Unexpected error parsing MaxComm response: {e}"
            ) from e
