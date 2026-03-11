from lib.ax25 import kiss_unescape, AX25Config, AX25FrameBuilder


def test_kiss_unescape_escaped_fend() -> None:
	# FESC+TFEND (\xdb\xdc) should unescape to FEND (\xc0)
	assert kiss_unescape(b"\xdb\xdc") == b"\xc0"


def test_kiss_unescape_escaped_fesc() -> None:
	# FESC+TFESC (\xdb\xdd) should unescape to FESC (\xdb)
	assert kiss_unescape(b"\xdb\xdd") == b"\xdb"


def test_kiss_unescape_no_escape() -> None:
	# Data with no escape sequences should pass through unchanged
	assert kiss_unescape(b"hello") == b"hello"


def test_kiss_unescape_mixed() -> None:
	# A mix of escape sequences and plain data
	result = kiss_unescape(b"\xdb\xdc" + b"abc" + b"\xdb\xdd")
	assert result == b"\xc0" + b"abc" + b"\xdb"


def test_kiss_unescape_escaped_fesc_then_literal_dc() -> None:
	# Regression: escaped FESC (\xdb\xdd) followed by a literal 0xDC
	# should decode to FESC (\xdb) then 0xDC.
	assert kiss_unescape(b"\xdb\xdd\xdc") == b"\xdb\xdc"


def test_decode_full_payload_not_truncated() -> None:
	# Build a KISS frame and verify that decode returns the full payload without
	# stripping the last 2 bytes (which were incorrectly assumed to be FCS).
	config = AX25Config("W1AW", 0, "K9JRR", 0)
	builder = AX25FrameBuilder(config)
	payload = b"Hello, World!"
	ax25_frame = builder.build_ax25_frame(payload)
	kiss_frame = builder.build_kiss_frame(ax25_frame)

	res = builder.decode(kiss_frame)
	assert res is not None
	dest, src, text = res

	assert dest == "W1AW-0"
	assert src == "K9JRR-0"
	assert text == "Hello, World!"


def test_decode_short_payload_not_truncated() -> None:
	# Verify that a short payload (where slicing -2 would drop real data) is preserved.
	config = AX25Config("W1AW", 0, "K9JRR", 0)
	builder = AX25FrameBuilder(config)
	payload = b"Hi"
	ax25_frame = builder.build_ax25_frame(payload)
	kiss_frame = builder.build_kiss_frame(ax25_frame)

	res = builder.decode(kiss_frame)
	assert res is not None
	dest, src, text = res

	assert dest == "W1AW-0"
	assert src == "K9JRR-0"
	assert text == "Hi"
