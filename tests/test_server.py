import asyncio
import json
from pathlib import Path
from typing import cast

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

import server
from lib.ax25 import AX25FrameBuilder, AX25FrameConfig
from lib.kiss import KISSFrameBuilder, KISSFrameConfig
from server import MessageRepository, MessageBrokerServer, parse_inbound_frame, InvalidFrameError


def build_valid_kiss_payload_hex() -> str:
	ax25_builder = AX25FrameBuilder(AX25FrameConfig("VK3ABC", 0, "VK3XYZ", 0))
	kiss_builder = KISSFrameBuilder(KISSFrameConfig(0x00))
	ax25_frame = ax25_builder.build_ax25_frame(b"Hello")
	return kiss_builder.build_kiss_frame(ax25_frame).hex()


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

	assert first_saved_id == "019d5332-1b4c-743c-9821-25ca99a09f0a"
	assert second_saved_id == first_saved_id

	stored_server_id = store.get_server_id("VK3XYZ-0", "c1-0001")

	assert stored_server_id == "019d5332-1b4c-743c-9821-25ca99a09f0a"
	store.close()


def test_protocol_server_routes_message_and_deduplicates_client_msg_id(tmp_path: Path) -> None:
	async def run_test() -> None:
		store = MessageRepository(tmp_path / "protocol-flow.db")
		protocol = MessageBrokerServer(store=store, server_source="SERVER-0")
		try:
			async with serve(protocol.handler, "127.0.0.1", 0) as ws_server:
				sockets = ws_server.sockets
				assert sockets is not None
				assert len(sockets) > 0
				port = int(sockets[0].getsockname()[1])
				url = f"ws://127.0.0.1:{port}"

				async with connect(url) as sender, connect(url) as recipient:
					bind_frame = {
						"type": "control",
						"source": "VK3ABC-0",
						"destination": "VK3XYZ-0",
						"ack_required": 0,
						"payload": {
							"subtype": "bind",
							"content": {"ready": True},
						},
					}
					await recipient.send(json.dumps(bind_frame))

					message_frame = {
						"type": "message",
						"client_msg_id": "c1-0001",
						"source": "VK3XYZ-0",
						"destination": "VK3ABC-0",
						"ack_required": 1,
						"payload": build_valid_kiss_payload_hex(),
					}

					await sender.send(json.dumps(message_frame))

					routed_raw = cast("str", await asyncio.wait_for(recipient.recv(), 2))
					routed_frame = cast("dict[str, object]", json.loads(routed_raw))
					assert routed_frame["type"] == "message"
					assert routed_frame["source"] == "VK3XYZ-0"
					assert routed_frame["destination"] == "VK3ABC-0"

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
					assert store.get_server_id("VK3XYZ-0", "c1-0001") == first_ack_for

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
		protocol = MessageBrokerServer(store=store, server_source="SERVER-0")
		try:
			async with serve(protocol.handler, "127.0.0.1", 0) as ws_server:
				sockets = ws_server.sockets
				assert sockets is not None
				assert len(sockets) > 0
				port = int(sockets[0].getsockname()[1])
				url = f"ws://127.0.0.1:{port}"

				async with connect(url) as sender, connect(url) as recipient:
					bind_frame = {
						"type": "control",
						"source": "VK3ABC-0",
						"destination": "VK3XYZ-0",
						"ack_required": 0,
						"payload": {
							"subtype": "bind",
							"content": {"ready": True},
						},
					}
					await recipient.send(json.dumps(bind_frame))

					message_frame = {
						"type": "message",
						"client_msg_id": "c1-0100",
						"source": "VK3XYZ-0",
						"destination": "VK3ABC-0",
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
						"source": "VK3ABC-0",
						"destination": "VK3XYZ-0",
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
					assert "VK3ABC-0" in by_source
					assert "SERVER-0" in by_source

					forwarded_payload = cast("dict[str, object]", by_source["VK3ABC-0"]["payload"])
					assert forwarded_payload["ack_for"] == ack_for
					assert forwarded_payload["status"] == "processed"

					server_payload = cast("dict[str, object]", by_source["SERVER-0"]["payload"])
					assert server_payload["ack_for"] == ack_for
					assert server_payload["status"] == "processed"
		finally:
			store.close()

	asyncio.run(run_test())


def test_protocol_server_expires_pending_ack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(server, "PENDING_ACK_TIMEOUT_SECONDS", 0.05)

	async def run_test() -> None:
		store = MessageRepository(tmp_path / "protocol-expiry.db")
		protocol = MessageBrokerServer(store=store, server_source="SERVER-0")
		try:
			async with serve(protocol.handler, "127.0.0.1", 0) as ws_server:
				sockets = ws_server.sockets
				assert sockets is not None
				assert len(sockets) > 0
				port = int(sockets[0].getsockname()[1])
				url = f"ws://127.0.0.1:{port}"

				async with connect(url) as sender, connect(url) as recipient:
					bind_frame = {
						"type": "control",
						"source": "VK3ABC-0",
						"destination": "VK3XYZ-0",
						"ack_required": 0,
						"payload": {
							"subtype": "bind",
							"content": {"ready": True},
						},
					}
					await recipient.send(json.dumps(bind_frame))

					message_frame = {
						"type": "message",
						"client_msg_id": "c1-timeout",
						"source": "VK3XYZ-0",
						"destination": "VK3ABC-0",
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
					assert forwarded_frame["source"] == "VK3ABC-0"
					forwarded_payload = cast("dict[str, object]", forwarded_frame["payload"])
					assert forwarded_payload["ack_for"] == ack_for
					assert forwarded_payload["status"] == "processed"

					with pytest.raises(asyncio.TimeoutError):
						await asyncio.wait_for(sender.recv(), 0.4)
		finally:
			store.close()

	asyncio.run(run_test())
