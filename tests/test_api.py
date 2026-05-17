"""Test the Solarmax API."""

import pytest
from unittest.mock import patch, MagicMock
import socket

from custom_components.solarmax.solarmax_api import (
    SolarmaxAPI,
    SolarmaxConnectionError,
    SolarmaxProtocolError,
    SolarmaxTimeoutError,
    FIELD_MAP_INVERTER,
)


@pytest.fixture
def api():
    """Create a SolarmaxAPI instance for testing."""
    return SolarmaxAPI("192.168.1.100", 12345)


def test_build_request(api):
    """Test request building with default address."""
    field_map = {"PAC": "AC_Power (W)"}
    request = api.build_request(field_map)

    assert request.startswith("{FB;01;")
    assert "PAC" in request
    assert request.endswith("}")


def test_build_request_custom_address():
    """Test request building with a custom inverter address."""
    api_addr2 = SolarmaxAPI("192.168.1.100", 12345, address=2)
    field_map = {"PAC": "AC_Power (W)"}
    request = api_addr2.build_request(field_map)

    assert request.startswith("{FB;02;")
    assert "PAC" in request
    assert request.endswith("}")


def test_calculate_checksum(api):
    """Test checksum calculation."""
    data = "FB;01;3A|64:PAC|"
    checksum = api.calculate_checksum(data)

    assert isinstance(checksum, str)
    assert len(checksum) == 4
    assert checksum.isupper()


def test_map_data_value(api):
    """Test data value mapping."""
    # Test power values (divided by 2)
    assert api.map_data_value("PAC", 3000) == 1500.0
    assert api.map_data_value("PDC", 2000) == 1000.0

    # Test voltage values (divided by 10)
    assert api.map_data_value("UL1", 2300) == 230.0
    assert api.map_data_value("UDC", 4000) == 400.0

    # Test current values (divided by 100)
    assert api.map_data_value("IDC", 650) == 6.5
    assert api.map_data_value("IL1", 1050) == 10.5

    # Test status values (unchanged)
    assert api.map_data_value("SYS", 20019) == 20019
    assert api.map_data_value("SAL", 0) == 0

    # Test other values (unchanged)
    assert api.map_data_value("KDY", 1234) == 1234


@patch("socket.socket")
def test_test_connection_success(mock_socket, api):
    """Test successful connection test."""
    mock_sock = MagicMock()
    mock_socket.return_value = mock_sock
    mock_sock.recv.return_value = b"test_response"

    result = api.test_connection()

    assert result is True
    mock_sock.connect.assert_called_once_with(("192.168.1.100", 12345))
    mock_sock.close.assert_called_once()


@patch("socket.socket")
def test_test_connection_failure(mock_socket, api):
    """Test failed connection test."""
    mock_sock = MagicMock()
    mock_socket.return_value = mock_sock
    mock_sock.connect.side_effect = socket.error("Connection failed")

    result = api.test_connection()

    assert result is False


@patch("socket.socket")
def test_get_data_success(mock_socket, api):
    """Test successful data retrieval."""
    mock_sock = MagicMock()
    mock_socket.return_value = mock_sock
    mock_sock.recv.return_value = b"{01|64:PAC=BB8;SYS=4E33,0|}"

    result = api.get_data()

    assert isinstance(result, dict)
    mock_sock.connect.assert_called()
    mock_sock.send.assert_called()
    mock_sock.close.assert_called()


@patch("socket.socket")
def test_get_data_connection_error(mock_socket, api):
    """Test data retrieval with connection error."""
    mock_socket.side_effect = socket.error("Connection failed")

    with pytest.raises(SolarmaxConnectionError):
        api.get_data()


@patch("socket.socket")
def test_get_data_timeout(mock_socket, api):
    """Test data retrieval with timeout."""
    mock_sock = MagicMock()
    mock_socket.return_value = mock_sock
    mock_sock.recv.return_value = b""  # Empty response triggers timeout

    with pytest.raises(SolarmaxTimeoutError):
        api.get_data()


def test_convert_to_json(api):
    """Test response conversion to JSON."""
    response = "{01|64:PAC=BB8;SYS=4E33,0;SAL=0|}"
    result = api.convert_to_json(response)

    assert isinstance(result, dict)
    assert "PAC" in result
    assert "SYS" in result
    assert "SAL" in result

    # Check value conversion
    assert result["PAC"]["value"] == 1500.0  # 3000 / 2
    assert result["SYS"]["value"] == 20019  # 0x4E33
    assert result["SAL"]["value"] == 0  # 0x0


