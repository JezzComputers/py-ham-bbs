import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
import json
import logging
import os
from pathlib import Path
from platform import python_version_tuple
import re
import sqlite3
from typing import Any, Final, cast

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lib.ax25 import AX25FrameBuilder, AX25FrameConfig, InvalidAX25Error, is_valid_callsign
from lib.kiss import InvalidKISSError, KISSFrameBuilder, KISSFrameConfig

if int(python_version_tuple()[1]) < 14:
	from uuid6 import uuid7  # pyright: ignore[reportMissingImports, reportUnknownVariableType]  # ty:ignore[unresolved-import]
else:
	from uuid import uuid7  # ty:ignore[unresolved-import]


logger = logging.getLogger(__name__)

VALID_FRAME_TYPES: Final[set[str]] = {"message", "ack", "control", "error"}
VALID_ACK_REQUIRED_VALUES: Final[set[int]] = {0, 1, 2}
VALID_ACK_STATUS_VALUES: Final[set[str]] = {"received", "processed", "failed"}
CALLSIGN_WITH_SSID_RE: Final[re.Pattern[str]] = re.compile(r"^([A-Z0-9]{1,6})-(\d{1,2})$")
DEFAULT_SERVER_SOURCE: Final[str] = "SERVER-0"
DEFAULT_DB_PATH: Final[str] = "py_ham_bbs_protocol.db"


def resolve_timezone() -> tzinfo:
	try:
		return ZoneInfo("Australia/Melbourne")
	except ZoneInfoNotFoundError:
		logger.warning("Timezone Australia/Melbourne unavailable; falling back to UTC")
		return UTC


LOCAL_TIMEZONE: Final[tzinfo] = resolve_timezone()


@dataclass(slots=True)
class ParsedInboundFrame:
	frame_type: str
	source: str
	destination: str
	ack_required: int
	payload: str | dict[str, Any]
	client_msg_id: str | None
	original_id: str | None


@dataclass(slots=True)
class PendingAckState:
	origin_websocket: ServerConnection
	origin_source: str
	ack_required: int
	awaiting_sources: set[str]
	client_msg_id: str | None


