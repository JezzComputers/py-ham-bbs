import { useCallback, useEffect, useRef, useState } from "react";

export type FrameType = "message" | "ack" | "control" | "error";
export type SocketStatus = "connecting" | "open" | "closed" | "error";
export type LogDirection = "inbound" | "outbound" | "system";

export interface ProtocolFrame {
	type: FrameType;
	client_msg_id?: string;
	id?: string;
	timestamp?: string;
	source: string;
	destination: string;
	ack_required: number;
	payload: string | Record<string, unknown>;
}

export interface ProtocolLogEntry {
	sequence: number;
	direction: LogDirection;
	receivedAt: string;
	raw: string;
	parsed?: ProtocolFrame;
	parseError?: string;
}

export interface ProtocolSocketState {
	status: SocketStatus;
	entries: ProtocolLogEntry[];
	lastError: string | null;
	sendFrame: (frame: ProtocolFrame) => boolean;
	clearEntries: () => void;
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function isProtocolFrame(value: unknown): value is ProtocolFrame {
	if (!isObjectRecord(value)) {
		return false;
	}

	if (
		typeof value.type !== "string" ||
		(value.type !== "message" && value.type !== "ack" && value.type !== "control" && value.type !== "error")
	) {
		return false;
	}

	if (typeof value.source !== "string" || typeof value.destination !== "string") {
		return false;
	}

	if (typeof value.ack_required !== "number") {
		return false;
	}

	if (!(typeof value.payload === "string" || isObjectRecord(value.payload))) {
		return false;
	}

	if (value.client_msg_id !== undefined && typeof value.client_msg_id !== "string") {
		return false;
	}

	if (value.id !== undefined && typeof value.id !== "string") {
		return false;
	}

	if (value.timestamp !== undefined && typeof value.timestamp !== "string") {
		return false;
	}

	return true;
}

export function useProtocolSocket(url: string): ProtocolSocketState {
	const websocketRef = useRef<WebSocket | null>(null);
	const sequenceRef = useRef(0);

	const [status, setStatus] = useState<SocketStatus>("connecting");
	const [entries, setEntries] = useState<ProtocolLogEntry[]>([]);
	const [lastError, setLastError] = useState<string | null>(null);

	const appendEntry = useCallback(
		(direction: LogDirection, raw: string, parsed?: ProtocolFrame, parseError?: string): void => {
			sequenceRef.current += 1;
			const nextEntry: ProtocolLogEntry = {
				sequence: sequenceRef.current,
				direction,
				receivedAt: new Date().toISOString(),
				raw,
			};
			if (parsed !== undefined) {
				nextEntry.parsed = parsed;
			}
			if (parseError !== undefined) {
				nextEntry.parseError = parseError;
			}
			setEntries((current) => [nextEntry, ...current].slice(0, 300));
		},
		[],
	);

	const clearEntries = useCallback((): void => {
		setEntries([]);
	}, []);

	const sendFrame = useCallback(
		(frame: ProtocolFrame): boolean => {
			const websocket = websocketRef.current;
			const serializedFrame = JSON.stringify(frame);
			if (websocket === null || websocket.readyState !== WebSocket.OPEN) {
				const message = "WebSocket is not open. Unable to send frame.";
				setLastError(message);
				appendEntry("system", serializedFrame, undefined, message);
				return false;
			}

			websocket.send(serializedFrame);
			appendEntry("outbound", serializedFrame, frame);
			return true;
		},
		[appendEntry],
	);

	useEffect(() => {
		const websocket = new WebSocket(url);
		websocketRef.current = websocket;

		websocket.onopen = () => {
			setStatus("open");
			setLastError(null);
			appendEntry("system", `Connected to ${url}`);
		};

		websocket.onmessage = (event) => {
			if (typeof event.data !== "string") {
				appendEntry("system", "<binary>", undefined, "Binary frame ignored; protocol expects UTF-8 JSON text.");
				return;
			}

			try {
				const parsed = JSON.parse(event.data) as unknown;
				if (isProtocolFrame(parsed)) {
					appendEntry("inbound", event.data, parsed);
					return;
				}
				appendEntry("inbound", event.data, undefined, "Frame does not match the protocol envelope.");
			} catch {
				appendEntry("inbound", event.data, undefined, "Failed to parse inbound frame as JSON.");
			}
		};

		websocket.onerror = () => {
			setStatus("error");
			setLastError("WebSocket connection error.");
			appendEntry("system", "WebSocket error", undefined, "WebSocket connection error.");
		};

		websocket.onclose = (event) => {
			setStatus("closed");
			appendEntry("system", `Connection closed (${event.code}).`);
		};

		return () => {
			websocket.close();
			websocketRef.current = null;
		};
	}, [appendEntry, url]);

	return {
		status,
		entries,
		lastError,
		sendFrame,
		clearEntries,
	};
}

