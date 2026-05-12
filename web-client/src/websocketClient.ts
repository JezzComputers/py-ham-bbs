const FEND = 0xc0;
const FESC = 0xdb;
const TFEND = 0xdc;
const TFESC = 0xdd;
const CALLSIGN_WITH_SSID_RE = /^([A-Z0-9]{1,6})(?:-(\d{1,2}))?$/;
const MAX_PAYLOAD_PREVIEW = 180;
const PROTOCOL_SERVER_SOURCE = "SERVER-0";

type PacketDirection = "IN" | "OUT";

interface SocketCallbacks {
	onLogLine: (line: string) => void;
	onStatus: (line: string) => void;
}

interface StationId {
	callsign: string;
	ssid: number;
}

interface SocketClient {
	verifyStudentId: (studentId: string) => Promise<string>;
	setRoute: (sourceCallsign: string, destinationCallsign: string) => void;
	sendText: (text: string) => void;
	dispose: () => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

export function formatNowISO8601(): string {
	const now = new Date();
	
	// Get local time components
	const year = now.getFullYear();
	const month = String(now.getMonth() + 1).padStart(2, '0');
	const date = String(now.getDate()).padStart(2, '0');
	const hours = String(now.getHours()).padStart(2, '0');
	const minutes = String(now.getMinutes()).padStart(2, '0');
	const seconds = String(now.getSeconds()).padStart(2, '0');
	const ms = String(now.getMilliseconds()).padStart(3, '0');
	
	// Calculate timezone offset
	const offset = -now.getTimezoneOffset();
	const offsetSign = offset >= 0 ? '+' : '-';
	const offsetHours = String(Math.trunc(Math.abs(offset) / 60)).padStart(2, '0');
	const offsetMinutes = String(Math.abs(offset % 60)).padStart(2, '0');
	
	return `${year}-${month}-${date}T${hours}:${minutes}:${seconds}.${ms}${offsetSign}${offsetHours}:${offsetMinutes}`;
}

export function normalizeStationId(value: string): string | null {
	const normalized = value.trim().toUpperCase();
	const match = CALLSIGN_WITH_SSID_RE.exec(normalized);
	if (match === null) {
		return null;
	}

	const callsign = match[1];
	const ssidText = match[2];
	if (callsign === undefined) {
		return null;
	}
	const ssid = ssidText === undefined ? 0 : Number.parseInt(ssidText, 10);
	if (Number.isNaN(ssid) || ssid < 0 || ssid > 15) {
		return null;
	}

	return `${callsign}-${ssid}`;
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

	const callsign = match[1];
	const ssidText = match[2];
	if (callsign === undefined || ssidText === undefined) {
		return null;
	}

	return {
		callsign,
		ssid: Number.parseInt(ssidText, 10),
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
			return `${formatNowISO8601()} ${direction} RAW ${packetText}`;
		}

		const time = typeof parsed.timestamp === "string" ? parsed.timestamp : formatNowISO8601();
		const type = typeof parsed.type === "string" ? parsed.type : "unknown";
		const source = typeof parsed.source === "string" ? parsed.source : "?";
		const destination = typeof parsed.destination === "string" ? parsed.destination : "?";
		const ackRequired = typeof parsed.ack_required === "number" ? String(parsed.ack_required) : "?";
		const payloadSummary = summarizePayload(parsed.payload);
		return `${time} ${direction} ${type} ${source} → ${destination} ack=${ackRequired} ${payloadSummary}`;
	} catch {
		return `${formatNowISO8601()} ${direction} RAW ${packetText}`;
	}
}

function toBindFrame(sourceCallsign: string): string | null {
	const source = normalizeStationId(sourceCallsign);
	if (source === null) {
		return null;
	}

	return JSON.stringify({
		type: "control",
		source,
		destination: PROTOCOL_SERVER_SOURCE,
		ack_required: 0,
		payload: {
			subtype: "bind",
			content: {
				callsign: source,
			},
		},
	});
}

