import zlib


def ax25_call(callsign: str, ssid: int = 0, last: bool = False) -> bytes:
	"""Truncate to 6 chars then pad to ensure exactly 6-character callsign"""
	_callsign: str = callsign.upper()[:6].ljust(6)
	encoded: bytes = bytes([(ord(c) << 1) & 0xFE for c in _callsign])
	ssid_byte: int = 0x60 | ((ssid & 0x0F) << 1)
	if last:
		ssid_byte |= 0x01
	return encoded + bytes([ssid_byte])


def kiss_escape(data: bytes) -> bytes:
	out: bytearray = bytearray()
	for b in data:
		if b == 0xDB:
			out += b"\xdb\xdd"
		elif b == 0xC0:
			out += b"\xdb\xdc"
		else:
			out.append(b)
	return bytes(out)


def kiss_unescape(data: bytes) -> bytes:
	out: bytearray = bytearray()
	i = 0
	length: int = len(data)
	while i < length:
		b: int = data[i]
		if b == 0xDB and i + 1 < length:
			next: int = data[i + 1]
			if next == 0xDC:
				out.append(0xC0)
				i += 2
				continue
			if next == 0xDD:
				out.append(0xDB)
				i += 2
				continue
		out.append(b)
		i += 1
	return bytes(out)


def parse_ax25_addresses(frame: bytes) -> tuple[list[bytes], int]:
	addresses: list[bytes] = []
	idx = 0
	while True:
		if idx + 7 > len(frame):
			raise ValueError("truncated AX.25 address field")
		addr: bytes = frame[idx : idx + 7]
		addresses.append(addr)
		idx += 7
		if addr[6] & 0x01:
			break
	return addresses, idx


def decode_call(raw: bytes) -> str:
	call: str = "".join(chr(b >> 1) for b in raw[:6]).strip()
	ssid: int = (raw[6] >> 1) & 0x0F
	return f"{call}-{ssid}"


class AX25Config:
	def __init__(
		self,
		dest_call: str,
		dest_ssid: int,
		src_call: str,
		src_ssid: int,
	) -> None:
		self.dest_call: str = dest_call
		self.dest_ssid: int = dest_ssid
		self.src_call: str = src_call
		self.src_ssid: int = src_ssid
		self._dest_frame: bytes = ax25_call(self.dest_call, self.dest_ssid)
		self._src_frame: bytes = ax25_call(self.src_call, self.src_ssid, last=True)

	@property
	def dest_frame(self) -> bytes:
		return self._dest_frame

	@property
	def src_frame(self) -> bytes:
		return self._src_frame


class AX25FrameBuilder:
	def __init__(
		self,
		config: AX25Config,
		control: bytes = b"\x03",
		pid: bytes = b"\x01",
	) -> None:
		"""Build AX.25 frames.

		Defaults: CONTROL = 0x03 (UI), PID = 0x01 (unstructured).
		"""
		self.config: AX25Config = config
		self.control: bytes = control
		self.pid: bytes = pid

	def build_ax25_frame(self, payload: bytes) -> bytes:
		compressed = zlib.compress(payload, level=9, wbits=15)
		if len(compressed) < len(payload):
			frame = self.config.dest_frame + self.config.src_frame + self.control + self.pid + compressed
			print(f"Compressed AX25 frame: {frame.hex()}")
		else:
			frame = self.config.dest_frame + self.config.src_frame + self.control + self.pid + payload
			print(f"Not compressed AX25 frame: {frame.hex()}")
		return frame

	def build_kiss_frame(self, ax25_frame: bytes) -> bytes:
		"""Build a KISS-framed byte sequence for the given AX.25 frame.

		Note: the TNC (Direwolf) appends the 2-byte FCS on-air, so this
		function does not append an FCS. Keep framing simple and let the
		TNC handle FCS.
		"""
		return b"\xc0\x00" + kiss_escape(ax25_frame) + b"\xc0"

	def decode(self, frame_bytes: bytes) -> tuple[str, str, str] | None:
		try:
			if not frame_bytes:
				return None

			# If KISS framing (FEND 0xC0) is present, extract the first
			# non-empty chunk between FEND bytes. This handles multiple
			# concatenated frames more robustly than stripping all FENDs.
			ax_frame: bytes = frame_bytes
			if 0xC0 in ax_frame:
				chunks: list[bytes] = ax_frame.split(b"\xc0")
				# Pick the first non-empty chunk (if any)
				ax_frame = next((c for c in chunks if c), b"")

			# Remove optional KISS command byte (0x00) if present
			if ax_frame and ax_frame[0] == 0x00:
				ax_frame = ax_frame[1:]

			# Unescape KISS special sequences
			ax_frame = kiss_unescape(ax_frame)

			# Minimal AX.25 length: two 7-byte addresses + CONTROL + PID = 16
			if len(ax_frame) < 16:
				return None

			try:
				addresses, idx = parse_ax25_addresses(ax_frame)
			except ValueError:
				return None
			if len(addresses) < 2:
				return None
			dest_raw: bytes = addresses[0]
			src_raw: bytes = addresses[1]
			# Require at least CONTROL and PID bytes after the addresses.
			if len(ax_frame) < idx + 2:
				return None
			payload: bytes = ax_frame[idx + 2 :]

			try:
				payload_data: bytes = zlib.decompress(payload)
				print("zlib detected, decompressing")
			except zlib.error:
				payload_data = payload
				print("zlib not detected, not decompressing")

			dest: str = decode_call(dest_raw)
			src: str = decode_call(src_raw)

			try:
				text: str = payload_data.decode("utf-8", errors="replace")
			except Exception:
				text = "<non-text payload>"

			return dest, src, text
		except Exception:
			return None
