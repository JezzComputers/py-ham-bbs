import asyncio
import json
from pathlib import Path
from typing import cast

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.asyncio.server import ServerConnection, serve

import server
from lib.ax25 import AX25FrameBuilder, AX25FrameConfig
from lib.kiss import KISSFrameBuilder, KISSFrameConfig
from server import InvalidFrameError, MessageBrokerServer, MessageRepository, parse_inbound_frame

SERVER_SOURCE = "SERVER-0"
SENDER_STUDENT_ID = "VK3XYZ-0"
RECIPIENT_STUDENT_ID = "VK3ABC-0"
SENDER_STUDENT_NAME = "Sender Student"
RECIPIENT_STUDENT_NAME = "Recipient Student"


def build_valid_kiss_payload_hex() -> str:
	ax25_builder = AX25FrameBuilder(AX25FrameConfig("VK3ABC", 0, "VK3XYZ", 0))
	kiss_builder = KISSFrameBuilder(KISSFrameConfig(0x00))
	ax25_frame = ax25_builder.build_ax25_frame(b"Hello")
	return kiss_builder.build_kiss_frame(ax25_frame).hex()


def build_verify_frame(student_id: str, client_msg_id: str) -> dict[str, object]:
	return {
		"type": "control",
		"client_msg_id": client_msg_id,
		"source": SERVER_SOURCE,
		"destination": SERVER_SOURCE,
		"ack_required": 0,
		"payload": {
			"subtype": "verify",
			"content": {"student_id": student_id},
		},
	}


async def verify_and_bind_session(websocket: ClientConnection, student_id: str) -> None:
	verify_client_msg_id = f"verify-{student_id}"
	await websocket.send(json.dumps(build_verify_frame(student_id, verify_client_msg_id)))
	verify_ack_raw = cast("str", await asyncio.wait_for(websocket.recv(), 2))
	verify_ack_frame = cast("dict[str, object]", json.loads(verify_ack_raw))
	assert verify_ack_frame["type"] == "ack"
	assert verify_ack_frame.get("client_msg_id") == verify_client_msg_id
	verify_ack_payload = cast("dict[str, object]", verify_ack_frame["payload"])
	assert verify_ack_payload["status"] == "processed"
	assert verify_ack_payload["student_id"] == student_id

	bind_frame = {
		"type": "control",
		"source": student_id,
		"destination": SERVER_SOURCE,
		"ack_required": 0,
		"payload": {
			"subtype": "bind",
			"content": {"callsign": student_id},
		},
	}
	await websocket.send(json.dumps(bind_frame))


def test_parse_inbound_message_accepts_valid_frame() -> None:
	frame = {
		"type": "message",
		"client_msg_id": "c1-0001",
		"source": "VK3XYZ-0",
		"destination": "VK3ABC-0",
		"ack_required": 1,
		"payload": build_valid_kiss_payload_hex(),
	}

	parsed = parse_inbound_frame(frame)

	assert parsed.frame_type == "message"
	assert parsed.client_msg_id == "c1-0001"
	assert parsed.source == "VK3XYZ-0"
	assert parsed.destination == "VK3ABC-0"
	assert parsed.ack_required == 1


def test_parse_inbound_unknown_ack_required_defaults_to_zero() -> None:
	frame = {
		"type": "message",
		"source": "VK3XYZ-0",
		"destination": "VK3ABC-0",
		"ack_required": 9,
		"payload": build_valid_kiss_payload_hex(),
	}

	parsed = parse_inbound_frame(frame)

	assert parsed.ack_required == 0


def test_parse_inbound_ack_requires_ack_for() -> None:
	frame = {
		"type": "ack",
		"source": "VK3ABC-0",
		"destination": "VK3XYZ-0",
		"ack_required": 0,
		"payload": {"status": "received"},
	}

	with pytest.raises(InvalidFrameError) as excinfo:
		parse_inbound_frame(frame)

	assert str(excinfo.value) == "ack payload must include ack_for as a string"


