class InvalidKISSError(ValueError):
	"""Raised when a KISS frame is invalid or uses an unsupported command."""


# KISS protocol magic bytes
FEND: int = 0xC0  # Frame End (frame delimiter)
FESC: int = 0xDB  # Frame Escape
TFEND: int = 0xDC  # Transposed FEND
TFESC: int = 0xDD  # Transposed FESC

# Prebuilt escape sequences
_ESC_TFEND: bytes = bytes([FESC, TFEND])
_ESC_TFESC: bytes = bytes([FESC, TFESC])


class KISSFrameConfig:
	def __init__(self, kiss_command: int) -> None:
		if not (0 <= kiss_command <= 0xFF):
			raise InvalidKISSError("KISS command must be exactly 1 byte")
		self._kiss_command: int = kiss_command

	@property
	def kiss_command(self) -> int:
		return self._kiss_command

	@kiss_command.setter
	def kiss_command(self, value: int) -> None:
		if not (0 <= value <= 0xFF):
			raise InvalidKISSError("KISS command must be exactly 1 byte")
		self._kiss_command = value


class KISSFrameBuilder:
	def __init__(self, config: KISSFrameConfig) -> None:
		self._config: KISSFrameConfig = config

	def build_kiss_frame(self, ax25_frame: bytes) -> bytes:
		"""Takes AX.25 frame and adds KISS framing and escapes"""
		out: bytearray = bytearray([FEND, self._config.kiss_command])
		for b in ax25_frame:
			if b == FESC:
				out.extend(_ESC_TFESC)
			elif b == FEND:
				out.extend(_ESC_TFEND)
			else:
				out.append(b)
		out.append(FEND)
		return bytes(out)

	def decode_kiss_frame(self, kiss_frame: bytes) -> bytes:
		"""Remove KISS framing and unescape. Raises InvalidKISSError on invalid input."""
		if len(kiss_frame) < 3 or kiss_frame[0] != FEND or kiss_frame[-1] != FEND:
			raise InvalidKISSError(f"Invalid KISS frame: {kiss_frame.hex()}")

		# decode port/command: high nibble = port, low nibble = command
		cmd_byte: int = kiss_frame[1]
		port: int = (cmd_byte >> 4) & 0x0F
		command: int = cmd_byte & 0x0F
		if command != 0x00:
			raise InvalidKISSError(f"Unsupported KISS command byte: {cmd_byte:02X} (port={port}, cmd={command})")

		kiss_payload: bytes = kiss_frame[2:-1]

		# Unescape KISS payload to recover raw AX.25 frame
		ax_array: bytearray = bytearray()
		i = 0
		length: int = len(kiss_payload)
		while i < length:
			b: int = kiss_payload[i]
			if b == FESC and i + 1 < length:
				nxt: int = kiss_payload[i + 1]
				if nxt == TFEND:
					ax_array.append(FEND)
					i += 2
					continue
				if nxt == TFESC:
					ax_array.append(FESC)
					i += 2
					continue
				ax_array.append(b)
				i += 1
			else:
				ax_array.append(b)
				i += 1
		return bytes(ax_array)
