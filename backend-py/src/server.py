from websockets import Response, Request
from websockets.datastructures import Headers
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
import logging
import os
from platform import python_version_tuple
import re
from typing import Any, Final, cast, Literal
import asyncio
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from lib.ax25 import InvalidAX25Error, is_valid_callsign
from lib.database import MessageRepository, SaveFrameResult, resolve_db_path
from lib.direwolf import DEFAULT_KISS_HOST, DEFAULT_KISS_PORT, DirewolfKISSClient, validate_kiss_payload
from lib.kiss import InvalidKISSError

if int(python_version_tuple()[1]) < 14:
	from uuid6 import uuid7  # pyright: ignore[reportMissingImports, reportUnknownVariableType]
else:
	from uuid import uuid7  # ty:ignore[unresolved-import]


class InvalidFrameError(ValueError):
	"""Raised when an inbound frame fails validation/normalization."""


class InvalidPayloadError(InvalidFrameError):
	"""Raised when a message payload is invalid (bad KISS/AX.25, wrong format, etc.)."""


logger = logging.getLogger(__name__)

FrameType = Literal["message", "ack", "control", "error"]
VALID_FRAME_TYPES: Final[frozenset[FrameType]] = frozenset({"message", "ack", "control", "error"})
AckReqValues = Literal[0, 1, 2]
VALID_ACK_REQUIRED_VALUES: Final[frozenset[AckReqValues]] = frozenset({0, 1, 2})
AckStatValues = Literal["received", "processed", "failed"]
VALID_ACK_STATUS_VALUES: Final[frozenset[AckStatValues]] = frozenset({"received", "processed", "failed"})
CALLSIGN_WITH_SSID_RE: Final[re.Pattern[str]] = re.compile(r"^([A-Z0-9]{1,6})(?:-(\d{1,2}))?$")
DEFAULT_SERVER_SOURCE: Final[str] = "SERVER-0"
DIREWOLF_ENABLED_ENV: Final[str] = "PY_HAM_BBS_DIREWOLF_ENABLED"
DIREWOLF_HOST_ENV: Final[str] = "PY_HAM_BBS_DIREWOLF_HOST"
DIREWOLF_PORT_ENV: Final[str] = "PY_HAM_BBS_DIREWOLF_PORT"
PENDING_ACK_TIMEOUT_SECONDS: Final[float] = 30.0
try:
	LOCAL_TIMEZONE: Final[tzinfo] = ZoneInfo("Australia/Melbourne")
except ZoneInfoNotFoundError:
	logger.warning("Timezone Australia/Melbourne unavailable; falling back to UTC")
	LOCAL_TIMEZONE: Final[tzinfo] = UTC  # pyright: ignore[reportConstantRedefinition, reportGeneralTypeIssues]


@dataclass(slots=True)
class ValidatedInboundFrame:
	"""Represents a validated and normalized inbound frame from a client, ready for processing."""

	frame_type: FrameType
	client_msg_id: str | None
	source: str
	destination: str
	ack_required: AckReqValues
	payload: bytes | dict[str, Any]


@dataclass(slots=True)
class PendingAcknowledgementState:
	"""Tracks the state of a message that has been sent with ack_required but is still awaiting acknowledgements from recipients."""

	origin_websocket: ServerConnection
	origin_source: str
	ack_required: AckReqValues
	awaiting_websockets: set[ServerConnection]
	successful_websockets: set[ServerConnection]
	failed_websockets: set[ServerConnection]
	client_msg_id: str | None
	timeout_task: asyncio.Task[None] | None


def now_iso() -> str:
	"""Get the current timestamp in ISO 8601 format with local timezone. Falls back to UTC if local timezone is unavailable."""

	return datetime.now(LOCAL_TIMEZONE).isoformat()