def test_parse_inbound_verify_requires_student_id() -> None:
	frame = {
		"type": "control",
		"source": SERVER_SOURCE,
		"destination": SERVER_SOURCE,
		"ack_required": 0,
		"payload": {
			"subtype": "verify",
			"content": {},
		},
	}

	with pytest.raises(InvalidFrameError) as excinfo:
		parse_inbound_frame(frame)

	assert str(excinfo.value) == "verify payload must include student_id as a non-empty string"


def test_parse_inbound_verify_requires_valid_student_id_callsign() -> None:
	frame = {
		"type": "control",
		"source": SERVER_SOURCE,
		"destination": SERVER_SOURCE,
		"ack_required": 0,
		"payload": {
			"subtype": "verify",
			"content": {"student_id": "student-sender"},
		},
	}

	with pytest.raises(InvalidFrameError) as excinfo:
		parse_inbound_frame(frame)

	assert str(excinfo.value) == "verify payload student_id must be a valid CALL or CALL-SSID station id"


def test_parse_inbound_verify_accepts_student_id_without_ssid() -> None:
	frame = {
		"type": "control",
		"source": SERVER_SOURCE,
		"destination": SERVER_SOURCE,
		"ack_required": 0,
		"payload": {
			"subtype": "verify",
			"content": {"student_id": "VK3XYZ"},
		},
	}

	parsed = parse_inbound_frame(frame)

	assert parsed.frame_type == "control"
	assert cast("dict[str, object]", parsed.payload)["subtype"] == "verify"
	assert server.normalize_station_id("VK3XYZ") == "VK3XYZ-0"


def test_parse_inbound_ack_rejects_invalid_status() -> None:
	frame = {
		"type": "ack",
		"source": "VK3ABC-0",
		"destination": "VK3XYZ-0",
		"ack_required": 0,
		"payload": {"ack_for": "ack-1", "status": "bogus"},
	}

	with pytest.raises(InvalidFrameError) as excinfo:
		parse_inbound_frame(frame)

	assert str(excinfo.value).startswith("ack payload status must be one of frozenset(")


def test_store_keeps_first_mapping_for_source_and_client_msg_id(tmp_path: Path) -> None:
	store = MessageRepository(tmp_path / "protocol.db")
	first_saved_id = store.save_frame(
		server_id="019d5332-1b4c-743c-9821-25ca99a09f0a",
		timestamp="2026-04-03T23:32:11.123456+11:00",
		frame_type="message",
		source="VK3XYZ-0",
		destination="VK3ABC-0",
		ack_required=1,
		payload=build_valid_kiss_payload_hex(),
		client_msg_id="c1-0001",
	)
	assert first_saved_id.inserted is True
	second_saved_id = store.save_frame(
		server_id="019d5332-1b4c-743c-9821-25ca99a09f0b",
		timestamp="2026-04-03T23:32:12.123456+11:00",
		frame_type="message",
		source="VK3XYZ-0",
		destination="VK3ABC-0",
		ack_required=1,
		payload=build_valid_kiss_payload_hex(),
		client_msg_id="c1-0001",
	)
	assert second_saved_id.inserted is False

	assert first_saved_id == "019d5332-1b4c-743c-9821-25ca99a09f0a"
	assert second_saved_id == first_saved_id

	stored_server_id = store.get_server_id("VK3XYZ-0", "c1-0001")

	assert stored_server_id == "019d5332-1b4c-743c-9821-25ca99a09f0a"
	store.close()


def test_store_ignores_non_message_frames_for_client_msg_id_dedup(tmp_path: Path) -> None:
	store = MessageRepository(tmp_path / "protocol-non-message.db")
	message_id = store.save_frame(
		server_id="019d5332-1b4c-743c-9821-25ca99a09f0d",
		timestamp="2026-04-03T23:32:14.123456+11:00",
		frame_type="message",
		source="VK3XYZ-0",
		destination="VK3ABC-0",
		ack_required=1,
		payload=build_valid_kiss_payload_hex(),
		client_msg_id="c1-0002",
	)
	control_id = store.save_frame(
		server_id="019d5332-1b4c-743c-9821-25ca99a09f0c",
		timestamp="2026-04-03T23:32:13.123456+11:00",
		frame_type="control",
		source="VK3XYZ-0",
		destination="VK3ABC-0",
		ack_required=0,
		payload=json.dumps({"subtype": "bind", "content": {"ready": True}}),
		client_msg_id="c1-0002",
	)
	assert message_id.inserted is True
	assert control_id.inserted is True

	assert message_id == "019d5332-1b4c-743c-9821-25ca99a09f0d"
	assert control_id == "019d5332-1b4c-743c-9821-25ca99a09f0c"
	assert control_id != message_id
	assert store.get_server_id("VK3XYZ-0", "c1-0002") == message_id
	store.close()


