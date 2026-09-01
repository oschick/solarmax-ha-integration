"""Solarmax Inverter API.

Connection/retry layer over the MaxComm protocol codec (see protocol.py).

Protocol reference: "Beschreibung des MaxComm Datenprotokolls" (August 2022)
"""

from __future__ import annotations

import logging
import socket
import time
from datetime import datetime
from typing import Any

from . import protocol
from .protocol import (
    FIELD_MAP_INVERTER,  # noqa: F401  (re-exported for tests/tools)
    PROTO_ETX,
    PROTO_FRS,  # noqa: F401  (re-exported for tests/tools)
    PROTO_FS,  # noqa: F401  (re-exported for tests/tools)
    PROTO_STX,  # noqa: F401  (re-exported for tests/tools)
    PROTO_US,  # noqa: F401  (re-exported for tests/tools)
    ProtocolError,
    RetryableProtocolError,
)

_LOGGER = logging.getLogger(__name__)

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

# Protocol timing (milliseconds)
PROTO_TYPICAL_RESPONSE_MS = 300
PROTO_MAX_TIMEOUT_MS = 3000

# Static identification keys — queried once for device info, not on every poll.
# These values do not change during operation.
FIELD_MAP_DEVICE_INFO = {
    "TYP": "Device_Type",  # ohne_Einheit_2 (device type identifier)
    "SWV": "Software_Version",  # ohne_Einheit_2 (firmware version number)
    "DIN": "Serial_Number",  # ohne_Einheit_2 (inverter serial number)
    "BDN": "Build_Number",  # ohne_Einheit_2 (firmware build/release number)
}


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


# Compatibility aliases: the codec's exceptions moved to protocol.py, but keep
# the old names raisable/catchable (and keep the same subclass relationship).
SolarmaxProtocolError = ProtocolError
SolarmaxProtocolRetryableError = RetryableProtocolError


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
        """Return the timestamp of the last successful data retrieval."""
        return self._last_successful_connection

    def build_request(self, field_map: dict[str, str]) -> str:
        """Build a MaxComm data request frame for the given fields.

        Raises SolarmaxProtocolError if request exceeds 255 bytes.
        """
        return protocol.build_request(self.address, list(field_map))

    def calculate_checksum(self, data: str) -> str:
        """Calculate MaxComm CRC: sum of ASCII values, formatted as 4-char hex."""
        return protocol.calculate_checksum(data)

    def _verify_response_checksum(self, response: str) -> bool:
        """Verify the CRC checksum of a MaxComm response frame."""
        return protocol.verify_frame_checksum(response)

    def map_data_value(self, field: str, value: int) -> float | int:
        """Convert raw hex digit value to physical units."""
        return protocol.scale_value(field, value)

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
        """Split a multi-frame response into individual frames."""
        return protocol.split_frames(data)

    def convert_to_json(self, data: str) -> dict[str, Any]:
        """Parse a MaxComm protocol response into a dictionary."""
        return protocol.parse_response(data, verify_checksum=self.verify_checksum)