def test_convert_to_json_invalid_response(api):
    """Test response conversion with invalid data."""
    response = "invalid_response"
    result = api.convert_to_json(response)

    assert result == {}


def test_last_successful_connection_tracking(api):
    """Test last successful connection timestamp tracking."""
    assert api.last_successful_connection is None

    with patch("socket.socket") as mock_socket:
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.recv.return_value = b"{01|64:PAC=BB8|}"

        api.get_data()

        assert api.last_successful_connection is not None


def test_convert_to_json_valid_crc(api):
    """Test response with valid CRC is parsed successfully."""
    # Build a response with correct CRC
    inner = "01;FB;1A|64:PAC=1F4;UDC=BB8|"
    crc = api.calculate_checksum(inner)
    response = "{" + inner + crc + "}"
    result = api.convert_to_json(response)

    assert "PAC" in result
    assert result["PAC"]["value"] == 250.0  # 500 / 2
    assert result["UDC"]["value"] == 300.0  # 3000 / 10


def test_convert_to_json_invalid_crc(api):
    """Test response with invalid CRC raises SolarmaxProtocolError."""
    # Use a response with wrong CRC
    response = "{01;FB;1A|64:PAC=1F4;UDC=BB8|0000}"
    with pytest.raises(SolarmaxProtocolError, match="checksum verification failed"):
        api.convert_to_json(response)


def test_convert_to_json_ipr_error(api):
    """Test IPR (invalid protocol) error response raises SolarmaxProtocolError."""
    inner = "01;FB;0E|3E8:IPR|"
    crc = api.calculate_checksum(inner)
    response = "{" + inner + crc + "}"
    with pytest.raises(SolarmaxProtocolError, match="invalid protocol"):
        api.convert_to_json(response)


def test_convert_to_json_ipn_error(api):
    """Test IPN (invalid port) error response raises SolarmaxProtocolError."""
    inner = "01;FB;0E|3E8:IPN|"
    crc = api.calculate_checksum(inner)
    response = "{" + inner + crc + "}"
    with pytest.raises(SolarmaxProtocolError, match="invalid port"):
        api.convert_to_json(response)


def test_convert_to_json_ipr_zero_padded_port(api):
    """Test IPR detection with zero-padded port (03E8)."""
    inner = "01;FB;0F|03E8:IPR|"
    crc = api.calculate_checksum(inner)
    response = "{" + inner + crc + "}"
    with pytest.raises(SolarmaxProtocolError, match="invalid protocol"):
        api.convert_to_json(response)


def test_convert_to_json_typ_swv(api):
    """Test parsing of TYP and SWV keys."""
    # TYP=20650 (0x50AA), SWV=40 (0x28)
    inner = "01;FB;1A|64:TYP=50AA;SWV=28|"
    crc = api.calculate_checksum(inner)
    response = "{" + inner + crc + "}"
    result = api.convert_to_json(response)

    assert result["TYP"]["value"] == 20650
    assert result["TYP"]["raw_value"] == 0x50AA
    assert result["SWV"]["value"] == 40
    assert result["SWV"]["raw_value"] == 0x28


def test_convert_to_json_not_applicable_key(api):
    """Test 'not applicable' keys (no '=' sign) are skipped gracefully."""
    # PAC has a value, UDC is "not applicable" (no '=')
    inner = "01;FB;1A|64:PAC=1F4;UDC|"
    crc = api.calculate_checksum(inner)
    response = "{" + inner + crc + "}"
    result = api.convert_to_json(response)

    assert "PAC" in result
    assert "UDC" not in result  # Not applicable keys are skipped


def test_get_data_protocol_error_no_retry(api):
    """Test that SolarmaxProtocolError is not retried."""
    # Build an IPR response
    inner = "01;FB;0E|3E8:IPR|"
    crc = api.calculate_checksum(inner)
    response = "{" + inner + crc + "}"

    with patch("socket.socket") as mock_socket:
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.recv.return_value = response.encode()

        with pytest.raises(SolarmaxProtocolError):
            api.get_data()

        # Should only have connected once (no retries for protocol errors)
        assert mock_sock.connect.call_count == 1
