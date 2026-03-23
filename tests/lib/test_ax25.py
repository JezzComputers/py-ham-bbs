import pytest

from lib.ax25 import AX25FrameBuilder, AX25FrameConfig
from lib.kiss import InvalidKISSError, KISSFrameBuilder, KISSFrameConfig
from lib.terminal import use_color

use_color()


def test_decode_full_payload_not_truncated() -> None:
	"""Build a KISS frame and verify that decode returns the full payload without
	stripping the last 2 bytes (which were incorrectly assumed to be FCS)."""
	ax25_config = AX25FrameConfig("W1AW", 0, "K9JRR", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)
	payload = b"Hello, World!"
	ax25_frame = ax25_builder.build_ax25_frame(payload)
	kiss_frame = kiss_builder.build_kiss_frame(ax25_frame)

	res = kiss_builder.decode_kiss_frame(kiss_frame)
	assert res is not None
	parsed = ax25_builder.decode_ax25_frame(res)
	assert parsed is not None
	dest, src, text = parsed

	assert dest == "W1AW-0"
	assert src == "K9JRR-0"
	assert text == "Hello, World!"


def test_decode_short_payload_not_truncated() -> None:
	"""Verify that a short payload (where slicing -2 would drop real data) is preserved."""
	ax25_config = AX25FrameConfig("W1AW", 0, "K9JRR", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)
	payload = b"Hi"
	ax25_frame = ax25_builder.build_ax25_frame(payload)
	kiss_frame = kiss_builder.build_kiss_frame(ax25_frame)

	res = kiss_builder.decode_kiss_frame(kiss_frame)
	assert res is not None
	parsed = ax25_builder.decode_ax25_frame(res)
	assert parsed is not None
	dest, src, text = parsed

	assert dest == "W1AW-0"
	assert src == "K9JRR-0"
	assert text == "Hi"


def test_build_kiss_frame_escapes_special_bytes() -> None:
	"""Payload includes bytes that must be escaped in KISS: 0xC0 (FEND) and 0xDB (FESC)."""
	ax25_config = AX25FrameConfig("W1AW", 0, "K9JRR", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)
	payload = b"\xc0ABC\xdb"
	ax25_frame = ax25_builder.build_ax25_frame(payload)
	kiss_frame = kiss_builder.build_kiss_frame(ax25_frame)

	# KISS frame should start and end with 0xC0 (FEND).
	assert kiss_frame[0] == 0xC0
	assert kiss_frame[-1] == 0xC0

	# Between the FEND markers, the payload bytes 0xC0 and 0xDB must be escaped.
	inner = kiss_frame[1:-1]

	# Command/port byte is the first byte of the inner frame; payload follows.
	command_and_payload = inner[1:]

	# No raw 0xC0 should appear in the escaped payload, and any 0xDB must be part of a
	# valid 2-byte escape sequence (0xDC or 0xDD).
	assert 0xC0 not in command_and_payload
	i = 0
	while i < len(command_and_payload):
		if command_and_payload[i] == 0xDB:
			# 0xDB must introduce a valid escape sequence and not be the last byte.
			assert i + 1 < len(command_and_payload)
			assert command_and_payload[i + 1] in (0xDC, 0xDD)
			i += 2
		else:
			i += 1

	# Escaped sequences for 0xC0 and 0xDB should be present.
	assert b"\xdb\xdc" in command_and_payload  # Escaped 0xC0
	assert b"\xdb\xdd" in command_and_payload  # Escaped 0xDB


def test_kiss_round_trip_with_escaped_bytes() -> None:
	"""Verify that bytes requiring KISS escaping survive a full encode/decode round trip."""
	ax25_config = AX25FrameConfig("W1AW", 0, "K9JRR", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)
	payload = b"\xc0ABC\xdb"
	ax25_frame = ax25_builder.build_ax25_frame(payload)
	kiss_frame = kiss_builder.build_kiss_frame(ax25_frame)

	res = kiss_builder.decode_kiss_frame(kiss_frame)
	assert res is not None
	parsed = ax25_builder.decode_ax25_frame(res)
	assert parsed is not None
	dest, src, text = parsed

	assert dest == "W1AW-0"
	assert src == "K9JRR-0"
	# decode() uses UTF-8 with errors="replace", so compute the expected text accordingly.
	assert text == payload.decode("utf-8", "replace")