def normalize_station_id(raw_value: str) -> str | None:
	"""Normalize a raw station ID value to the standard all caps CALL-SSID format, defaulting missing SSID to 0."""

	match = CALLSIGN_WITH_SSID_RE.fullmatch(raw_value.strip().upper())
	if match is None:
		return None

	callsign = match.group(1)
	ssid_text = match.group(2)
	ssid = int(ssid_text) if ssid_text is not None else 0
	if not is_valid_callsign(callsign) or not (0 <= ssid <= 15):
		return None

	return f"{callsign}-{ssid}"


def normalize_ack_required(raw_value: AckReqValues | None) -> AckReqValues:
	"""Normalize the ack_required value, ensuring it is one of the valid integers (0, 1, 2). Defaults to 0 if invalid."""

	if raw_value in VALID_ACK_REQUIRED_VALUES:
		return raw_value
	return 0


def validate_message_payload_hex(payload: bytes) -> bytes:
	"""Validate a KISS/AX.25 payload and return the validated bytes or raise InvalidPayloadError.

	Raises:
		InvalidPayloadError: when payload is missing, malformed, or not a valid KISS/AX.25 frame.
	"""

	try:
		return validate_kiss_payload(payload)
	except (InvalidKISSError, InvalidAX25Error) as e:
		raise InvalidPayloadError(f"payload is not a valid KISS/AX.25 frame: {e}") from e
	except ValueError as e:
		raise InvalidPayloadError(str(e)) from e


def payload_to_store_text(payload: bytes | dict[str, Any]) -> str:
	if isinstance(payload, bytes):
		return payload.hex()
	return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def parse_inbound_frame(raw_frame: dict[str, Any]) -> ValidatedInboundFrame:
	"""Parse and validate an inbound raw frame.

	Returns a `ValidatedInboundFrame` on success.

	Raises:
		InvalidFrameError: when the frame is malformed or fails validation
		(invalid type, missing or malformed fields, invalid payload, etc.).
	"""

	frame_type = raw_frame.get("type")
	if frame_type not in VALID_FRAME_TYPES:
		raise InvalidFrameError(f"type must be one of {VALID_FRAME_TYPES}")

	client_msg_id = raw_frame.get("client_msg_id")
	if client_msg_id is not None and not isinstance(client_msg_id, str):
		raise InvalidFrameError("client_msg_id must be a string when provided")

	source = raw_frame.get("source")
	if not isinstance(source, str):
		raise InvalidFrameError("source must be a string")
	source = normalize_station_id(source)
	if source is None:
		raise InvalidFrameError("source must be a valid station id in CALL or CALL-SSID format")

	destination = raw_frame.get("destination")
	if not isinstance(destination, str):
		raise InvalidFrameError("destination must be a string")
	destination = normalize_station_id(destination)
	if destination is None:
		raise InvalidFrameError("destination must be a valid station id in CALL or CALL-SSID format")

	ack_required: AckReqValues = normalize_ack_required(raw_frame.get("ack_required", 0))

	if frame_type == "message":
		payload = raw_frame.get("payload")
		if isinstance(payload, str):
			try:
				payload_bytes = bytes.fromhex(payload)
			except ValueError as e:
				raise InvalidFrameError("payload must be a hex string for type=message") from e
		else:
			raise InvalidFrameError(f"payload must be a hex string for type=message, got {type(payload).__name__}")
		validated_payload = validate_message_payload_hex(payload_bytes)
	else:
		payload: object = raw_frame.get("payload")
		if not isinstance(payload, dict):
			raise InvalidFrameError(f"payload must be a JSON object for type={frame_type}")
		payload = cast(dict[str, Any], payload)
		if frame_type == "ack":
			ack_for = payload.get("ack_for")
			if not isinstance(ack_for, str):
				raise InvalidFrameError("ack payload must include ack_for as a string")
			status = payload.get("status")
			if status is None or not isinstance(status, str) or status not in VALID_ACK_STATUS_VALUES:
				raise InvalidFrameError(f"ack payload status must be one of {VALID_ACK_STATUS_VALUES}")
		elif frame_type == "control" and payload.get("subtype") == "verify":
			content = payload.get("content")
			if not isinstance(content, dict):
				raise InvalidFrameError("verify payload must include content as a JSON object")
			student_id = content.get("student_id")
			if not isinstance(student_id, str) or student_id.strip() == "":
				raise InvalidFrameError("verify payload must include student_id as a non-empty string")
			if normalize_station_id(student_id) is None:
				raise InvalidFrameError("verify payload student_id must be a valid CALL or CALL-SSID station id")
		validated_payload = payload

	return ValidatedInboundFrame(
		frame_type=frame_type,
		client_msg_id=client_msg_id,
		source=source,
		destination=destination,
		ack_required=ack_required,
		payload=validated_payload,
	)


