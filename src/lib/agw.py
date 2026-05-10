from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
import re
from typing import Final

from lib.ax25 import is_valid_callsign


DEFAULT_AGW_HOST: Final[str] = "127.0.0.1"
DEFAULT_AGW_PORT: Final[int] = 8000
DEFAULT_AGW_CHANNEL: Final[int] = 0
DEFAULT_AGW_PID: Final[int] = 0xF0

_CALL_RE: Final[re.Pattern[str]] = re.compile(r"^([A-Z0-9]{1,6})(?:-(\d{1,2}))?$", re.IGNORECASE)
_HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<BBBBBBBB10s10sII")


class InvalidAGWError(ValueError):
	"""Raised when AGW frame construction or parsing fails."""


@dataclass(slots=True, frozen=True)
class AGWHeader:
	port: int
	datakind: str
	pid: int
	call_from: str
	call_to: str
	data_len: int
	user_reserved: int


@dataclass(slots=True, frozen=True)
class AGWFrame:
	header: AGWHeader
	data: bytes


class AGWClient:
	"""Minimal AGWPE-compatible client for Dire Wolf."""

	def __init__(self, sock: socket.socket) -> None:
		self._sock = sock

	@classmethod
	def connect(cls, host: str = DEFAULT_AGW_HOST, port: int = DEFAULT_AGW_PORT, timeout: float = 10.0) -> AGWClient:
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			sock.settimeout(timeout)
			sock.connect((host, port))
			sock.settimeout(None)
			return cls(sock)
		except Exception:
			sock.close()
			raise

	def close(self) -> None:
		self._sock.close()

	def send_frame(self, frame: AGWFrame) -> None:
		header = frame.header
		if len(frame.data) != header.data_len:
			raise InvalidAGWError("frame data length does not match AGW header length")

		# Validate header fields before struct.pack() to ensure consistent errors
		if not (0 <= header.port <= 0xFF):
			raise InvalidAGWError("port must be in range 0..255")
		if not (0 <= header.pid <= 0xFF):
			raise InvalidAGWError("pid must be in range 0..255")
		if len(header.datakind) != 1 or ord(header.datakind) > 0x7F:
			raise InvalidAGWError("datakind must be a single ASCII character")

		raw_header = _HEADER_STRUCT.pack(
			header.port,
			0,
			0,
			0,
			ord(header.datakind),
			0,
			header.pid,
			0,
			_encode_call(header.call_from),
			_encode_call(header.call_to),
			header.data_len,
			header.user_reserved,
		)
		self._sock.sendall(raw_header + frame.data)

	def send_command(
		self,
		datakind: str,
		*,
		call_from: str = "",
		call_to: str = "",
		pid: int = 0,
		port: int = DEFAULT_AGW_CHANNEL,
		user_reserved: int = 0,
		data: bytes = b"",
	) -> None:
		datakind = _normalize_datakind(datakind)
		if not (0 <= port <= 0xFF):
			raise InvalidAGWError("port must be in range 0..255")
		if not (0 <= pid <= 0xFF):
			raise InvalidAGWError("pid must be in range 0..255")

		frame = AGWFrame(
			header=AGWHeader(
				port=port,
				datakind=datakind,
				pid=pid,
				call_from=call_from,
				call_to=call_to,
				data_len=len(data),
				user_reserved=user_reserved,
			),
			data=data,
		)
		self.send_frame(frame)

	def recv_frame(self) -> AGWFrame:
		raw_header = self._recv_exact(_HEADER_STRUCT.size)
		(
			port,
			_reserved1,
			_reserved2,
			_reserved3,
			datakind_byte,
			_reserved4,
			pid,
			_reserved5,
			call_from_raw,
			call_to_raw,
			data_len,
			user_reserved,
		) = _HEADER_STRUCT.unpack(raw_header)

		# Sanity check on payload size to avoid attempting to read/allocate
		# extremely large payloads from a malicious or buggy peer.
		max_payload_size = 0x7FFFFFFF  # 2GB (practical upper bound)
		if data_len > max_payload_size:
			raise InvalidAGWError(f"AGW data length {data_len} exceeds maximum {max_payload_size}")

		data = self._recv_exact(data_len)
		header = AGWHeader(
			port=port,
			datakind=chr(datakind_byte),
			pid=pid,
			call_from=_decode_call(call_from_raw),
			call_to=_decode_call(call_to_raw),
			data_len=data_len,
			user_reserved=user_reserved,
		)
		return AGWFrame(header=header, data=data)

	def request_version(self) -> None:
		self.send_command("R")

	def request_port_info(self) -> None:
		self.send_command("G")

	def register_callsign(self, call: str, *, channel: int = DEFAULT_AGW_CHANNEL) -> None:
		self.send_command("X", call_from=normalize_call(call), port=channel)

	def unregister_callsign(self, call: str, *, channel: int = DEFAULT_AGW_CHANNEL) -> None:
		self.send_command("x", call_from=normalize_call(call), port=channel)

	def connect_station(self, call_from: str, call_to: str, *, channel: int = DEFAULT_AGW_CHANNEL, pid: int = DEFAULT_AGW_PID) -> None:
		self.send_command("C", call_from=normalize_call(call_from), call_to=normalize_call(call_to), port=channel, pid=pid)

	def disconnect_station(self, call_from: str, call_to: str, *, channel: int = DEFAULT_AGW_CHANNEL) -> None:
		self.send_command("d", call_from=normalize_call(call_from), call_to=normalize_call(call_to), port=channel)

	def send_connected_data(self, call_from: str, call_to: str, payload: bytes, *, channel: int = DEFAULT_AGW_CHANNEL, pid: int = DEFAULT_AGW_PID) -> None:
		if payload == b"":
			raise InvalidAGWError("connected payload cannot be empty")
		self.send_command("D", call_from=normalize_call(call_from), call_to=normalize_call(call_to), port=channel, pid=pid, data=payload)

	def _recv_exact(self, size: int) -> bytes:
		if size == 0:
			return b""

		data = bytearray()
		while len(data) < size:
			chunk = self._sock.recv(size - len(data))
			if chunk == b"":
				raise ConnectionError("AGW socket closed")
			data.extend(chunk)
		return bytes(data)