def test_decode_kiss_dangling_fesc_does_not_crash() -> None:
	"""Construct a KISS frame where the payload ends with a dangling 0xDB (FESC) byte.
	This exercises the unescape logic's handling of an unterminated escape sequence."""
	ax25_config = AX25FrameConfig("W1AW", 0, "K9JRR", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)

	# KISS frame: 0xC0, command=0x00, data=[0xDB], 0xC0
	kiss_frame = bytes([0xC0, 0x00, 0xDB, 0xC0])

	res = kiss_builder.decode_kiss_frame(kiss_frame)
	# Decoder should not raise on malformed escape sequences; raw AX.25 should be returned
	# but later AX.25 parsing will reject this as not a valid frame.
	assert res is not None
	assert ax25_builder.decode_ax25_frame(res) is None


def test_decode_kiss_nonstandard_escape_sequence_does_not_crash() -> None:
	"""Construct a KISS frame containing a non-standard escape sequence: 0xDB followed
	by a byte other than 0xDC or 0xDD. This ensures the byte-walking loop in the
	unescape logic correctly handles unknown escape codes."""
	ax25_config = AX25FrameConfig("W1AW", 0, "K9JRR", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)

	# KISS frame: 0xC0, command=0x00, data=[0xDB, 0x00], 0xC0
	kiss_frame = bytes([0xC0, 0x00, 0xDB, 0x00, 0xC0])

	res = kiss_builder.decode_kiss_frame(kiss_frame)
	# As with the dangling FESC case, decoder should be robust; raw AX.25 is returned
	# but AX.25 parsing should reject it as invalid.
	assert res is not None
	assert ax25_builder.decode_ax25_frame(res) is None


def test_decode_handles_non_zero_kiss_command() -> None:
	"""Build a normal KISS frame, then modify the command byte to be non-zero and ensure
	that decode can handle it without raising and correctly rejects non-data commands."""
	ax25_config = AX25FrameConfig("W1AW", 0, "K9JRR", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)
	payload = b"OK"
	ax25_frame = ax25_builder.build_ax25_frame(payload)
	kiss_frame = kiss_builder.build_kiss_frame(ax25_frame)

	# KISS frame format: 0xC0, command byte, data..., 0xC0
	assert kiss_frame[0] == 0xC0
	assert kiss_frame[-1] == 0xC0

	# Change the command byte to a non-zero value (e.g., 0x10) while preserving payload.
	modified = bytearray(kiss_frame)
	modified[1] = 0x10
	kiss_frame_non_zero = bytes(modified)

	# Non-zero KISS command bytes indicate non-data frames; decoder now raises InvalidKISSError
	with pytest.raises(InvalidKISSError):
		kiss_builder.decode_kiss_frame(kiss_frame_non_zero)


def test_kiss_round_trip_with_compressed_payload() -> None:
	"""Use a highly repetitive and sufficiently large payload to encourage compression in
	build_ax25_frame(), then verify that decode() correctly reconstructs the original
	message after a full AX.25 + KISS round trip."""
	ax25_config = AX25FrameConfig("W1AW", 0, "K9JRR", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)
	# Large, repetitive payload should be attractive to typical compressors.
	payload = b"AJFKDSFJKSDJFKDJFSJWDFKJSKFDFHUIHSBDU" * 10000
	ax25_frame = ax25_builder.build_ax25_frame(payload)
	kiss_frame = kiss_builder.build_kiss_frame(ax25_frame)

	res = kiss_builder.decode_kiss_frame(kiss_frame)
	assert res is not None
	parsed = ax25_builder.decode_ax25_frame(res)
	assert parsed is not None
	dest, src, text = parsed

	assert dest == "W1AW-0"
	assert src == "K9JRR-0"
	# decode() uses UTF-8 with errors="replace"; ASCII payload should round-trip exactly.
	assert text == payload.decode("utf-8", "replace")