def resolve_server_source() -> str:
	configured_source = os.getenv("PY_HAM_BBS_SERVER_SOURCE", DEFAULT_SERVER_SOURCE)
	normalized = normalize_station_id(configured_source)
	if normalized is None:
		logger.warning("Invalid PY_HAM_BBS_SERVER_SOURCE=%s; using %s", configured_source, DEFAULT_SERVER_SOURCE)
		return DEFAULT_SERVER_SOURCE
	return normalized


def resolve_direwolf_client() -> DirewolfKISSClient | None:
	enabled_raw = os.getenv(DIREWOLF_ENABLED_ENV, "1")
	if enabled_raw.strip().lower() not in {"1", "true", "yes", "on"}:
		return None

	host = os.getenv(DIREWOLF_HOST_ENV, DEFAULT_KISS_HOST)
	port_raw = os.getenv(DIREWOLF_PORT_ENV, str(DEFAULT_KISS_PORT))
	try:
		port = int(port_raw)
	except ValueError:
		logger.warning("Invalid %s=%s; using %s", DIREWOLF_PORT_ENV, port_raw, DEFAULT_KISS_PORT)
		port = DEFAULT_KISS_PORT
	if port <= 0 or port > 65535:
		logger.warning("Invalid %s=%s; using %s", DIREWOLF_PORT_ENV, port, DEFAULT_KISS_PORT)
		port = DEFAULT_KISS_PORT

	return DirewolfKISSClient(host=host, port=port)