def test_bind_source_rejects_double_bind(tmp_path: Path) -> None:
	store = MessageRepository(tmp_path / "protocol-bind.db")
	protocol = MessageBrokerServer(store=store, server_source=SERVER_SOURCE)
	fake_websocket = cast(ServerConnection, object())

	first_bind_ok, first_bound_source = protocol.try_bind_source(fake_websocket, "VK3XYZ-0")
	second_bind_ok, second_bound_source = protocol.try_bind_source(fake_websocket, "VK3ABC-0")

	assert first_bind_ok is True
	assert first_bound_source is None
	assert second_bind_ok is False
	assert second_bound_source == "VK3XYZ-0"
	store.close()


def test_protocol_server_routes_message_and_deduplicates_client_msg_id(tmp_path: Path) -> None:
	async def run_test() -> None:
		store = MessageRepository(tmp_path / "protocol-flow.db")
		store.save_allowed_student(SENDER_STUDENT_ID, SENDER_STUDENT_NAME)
		store.save_allowed_student(RECIPIENT_STUDENT_ID, RECIPIENT_STUDENT_NAME)
		protocol = MessageBrokerServer(store=store, server_source="SERVER-0")
		try:
			async with serve(protocol.handler, "127.0.0.1", 0) as ws_server:
				sockets = ws_server.sockets
				assert sockets is not None
				assert len(sockets) > 0
				port = int(sockets[0].getsockname()[1])
				url = f"ws://127.0.0.1:{port}"

				async with connect(url) as sender, connect(url) as recipient:
					await verify_and_bind_session(sender, SENDER_STUDENT_ID)
					await verify_and_bind_session(recipient, RECIPIENT_STUDENT_ID)

					message_frame = {
						"type": "message",
						"client_msg_id": "c1-0001",
						"source": SENDER_STUDENT_ID,
						"destination": RECIPIENT_STUDENT_ID,
						"ack_required": 1,
						"payload": build_valid_kiss_payload_hex(),
					}

					await sender.send(json.dumps(message_frame))

					routed_raw = cast("str", await asyncio.wait_for(recipient.recv(), 2))
					routed_frame = cast("dict[str, object]", json.loads(routed_raw))
					assert routed_frame["type"] == "message"
					assert routed_frame["source"] == SENDER_STUDENT_ID
					assert routed_frame["destination"] == RECIPIENT_STUDENT_ID

					# canonical frame should include server-assigned id and timestamp
					assert isinstance(routed_frame.get("id"), str)
					assert isinstance(routed_frame.get("timestamp"), str)
					# payload should be a hex string for message frames
					assert isinstance(routed_frame.get("payload"), str)
					assert routed_frame["payload"]

					ack_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					ack_frame = cast("dict[str, object]", json.loads(ack_raw))
					assert ack_frame["type"] == "ack"
					# client correlation id should be present both top-level and in payload
					assert ack_frame.get("client_msg_id") == "c1-0001"
					ack_payload = cast("dict[str, object]", ack_frame["payload"])
					assert ack_payload["status"] == "received"
					first_ack_for = cast("str", ack_payload["ack_for"])

					# server should have persisted mapping client_msg_id -> server id
					assert store.get_server_id(SENDER_STUDENT_ID, "c1-0001") == first_ack_for

					await sender.send(json.dumps(message_frame))
					duplicate_ack_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					duplicate_ack_frame = cast("dict[str, object]", json.loads(duplicate_ack_raw))
					duplicate_payload = cast("dict[str, object]", duplicate_ack_frame["payload"])
					assert duplicate_payload["ack_for"] == first_ack_for
					# duplicate ACK should also carry the client_msg_id top-level and in payload
					assert duplicate_ack_frame.get("client_msg_id") == "c1-0001"
					assert duplicate_payload.get("client_msg_id") == "c1-0001"

					with pytest.raises(asyncio.TimeoutError):
						await asyncio.wait_for(recipient.recv(), 0.4)
		finally:
			store.close()

	asyncio.run(run_test())


