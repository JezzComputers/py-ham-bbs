import re
import zlib


class InvalidAX25Error(ValueError):
	"""Raised when an AX.25 frame is structurally invalid or truncated."""


def is_valid_callsign(call: str) -> bool:
	# AX.25 address field: 1-6 uppercase letters/digits (SSID is separate)
	return call.isascii() and bool(re.fullmatch(r"[A-Z0-9]{1,6}", call, re.IGNORECASE))


def ax25_call(callsign: str, ssid: int = 0, last: bool = False) -> bytes:
	"""Truncate to 6 chars then pad to ensure exactly 6-character callsign"""
	_callsign: str = callsign.upper()[:6].ljust(6)
	encoded: bytes = bytes([(ord(c) << 1) & 0xFE for c in _callsign])
	ssid_byte: int = 0x60 | ((ssid & 0x0F) << 1)
	if last:
		ssid_byte |= 0x01
	return encoded + bytes([ssid_byte])


def decode_call(raw: bytes) -> str:
	call: str = "".join(chr(b >> 1) for b in raw[:6]).strip()
	ssid: int = (raw[6] >> 1) & 0x0F
	return f"{call}-{ssid}"


def parse_ax25_addresses(frame: bytes) -> tuple[list[bytes], int]:
	addresses: list[bytes] = []
	idx = 0
	while True:
		if idx + 7 > len(frame):
			raise InvalidAX25Error("truncated AX.25 address field")
		addr: bytes = frame[idx : idx + 7]
		addresses.append(addr)
		idx += 7
		if addr[6] & 0x01:
			break
	return addresses, idx


class AX25FrameConfig:
	"""
	Represents the configuration for an AX.25 frame, managing destination
	and source callsigns and SSIDs, and providing their encoded frame
	representations as bytes.
	"""

	def __init__(self, dest_call: str, dest_ssid: int, src_call: str, src_ssid: int) -> None:
		self._dest_call: str = dest_call.upper()
		self._dest_ssid: int = dest_ssid
		self._src_call: str = src_call.upper()
		self._src_ssid: int = src_ssid
		self._dest_frame: bytes = ax25_call(self._dest_call, self._dest_ssid)
		self._src_frame: bytes = ax25_call(self._src_call, self._src_ssid, last=True)

	# Destination properties
	@property
	def dest_call(self) -> str:
		return self._dest_call

	@dest_call.setter
	def dest_call(self, value: str) -> None:
		self._dest_call = value.upper()
		self._dest_frame = ax25_call(self._dest_call, self._dest_ssid)

	@property
	def dest_ssid(self) -> int:
		return self._dest_ssid

	@dest_ssid.setter
	def dest_ssid(self, value: int) -> None:
		self._dest_ssid = value
		self._dest_frame = ax25_call(self._dest_call, self._dest_ssid)

	# Source properties
	@property
	def src_call(self) -> str:
		return self._src_call

	@src_call.setter
	def src_call(self, value: str) -> None:
		self._src_call = value.upper()
		self._src_frame = ax25_call(self._src_call, self._src_ssid, last=True)

	@property
	def src_ssid(self) -> int:
		return self._src_ssid

	@src_ssid.setter
	def src_ssid(self, value: int) -> None:
		self._src_ssid = value
		self._src_frame = ax25_call(self._src_call, self._src_ssid, last=True)

	# Encoded frames
	@property
	def dest_frame(self) -> bytes:
		return self._dest_frame

	@property
	def src_frame(self) -> bytes:
		return self._src_frame


class AX25FrameBuilder:
	"""
	Builds and decodes AX.25 protocol frames, automatically handling payload
	compression and extraction of source, destination, and message text from
	frames.
	"""

	def __init__(self, config: AX25FrameConfig, ax25_control: int = 0x03, ax25_pid: int = 0x01) -> None:
		self.config: AX25FrameConfig = config
		self.control: int = ax25_control
		self.pid: int = ax25_pid

	def build_ax25_frame(self, payload: bytes) -> bytes:
		compressed: bytes = zlib.compress(payload, level=9, wbits=15)
		return self.config.dest_frame + self.config.src_frame + bytes([self.control]) + bytes([self.pid]) + (compressed if len(compressed) < len(payload) else payload)

	def decode_ax25_frame(self, ax25_frame: bytes) -> tuple[str, str, str]:
		"""
		Decodes an AX.25 frame from bytes, extracting and returning the
		destination callsign, source callsign, and UTF-8 decoded payload text.
		Raises InvalidAX25Error if the frame is invalid or cannot be parsed.
		"""

		# Minimal AX.25 length: two 7-byte addresses + CONTROL + PID = 16
		if len(ax25_frame) < 16:
			raise InvalidAX25Error("truncated AX.25 frame")

		try:
			addresses, idx = parse_ax25_addresses(ax25_frame)
		except InvalidAX25Error as e:
			raise InvalidAX25Error("invalid AX.25 address field") from e

		if len(addresses) < 2:
			raise InvalidAX25Error("insufficient AX.25 addresses")

		# Require at least CONTROL and PID bytes after the addresses.
		if len(ax25_frame) < idx + 2:
			raise InvalidAX25Error("truncated AX.25 frame")

		dest: str = decode_call(addresses[0])
		src: str = decode_call(addresses[1])
		payload: bytes = ax25_frame[idx + 2 :]

		try:
			text: str = zlib.decompress(payload, wbits=15).decode(encoding="utf-8", errors="replace")
		except zlib.error:
			text: str = payload.decode(encoding="utf-8", errors="replace")

		return dest, src, text