class MessageBrokerServer:
	"""Core server class that manages client connections, message routing, and interactions with the message repository and Direwolf client."""

	__slots__ = ("_store", "_server_source", "_direwolf_client", "_bound_sources", "_routes", "_pending_acks", "_verified_sources")

	def __init__(self, store: MessageRepository, server_source: str, direwolf_client: DirewolfKISSClient | None = None) -> None:
		self._store = store
		self._server_source = server_source
		self._direwolf_client = direwolf_client
		self._bound_sources: dict[ServerConnection, str] = {}
		self._routes: dict[str, set[ServerConnection]] = {}
		self._pending_acks: dict[str, PendingAcknowledgementState] = {}
		self._verified_sources: dict[ServerConnection, str] = {}

	def _build_frame(
		self,
		frame_type: str,
		source: str,
		destination: str,
		ack_required: AckReqValues,
		payload: bytes | dict[str, Any],
		client_msg_id: str | None = None,
		frame_id: str | None = None,
		timestamp: str | None = None,
	) -> dict[str, Any]:
		frame: dict[str, Any] = {
			"type": frame_type,
			"id": frame_id or str(uuid7()),
			"timestamp": timestamp or now_iso(),
			"source": source,
			"destination": destination,
			"ack_required": ack_required,
			"payload": payload,
		}
		if client_msg_id is not None:
			frame["client_msg_id"] = client_msg_id
		# Ensure payload is JSON-serializable for outgoing frames: represent bytes as hex string
		if isinstance(frame["payload"], (bytes, bytearray)):
			frame["payload"] = bytes(frame["payload"]).hex()
		return frame

	def _save_frame(self, frame: dict[str, Any]) -> SaveFrameResult:
		payload = frame["payload"]
		if isinstance(payload, str):
			payload_text = payload_to_store_text(bytes.fromhex(payload))
		elif isinstance(payload, dict):
			payload_text = payload_to_store_text(cast(dict[str, Any], payload))
		else:
			raise InvalidPayloadError("payload must be a hex string or JSON object for storage")
		client_msg_id_value = frame.get("client_msg_id")
		client_msg_id = client_msg_id_value if isinstance(client_msg_id_value, str) else None
		return self._store.save_frame(
			server_id=str(frame["id"]),
			timestamp=str(frame["timestamp"]),
			frame_type=frame["type"],
			source=str(frame["source"]),
			destination=str(frame["destination"]),
			ack_required=frame["ack_required"],
			payload=payload_text,
			client_msg_id=client_msg_id,
		)

	def _current_verified_source_for(self, websocket: ServerConnection) -> str | None:
		return self._verified_sources.get(websocket)

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

	def try_bind_source(self, websocket: ServerConnection, source: str) -> tuple[bool, str | None]:
		"""Public shim around _bind_source for callers that need to inspect bind behavior."""

		return self._bind_source(websocket, source)

	async def _remove_connection(self, websocket: ServerConnection) -> None:
		bound_source = self._bound_sources.pop(websocket, None)
		self._verified_sources.pop(websocket, None)
		if bound_source is not None:
			peers = self._routes.get(bound_source)
			if peers is not None:
				peers.discard(websocket)
				if not peers:
					self._routes.pop(bound_source, None)

		for message_id, state in list(self._pending_acks.items()):
			if state.origin_websocket is websocket:
				self._pop_pending_ack(message_id)
				continue
			if websocket in state.awaiting_websockets:
				state.awaiting_websockets.discard(websocket)
				state.failed_websockets.add(websocket)
				await self._finish_pending_ack_if_ready(message_id, state)

	def _resolve_recipients(self, destination: str) -> set[ServerConnection]:
		return set(self._routes.get(destination, set()))

	def _cancel_pending_timeout(self, state: PendingAcknowledgementState) -> None:
		timeout_task = state.timeout_task
		if timeout_task is None:
			return
		if not timeout_task.done():
			timeout_task.cancel()

	def _mark_pending_source_success(self, state: PendingAcknowledgementState, websocket: ServerConnection) -> None:
		state.awaiting_websockets.discard(websocket)
		state.successful_websockets.add(websocket)

	def _mark_pending_source_failure(self, state: PendingAcknowledgementState, websocket: ServerConnection) -> None:
		state.awaiting_websockets.discard(websocket)
		state.failed_websockets.add(websocket)

	def _pop_pending_ack(self, message_id: str) -> PendingAcknowledgementState | None:
		state = self._pending_acks.pop(message_id, None)
		if state is not None:
			self._cancel_pending_timeout(state)
		return state

	async def _expire_pending_ack(self, message_id: str) -> None:
		try:
			await asyncio.sleep(PENDING_ACK_TIMEOUT_SECONDS)
		except asyncio.CancelledError:
			return
		state = self._pending_acks.get(message_id)
		if state is None:
			return
		state.failed_websockets.update(state.awaiting_websockets)
		state.awaiting_websockets.clear()
		await self._finish_pending_ack_if_ready(message_id, state)

	def _create_canonical_frame(self, frame_type: str, parsed: ValidatedInboundFrame, frame_id: str | None = None, timestamp: str | None = None) -> tuple[dict[str, Any], bool]:
		"""Build, persist, and return the canonical frame for a parsed inbound frame."""

		canonical = self._build_frame(
			frame_type=frame_type,
			source=parsed.source,
			destination=parsed.destination,
			ack_required=parsed.ack_required,
			payload=parsed.payload,
			client_msg_id=parsed.client_msg_id,
			frame_id=frame_id,
			timestamp=timestamp,
		)
		saved_frame = self._save_frame(canonical)
		canonical["id"] = saved_frame
		return canonical, saved_frame.inserted

	async def _deliver_and_setup_pending(self, origin_ws: ServerConnection, origin_source: str, parsed: ValidatedInboundFrame, canonical: dict[str, Any]) -> set[ServerConnection]:
		"""Fanout a canonical frame and set up pending ack state when required.

		Returns the set of delivered recipient websockets.
		"""

		recipients = self._resolve_recipients(parsed.destination)
		delivered = await self._fanout(recipients, canonical)
		if parsed.ack_required != 0:
			ack_status = "received" if delivered else "failed"
			await self._send_acceptance_ack(
				websocket=origin_ws,
				destination=origin_source,
				ack_for=str(canonical["id"]),
				client_msg_id=parsed.client_msg_id,
				status=ack_status,
			)
			if delivered:
				message_id = str(canonical["id"])
				state = PendingAcknowledgementState(
					origin_websocket=origin_ws,
					origin_source=origin_source,
					ack_required=parsed.ack_required,
					awaiting_websockets=delivered,
					successful_websockets=set(),
					failed_websockets=set(),
					client_msg_id=parsed.client_msg_id,
					timeout_task=None,
				)
				self._pending_acks[message_id] = state
				state.timeout_task = asyncio.create_task(self._expire_pending_ack(message_id))
		return delivered

	async def _finish_pending_ack_if_ready(self, message_id: str, state: PendingAcknowledgementState) -> bool:
		if state.ack_required == 1:
			if state.successful_websockets:
				await self._send_pending_status(state, message_id, "processed")
				self._pop_pending_ack(message_id)
				return True
			if not state.awaiting_websockets:
				await self._send_pending_status(state, message_id, "failed")
				self._pop_pending_ack(message_id)
				return True
			return False

		if state.awaiting_websockets:
			return False

		final_status = "failed" if state.failed_websockets else "processed"
		await self._send_pending_status(state, message_id, final_status)
		self._pop_pending_ack(message_id)
		return True

	async def _fanout(self, recipients: set[ServerConnection], frame: dict[str, Any]) -> set[ServerConnection]:
		delivered_websockets: set[ServerConnection] = set()
		for recipient in recipients:
			if await self._send_frame(recipient, frame):
				delivered_websockets.add(recipient)
			else:
				await self._remove_connection(recipient)
		return delivered_websockets

	async def _send_to_direwolf(self, payload: bytes, source: str, destination: str) -> None:
		if self._direwolf_client is None:
			return
		try:
			await asyncio.to_thread(self._direwolf_client.send_kiss_frame, payload)
		except OSError as exc:
			logger.warning("Direwolf send failed for %s → %s: %s", source, destination, exc)

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
		extra_payload: dict[str, Any] | None = None,
	) -> None:
		payload: dict[str, Any] = {"ack_for": ack_for, "status": status}
		if client_msg_id is not None:
			payload["client_msg_id"] = client_msg_id
		if extra_payload is not None:
			payload.update(extra_payload)
		ack_frame = self._build_frame(
			frame_type="ack",
			source=self._server_source,
			destination=destination,
			ack_required=0,
			payload=payload,
			client_msg_id=client_msg_id,
		)
		await self._send_frame(websocket, ack_frame)

	async def _send_pending_status(self, state: PendingAcknowledgementState, ack_for: str, status: str) -> None:
		await self._send_acceptance_ack(
			websocket=state.origin_websocket,
			destination=state.origin_source,
			ack_for=ack_for,
			client_msg_id=state.client_msg_id,
			status=status,
		)

	async def _handle_verification(self, websocket: ServerConnection, frame: ValidatedInboundFrame) -> None:
		if not isinstance(frame.payload, dict):
			return

		canonical_frame, _ = self._create_canonical_frame("control", frame)
		payload = frame.payload
		content = payload.get("content")
		if not isinstance(content, dict):
			await self._send_error(
				websocket=websocket,
				message="verify payload must include content",
				original_id=str(canonical_frame["id"]),
				original_client_msg_id=frame.client_msg_id,
				source_hint=frame.source,
			)
			return

		student_id_value = content.get("student_id")
		if not isinstance(student_id_value, str) or student_id_value.strip() == "":
			await self._send_error(
				websocket=websocket,
				message="verify payload must include student_id",
				original_id=str(canonical_frame["id"]),
				original_client_msg_id=frame.client_msg_id,
				source_hint=frame.source,
			)
			return

		student_id = normalize_station_id(student_id_value)
		if student_id is None:
			await self._send_error(
				websocket=websocket,
				message="verify payload student_id must be a valid CALL-SSID station id",
				original_id=str(canonical_frame["id"]),
				original_client_msg_id=frame.client_msg_id,
				source_hint=frame.source,
			)
			return

		if self._store.get_allowed_student_name(student_id) is None:
			await self._send_acceptance_ack(
				websocket=websocket,
				destination=frame.source,
				ack_for=str(canonical_frame["id"]),
				client_msg_id=frame.client_msg_id,
				status="failed",
				extra_payload={"student_id": student_id, "reason": "student id is not allowed"},
			)
			return

		current_verified_source = self._verified_sources.get(websocket)
		if current_verified_source is not None and current_verified_source != student_id:
			await self._send_error(
				websocket=websocket,
				message=f"session is already verified for {current_verified_source}",
				original_id=str(canonical_frame["id"]),
				original_client_msg_id=frame.client_msg_id,
				source_hint=frame.source,
			)
			return

		self._verified_sources[websocket] = student_id
		await self._send_acceptance_ack(
			websocket=websocket,
			destination=frame.source,
			ack_for=str(canonical_frame["id"]),
			client_msg_id=frame.client_msg_id,
			status="processed",
			extra_payload={"student_id": student_id},
		)

	async def _handle_message(self, websocket: ServerConnection, frame: ValidatedInboundFrame) -> None:
		message_id = str(uuid7())
		timestamp = now_iso()
		canonical_message, inserted = self._create_canonical_frame("message", frame, frame_id=message_id, timestamp=timestamp)
		if not inserted:
			if frame.ack_required != 0:
				await self._send_acceptance_ack(
					websocket=websocket,
					destination=frame.source,
					ack_for=str(canonical_message["id"]),
					client_msg_id=frame.client_msg_id,
					status="received",
				)
			return
		if isinstance(frame.payload, (bytes, bytearray)):
			await self._send_to_direwolf(bytes(frame.payload), frame.source, frame.destination)
		await self._deliver_and_setup_pending(websocket, frame.source, frame, canonical_message)

	async def _handle_passthrough(self, websocket: ServerConnection, frame: ValidatedInboundFrame) -> None:
		canonical_frame, _ = self._create_canonical_frame(frame.frame_type, frame)
		await self._deliver_and_setup_pending(websocket, frame.source, frame, canonical_frame)

	async def _handle_ack(self, websocket: ServerConnection, frame: ValidatedInboundFrame) -> None:
		if not isinstance(frame.payload, dict):
			return

		ack_for_value = frame.payload.get("ack_for")
		if not isinstance(ack_for_value, str):
			return

		status_value = frame.payload.get("status")
		incoming_status = cast(AckStatValues, status_value)
		ack_payload: dict[str, Any] = {
			"ack_for": ack_for_value,
			"status": incoming_status,
		}
		incoming_client_id = frame.payload.get("client_msg_id")
		if isinstance(incoming_client_id, str):
			ack_payload["client_msg_id"] = incoming_client_id

		canonical_ack = self._build_frame(
			frame_type="ack",
			source=frame.source,
			destination=frame.destination,
			ack_required=frame.ack_required,
			payload=ack_payload,
			client_msg_id=frame.client_msg_id,
		)
		canonical_ack["id"] = self._save_frame(canonical_ack)
		await self._fanout(self._resolve_recipients(frame.destination), canonical_ack)

		pending_state = self._pending_acks.get(ack_for_value)
		if pending_state is None:
			return

		if incoming_status == "failed":
			self._mark_pending_source_failure(pending_state, websocket)
			await self._finish_pending_ack_if_ready(ack_for_value, pending_state)
			return

		self._mark_pending_source_success(pending_state, websocket)

		if pending_state.ack_required == 1:
			await self._finish_pending_ack_if_ready(ack_for_value, pending_state)
			return

		if pending_state.awaiting_websockets:
			await self._send_pending_status(pending_state, ack_for_value, "received")
			return

		await self._finish_pending_ack_if_ready(ack_for_value, pending_state)

	async def _process_frame(self, websocket: ServerConnection, raw_frame: dict[str, Any]) -> None:
		source_raw = raw_frame.get("source")
		source_hint = normalize_station_id(source_raw if isinstance(source_raw, str) else "")
		original_id = raw_frame.get("id") if isinstance(raw_frame.get("id"), str) else None
		original_client_msg_id = raw_frame.get("client_msg_id") if isinstance(raw_frame.get("client_msg_id"), str) else None

		try:
			parsed_frame = parse_inbound_frame(raw_frame)
		except InvalidFrameError as exc:
			await self._send_error(
				websocket=websocket,
				message=str(exc) or "Invalid message format",
				original_id=original_id,
				original_client_msg_id=original_client_msg_id,
				source_hint=source_hint,
			)
			return

		if parsed_frame.frame_type == "control" and isinstance(parsed_frame.payload, dict) and parsed_frame.payload.get("subtype") == "verify":
			await self._handle_verification(websocket, parsed_frame)
			return

		verified_source = self._current_verified_source_for(websocket)
		if verified_source is None:
			await self._send_error(
				websocket=websocket,
				message="student id must be verified before sending frames",
				original_id=original_id,
				original_client_msg_id=original_client_msg_id,
				source_hint=parsed_frame.source,
			)
			return
		if parsed_frame.source != verified_source:
			await self._send_error(
				websocket=websocket,
				message=f"source must match verified student route {verified_source}",
				original_id=original_id,
				original_client_msg_id=original_client_msg_id,
				source_hint=parsed_frame.source,
			)
			return

		bind_ok, bound_source = self._bind_source(websocket, parsed_frame.source)
		if not bind_ok:
			await self._send_error(
				websocket=websocket,
				message=f"source is bound to {bound_source} for this session",
				original_id=original_id,
				original_client_msg_id=parsed_frame.client_msg_id,
				source_hint=parsed_frame.source,
			)
			return

		if parsed_frame.frame_type == "message":
			await self._handle_message(websocket, parsed_frame)
			return
		if parsed_frame.frame_type == "ack":
			await self._handle_ack(websocket, parsed_frame)
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

				await self._process_frame(websocket, cast(dict[str, Any], raw))
		except ConnectionClosed as exc:
			logger.info("Connection closed: %s", exc)
		finally:
			await self._remove_connection(websocket)
			logger.info("Client disconnected: %s", websocket.remote_address)


async def health_check(connection: ServerConnection, request: Request) -> Response | None:
	if request.path == "/healthz":
		return Response(200, "OK", Headers(), body=b"ok\n")
	return None


async def main() -> None:
	logging.basicConfig(level=logging.INFO)
	logger.info("Started")
	db_path = resolve_db_path()
	server_source = resolve_server_source()
	store = MessageRepository(db_path)
	direwolf_client = resolve_direwolf_client()
	protocol_server = MessageBrokerServer(store, server_source, direwolf_client=direwolf_client)

	logger.info("Using protocol store: %s", db_path)
	logger.info("Server source identity: %s", server_source)
	if direwolf_client is not None:
		logger.info("Direwolf KISS enabled: %s:%s", direwolf_client.host, direwolf_client.port)

	try:
		async with serve(protocol_server.handler, "0.0.0.0", 8765, process_request=health_check) as server:  # noqa: S104
			logger.info("Protocol server started on ws://0.0.0.0:8765")
			await server.serve_forever()
	finally:
		if direwolf_client is not None:
			direwolf_client.close()
		store.close()
		logger.info("Exited")


if __name__ == "__main__":
	asyncio.run(main())