def normalize_call(raw: str) -> str:
	"""Normalize CALL or CALL-SSID to upper case and validate."""

	match = _CALL_RE.fullmatch(raw.strip().upper())
	if match is None:
		raise InvalidAGWError("callsign must be CALL or CALL-SSID")

	call = match.group(1)
	ssid_raw = match.group(2)

	if not is_valid_callsign(call):
		raise InvalidAGWError("callsign body must be 1-6 A-Z or 0-9 characters")

	if ssid_raw is None:
		return call

	ssid = int(ssid_raw)
	if not (0 <= ssid <= 15):
		raise InvalidAGWError("SSID must be in range 0..15")

	return f"{call}-{ssid}"


def parse_port_info(data: bytes) -> list[str]:
	"""Parse AGW 'G' response text into a list of channel descriptions."""

	text = data.decode("ascii", errors="replace").strip("\x00")
	parts = [part.strip() for part in text.split(";") if part.strip()]
	if len(parts) <= 1:
		return []
	return parts[1:]


def _encode_call(value: str) -> bytes:
	if value == "":
		return b"\x00" * 10

	normalized = normalize_call(value)
	raw = normalized.encode("ascii")
	if len(raw) > 9:
		raise InvalidAGWError("AGW callsign field supports up to 9 visible characters")
	return raw.ljust(10, b"\x00")


def _decode_call(raw: bytes) -> str:
	return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _normalize_datakind(datakind: str) -> str:
	if len(datakind) != 1:
		raise InvalidAGWError("datakind must be a single ASCII character")
	if ord(datakind) > 0x7F:
		raise InvalidAGWError("datakind must be ASCII")
	return datakind
