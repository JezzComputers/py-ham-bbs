"""Direwolf KISS helpers and stream handling utilities."""

import os
import socket
import time
from typing import Final

from .ax25 import AX25FrameBuilder, InvalidAX25Error
from .kiss import FEND, InvalidKISSError, KISSFrameBuilder, KISSFrameConfig
from .terminal import BLUE, CYAN, GREEN, MAGENTA, RESET

DEFAULT_KISS_HOST: Final[str] = os.getenv("DIREWOLF_HOST", "127.0.0.1")
DEFAULT_KISS_PORT: Final[int] = int(os.getenv("DIREWOLF_PORT", "8001"))
MIN_KISS_FRAME_LEN: Final[int] = 3
MIN_KISS_AX25_LEN: Final[int] = 19
KISS_CONNECT_RETRIES: Final[int] = 3
KISS_CONNECT_RETRY_DELAY: Final[float] = 0.5  # seconds


class KISSStreamDecoder:
	"""Incrementally splits a KISS byte stream into complete frames."""

	__slots__ = ("_buffer",)

	def __init__(self) -> None:
		self._buffer = bytearray()

	def feed(self, data: bytes) -> list[bytes]:
		if data:
			self._buffer.extend(data)

		frames: list[bytes] = []
		while True:
			try:
				start = self._buffer.index(FEND)
			except ValueError:
				self._buffer.clear()
				break

			if start > 0:
				del self._buffer[:start]

			try:
				end: int = self._buffer.index(FEND, 1)
			except ValueError:
				break

			frame = bytes(self._buffer[: end + 1])
			del self._buffer[: end + 1]

			if len(frame) > MIN_KISS_FRAME_LEN:
				frames.append(frame)

		return frames


class DirewolfKISSClient:
	"""A simple client for sending KISS frames to a Direwolf instance over TCP."""

	__slots__ = ("_host", "_port", "_socket")

	def __init__(self, host: str = DEFAULT_KISS_HOST, port: int = DEFAULT_KISS_PORT) -> None:
		self._host: str = host
		self._port: int = port
		self._socket = None

	@property
	def host(self) -> str:
		return self._host

	@property
	def port(self) -> int:
		return self._port

	def connect(self) -> None:
		if self._socket is not None:
			return
		self._socket = kiss_connect(self._host, self._port)

	def close(self) -> None:
		if self._socket is None:
			return
		self._socket.close()
		self._socket = None

	def send_kiss_frame(self, kiss_frame: bytes) -> None:
		if self._socket is None:
			self.connect()
		if self._socket is None:
			raise OSError("Direwolf KISS socket not connected")
		self._socket.sendall(kiss_frame)


def kiss_connect(host: str = DEFAULT_KISS_HOST, port: int = DEFAULT_KISS_PORT) -> socket.socket:
	last_exc: OSError | None = None
	for attempt in range(1, KISS_CONNECT_RETRIES + 1):
		try:
			s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			s.connect((host, port))
			return s
		except OSError as exc:
			last_exc = exc
			if attempt < KISS_CONNECT_RETRIES:
				time.sleep(KISS_CONNECT_RETRY_DELAY)
	assert last_exc is not None
	raise last_exc


def validate_kiss_payload(payload: bytes) -> bytes:
	"""Validate a KISS/AX.25 payload and return the validated bytes.

	Raises:
		ValueError: when payload is missing or malformed.
		InvalidKISSError: when the KISS frame is malformed.
		InvalidAX25Error: when the AX.25 frame is malformed.
	"""

	payload = bytes(payload)
	if payload == b"":
		raise ValueError("payload cannot be empty")
	if len(payload) < MIN_KISS_AX25_LEN:
		raise ValueError("payload length must be at least 19 bytes (to accommodate minimal KISS/AX.25 frame)")
	if payload[0] != FEND or payload[-1] != FEND:
		raise ValueError("payload must include leading and trailing C0 (FEND) bytes")

	ax25_frame = KISSFrameBuilder(KISSFrameConfig()).decode_kiss_frame(payload)
	AX25FrameBuilder.decode_ax25_frame(ax25_frame)
	return payload


def send_frame(sock: socket.socket, text: str, ax25_builder: AX25FrameBuilder, kiss_builder: KISSFrameBuilder) -> None:
	"""Build a KISS frame from `text` then add AX.25 and send it to Direwolf."""

	payload: bytes = text.encode("utf-8")
	frame: bytes = ax25_builder.build_ax25_frame(payload)
	kiss_frame: bytes = kiss_builder.build_kiss_frame(frame)
	sock.sendall(kiss_frame)
	print(f"{GREEN}[TX]{RESET} {text}")


def listener(sock: socket.socket, kiss_builder: KISSFrameBuilder, ax25_builder: AX25FrameBuilder) -> None:
	decoder = KISSStreamDecoder()

	while True:
		try:
			chunk = sock.recv(4096)
			if not chunk:
				print(f"{MAGENTA}RX socket closed{RESET}")
				break

			print(f"\n{CYAN}[RX RAW]{RESET} {chunk.hex()}")
			for frame in decoder.feed(chunk):
				print(f"{BLUE}[KISS FRAME]{RESET} {frame.hex()}")

				try:
					ax25_frame: bytes = kiss_builder.decode_kiss_frame(bytes(frame))
					res: tuple[str, str, str] = ax25_builder.decode_ax25_frame(ax25_frame)

				except InvalidKISSError as e:
					print(f"{MAGENTA}[DECODED]{RESET} <invalid KISS frame: {e}>")
					continue

				except InvalidAX25Error as e:
					print(f"{MAGENTA}[DECODED]{RESET} <invalid AX.25 frame: {e}>")
					continue

				else:
					dest, src, text = res
					print(f"{BLUE}[DECODED]{RESET} {src} -> {dest} : {text}")

			print(">>> ", end="", flush=True)

		except OSError as e:
			print(f"{MAGENTA}RX error:{RESET} {e}")
			break
