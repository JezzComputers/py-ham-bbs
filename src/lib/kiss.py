class InvalidKISSError(ValueError):
	"""Raised when a KISS frame is invalid or uses an unsupported command."""


class KISSFrameConfig:
	def __init__(self, kiss_command: bytes) -> None:
		self._kiss_command: bytes = kiss_command

	@property
	def kiss_command(self) -> bytes:
		return self._kiss_command

	@kiss_command.setter
	def kiss_command(self, value: bytes) -> None:
		self._kiss_command = value


class KISSFrameBuilder:
	def __init__(self, config: KISSFrameConfig) -> None:
		self._config: KISSFrameConfig = config

	def build_kiss_frame(self, ax25_frame: bytes) -> bytes:
		"""Takes AX.25 frame and adds KISS framing and escapes"""
		out: bytearray = bytearray(b"\xC0" + self._config.kiss_command)
		for b in ax25_frame:
			if b == 0xDB:
				out.extend(b"\xDB\xDD")
			elif b == 0xC0:
				out.extend(b"\xDB\xDC")
			else:
				out.append(b)
		out.append(0xC0)
		return bytes(out)

	def decode_kiss_frame(self, kiss_frame: bytes) -> bytes:
		"""Remove KISS framing and unescape. Raises InvalidKISSError on invalid input."""
		if len(kiss_frame) < 3 or kiss_frame[0] != 0xC0 or kiss_frame[-1] != 0xC0:
			if len(kiss_frame) > 1 and kiss_frame[1] != 0x00:
				raise InvalidKISSError(f"Unsupported KISS command byte: {kiss_frame[1]:02X}")
			raise InvalidKISSError(f"Invalid KISS frame: {kiss_frame.hex()}")

		kiss_payload: bytes = kiss_frame[2:-1]

		# Unescape KISS payload to recover raw AX.25 frame
		ax_array: bytearray = bytearray()
		i = 0
		length: int = len(kiss_payload)
		while i < length:
			b: int = kiss_payload[i]
			if b == 0xDB and i + 1 < length:
				nxt: int = kiss_payload[i + 1]
				if nxt == 0xDC:
					ax_array.append(0xC0)
					i += 2
					continue
				if nxt == 0xDD:
					ax_array.append(0xDB)
					i += 2
					continue
				ax_array.append(b)
				i += 1
			else:
				ax_array.append(b)
				i += 1
		return bytes(ax_array)
