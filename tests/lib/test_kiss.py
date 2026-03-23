import pytest

from lib.kiss import InvalidKISSError, KISSFrameBuilder, KISSFrameConfig


def test_kiss_config_invalid_value_raises() -> None:
	with pytest.raises(InvalidKISSError):
		KISSFrameConfig(-1)
	with pytest.raises(InvalidKISSError):
		KISSFrameConfig(0x1FF)


def test_kiss_config_setter_invalid_raises() -> None:
	cfg = KISSFrameConfig(0x00)
	with pytest.raises(InvalidKISSError):
		cfg.kiss_command = -5
	with pytest.raises(InvalidKISSError):
		cfg.kiss_command = 0x100


def test_build_kiss_frame_basic_framing_and_command() -> None:
	cfg = KISSFrameConfig(0x00)
	builder = KISSFrameBuilder(cfg)
	ax25 = b"ABC"
	kiss = builder.build_kiss_frame(ax25)

	# Frame begins and ends with FEND (0xC0) and contains the command byte.
	assert kiss[0] == 0xC0
	assert kiss[-1] == 0xC0
	assert kiss[1] == 0x00

	# Payload (after command byte) should equal original when no escaping required.
	assert kiss[2:-1] == ax25


def test_build_kiss_frame_escapes_special_bytes() -> None:
	cfg = KISSFrameConfig(0x00)
	builder = KISSFrameBuilder(cfg)

	# AX.25 payload contains FEND (0xC0) then FESC (0xDB) then a normal byte.
	ax25 = bytes([0xC0, 0xDB, 0x01])
	kiss = builder.build_kiss_frame(ax25)
	inner = kiss[1:-1]
	payload = inner[1:]

	# Expect escaped sequences for 0xC0 -> DB DC, and 0xDB -> DB DD
	assert b"\xdb\xdc" in payload
	assert b"\xdb\xdd" in payload


def test_decode_kiss_frame_unescapes_and_returns_original() -> None:
	cfg = KISSFrameConfig(0x00)
	builder = KISSFrameBuilder(cfg)

	ax25 = bytes([0xC0, 0xDB, 0x55, 0x00])
	kiss = builder.build_kiss_frame(ax25)

	decoded = builder.decode_kiss_frame(kiss)
	assert decoded == ax25


def test_decode_invalid_frames_raise() -> None:
	cfg = KISSFrameConfig(0x00)
	builder = KISSFrameBuilder(cfg)

	# Too short
	with pytest.raises(InvalidKISSError):
		builder.decode_kiss_frame(b"")

	# Missing starting FEND
	with pytest.raises(InvalidKISSError):
		builder.decode_kiss_frame(bytes([0x00, 0x00, 0xC0]))

	# Missing ending FEND
	with pytest.raises(InvalidKISSError):
		builder.decode_kiss_frame(bytes([0xC0, 0x00, 0x00]))


def test_decode_nonzero_command_raises() -> None:
	cfg = KISSFrameConfig(0x00)
	builder = KISSFrameBuilder(cfg)

	ax25 = b"OK"
	kiss = bytearray(builder.build_kiss_frame(ax25))
	# Set command byte to non-zero
	kiss[1] = 0x10

	with pytest.raises(InvalidKISSError):
		builder.decode_kiss_frame(bytes(kiss))


def test_round_trip_build_then_decode() -> None:
	cfg = KISSFrameConfig(0x00)
	builder = KISSFrameBuilder(cfg)

	ax25 = b"Hello, KISS!\xc0\xdb"
	kiss = builder.build_kiss_frame(ax25)
	decoded = builder.decode_kiss_frame(kiss)

	assert decoded == ax25
