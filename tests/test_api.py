"""Test the Solarmax API."""

import importlib.util
import pathlib
import socket
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solarmax.solarmax_api import (
    FIELD_MAP_DEVICE_INFO,
    FIELD_MAP_INVERTER,
    SolarmaxAPI,
    SolarmaxConnectionError,
    SolarmaxProtocolError,
    SolarmaxTimeoutError,
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
    # Sum of ASCII values of the data, as 4-digit uppercase hex
    assert checksum == format(sum(ord(c) for c in data), "04X")


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

    # Test daily energy values (divided by 10, 0.1 kWh/digit)
    assert api.map_data_value("KDY", 1234) == 123.4
    assert api.map_data_value("KLD", 85) == 8.5

    # Test frequency values (divided by 100, 0.01 Hz/digit)
    assert api.map_data_value("TNF", 5000) == 50.0

    # Raw 1:1 fields stay int (no scaling): monthly energy, temperature, hours
    assert api.map_data_value("KMT", 350) == 350
    assert api.map_data_value("TKK", 42) == 42
    assert isinstance(api.map_data_value("KMT", 350), int)


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
    mock_sock.connect.side_effect = OSError("Connection failed")

    result = api.test_connection()

    assert result is False


@patch("socket.socket")
def test_get_data_success(mock_socket, api):
    """Test successful data retrieval."""
    mock_sock = MagicMock()
    mock_socket.return_value = mock_sock
    inner = "01;FB;15|64:PAC=BB8;SYS=4E33,0|"
    crc = api.calculate_checksum(inner)
    mock_sock.recv.return_value = ("{" + inner + crc + "}").encode()

    result = api.get_data()

    assert isinstance(result, dict)
    mock_sock.connect.assert_called()
    mock_sock.send.assert_called()
    mock_sock.close.assert_called()


@patch("socket.socket")
def test_get_data_connection_error(mock_socket, api):
    """Test data retrieval with connection error."""
    mock_socket.side_effect = OSError("Connection failed")

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
    inner = "01;FB;1F|64:PAC=BB8;SYS=4E33,0;SAL=0|"
    crc = api.calculate_checksum(inner)
    response = "{" + inner + crc + "}"
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
    """Test conversion of invalid/unframed data raises SolarmaxProtocolError."""
    with pytest.raises(SolarmaxProtocolError):
        api.convert_to_json("invalid_response")


def test_last_successful_connection_tracking(api):
    """Test last successful connection timestamp tracking."""
    assert api.last_successful_connection is None

    with patch("socket.socket") as mock_socket:
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        inner = "01;FB;0F|64:PAC=BB8|"
        crc = api.calculate_checksum(inner)
        mock_sock.recv.return_value = ("{" + inner + crc + "}").encode()

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


@patch("custom_components.solarmax.solarmax_api.time.sleep")
@patch("socket.socket")
def test_get_data_retries_transient_protocol_error(mock_socket, mock_sleep, api):
    """Test that transient protocol errors (corrupted response) are retried."""
    inner = "01;FB;1A|64:PAC=1F4;UDC=BB8|"
    corrupted = "{" + inner + "0000}"  # Wrong CRC — transient line noise

    mock_sock = MagicMock()
    mock_socket.return_value = mock_sock
    mock_sock.recv.return_value = corrupted.encode()

    with pytest.raises(SolarmaxProtocolError):
        api.get_data()

    # Retried on all DATA_RETRIES attempts before giving up
    assert mock_sock.connect.call_count == 3


def test_emulator_and_api_agree_on_tnf_scaling(api):
    """The emulator's TNF response must decode to 50.0 Hz via the API."""
    import sys

    emulator_path = (
        pathlib.Path(__file__).parent.parent / "tools" / "inverter_emulator.py"
    )
    spec = importlib.util.spec_from_file_location("inverter_emulator", emulator_path)
    assert spec.loader is not None
    emulator_mod = importlib.util.module_from_spec(spec)
    # dataclass processing resolves field types through sys.modules
    sys.modules[spec.name] = emulator_mod
    try:
        spec.loader.exec_module(emulator_mod)
    finally:
        sys.modules.pop(spec.name, None)

    response = emulator_mod.SolarmaxEmulator(address=1).build_response(["TNF"])
    result = api.convert_to_json(response)

    assert result["TNF"]["value"] == 50.0


def test_convert_to_json_multi_frame(api):
    """Test parsing of multi-frame responses (continuation frames end with ')')."""
    # Build a realistic multi-frame response like a real inverter sends
    # Frame 1 ends with ')' (continuation), Frame 2 ends with '}' (final)
    inner1 = "01;FB;FF|64:PAC=2FA;UDC=D23;IDC=89;UL1=91C;UL2=8F0;UL3=8FD;IL1=84;IL2=82;IL3=87;KDY=D;KMT=102;KYR=602;KT0=9225;KHR=7848;TKK=24;SYS=4E28,0;SAL=0;TYP=50AA;DIN=9973BB;BDN=391;PIN=41A0;PRL=4;ULH=A55;ULL=730;TNH=141E;TNL=128E;PDC=340;PD01=1BE;PD02=182;U|"  # noqa: E501
    crc1 = api.calculate_checksum(inner1)
    frame1 = "{" + inner1 + crc1 + ")"  # Continuation frame ends with ')'

    inner2 = (
        "01;FB;53|D01=D23;UD02=AA0;ID01=43;ID02=46;KLM=294;KLY=11DF;TNF=138A;CAC=193D|"
    )
    crc2 = api.calculate_checksum(inner2)
    frame2 = "{" + inner2 + crc2 + "}"  # Final frame ends with '}'

    response = frame1 + frame2
    result = api.convert_to_json(response)

    # Field split across frames: "U" + "D01=D23" -> "UD01"
    assert "UD01" in result
    assert result["UD01"]["raw_value"] == 0xD23

    # Fields from first frame
    assert "PAC" in result
    assert result["PAC"]["value"] == 0x2FA / 2

    # Fields from second frame
    assert "CAC" in result
    assert result["CAC"]["raw_value"] == 0x193D
    assert "TNF" in result
    assert result["TNF"]["value"] == 0x138A / 100.0


def test_split_response_frames(api):
    """Test frame splitting with continuation delimiter ')'."""
    inner1 = "01;FB;10|64:PAC=1F4|"
    crc1 = api.calculate_checksum(inner1)
    frame1 = "{" + inner1 + crc1 + ")"

    inner2 = "01;FB;10|UDC=BB8|"
    crc2 = api.calculate_checksum(inner2)
    frame2 = "{" + inner2 + crc2 + "}"

    response = frame1 + frame2
    frames = api._split_response_frames(response)

    assert len(frames) == 2
    assert frames[0].endswith(")")
    assert frames[1].endswith("}")


def test_verify_response_checksum_continuation_frame(api):
    """Test CRC verification works for continuation frames (ending with ')')."""
    inner = "01;FB;10|64:PAC=1F4|"
    crc = api.calculate_checksum(inner)
    frame = "{" + inner + crc + ")"  # Continuation frame

    assert api._verify_response_checksum(frame) is True


@patch("socket.socket")
def test_get_data_multi_frame_recv(mock_socket, api):
    """Test that get_data reads multiple TCP chunks for multi-frame responses."""
    mock_sock = MagicMock()
    mock_socket.return_value = mock_sock

    # Field "UDC" is split across the frame boundary ("U" + "DC=BB8"),
    # as a real inverter splits data mid-field
    inner1 = "01;FB;16|64:PAC=BB8;SYS=4E33,0;U|"
    crc1 = api.calculate_checksum(inner1)
    frame1 = "{" + inner1 + crc1 + ")"

    inner2 = "01;FB;0D|DC=BB8|"
    crc2 = api.calculate_checksum(inner2)
    frame2 = "{" + inner2 + crc2 + "}"

    # Simulate data arriving in two TCP chunks
    mock_sock.recv.side_effect = [
        frame1.encode(),
        frame2.encode(),
        TimeoutError(),
    ]

    result = api.get_data()

    assert "PAC" in result
    assert "UDC" in result


def test_build_request_overflow_guard(api):
    """Test that build_request raises when request exceeds 255 bytes."""
    # Create a field map with enough keys to exceed the 255-byte limit
    huge_map = {f"K{i:03d}": f"Field_{i}" for i in range(100)}
    with pytest.raises(SolarmaxProtocolError, match="Request too large"):
        api.build_request(huge_map)


def test_build_request_within_limit(api):
    """Test that build_request succeeds for FIELD_MAP_INVERTER (under 255 bytes)."""
    request = api.build_request(FIELD_MAP_INVERTER)
    assert len(request) <= 255
    assert request.startswith("{")
    assert request.endswith("}")


def test_build_request_device_info(api):
    """Test that build_request succeeds for FIELD_MAP_DEVICE_INFO."""
    request = api.build_request(FIELD_MAP_DEVICE_INFO)
    assert len(request) <= 255
    assert "TYP" in request
    assert "SWV" in request
    assert "DIN" in request
    assert "BDN" in request


def test_receive_slow_first_frame(api):
    """Test that a slow-to-arrive response is still received successfully."""
    inner = "01;FB;14|64:PAC=BB8|"
    frame = "{" + inner + api.calculate_checksum(inner) + "}"

    sock = MagicMock()
    # First two reads time out, then the full frame arrives
    sock.recv.side_effect = [socket.timeout, socket.timeout, frame.encode()]

    response = api._send_request_and_receive_response(sock, "request")

    assert response == frame


def test_receive_no_response_raises_timeout():
    """Test that a never-responding inverter raises SolarmaxTimeoutError."""
    api = SolarmaxAPI("192.168.1.100", 12345, timeout=1)

    sock = MagicMock()
    sock.recv.side_effect = socket.timeout

    with pytest.raises(SolarmaxTimeoutError):
        api._send_request_and_receive_response(sock, "request")
