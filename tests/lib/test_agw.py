import pytest
import socket
from io import BytesIO
from typing import cast

from lib.agw import (
	AGWClient,
	AGWFrame,
	AGWHeader,
	InvalidAGWError,
	normalize_call,
	parse_port_info,
	_encode_call,  # type: ignore[private-usage]
	_decode_call,  # type: ignore[private-usage]
	_HEADER_STRUCT,  # type: ignore[private-usage]
)


# ============================================================================
# normalize_call() tests
# ============================================================================


def test_normalize_call_basic() -> None:
	"""Test basic callsign normalization."""
	assert normalize_call("W1AW") == "W1AW"
	assert normalize_call("w1aw") == "W1AW"
	assert normalize_call("k9jrr") == "K9JRR"


def test_normalize_call_with_ssid() -> None:
	"""Test callsign normalization with SSID."""
	assert normalize_call("W1AW-0") == "W1AW-0"
	assert normalize_call("w1aw-5") == "W1AW-5"
	assert normalize_call("K9JRR-15") == "K9JRR-15"


def test_normalize_call_strips_whitespace() -> None:
	"""Test that whitespace is stripped."""
	assert normalize_call("  W1AW  ") == "W1AW"
	assert normalize_call(" W1AW-5 ") == "W1AW-5"


def test_normalize_call_single_char() -> None:
	"""Test single character callsigns."""
	assert normalize_call("A") == "A"
	assert normalize_call("5") == "5"
	assert normalize_call("W-1") == "W-1"


def test_normalize_call_six_chars() -> None:
	"""Test maximum length (6 characters)."""
	assert normalize_call("ABCDEF") == "ABCDEF"
	assert normalize_call("ABCDEF-0") == "ABCDEF-0"


@pytest.mark.parametrize(
	"invalid_call",
	[
		"",  # empty
		"A-",  # missing SSID number
		"A--5",  # double dash
		"ABCDEFG",  # too long
		"A B",  # space in middle
		"A-16",  # SSID out of range
		"A--1",  # invalid SSID format
		"A@",  # invalid character
	],
)
def test_normalize_call_invalid_raises(invalid_call: str) -> None:
	"""Test that invalid callsigns raise InvalidAGWError."""
	with pytest.raises(InvalidAGWError):
		normalize_call(invalid_call)


# ============================================================================
# _encode_call() tests
# ============================================================================


def test_encode_call_basic() -> None:
	"""Test basic callsign encoding."""
	encoded = _encode_call("W1AW")
	assert encoded == b"W1AW\x00\x00\x00\x00\x00\x00"
	assert len(encoded) == 10


def test_encode_call_empty() -> None:
	"""Test encoding empty callsign."""
	encoded = _encode_call("")
	assert encoded == b"\x00" * 10


def test_encode_call_single_char() -> None:
	"""Test encoding single character callsign."""
	encoded = _encode_call("A")
	assert encoded == b"A\x00\x00\x00\x00\x00\x00\x00\x00\x00"


def test_encode_call_with_ssid() -> None:
	"""Test encoding callsign with SSID."""
	encoded = _encode_call("W1AW-5")
	assert encoded == b"W1AW-5\x00\x00\x00\x00"


def test_encode_call_max_length() -> None:
	"""Test encoding with maximum visible characters (9)."""
	encoded = _encode_call("ABCDEF-15")
	assert encoded == b"ABCDEF-15\x00"
	assert len(encoded) == 10


def test_encode_call_too_long_raises() -> None:
	"""Test that callsigns longer than 9 visible characters raise an error."""
	with pytest.raises(InvalidAGWError):
		_encode_call("ABCDEFGHIJ")  # 10 chars


# ============================================================================
# _decode_call() tests
# ============================================================================


def test_decode_call_basic() -> None:
	"""Test basic callsign decoding."""
	decoded = _decode_call(b"W1AW\x00\x00\x00\x00\x00\x00")
	assert decoded == "W1AW"


def test_decode_call_empty() -> None:
	"""Test decoding all zeros."""
	decoded = _decode_call(b"\x00" * 10)
	assert decoded == ""


def test_decode_call_with_ssid() -> None:
	"""Test decoding callsign with SSID."""
	decoded = _decode_call(b"W1AW-5\x00\x00\x00\x00")
	assert decoded == "W1AW-5"


def test_decode_call_with_padding() -> None:
	"""Test decoding with null padding."""
	decoded = _decode_call(b"K9JRR\x00\x00\x00\x00\x00")
	assert decoded == "K9JRR"