def test_protocol_server_processes_recipient_ack(tmp_path: Path) -> None:
	async def run_test() -> None:
		store = MessageRepository(tmp_path / "protocol-ack.db")
		store.save_allowed_student(SENDER_STUDENT_ID, SENDER_STUDENT_NAME)
		store.save_allowed_student(RECIPIENT_STUDENT_ID, RECIPIENT_STUDENT_NAME)
		protocol = MessageBrokerServer(store=store, server_source="SERVER-0")
		try:
			async with serve(protocol.handler, "127.0.0.1", 0) as ws_server:
				sockets = ws_server.sockets
				assert sockets is not None
				assert len(sockets) > 0
				port = int(sockets[0].getsockname()[1])
				url = f"ws://127.0.0.1:{port}"

				async with connect(url) as sender, connect(url) as recipient:
					await verify_and_bind_session(sender, SENDER_STUDENT_ID)
					await verify_and_bind_session(recipient, RECIPIENT_STUDENT_ID)

					message_frame = {
						"type": "message",
						"client_msg_id": "c1-0100",
						"source": SENDER_STUDENT_ID,
						"destination": RECIPIENT_STUDENT_ID,
						"ack_required": 2,
						"payload": build_valid_kiss_payload_hex(),
					}

					await sender.send(json.dumps(message_frame))

					routed_raw = cast("str", await asyncio.wait_for(recipient.recv(), 2))
					routed_frame = cast("dict[str, object]", json.loads(routed_raw))
					ack_for = cast("str", routed_frame["id"])

					acceptance_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					acceptance_frame = cast("dict[str, object]", json.loads(acceptance_raw))
					acceptance_payload = cast("dict[str, object]", acceptance_frame["payload"])
					assert acceptance_payload["ack_for"] == ack_for
					assert acceptance_payload["status"] == "received"

					recipient_ack = {
						"type": "ack",
						"source": RECIPIENT_STUDENT_ID,
						"destination": SENDER_STUDENT_ID,
						"ack_required": 0,
						"payload": {
							"ack_for": ack_for,
							"status": "processed",
						},
					}
					await recipient.send(json.dumps(recipient_ack))

					ack_one_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					ack_two_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					frames = [
						cast("dict[str, object]", json.loads(ack_one_raw)),
						cast("dict[str, object]", json.loads(ack_two_raw)),
					]
					by_source = {cast("str", frame["source"]): frame for frame in frames}
					assert RECIPIENT_STUDENT_ID in by_source
					assert SERVER_SOURCE in by_source

					forwarded_payload = cast("dict[str, object]", by_source[RECIPIENT_STUDENT_ID]["payload"])
					assert forwarded_payload["ack_for"] == ack_for
					assert forwarded_payload["status"] == "processed"

					server_payload = cast("dict[str, object]", by_source[SERVER_SOURCE]["payload"])
					assert server_payload["ack_for"] == ack_for
					assert server_payload["status"] == "processed"
		finally:
			store.close()

	asyncio.run(run_test())


