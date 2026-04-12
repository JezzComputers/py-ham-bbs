import { useCallback, useEffect, useRef, useState } from "react";

export interface PlainSocketState {
	inboundText: string;
	sendText: (text: string) => void;
}

type PacketDirection = "IN" | "OUT";

const FEND = 0xc0;
const FESC = 0xdb;
const TFEND = 0xdc;
const TFESC = 0xdd;
const CALLSIGN_WITH_SSID_RE = /^([A-Z0-9]{1,6})-(\d{1,2})$/;
const MAX_LOG_LINES = 300;
const MAX_PAYLOAD_PREVIEW = 180;

interface StationId {
	callsign: string;
	ssid: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function normalizeStationId(value: string): string | null {
	const normalized = value.trim().toUpperCase();
	const match = CALLSIGN_WITH_SSID_RE.exec(normalized);
	if (match === null) {
		return null;
	}

	const ssid = Number.parseInt(match[2], 10);
	if (Number.isNaN(ssid) || ssid < 0 || ssid > 15) {
		return null;
	}

	return `${match[1]}-${ssid}`;
}

function parseStationId(stationId: string): StationId | null {
	const normalized = normalizeStationId(stationId);
	if (normalized === null) {
		return null;
	}

	const match = CALLSIGN_WITH_SSID_RE.exec(normalized);
	if (match === null) {
		return null;
	}

	return {
		callsign: match[1],
		ssid: Number.parseInt(match[2], 10),
	};
}

function encodeAddress(callsign: string, ssid: number, isLast: boolean): number[] {
	const padded = callsign.padEnd(6, " ").slice(0, 6);
	const encoded = Array.from(padded).map((char) => (char.charCodeAt(0) << 1) & 0xfe);
	let ssidByte = 0x60 | ((ssid & 0x0f) << 1);
	if (isLast) {
		ssidByte |= 0x01;
	}
	encoded.push(ssidByte);
	return encoded;
}

function bytesToHex(bytes: Uint8Array): string {
	return Array.from(bytes)
		.map((byte) => byte.toString(16).padStart(2, "0"))
		.join("");
}

function encodeMessagePayload(text: string, sourceStationId: string, destinationStationId: string): string | null {
	const source = parseStationId(sourceStationId);
	const destination = parseStationId(destinationStationId);
	if (source === null || destination === null) {
		return null;
	}

	const ax25: number[] = [
		...encodeAddress(destination.callsign, destination.ssid, false),
		...encodeAddress(source.callsign, source.ssid, true),
		0x03,
		0x01,
		...Array.from(new TextEncoder().encode(text)),
	];

	const escapedKiss: number[] = [FEND, 0x00];
	for (const byte of ax25) {
		if (byte === FEND) {
			escapedKiss.push(FESC, TFEND);
			continue;
		}
		if (byte === FESC) {
			escapedKiss.push(FESC, TFESC);
			continue;
		}
		escapedKiss.push(byte);
	}
	escapedKiss.push(FEND);

	return bytesToHex(new Uint8Array(escapedKiss));
}

function summarizePayload(payload: unknown): string {
	if (typeof payload === "string") {
		return payload.length > MAX_PAYLOAD_PREVIEW ? `${payload.slice(0, MAX_PAYLOAD_PREVIEW)}...` : payload;
	}

	if (!isRecord(payload)) {
		return String(payload);
	}

	try {
		const serialized = JSON.stringify(payload);
		return serialized.length > MAX_PAYLOAD_PREVIEW ? `${serialized.slice(0, MAX_PAYLOAD_PREVIEW)}...` : serialized;
	} catch {
		return "[payload unavailable]";
	}
}

function formatPacketLog(direction: PacketDirection, packetText: string): string {
	try {
		const parsed = JSON.parse(packetText) as unknown;
		if (!isRecord(parsed)) {
			return `${new Date().toISOString()} ${direction} RAW ${packetText}`;
		}

		const time = typeof parsed.timestamp === "string" ? parsed.timestamp : new Date().toISOString();
		const type = typeof parsed.type === "string" ? parsed.type : "unknown";
		const source = typeof parsed.source === "string" ? parsed.source : "?";
		const destination = typeof parsed.destination === "string" ? parsed.destination : "?";
		const ackRequired = typeof parsed.ack_required === "number" ? String(parsed.ack_required) : "?";
		const payloadSummary = summarizePayload(parsed.payload);
		return `${time} ${direction} ${type} ${source} -> ${destination} ack=${ackRequired} ${payloadSummary}`;
	} catch {
		return `${new Date().toISOString()} ${direction} RAW ${packetText}`;
	}
}

function appendLine(current: string, line: string): string {
	const updated = current === "" ? line : `${current}\n${line}`;
	const lines = updated.split("\n");
	if (lines.length <= MAX_LOG_LINES) {
		return updated;
	}
	return lines.slice(lines.length - MAX_LOG_LINES).join("\n");
}

function toBindFrame(sourceCallsign: string): string | null {
	const source = normalizeStationId(sourceCallsign);
	if (source === null) {
		return null;
	}

	return JSON.stringify({
		type: "control",
		source,
		destination: source,
		ack_required: 0,
		payload: {
			subtype: "bind",
			content: {
				callsign: source,
			},
		},
	});
}

function toMessageFrame(text: string, sourceCallsign: string, destinationCallsign: string, clientMsgId: string): string | null {
	const source = normalizeStationId(sourceCallsign);
	const destination = normalizeStationId(destinationCallsign);
	if (source === null || destination === null) {
		return null;
	}

	const payloadHex = encodeMessagePayload(text, source, destination);
	if (payloadHex === null) {
		return null;
	}

	return JSON.stringify({
		type: "message",
		client_msg_id: clientMsgId,
		source,
		destination: destination,
		ack_required: 0,
		payload: payloadHex,
	});
}

function toAckFrame(incomingPacket: string, localSourceCallsign: string, clientMsgId: string): string | null {
	let parsedUnknown: unknown;
	try {
		parsedUnknown = JSON.parse(incomingPacket) as unknown;
	} catch {
		return null;
	}

	if (!isRecord(parsedUnknown) || parsedUnknown.type !== "message") {
		return null;
	}

	const ackRequired = parsedUnknown.ack_required;
	if (typeof ackRequired !== "number" || ackRequired === 0) {
		return null;
	}

	const ackFor = parsedUnknown.id;
	const destinationSource = parsedUnknown.source;
	if (typeof ackFor !== "string" || typeof destinationSource !== "string") {
		return null;
	}

	const source = normalizeStationId(localSourceCallsign);
	const destination = normalizeStationId(destinationSource);
	if (source === null || destination === null) {
		return null;
	}

	const payload: Record<string, unknown> = {
		ack_for: ackFor,
		status: "processed",
	};
	if (typeof parsedUnknown.client_msg_id === "string") {
		payload.client_msg_id = parsedUnknown.client_msg_id;
	}

	return JSON.stringify({
		type: "ack",
		client_msg_id: clientMsgId,
		source,
		destination,
		ack_required: 0,
		payload,
	});
}

export function usePlainSocket(url: string, sourceCallsign: string, destinationCallsign: string): PlainSocketState {
	const websocketRef = useRef<WebSocket | null>(null);
	const clientCounterRef = useRef(0);
	const [inboundText, setInboundText] = useState("");

	const pushLog = useCallback((line: string): void => {
		setInboundText((current) => appendLine(current, line));
	}, []);

	const nextClientMsgId = useCallback((): string => {
		clientCounterRef.current += 1;
		return `web-${Date.now()}-${clientCounterRef.current}`;
	}, []);

	const sendText = useCallback((text: string): void => {
		const websocket = websocketRef.current;
		if (websocket === null || websocket.readyState !== WebSocket.OPEN) {
			pushLog(`${new Date().toISOString()} OUT DROP socket-not-open`);
			return;
		}

		const packet = toMessageFrame(text, sourceCallsign, destinationCallsign, nextClientMsgId());
		if (packet === null) {
			pushLog(`${new Date().toISOString()} OUT DROP invalid-callsign`);
			return;
		}
		websocket.send(packet);
		pushLog(formatPacketLog("OUT", packet));
	}, [destinationCallsign, nextClientMsgId, pushLog, sourceCallsign]);

	useEffect(() => {
		const websocket = new WebSocket(url);
		websocketRef.current = websocket;

		websocket.onopen = () => {
			const bindPacket = toBindFrame(sourceCallsign);
			if (bindPacket === null) {
				pushLog(`${new Date().toISOString()} OUT DROP invalid-callsign`);
				return;
			}
			websocket.send(bindPacket);
			pushLog(formatPacketLog("OUT", bindPacket));
		};

		websocket.onmessage = (event) => {
			if (typeof event.data !== "string") {
				return;
			}

			pushLog(formatPacketLog("IN", event.data));

			const ackPacket = toAckFrame(event.data, sourceCallsign, nextClientMsgId());
			if (ackPacket === null) {
				return;
			}
			websocket.send(ackPacket);
			pushLog(formatPacketLog("OUT", ackPacket));
		};

		return () => {
			try {
				if (websocket.readyState !== WebSocket.CLOSED) {
					websocket.close();
				}
			} catch {
				// ignore
			}

			if (websocketRef.current === websocket) {
				websocketRef.current = null;
			}
		};
	}, [nextClientMsgId, pushLog, sourceCallsign, url]);

	return {
		inboundText,
		sendText,
	};
}