def test_round_trip_encode_decode() -> None:
	"""Test that encode then decode returns original."""
	calls = ["W1AW", "K9JRR", "ABCDEF-15", "A", ""]
	for call in calls:
		encoded = _encode_call(call)
		decoded = _decode_call(encoded)
		# If call is empty string, normalize_call would fail, so just check the round trip
		if call:
			assert decoded == normalize_call(call)
		else:
			assert decoded == ""


# ============================================================================
# parse_port_info() tests
# ============================================================================


def test_parse_port_info_basic() -> None:
	"""Test parsing basic port info response."""
	data = b"Port0; COM1: 1200 bps; COM2: 9600 bps\x00"
	ports = parse_port_info(data)
	assert len(ports) == 2
	assert "COM1: 1200 bps" in ports
	assert "COM2: 9600 bps" in ports


def test_parse_port_info_single_port() -> None:
	"""Test parsing port info with single port."""
	data = b"Port0; COM1: 1200 bps\x00"
	ports = parse_port_info(data)
	assert len(ports) == 1
	assert ports[0] == "COM1: 1200 bps"


def test_parse_port_info_empty() -> None:
	"""Test parsing with minimal response."""
	data = b"Port0;\x00"
	ports = parse_port_info(data)
	assert ports == []


def test_parse_port_info_no_nulls() -> None:
	"""Test parsing without null termination."""
	data = b"Port0; COM1: 1200 bps"
	ports = parse_port_info(data)
	assert len(ports) == 1
	assert ports[0] == "COM1: 1200 bps"


def test_parse_port_info_strips_whitespace() -> None:
	"""Test that whitespace is properly stripped."""
	data = b" Port0 ;  COM1: 1200  ;  COM2: 9600  \x00"
	ports = parse_port_info(data)
	assert len(ports) == 2
	assert ports[0] == "COM1: 1200"
	assert ports[1] == "COM2: 9600"


# ============================================================================
# AGWFrame and header validation tests
# ============================================================================


def test_agw_frame_construction() -> None:
	"""Test basic AGWFrame construction."""
	header = AGWHeader(
		port=0,
		datakind="D",
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=5,
		user_reserved=0,
	)
	data = b"Hello"
	frame = AGWFrame(header=header, data=data)

	assert frame.header.port == 0
	assert frame.header.datakind == "D"
	assert frame.data == data


def test_agw_header_immutable() -> None:
	"""Test that AGWHeader is immutable (frozen dataclass)."""
	header = AGWHeader(
		port=0,
		datakind="D",
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=0,
		user_reserved=0,
	)
	with pytest.raises(AttributeError):
		header.port = 1  # type: ignore[misc]


# ============================================================================
# AGWClient.send_frame() validation tests
# ============================================================================


class MockSocket:
	"""Mock socket for testing without real network connection."""

	def __init__(self) -> None:
		self.sent_data = BytesIO()

	def sendall(self, data: bytes) -> None:
		self.sent_data.write(data)

	def close(self) -> None:
		pass


def create_mock_client() -> tuple[AGWClient, MockSocket]:
	"""Helper to create a client with a mock socket."""
	mock_sock = MockSocket()
	client = AGWClient(cast(socket.socket, mock_sock))
	return client, mock_sock


def test_send_frame_valid() -> None:
	"""Test sending a valid frame."""
	client, mock_sock = create_mock_client()

	header = AGWHeader(
		port=0,
		datakind="D",
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=5,
		user_reserved=0,
	)
	frame = AGWFrame(header=header, data=b"Hello")
	client.send_frame(frame)

	# Should have written header + data
	sent = mock_sock.sent_data.getvalue()
	assert len(sent) == _HEADER_STRUCT.size + 5


def test_send_frame_data_len_mismatch_raises() -> None:
	"""Test that data length mismatch raises InvalidAGWError."""
	client, _ = create_mock_client()

	header = AGWHeader(
		port=0,
		datakind="D",
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=10,  # Claims 10 bytes
		user_reserved=0,
	)
	frame = AGWFrame(header=header, data=b"Hello")  # Only 5 bytes

	with pytest.raises(InvalidAGWError, match="data length does not match"):
		client.send_frame(frame)


def test_send_frame_invalid_port_raises() -> None:
	"""Test that invalid port raises InvalidAGWError."""
	client, _ = create_mock_client()

	header = AGWHeader(
		port=256,  # Out of range
		datakind="D",
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=0,
		user_reserved=0,
	)
	frame = AGWFrame(header=header, data=b"")

	with pytest.raises(InvalidAGWError, match=r"port must be in range 0\..*255"):
		client.send_frame(frame)