def test_protocol_server_expires_pending_ack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(server, "PENDING_ACK_TIMEOUT_SECONDS", 0.05)

	async def run_test() -> None:
		store = MessageRepository(tmp_path / "protocol-expiry.db")
		store.save_allowed_student(SENDER_STUDENT_ID, SENDER_STUDENT_NAME)
		store.save_allowed_student(RECIPIENT_STUDENT_ID, RECIPIENT_STUDENT_NAME)
		protocol = MessageBrokerServer(store=store, server_source="SERVER-0")
		try:
			async with serve(protocol.handler, "127.0.0.1", 0) as ws_server:
				sockets = ws_server.sockets
				assert sockets is not None
				assert len(sockets) > 0
				port = int(sockets[0].getsockname()[1])
				url = f"ws://127.0.0.1:{port}"

				async with connect(url) as sender, connect(url) as recipient:
					await verify_and_bind_session(sender, SENDER_STUDENT_ID)
					await verify_and_bind_session(recipient, RECIPIENT_STUDENT_ID)

					message_frame = {
						"type": "message",
						"client_msg_id": "c1-timeout",
						"source": SENDER_STUDENT_ID,
						"destination": RECIPIENT_STUDENT_ID,
						"ack_required": 2,
						"payload": build_valid_kiss_payload_hex(),
					}

					await sender.send(json.dumps(message_frame))

					routed_raw = cast("str", await asyncio.wait_for(recipient.recv(), 2))
					routed_frame = cast("dict[str, object]", json.loads(routed_raw))
					assert routed_frame["type"] == "message"

					acceptance_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					acceptance_frame = cast("dict[str, object]", json.loads(acceptance_raw))
					acceptance_payload = cast("dict[str, object]", acceptance_frame["payload"])
					ack_for = cast("str", acceptance_payload["ack_for"])
					assert acceptance_payload["status"] == "received"

					failed_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					failed_frame = cast("dict[str, object]", json.loads(failed_raw))
					failed_payload = cast("dict[str, object]", failed_frame["payload"])
					assert failed_payload["ack_for"] == ack_for
					assert failed_payload["status"] == "failed"

					await asyncio.sleep(0.05)

					late_ack = {
						"type": "ack",
						"source": "VK3ABC-0",
						"destination": "VK3XYZ-0",
						"ack_required": 0,
						"payload": {
							"ack_for": ack_for,
							"status": "processed",
						},
					}
					await recipient.send(json.dumps(late_ack))

					forwarded_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					forwarded_frame = cast("dict[str, object]", json.loads(forwarded_raw))
					assert forwarded_frame["source"] == RECIPIENT_STUDENT_ID
					forwarded_payload = cast("dict[str, object]", forwarded_frame["payload"])
					assert forwarded_payload["ack_for"] == ack_for
					assert forwarded_payload["status"] == "processed"

					with pytest.raises(asyncio.TimeoutError):
						await asyncio.wait_for(sender.recv(), 0.4)
		finally:
			store.close()

	asyncio.run(run_test())


def test_protocol_server_passthrough_control_frame_is_fanned_out(tmp_path: Path) -> None:
	async def run_test() -> None:
		store = MessageRepository(tmp_path / "protocol-control.db")
		store.save_allowed_student(SENDER_STUDENT_ID, SENDER_STUDENT_NAME)
		store.save_allowed_student(RECIPIENT_STUDENT_ID, RECIPIENT_STUDENT_NAME)
		protocol = MessageBrokerServer(store=store, server_source=SERVER_SOURCE)
		try:
			async with serve(protocol.handler, "127.0.0.1", 0) as ws_server:
				sockets = ws_server.sockets
				assert sockets is not None
				assert len(sockets) > 0
				port = int(sockets[0].getsockname()[1])
				url = f"ws://127.0.0.1:{port}"

				async with connect(url) as sender, connect(url) as recipient:
					await verify_and_bind_session(sender, SENDER_STUDENT_ID)
					await verify_and_bind_session(recipient, RECIPIENT_STUDENT_ID)

					control_frame = {
						"type": "control",
						"source": SENDER_STUDENT_ID,
						"destination": RECIPIENT_STUDENT_ID,
						"ack_required": 0,
						"payload": {
							"subtype": "notice",
							"content": {"ready": True},
						},
					}

					await sender.send(json.dumps(control_frame))

					routed_raw = cast("str", await asyncio.wait_for(recipient.recv(), 2))
					routed_frame = cast("dict[str, object]", json.loads(routed_raw))
					assert routed_frame["type"] == "control"
					assert routed_frame["source"] == SENDER_STUDENT_ID
					assert routed_frame["destination"] == RECIPIENT_STUDENT_ID
					routed_payload = cast("dict[str, object]", routed_frame["payload"])
					assert routed_payload["subtype"] == "notice"
					assert cast("dict[str, object]", routed_payload["content"])["ready"] is True
		finally:
			store.close()

	asyncio.run(run_test())


