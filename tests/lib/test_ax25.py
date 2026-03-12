from lib.ax25 import AX25Config, AX25FrameBuilder


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