def test_send_frame_negative_port_raises() -> None:
	"""Test that negative port raises InvalidAGWError."""
	client, _ = create_mock_client()

	header = AGWHeader(
		port=-1,  # Out of range
		datakind="D",
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=0,
		user_reserved=0,
	)
	frame = AGWFrame(header=header, data=b"")

	with pytest.raises(InvalidAGWError, match=r"port must be in range 0\..*255"):
		client.send_frame(frame)


def test_send_frame_invalid_pid_raises() -> None:
	"""Test that invalid PID raises InvalidAGWError."""
	client, _ = create_mock_client()

	header = AGWHeader(
		port=0,
		datakind="D",
		pid=256,  # Out of range
		call_from="W1AW",
		call_to="K9JRR",
		data_len=0,
		user_reserved=0,
	)
	frame = AGWFrame(header=header, data=b"")

	with pytest.raises(InvalidAGWError, match=r"pid must be in range 0\..*255"):
		client.send_frame(frame)


def test_send_frame_invalid_datakind_empty_raises() -> None:
	"""Test that empty datakind raises InvalidAGWError."""
	client, _ = create_mock_client()

	header = AGWHeader(
		port=0,
		datakind="",  # Invalid
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=0,
		user_reserved=0,
	)
	frame = AGWFrame(header=header, data=b"")

	with pytest.raises(InvalidAGWError, match="datakind must be a single ASCII character"):
		client.send_frame(frame)


def test_send_frame_invalid_datakind_multi_char_raises() -> None:
	"""Test that multi-character datakind raises InvalidAGWError."""
	client, _ = create_mock_client()

	header = AGWHeader(
		port=0,
		datakind="DD",  # Invalid
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=0,
		user_reserved=0,
	)
	frame = AGWFrame(header=header, data=b"")

	with pytest.raises(InvalidAGWError, match="datakind must be a single ASCII character"):
		client.send_frame(frame)


def test_send_frame_invalid_datakind_non_ascii_raises() -> None:
	"""Test that non-ASCII datakind raises InvalidAGWError."""
	client, _ = create_mock_client()

	header = AGWHeader(
		port=0,
		datakind="\xff",  # Non-ASCII
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=0,
		user_reserved=0,
	)
	frame = AGWFrame(header=header, data=b"")

	with pytest.raises(InvalidAGWError, match="datakind must be a single ASCII character"):
		client.send_frame(frame)


# ============================================================================
# AGWClient.send_command() validation tests
# ============================================================================


def test_send_command_valid() -> None:
	"""Test sending a valid command."""
	client, mock_sock = create_mock_client()
	client.send_command("D", call_from="W1AW", call_to="K9JRR", data=b"test")

	sent = mock_sock.sent_data.getvalue()
	assert len(sent) == _HEADER_STRUCT.size + 4


def test_send_command_invalid_port_raises() -> None:
	"""Test that invalid port raises InvalidAGWError."""
	client, _ = create_mock_client()

	with pytest.raises(InvalidAGWError, match=r"port must be in range 0\..*255"):
		client.send_command("D", port=256)


def test_send_command_invalid_pid_raises() -> None:
	"""Test that invalid PID raises InvalidAGWError."""
	client, _ = create_mock_client()

	with pytest.raises(InvalidAGWError, match=r"pid must be in range 0\..*255"):
		client.send_command("D", pid=256)


def test_send_command_invalid_datakind_raises() -> None:
	"""Test that invalid datakind raises InvalidAGWError."""
	client, _ = create_mock_client()

	with pytest.raises(InvalidAGWError, match="datakind must be a single ASCII character"):
		client.send_command("", data=b"")  # Empty datakind


def test_send_command_empty_payload() -> None:
	"""Test that empty payload raises InvalidAGWError."""
	client, _ = create_mock_client()

	with pytest.raises(InvalidAGWError, match="connected payload cannot be empty"):
		client.send_connected_data("W1AW", "K9JRR", b"")


# ============================================================================
# AGWClient.recv_frame() validation tests
# ============================================================================


class MockRecvSocket:
	"""Mock socket that simulates receiving AGW frames."""

	def __init__(self, data: bytes) -> None:
		self.data = BytesIO(data)

	def recv(self, size: int) -> bytes:
		chunk = self.data.read(size)
		if not chunk and size > 0:
			return b""  # Connection closed
		return chunk

	def close(self) -> None:
		pass


def test_recv_frame_valid() -> None:
	"""Test receiving a valid frame."""
	# Build a valid AGW frame
	header = AGWHeader(
		port=0,
		datakind="D",
		pid=0xF0,
		call_from="W1AW",
		call_to="K9JRR",
		data_len=5,
		user_reserved=0,
	)
	frame_to_send = AGWFrame(header=header, data=b"Hello")

	client, mock_sock = create_mock_client()
	client.send_frame(frame_to_send)

	# Now receive it
	recv_client = AGWClient(cast(socket.socket, MockRecvSocket(mock_sock.sent_data.getvalue())))
	received = recv_client.recv_frame()

	assert received.header.datakind == "D"
	assert received.header.call_from == "W1AW"
	assert received.header.call_to == "K9JRR"
	assert received.data == b"Hello"