def test_protocol_server_reports_failed_after_last_recipient_disconnects(tmp_path: Path) -> None:
	async def run_test() -> None:
		store = MessageRepository(tmp_path / "protocol-disconnect.db")
		store.save_allowed_student(SENDER_STUDENT_ID, SENDER_STUDENT_NAME)
		store.save_allowed_student(RECIPIENT_STUDENT_ID, RECIPIENT_STUDENT_NAME)
		protocol = MessageBrokerServer(store=store, server_source=SERVER_SOURCE)
		try:
			async with serve(protocol.handler, "127.0.0.1", 0) as ws_server:
				sockets = ws_server.sockets
				assert sockets is not None
				assert len(sockets) > 0
				port = int(sockets[0].getsockname()[1])
				url = f"ws://127.0.0.1:{port}"

				async with connect(url) as sender, connect(url) as recipient_a, connect(url) as recipient_b:
					await verify_and_bind_session(sender, SENDER_STUDENT_ID)
					await verify_and_bind_session(recipient_a, RECIPIENT_STUDENT_ID)
					await verify_and_bind_session(recipient_b, RECIPIENT_STUDENT_ID)

					message_frame = {
						"type": "message",
						"client_msg_id": "c1-disconnect",
						"source": SENDER_STUDENT_ID,
						"destination": RECIPIENT_STUDENT_ID,
						"ack_required": 2,
						"payload": build_valid_kiss_payload_hex(),
					}

					await sender.send(json.dumps(message_frame))

					await asyncio.wait_for(recipient_a.recv(), 2)
					await asyncio.wait_for(recipient_b.recv(), 2)

					received_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					received_frame = cast("dict[str, object]", json.loads(received_raw))
					received_payload = cast("dict[str, object]", received_frame["payload"])
					ack_for = cast("str", received_payload["ack_for"])
					assert received_payload["status"] == "received"

					await recipient_a.close()

					with pytest.raises(asyncio.TimeoutError):
						await asyncio.wait_for(sender.recv(), 0.3)

					recipient_b_ack = {
						"type": "ack",
						"source": RECIPIENT_STUDENT_ID,
						"destination": SENDER_STUDENT_ID,
						"ack_required": 0,
						"payload": {
							"ack_for": ack_for,
							"status": "processed",
						},
					}
					await recipient_b.send(json.dumps(recipient_b_ack))

					forwarded_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					forwarded_frame = cast("dict[str, object]", json.loads(forwarded_raw))
					forwarded_payload = cast("dict[str, object]", forwarded_frame["payload"])
					assert forwarded_payload["ack_for"] == ack_for
					assert forwarded_payload["status"] == "processed"

					failed_raw = cast("str", await asyncio.wait_for(sender.recv(), 2))
					failed_frame = cast("dict[str, object]", json.loads(failed_raw))
					failed_payload = cast("dict[str, object]", failed_frame["payload"])
					assert failed_payload["ack_for"] == ack_for
					assert failed_payload["status"] == "failed"
		finally:
			store.close()

	asyncio.run(run_test())


def test_resolve_direwolf_client_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv(server.DIREWOLF_ENABLED_ENV, "0")
	assert server.resolve_direwolf_client() is None

	monkeypatch.setenv(server.DIREWOLF_ENABLED_ENV, "1")
	monkeypatch.setenv(server.DIREWOLF_HOST_ENV, "example.local")
	monkeypatch.setenv(server.DIREWOLF_PORT_ENV, "9001")
	client = server.resolve_direwolf_client()
	assert client is not None
	assert client.host == "example.local"
	assert client.port == 9001

	monkeypatch.setenv(server.DIREWOLF_PORT_ENV, "not-a-number")
	client_with_invalid_port = server.resolve_direwolf_client()
	assert client_with_invalid_port is not None
	assert client_with_invalid_port.port == server.DEFAULT_KISS_PORT
