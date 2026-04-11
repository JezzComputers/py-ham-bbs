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

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function parseTimeLabel(value: unknown): string {
	if (typeof value !== "string") {
		return new Date().toISOString();
	}

	const parsed = new Date(value);
	if (Number.isNaN(parsed.getTime())) {
		return value;
	}

	return parsed.toISOString();
}

function summarizePayload(payload: unknown): string {
	if (typeof payload === "string") {
		const decodedRadioText = decodeRadioPayload(payload);
		if (decodedRadioText !== null) {
			return `radio: ${decodedRadioText}`;
		}
		return payload;
	}

	if (!isRecord(payload)) {
		return String(payload);
	}

	const subtype = payload.subtype;
	const content = payload.content;
	if (typeof subtype === "string" && isRecord(content) && typeof content.message === "string") {
		return `${subtype}: ${content.message}`;
	}

	try {
		const serialized = JSON.stringify(payload);
		return serialized.length > 180 ? `${serialized.slice(0, 180)}...` : serialized;
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

		const time = parseTimeLabel(parsed.timestamp);
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

function parseCallsignAndSsid(stationId: string): { callsign: string; ssid: number } | null {
	const normalized = stationId.trim().toUpperCase();
	const match = CALLSIGN_WITH_SSID_RE.exec(normalized);
	if (match === null) {
		return null;
	}

	const ssid = Number.parseInt(match[2], 10);
	if (Number.isNaN(ssid) || ssid < 0 || ssid > 15) {
		return null;
	}

	return {
		callsign: match[1],
		ssid,
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

function buildAx25Frame(text: string, sourceCallsign: string, destinationCallsign: string): Uint8Array | null {
	const source = parseCallsignAndSsid(sourceCallsign);
	const destination = parseCallsignAndSsid(destinationCallsign);
	if (source === null || destination === null) {
		return null;
	}

	const destinationAddress = encodeAddress(destination.callsign, destination.ssid, false);
	const sourceAddress = encodeAddress(source.callsign, source.ssid, true);
	const control = [0x03];
	const pid = [0x01];
	const payload = Array.from(new TextEncoder().encode(text));
	return new Uint8Array([...destinationAddress, ...sourceAddress, ...control, ...pid, ...payload]);
}

function buildKissFrame(ax25Frame: Uint8Array): Uint8Array {
	const output: number[] = [FEND, 0x00];
	for (const byte of ax25Frame) {
		if (byte === FEND) {
			output.push(FESC, TFEND);
			continue;
		}
		if (byte === FESC) {
			output.push(FESC, TFESC);
			continue;
		}
		output.push(byte);
	}
	output.push(FEND);
	return new Uint8Array(output);
}

function bytesToHex(bytes: Uint8Array): string {
	return Array.from(bytes)
		.map((byte) => byte.toString(16).padStart(2, "0"))
		.join("");
}

function hexToBytes(hex: string): Uint8Array | null {
	if (hex.length % 2 !== 0 || !/^[0-9A-Fa-f]+$/.test(hex)) {
		return null;
	}

	const bytes = new Uint8Array(hex.length / 2);
	for (let index = 0; index < bytes.length; index += 1) {
		bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
	}
	return bytes;
}

function decodeCall(address: Uint8Array): string {
	const callsign = String.fromCharCode(...address.slice(0, 6).map((byte) => byte >> 1)).trim();
	const ssid = (address[6] >> 1) & 0x0f;
	return `${callsign}-${ssid}`;
}

function decodeKissFrame(kissFrame: Uint8Array): Uint8Array | null {
	if (kissFrame.length < 4 || kissFrame[0] !== FEND || kissFrame[kissFrame.length - 1] !== FEND) {
		return null;
	}

	const command = kissFrame[1] & 0x0f;
	if (command !== 0x00) {
		return null;
	}

	const payload = kissFrame.slice(2, -1);
	const decoded: number[] = [];
	for (let index = 0; index < payload.length; index += 1) {
		const byte = payload[index];
		if (byte === FESC && index + 1 < payload.length) {
			const next = payload[index + 1];
			if (next === TFEND) {
				decoded.push(FEND);
				index += 1;
				continue;
			}
			if (next === TFESC) {
				decoded.push(FESC);
				index += 1;
				continue;
			}
		}
		decoded.push(byte);
	}
	return new Uint8Array(decoded);
}

function decodeRadioPayload(payloadHex: string): string | null {
	const kissFrame = hexToBytes(payloadHex);
	if (kissFrame === null) {
		return null;
	}

	const ax25Frame = decodeKissFrame(kissFrame);
	if (ax25Frame === null || ax25Frame.length < 16) {
		return null;
	}

	let addressIndex = 0;
	const addresses: Uint8Array[] = [];
	while (addressIndex + 7 <= ax25Frame.length) {
		const address = ax25Frame.slice(addressIndex, addressIndex + 7);
		addresses.push(address);
		addressIndex += 7;
		if ((address[6] & 0x01) === 1) {
			break;
		}
	}

	if (addresses.length < 2 || addressIndex + 2 > ax25Frame.length) {
		return null;
	}

	const source = decodeCall(addresses[1]);
	const destination = decodeCall(addresses[0]);
	const payload = ax25Frame.slice(addressIndex + 2);
	const text = new TextDecoder().decode(payload);
	return `${source} -> ${destination} ${text}`;
}

function appendLine(current: string, line: string): string {
	const updated = current === "" ? line : `${current}\n${line}`;
	const lines = updated.split("\n");
	if (lines.length <= 300) {
		return updated;
	}
	return lines.slice(lines.length - 300).join("\n");
}

function toBindFrame(sourceCallsign: string): string {
	return JSON.stringify({
		type: "control",
		source: sourceCallsign,
		destination: sourceCallsign,
		ack_required: 0,
		payload: {
			subtype: "bind",
			content: {
				callsign: sourceCallsign,
			},
		},
	});
}

function toMessageFrame(text: string, sourceCallsign: string, destinationCallsign: string): string | null {
	const ax25Frame = buildAx25Frame(text, sourceCallsign, destinationCallsign);
	if (ax25Frame === null) {
		return null;
	}

	const kissFrame = buildKissFrame(ax25Frame);
	const payloadHex = bytesToHex(kissFrame);

	return JSON.stringify({
		type: "message",
		source: sourceCallsign,
		destination: destinationCallsign,
		ack_required: 0,
		payload: payloadHex,
	});
}

export function usePlainSocket(url: string, sourceCallsign: string, destinationCallsign: string): PlainSocketState {
	const websocketRef = useRef<WebSocket | null>(null);
	const [inboundText, setInboundText] = useState("");
	const [connectionCycle, setConnectionCycle] = useState(0);

	const pushLog = useCallback((line: string): void => {
		setInboundText((current) => appendLine(current, line));
	}, []);

	const sendText = useCallback((text: string): void => {
		const websocket = websocketRef.current;
		if (websocket === null || websocket.readyState !== WebSocket.OPEN) {
			pushLog(`${new Date().toISOString()} OUT DROP socket-not-open`);
			return;
		}

		const packet = toMessageFrame(text, sourceCallsign, destinationCallsign);
		if (packet === null) {
			pushLog(`${new Date().toISOString()} OUT DROP invalid-callsign`);
			return;
		}
		websocket.send(packet);
		pushLog(formatPacketLog("OUT", packet));
	}, [destinationCallsign, pushLog, sourceCallsign]);

	useEffect(() => {
		const onPageHide = (): void => {
			const websocket = websocketRef.current;
			if (websocket !== null && websocket.readyState === WebSocket.OPEN) {
				websocket.close();
			}
		};

		const onPageShow = (event: PageTransitionEvent): void => {
			if (event.persisted) {
				setConnectionCycle((current) => current + 1);
			}
		};

		window.addEventListener("pagehide", onPageHide);
		window.addEventListener("pageshow", onPageShow);

		return () => {
			window.removeEventListener("pagehide", onPageHide);
			window.removeEventListener("pageshow", onPageShow);
		};
	}, []);

	useEffect(() => {
		const websocket = new WebSocket(url);
		let disposed = false;
		websocketRef.current = websocket;

		websocket.onopen = () => {
			if (!disposed) {
				const bindPacket = toBindFrame(sourceCallsign);
				websocket.send(bindPacket);
				pushLog(formatPacketLog("OUT", bindPacket));
				return;
			}
			websocket.close();
		};

		websocket.onmessage = (event) => {
			if (typeof event.data !== "string") {
				return;
			}

			pushLog(formatPacketLog("IN", event.data));
		};

		return () => {
			disposed = true;

			if (websocket.readyState === WebSocket.OPEN) {
				websocket.close();
			}

			if (websocketRef.current === websocket) {
				websocketRef.current = null;
			}
		};
	}, [connectionCycle, pushLog, sourceCallsign, url]);

	return {
		inboundText,
		sendText,
	};
}