def test_recv_frame_oversized_payload_raises() -> None:
	"""Test that oversized payload length raises InvalidAGWError."""
	# Create a header with an absurdly large payload size
	raw_header = _HEADER_STRUCT.pack(
		0,  # port
		0,  # reserved1
		0,  # reserved2
		0,  # reserved3
		ord("D"),  # datakind
		0,  # reserved4
		0xF0,  # pid
		0,  # reserved5
		b"W1AW\x00\x00\x00\x00\x00\x00",  # call_from
		b"K9JRR\x00\x00\x00\x00\x00",  # call_to
		0x7FFFFFFF + 1,  # data_len - oversized
		0,  # user_reserved
	)

	client = AGWClient(cast(socket.socket, MockRecvSocket(raw_header)))
	with pytest.raises(InvalidAGWError, match="exceeds maximum"):
		client.recv_frame()


def test_recv_frame_empty_data() -> None:
	"""Test receiving a frame with empty payload."""
	header = AGWHeader(
		port=0,
		datakind="R",
		pid=0,
		call_from="",
		call_to="",
		data_len=0,
		user_reserved=0,
	)
	frame_to_send = AGWFrame(header=header, data=b"")

	client, mock_sock = create_mock_client()
	client.send_frame(frame_to_send)

	recv_client = AGWClient(cast(socket.socket, MockRecvSocket(mock_sock.sent_data.getvalue())))
	received = recv_client.recv_frame()

	assert received.data == b""


# ============================================================================
# Edge case and integration tests
# ============================================================================


def test_round_trip_frame_with_special_chars() -> None:
	"""Test round-trip frame serialization with special characters."""
	header = AGWHeader(
		port=1,
		datakind="D",
		pid=0xF0,
		call_from="AB-15",
		call_to="CD-9",
		data_len=11,
		user_reserved=42,
	)
	data = b"Test\x00\xff\xab\xcd\x12\x34\x56"
	frame = AGWFrame(header=header, data=data)

	client, mock_sock = create_mock_client()
	client.send_frame(frame)

	recv_client = AGWClient(cast(socket.socket, MockRecvSocket(mock_sock.sent_data.getvalue())))
	received = recv_client.recv_frame()

	assert received.header.port == 1
	assert received.header.datakind == "D"
	assert received.header.pid == 0xF0
	assert received.header.call_from == "AB-15"
	assert received.header.call_to == "CD-9"
	assert received.header.user_reserved == 42
	assert received.data == data


def test_register_callsign_sends_normalized() -> None:
	"""Test that register_callsign normalizes the callsign."""
	client, mock_sock = create_mock_client()
	client.register_callsign("w1aw-5", channel=0)

	# Verify the sent data contains normalized callsign
	sent = mock_sock.sent_data.getvalue()
	assert len(sent) == _HEADER_STRUCT.size

	# Extract and verify the call_from field
	unpacked = _HEADER_STRUCT.unpack(sent)
	call_from_raw = unpacked[8]  # call_from is at index 8
	call_from = _decode_call(call_from_raw)
	assert call_from == "W1AW-5"


def test_all_valid_datakind_chars() -> None:
	"""Test that all common datakind characters are accepted."""
	client, _ = create_mock_client()
	for char in "RGXCDPGM":  # Common datakind values
		client.send_command(char)  # Should not raise


def test_port_boundary_values() -> None:
	"""Test port boundary values (0 and 255)."""
	client, _ = create_mock_client()

	# Port 0 should work
	client.send_command("D", port=0)

	# Port 255 should work
	client.send_command("D", port=255)

	# Port -1 and 256 should fail (tested earlier, but explicit here)
	with pytest.raises(InvalidAGWError):
		client.send_command("D", port=-1)

	with pytest.raises(InvalidAGWError):
		client.send_command("D", port=256)


def test_pid_boundary_values() -> None:
	"""Test PID boundary values (0 and 255)."""
	client, _ = create_mock_client()

	# PID 0 should work
	client.send_command("D", pid=0)

	# PID 255 should work
	client.send_command("D", pid=255)

	# PID -1 and 256 should fail
	with pytest.raises(InvalidAGWError):
		client.send_command("D", pid=-1)

	with pytest.raises(InvalidAGWError):
		client.send_command("D", pid=256)