function toVerifyFrame(studentId: string, clientMsgId: string): string | null {
	const normalizedStudentId = normalizeStationId(studentId);
	if (normalizedStudentId === null) {
		return null;
	}

	return JSON.stringify({
		type: "control",
		client_msg_id: clientMsgId,
		source: PROTOCOL_SERVER_SOURCE,
		destination: PROTOCOL_SERVER_SOURCE,
		ack_required: 0,
		payload: {
			subtype: "verify",
			content: {
				student_id: normalizedStudentId,
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
		destination,
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

export function createSocketClient(url: string, callbacks: SocketCallbacks): SocketClient {
	let assignedSource: string | null = null;
	let assignedDestination: string | null = null;
	let boundSource: string | null = null;
	let socketGeneration = 0;
	let socket: WebSocket | null = null;
	let clientCounter = 0;
	let pendingVerification: {
		studentId: string;
		clientMsgId: string;
		resolve: (sourceCallsign: string) => void;
		reject: (error: Error) => void;
	} | null = null;

	const nextClientMsgId = (): string => {
		clientCounter += 1;
		return `web-${Date.now()}-${clientCounter}`;
	};

	const pushLog = (line: string): void => {
		callbacks.onLogLine(line);
	};

	const rejectPendingVerification = (message: string): void => {
		const pending = pendingVerification;
		if (pending === null) {
			return;
		}

		pendingVerification = null;
		pending.reject(new Error(message));
	};

	const closeSocket = (): void => {
		const currentSocket = socket;
		socket = null;
		boundSource = null;
		if (currentSocket === null) {
			return;
		}

		try {
			currentSocket.close();
		} catch {
			// Ignore shutdown errors.
		}
	};

	const syncSocketBinding = (): void => {
		const currentSocket = socket;
		if (
			currentSocket === null
			|| currentSocket.readyState !== WebSocket.OPEN
			|| pendingVerification !== null
			|| assignedSource === null
		)
		{
			return;
		}

		if (boundSource === assignedSource) {
			return;
		}

		const bindFrame = toBindFrame(assignedSource);
		if (bindFrame === null) {
			pushLog(`${formatNowISO8601()} OUT DROP invalid-callsign`);
			return;
		}

		currentSocket.send(bindFrame);
		boundSource = assignedSource;
		pushLog(formatPacketLog("OUT", bindFrame));
		callbacks.onStatus(`Bound as ${assignedSource} and ready to relay messages.`);
	};

	const handleVerificationAck = (packetText: string): boolean => {
		let parsedUnknown: unknown;
		try {
			parsedUnknown = JSON.parse(packetText) as unknown;
		} catch {
			return true;
		}

		if (!isRecord(parsedUnknown) || parsedUnknown.type !== "ack") {
			return false;
		}

		const pending = pendingVerification;
		if (pending === null) {
			return false;
		}

		const packetClientMsgId = typeof parsedUnknown.client_msg_id === "string" ? parsedUnknown.client_msg_id : null;
		const payload = isRecord(parsedUnknown.payload) ? parsedUnknown.payload : null;
		const payloadClientMsgId = typeof payload?.client_msg_id === "string" ? payload.client_msg_id : null;
		if (packetClientMsgId !== pending.clientMsgId && payloadClientMsgId !== pending.clientMsgId) {
			return true;
		}

		const status = typeof payload?.status === "string" ? payload.status : null;
		if (status === "processed") {
			pendingVerification = null;
			assignedSource = pending.studentId;
			boundSource = null;
			pending.resolve(pending.studentId);
			syncSocketBinding();
			return true;
		}

		if (status === "failed") {
			const reason = typeof payload?.reason === "string" ? payload.reason : "Student ID verification failed.";
			rejectPendingVerification(reason);
			return true;
		}

		rejectPendingVerification("Verification response was malformed.");
		return true;
	};

	const openSocket = (): void => {
		socketGeneration += 1;
		const generation = socketGeneration;
		closeSocket();
		callbacks.onStatus(`Opening websocket at ${url}.`);

		let nextSocket: WebSocket;
		try {
			nextSocket = new WebSocket(url);
		} catch (error) {
			callbacks.onStatus(`Unable to open websocket: ${String(error)}`);
			pushLog(`${formatNowISO8601()} OUT DROP websocket-open-failed`);
			rejectPendingVerification(`Unable to open websocket: ${String(error)}`);
			return;
		}

		socket = nextSocket;

		nextSocket.onopen = () => {
			if (generation !== socketGeneration || socket !== nextSocket) {
				return;
			}

			if (pendingVerification !== null) {
				const verifyFrame = toVerifyFrame(pendingVerification.studentId, pendingVerification.clientMsgId);
				if (verifyFrame === null) {
					rejectPendingVerification("Unable to build verification frame.");
					pushLog(`${formatNowISO8601()} OUT DROP invalid-student-id`);
					return;
				}

				nextSocket.send(verifyFrame);
				pushLog(formatPacketLog("OUT", verifyFrame));
				callbacks.onStatus(`Verifying student ID ${pendingVerification.studentId}.`);
				return;
			}

			syncSocketBinding();
			if (assignedSource === null) {
				callbacks.onStatus("Socket opened. Verify a student ID to continue.");
			}
		};

		nextSocket.onmessage = (event) => {
			if (generation !== socketGeneration || socket !== nextSocket) {
				return;
			}

			if (typeof event.data !== "string") {
				return;
			}

			pushLog(formatPacketLog("IN", event.data));

			if (pendingVerification !== null && handleVerificationAck(event.data)) {
				return;
			}

			const ackFrame = toAckFrame(event.data, assignedSource ?? "", nextClientMsgId());
			if (ackFrame === null) {
				return;
			}

			nextSocket.send(ackFrame);
			pushLog(formatPacketLog("OUT", ackFrame));
		};

		nextSocket.onclose = () => {
			if (generation !== socketGeneration || socket !== nextSocket) {
				return;
			}

			socket = null;
			boundSource = null;
			if (pendingVerification !== null) {
				rejectPendingVerification("Verification socket closed before it completed.");
			}
			callbacks.onStatus("Socket closed. Verify the student ID again to reconnect.");
		};

		nextSocket.onerror = () => {
			if (generation !== socketGeneration || socket !== nextSocket) {
				return;
			}

			callbacks.onStatus(`Websocket error at ${url}.`);
		};
	};

	const verifyStudentId = (studentId: string): Promise<string> => {
		const normalizedStudentId = normalizeStationId(studentId);
		if (normalizedStudentId === null) {
			return Promise.reject(new Error("Student ID must be a valid callsign like VK3ABC or VK3ABC-0."));
		}

		if (pendingVerification !== null) {
			const pending = pendingVerification;
			pendingVerification = null;
			pending.reject(new Error("A verification request is already in progress."));
		}

		assignedSource = null;
		assignedDestination = null;
		boundSource = null;
		closeSocket();

		return new Promise<string>((resolve, reject) => {
			pendingVerification = {
				studentId: normalizedStudentId,
				clientMsgId: nextClientMsgId(),
				resolve,
				reject,
			};
			openSocket();
		});
	};

	const setRoute = (nextSourceCallsign: string, nextDestinationCallsign: string): void => {
		const normalizedSource = normalizeStationId(nextSourceCallsign);
		const normalizedDestination = normalizeStationId(nextDestinationCallsign);
		if (normalizedSource === null || normalizedDestination === null) {
			pushLog(`${formatNowISO8601()} OUT DROP invalid-callsign`);
			return;
		}

		const currentSocket = socket;
		const sourceChanged = normalizedSource !== assignedSource;
		assignedSource = normalizedSource;
		assignedDestination = normalizedDestination;

		if (pendingVerification !== null) {
			return;
		}

		if (currentSocket === null || currentSocket.readyState !== WebSocket.OPEN) {
			openSocket();
			return;
		}

		if (boundSource !== null && sourceChanged && boundSource !== normalizedSource) {
			openSocket();
			return;
		}

		syncSocketBinding();
	};

	const sendText = (text: string): void => {
		const currentSocket = socket;
		if (
			currentSocket === null
			|| currentSocket.readyState !== WebSocket.OPEN
			|| assignedSource === null
			|| assignedDestination === null
			|| boundSource !== assignedSource
		)
		{
			pushLog(`${formatNowISO8601()} OUT DROP route-not-verified`);
			return;
		}

		const packet = toMessageFrame(text, assignedSource, assignedDestination, nextClientMsgId());
		if (packet === null) {
			pushLog(`${formatNowISO8601()} OUT DROP invalid-callsign`);
			return;
		}

		currentSocket.send(packet);
		pushLog(formatPacketLog("OUT", packet));
	};

	const dispose = (): void => {
		socketGeneration += 1;
		if (pendingVerification !== null) {
			const pending = pendingVerification;
			pendingVerification = null;
			pending.reject(new Error("Verification was cancelled."));
		}
		closeSocket();
	};

	return {
		verifyStudentId,
		setRoute,
		sendText,
		dispose,
	};
}