class MessageStore:
	def __init__(self, db_path: Path) -> None:
		db_path.parent.mkdir(parents=True, exist_ok=True)
		self._connection = sqlite3.connect(db_path, check_same_thread=False)
		self._connection.row_factory = sqlite3.Row
		self._create_schema()

	def _create_schema(self) -> None:
		with self._connection:
			self._connection.execute(
				"""
				CREATE TABLE IF NOT EXISTS messages (
					server_id TEXT PRIMARY KEY,
					timestamp TEXT NOT NULL,
					type TEXT NOT NULL,
					source TEXT NOT NULL,
					destination TEXT NOT NULL,
					ack_required INTEGER NOT NULL,
					payload TEXT NOT NULL,
					client_msg_id TEXT
				)
				""",
			)
			self._connection.execute(
				"""
				CREATE UNIQUE INDEX IF NOT EXISTS idx_source_client_msg
				ON messages(source, client_msg_id)
				WHERE client_msg_id IS NOT NULL
				""",
			)

	def close(self) -> None:
		self._connection.close()

	def get_server_id(self, source: str, client_msg_id: str) -> str | None:
		row = self._connection.execute(
			"""
			SELECT server_id
			FROM messages
			WHERE source = ? AND client_msg_id = ?
			LIMIT 1
			""",
			(source, client_msg_id),
		).fetchone()
		if row is None:
			return None
		server_id = row["server_id"]
		if isinstance(server_id, str):
			return server_id
		return None

	def save_frame(
		self,
		server_id: str,
		timestamp: str,
		frame_type: str,
		source: str,
		destination: str,
		ack_required: int,
		payload: str,
		client_msg_id: str | None,
	) -> None:
		with self._connection:
			self._connection.execute(
				"""
				INSERT OR IGNORE INTO messages
				(server_id, timestamp, type, source, destination, ack_required, payload, client_msg_id)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(server_id, timestamp, frame_type, source, destination, ack_required, payload, client_msg_id),
			)


def generate_id() -> str:
	return str(uuid7())  # pyright: ignore[reportUnknownArgumentType]


def now_iso() -> str:
	return datetime.now(LOCAL_TIMEZONE).isoformat()


def normalize_station_id(raw_value: object) -> str | None:
	if not isinstance(raw_value, str):
		return None

	cleaned = raw_value.strip().upper()
	match = CALLSIGN_WITH_SSID_RE.fullmatch(cleaned)
	if match is None:
		return None

	callsign = match.group(1)
	ssid = int(match.group(2))
	if not is_valid_callsign(callsign) or not (0 <= ssid <= 15):
		return None

	return f"{callsign}-{ssid}"


def normalize_ack_required(raw_value: object) -> int:
	if isinstance(raw_value, bool):
		return int(raw_value)
	if isinstance(raw_value, int) and raw_value in VALID_ACK_REQUIRED_VALUES:
		return raw_value
	return 0


def validate_message_payload_hex(raw_payload: object) -> tuple[str | None, str | None]:
	if not isinstance(raw_payload, str):
		return None, "payload must be a hex string for type=message"

	payload_hex = raw_payload.strip()
	if payload_hex == "":
		return None, "payload cannot be empty"
	if len(payload_hex) % 2 != 0:
		return None, "payload hex length must be even"

	try:
		payload_bytes = bytes.fromhex(payload_hex)
	except ValueError:
		return None, "payload is not valid hex"

	if payload_bytes[0] != 0xC0 or payload_bytes[-1] != 0xC0:
		return None, "payload must include leading and trailing C0 bytes"

	try:
		kiss_builder = KISSFrameBuilder(KISSFrameConfig(0x00))
		ax25_frame = kiss_builder.decode_kiss_frame(payload_bytes)
		ax25_builder = AX25FrameBuilder(AX25FrameConfig("N0CALL", 0, "N0CALL", 0))
		ax25_builder.decode_ax25_frame(ax25_frame)
	except (InvalidKISSError, InvalidAX25Error) as exc:
		return None, f"payload is not a valid KISS/AX.25 frame: {exc}"

	return payload_hex.lower(), None


def payload_to_store_text(payload: str | dict[str, Any]) -> str:
	if isinstance(payload, str):
		return payload
	return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse_inbound_frame(raw_frame: dict[str, Any]) -> tuple[ParsedInboundFrame | None, str | None]:
	frame_type = raw_frame.get("type")
	if not isinstance(frame_type, str) or frame_type not in VALID_FRAME_TYPES:
		return None, "type must be one of message, ack, control, error"

	client_msg_id = raw_frame.get("client_msg_id")
	if client_msg_id is not None and not isinstance(client_msg_id, str):
		return None, "client_msg_id must be a string when provided"

	original_id = raw_frame.get("id")
	original_frame_id = original_id if isinstance(original_id, str) else None

	source = normalize_station_id(raw_frame.get("source"))
	if source is None:
		return None, "source must be a valid station id in CALL-SSID format"

	destination = normalize_station_id(raw_frame.get("destination"))
	if destination is None:
		return None, "destination must be a valid station id in CALL-SSID format"

	ack_required = normalize_ack_required(raw_frame.get("ack_required", 0))
	payload = raw_frame.get("payload")

	if frame_type == "message":
		normalized_payload, payload_error = validate_message_payload_hex(payload)
		if payload_error is not None or normalized_payload is None:
			return None, payload_error or "payload is invalid"
		validated_payload: str | dict[str, Any] = normalized_payload
	else:
		if not isinstance(payload, dict):
			return None, f"payload must be a JSON object for type={frame_type}"
		object_payload = cast("dict[str, Any]", payload)
		if frame_type == "ack":
			ack_for = object_payload.get("ack_for")
			if not isinstance(ack_for, str):
				return None, "ack payload must include ack_for as a string"
			status = object_payload.get("status")
			if status is not None and (not isinstance(status, str) or status not in VALID_ACK_STATUS_VALUES):
				return None, "ack payload status must be one of received, processed, failed"
		validated_payload = object_payload

	return ParsedInboundFrame(
		frame_type=frame_type,
		source=source,
		destination=destination,
		ack_required=ack_required,
		payload=validated_payload,
		client_msg_id=client_msg_id,
		original_id=original_frame_id,
	), None


def resolve_db_path() -> Path:
	raw_path = os.getenv("PY_HAM_BBS_DB_PATH", DEFAULT_DB_PATH)
	return Path(raw_path).expanduser().resolve()


def resolve_server_source() -> str:
	configured_source = os.getenv("PY_HAM_BBS_SERVER_SOURCE", DEFAULT_SERVER_SOURCE)
	normalized = normalize_station_id(configured_source)
	if normalized is None:
		logger.warning("Invalid PY_HAM_BBS_SERVER_SOURCE=%s; using %s", configured_source, DEFAULT_SERVER_SOURCE)
		return DEFAULT_SERVER_SOURCE
	return normalized


class ProtocolServer:
	def __init__(self, store: MessageStore, server_source: str) -> None:
		self._store = store
		self._server_source = server_source
		self._bound_sources: dict[ServerConnection, str] = {}
		self._routes: dict[str, set[ServerConnection]] = {}
		self._pending_acks: dict[str, PendingAckState] = {}

	def _build_frame(
		self,
		frame_type: str,
		source: str,
		destination: str,
		ack_required: int,
		payload: str | dict[str, Any],
		client_msg_id: str | None = None,
		frame_id: str | None = None,
		timestamp: str | None = None,
	) -> dict[str, Any]:
		frame: dict[str, Any] = {
			"type": frame_type,
			"id": frame_id or generate_id(),
			"timestamp": timestamp or now_iso(),
			"source": source,
			"destination": destination,
			"ack_required": ack_required,
			"payload": payload,
		}
		if client_msg_id is not None:
			frame["client_msg_id"] = client_msg_id
		return frame

	def _save_frame(self, frame: dict[str, Any]) -> None:
		payload = frame["payload"]
		if isinstance(payload, str):
			payload_text = payload_to_store_text(payload)
		elif isinstance(payload, dict):
			payload_text = payload_to_store_text(cast("dict[str, Any]", payload))
		else:
			payload_text = str(payload)
		client_msg_id_value = frame.get("client_msg_id")
		client_msg_id = client_msg_id_value if isinstance(client_msg_id_value, str) else None
		self._store.save_frame(
			server_id=str(frame["id"]),
			timestamp=str(frame["timestamp"]),
			frame_type=str(frame["type"]),
			source=str(frame["source"]),
			destination=str(frame["destination"]),
			ack_required=int(frame["ack_required"]),
			payload=payload_text,
			client_msg_id=client_msg_id,
		)

	async def _send_frame(self, websocket: ServerConnection, frame: dict[str, Any]) -> bool:
		try:
			await websocket.send(json.dumps(frame))
			return True
		except ConnectionClosed:
			return False

	def _current_source_for(self, websocket: ServerConnection) -> str | None:
		return self._bound_sources.get(websocket)

	def _bind_source(self, websocket: ServerConnection, source: str) -> tuple[bool, str | None]:
		bound_source = self._bound_sources.get(websocket)
		if bound_source is None:
			self._bound_sources[websocket] = source
			self._routes.setdefault(source, set()).add(websocket)
			return True, None
		if bound_source != source:
			return False, bound_source
		return True, None

	async def _remove_connection(self, websocket: ServerConnection) -> None:
		bound_source = self._bound_sources.pop(websocket, None)
		if bound_source is not None:
			peers = self._routes.get(bound_source)
			if peers is not None:
				peers.discard(websocket)
				if not peers:
					self._routes.pop(bound_source, None)

		for message_id, state in list(self._pending_acks.items()):
			if state.origin_websocket is websocket:
				self._pending_acks.pop(message_id, None)
				continue
			if bound_source is not None and bound_source in state.awaiting_sources:
				state.awaiting_sources.discard(bound_source)
				await self._send_pending_status(state, message_id, "failed")
				self._pending_acks.pop(message_id, None)

	def _resolve_recipients(self, destination: str) -> set[ServerConnection]:
		return set(self._routes.get(destination, set()))

	async def _fanout(self, recipients: set[ServerConnection], frame: dict[str, Any]) -> set[str]:
		delivered_sources: set[str] = set()
		for recipient in recipients:
			if await self._send_frame(recipient, frame):
				recipient_source = self._bound_sources.get(recipient)
				if recipient_source is not None:
					delivered_sources.add(recipient_source)
			else:
				await self._remove_connection(recipient)
		return delivered_sources

	async def _send_error(
		self,
		websocket: ServerConnection,
		message: str,
		original_id: str | None,
		original_client_msg_id: str | None,
		source_hint: str | None,
	) -> None:
		destination = source_hint or self._current_source_for(websocket) or self._server_source
		content: dict[str, Any] = {"message": message, "original_id": original_id}
		if original_client_msg_id is not None:
			content["original_client_msg_id"] = original_client_msg_id
		payload = {"subtype": "protocol", "content": content}
		error_frame = self._build_frame(
			frame_type="error",
			source=self._server_source,
			destination=destination,
			ack_required=0,
			payload=payload,
			client_msg_id=original_client_msg_id,
		)
		await self._send_frame(websocket, error_frame)

	async def _send_acceptance_ack(
		self,
		websocket: ServerConnection,
		destination: str,
		ack_for: str,
		client_msg_id: str | None,
		status: str,
	) -> None:
		payload: dict[str, Any] = {"ack_for": ack_for, "status": status}
		if client_msg_id is not None:
			payload["client_msg_id"] = client_msg_id
		ack_frame = self._build_frame(
			frame_type="ack",
			source=self._server_source,
			destination=destination,
			ack_required=0,
			payload=payload,
		)
		await self._send_frame(websocket, ack_frame)

	async def _send_pending_status(self, state: PendingAckState, ack_for: str, status: str) -> None:
		await self._send_acceptance_ack(
			websocket=state.origin_websocket,
			destination=state.origin_source,
			ack_for=ack_for,
			client_msg_id=state.client_msg_id,
			status=status,
		)

	async def _handle_message(self, websocket: ServerConnection, frame: ParsedInboundFrame) -> None:
		if frame.client_msg_id is not None:
			existing_server_id = self._store.get_server_id(frame.source, frame.client_msg_id)
			if existing_server_id is not None:
				if frame.ack_required != 0:
					await self._send_acceptance_ack(
						websocket=websocket,
						destination=frame.source,
						ack_for=existing_server_id,
						client_msg_id=frame.client_msg_id,
						status="received",
					)
				return

		message_id = generate_id()
		timestamp = now_iso()
		canonical_message = self._build_frame(
			frame_type="message",
			source=frame.source,
			destination=frame.destination,
			ack_required=frame.ack_required,
			payload=frame.payload,
			client_msg_id=frame.client_msg_id,
			frame_id=message_id,
			timestamp=timestamp,
		)
		self._save_frame(canonical_message)

		recipients = self._resolve_recipients(frame.destination)
		delivered_sources = await self._fanout(recipients, canonical_message)

		if frame.ack_required != 0:
			ack_status = "received" if delivered_sources else "failed"
			await self._send_acceptance_ack(
				websocket=websocket,
				destination=frame.source,
				ack_for=message_id,
				client_msg_id=frame.client_msg_id,
				status=ack_status,
			)
			if delivered_sources:
				self._pending_acks[message_id] = PendingAckState(
					origin_websocket=websocket,
					origin_source=frame.source,
					ack_required=frame.ack_required,
					awaiting_sources=delivered_sources,
					client_msg_id=frame.client_msg_id,
				)

	async def _handle_passthrough(self, websocket: ServerConnection, frame: ParsedInboundFrame) -> None:
		if frame.client_msg_id is not None:
			existing_server_id = self._store.get_server_id(frame.source, frame.client_msg_id)
			if existing_server_id is not None:
				if frame.ack_required != 0:
					await self._send_acceptance_ack(
						websocket=websocket,
						destination=frame.source,
						ack_for=existing_server_id,
						client_msg_id=frame.client_msg_id,
						status="received",
					)
				return

		canonical_frame = self._build_frame(
			frame_type=frame.frame_type,
			source=frame.source,
			destination=frame.destination,
			ack_required=frame.ack_required,
			payload=frame.payload,
			client_msg_id=frame.client_msg_id,
		)
		self._save_frame(canonical_frame)

		recipients = self._resolve_recipients(frame.destination)
		delivered_sources = await self._fanout(recipients, canonical_frame)

		if frame.ack_required != 0:
			ack_status = "received" if delivered_sources else "failed"
			await self._send_acceptance_ack(
				websocket=websocket,
				destination=frame.source,
				ack_for=str(canonical_frame["id"]),
				client_msg_id=frame.client_msg_id,
				status=ack_status,
			)
			if delivered_sources:
				self._pending_acks[str(canonical_frame["id"])] = PendingAckState(
					origin_websocket=websocket,
					origin_source=frame.source,
					ack_required=frame.ack_required,
					awaiting_sources=delivered_sources,
					client_msg_id=frame.client_msg_id,
				)

	async def _handle_ack(self, frame: ParsedInboundFrame) -> None:
		if not isinstance(frame.payload, dict):
			return

		ack_for_value = frame.payload.get("ack_for")
		if not isinstance(ack_for_value, str):
			return

		status_value = frame.payload.get("status")
		incoming_status = status_value if isinstance(status_value, str) and status_value in VALID_ACK_STATUS_VALUES else "received"
		ack_payload: dict[str, Any] = {
			"ack_for": ack_for_value,
			"status": incoming_status,
		}
		if frame.client_msg_id is not None:
			ack_payload["client_msg_id"] = frame.client_msg_id

		canonical_ack = self._build_frame(
			frame_type="ack",
			source=frame.source,
			destination=frame.destination,
			ack_required=frame.ack_required,
			payload=ack_payload,
			client_msg_id=frame.client_msg_id,
		)
		self._save_frame(canonical_ack)
		await self._fanout(self._resolve_recipients(frame.destination), canonical_ack)

		pending_state = self._pending_acks.get(ack_for_value)
		if pending_state is None:
			return

		if incoming_status == "failed":
			await self._send_pending_status(pending_state, ack_for_value, "failed")
			self._pending_acks.pop(ack_for_value, None)
			return

		if frame.source in pending_state.awaiting_sources:
			pending_state.awaiting_sources.discard(frame.source)

		if pending_state.ack_required == 1:
			await self._send_pending_status(pending_state, ack_for_value, "processed")
			self._pending_acks.pop(ack_for_value, None)
			return

		if pending_state.awaiting_sources:
			await self._send_pending_status(pending_state, ack_for_value, "received")
			return

		await self._send_pending_status(pending_state, ack_for_value, "processed")
		self._pending_acks.pop(ack_for_value, None)

	async def _process_frame(self, websocket: ServerConnection, raw_frame: dict[str, Any]) -> None:
		parsed_frame, parse_error = parse_inbound_frame(raw_frame)
		source_hint = normalize_station_id(raw_frame.get("source"))
		original_id = raw_frame.get("id") if isinstance(raw_frame.get("id"), str) else None
		original_client_msg_id = raw_frame.get("client_msg_id") if isinstance(raw_frame.get("client_msg_id"), str) else None

		if parsed_frame is None:
			await self._send_error(
				websocket=websocket,
				message=parse_error or "Invalid message format",
				original_id=original_id,
				original_client_msg_id=original_client_msg_id,
				source_hint=source_hint,
			)
			return

		bind_ok, bound_source = self._bind_source(websocket, parsed_frame.source)
		if not bind_ok:
			await self._send_error(
				websocket=websocket,
				message=f"source is bound to {bound_source} for this session",
				original_id=parsed_frame.original_id,
				original_client_msg_id=parsed_frame.client_msg_id,
				source_hint=parsed_frame.source,
			)
			return

		if parsed_frame.frame_type == "message":
			await self._handle_message(websocket, parsed_frame)
			return
		if parsed_frame.frame_type == "ack":
			await self._handle_ack(parsed_frame)
			return
		await self._handle_passthrough(websocket, parsed_frame)

	async def handler(self, websocket: ServerConnection) -> None:
		logger.info("Client connected: %s", websocket.remote_address)
		try:
			async for incoming_frame in websocket:
				if not isinstance(incoming_frame, str):
					await self._send_error(
						websocket=websocket,
						message="Only text WebSocket frames are supported",
						original_id=None,
						original_client_msg_id=None,
						source_hint=None,
					)
					continue

				try:
					raw = json.loads(incoming_frame)
				except json.JSONDecodeError:
					await self._send_error(
						websocket=websocket,
						message="Invalid JSON payload",
						original_id=None,
						original_client_msg_id=None,
						source_hint=None,
					)
					continue

				if not isinstance(raw, dict):
					await self._send_error(
						websocket=websocket,
						message="Frame payload must be a JSON object",
						original_id=None,
						original_client_msg_id=None,
						source_hint=None,
					)
					continue

				await self._process_frame(websocket, cast("dict[str, Any]", raw))
		except ConnectionClosed as exc:
			logger.info("Connection closed: %s", exc)
		finally:
			await self._remove_connection(websocket)
			logger.info("Client disconnected: %s", websocket.remote_address)


async def main() -> None:
	db_path = resolve_db_path()
	server_source = resolve_server_source()
	store = MessageStore(db_path)
	protocol_server = ProtocolServer(store, server_source)

	logger.info("Using protocol store: %s", db_path)
	logger.info("Server source identity: %s", server_source)

	try:
		async with serve(protocol_server.handler, "0.0.0.0", 8765) as server:  # noqa: S104
			print("Protocol server started on ws://0.0.0.0:8765")
			await server.serve_forever()
	finally:
		store.close()


if __name__ == "__main__":
	asyncio.run(main())
