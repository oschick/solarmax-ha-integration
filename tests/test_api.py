"""Test the Solarmax API."""

import pytest
from unittest.mock import patch, MagicMock
import socket

from custom_components.solarmax.solarmax_api import (
    SolarmaxAPI, 
    SolarmaxConnectionError, 
    SolarmaxTimeoutError,
    FIELD_MAP_INVERTER
)


@pytest.fixture
def api():
    """Create a SolarmaxAPI instance for testing."""
    return SolarmaxAPI("192.168.1.100", 12345)


def test_build_request(api):
    """Test request building."""
    field_map = {"PAC": "AC_Power (W)"}
    request = api.build_request(field_map)
    
    assert request.startswith("{FB;01;")
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
    result = api.convert_to_json(FIELD_MAP_INVERTER, response)
    
    assert isinstance(result, dict)
    assert "PAC" in result
    assert "SYS" in result
    assert "SAL" in result
    
    # Check value conversion
    assert result["PAC"]["value"] == 1500.0  # 3000 / 2
    assert result["SYS"]["value"] == 20019   # 0x4E33
    assert result["SAL"]["value"] == 0       # 0x0


def test_convert_to_json_invalid_response(api):
    """Test response conversion with invalid data."""
    response = "invalid_response"
    result = api.convert_to_json(FIELD_MAP_INVERTER, response)
    
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
