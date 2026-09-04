import { createSocketClient, normalizeStationId, formatNowISO8601 } from "./websocketClient";

const studentIdInput = document.getElementById("student-id") as HTMLInputElement | null;
const destInput = document.getElementById("destination-callsign") as HTMLInputElement | null;
const outboundInput = document.getElementById("outbound-message") as HTMLInputElement | null;
const verifyBtn = document.getElementById("verify-button") as HTMLButtonElement | null;
const verifyStatus = document.getElementById("verify-status") as HTMLSpanElement | null;
const logArea = document.getElementById("packet-log") as HTMLTextAreaElement | null;
const MAX_LOG_LINES = 300;

if (!studentIdInput || !destInput || !outboundInput || !verifyBtn || !verifyStatus || !logArea) {
	throw new Error("App controls were not found in the page markup.");
}

const socketProtocol = location.protocol === "https:" ? "wss" : "ws";
const socketUrl = `${socketProtocol}://${location.host}/ws`;
let logBuffer = "";
let verifiedStudentId: string | null = null;
let verifiedSource: string | null = null;
let verifiedDestination: string | null = null;

type VerificationState = "idle" | "verified" | "invalid";

const verificationLabels: Record<VerificationState, string> = {
	idle: "Student ID not verified.",
	verified: "Student ID verified.",
	invalid: "Student ID verification failed.",
};

const verificationGlyphs: Record<VerificationState, string> = {
	idle: "—",
	verified: "✓",
	invalid: "✕",
};

let verificationState: VerificationState = "idle";

function appendLine(current: string, line: string): string {
	const updated = current === "" ? line : `${current}\n${line}`;
	const lines = updated.split("\n");
	if (lines.length <= MAX_LOG_LINES) {
		return updated;
	}
	return lines.slice(lines.length - MAX_LOG_LINES).join("\n");
}

const appendLogLine = (line: string): void => {
	logBuffer = appendLine(logBuffer, line);
	logArea.value = logBuffer;
	logArea.scrollTop = logArea.scrollHeight;
};

const setVerificationIndicator = (state: VerificationState, label: string = verificationLabels[state]): void => {
	verificationState = state;
	verifyStatus.dataset.state = state;
	verifyStatus.textContent = verificationGlyphs[state];
	verifyStatus.setAttribute("aria-label", label);
	verifyStatus.title = label;
};

const syncVerificationIndicator = (): void => {
	const currentStudentId = normalizeStationId(studentIdInput.value);
	const currentDestination = normalizeStationId(destInput.value);

	if (
		verifiedStudentId !== null
		&& verifiedSource !== null
		&& verifiedDestination !== null
		&& currentStudentId === verifiedStudentId
		&& currentDestination === verifiedDestination
	)
	{
		setVerificationIndicator("verified", `Student ID ${verifiedStudentId} verified.`);
		return;
	}

	setVerificationIndicator("idle");
};

const currentRouteIsVerified = (): boolean => {
	const currentStudentId = normalizeStationId(studentIdInput.value);
	const currentDestination = normalizeStationId(destInput.value);
	return verifiedStudentId !== null && verifiedSource !== null && verifiedDestination !== null && currentStudentId === verifiedStudentId && currentDestination === verifiedDestination;
};

const socketClient = createSocketClient(socketUrl, {
	onLogLine: (line: string) => {
		appendLogLine(line);
	},
	onStatus: (line: string) => {
		const message = `${formatNowISO8601()} STATUS ${line}`;
		console.log(message);
		appendLogLine(message);
	},
});

const appendStatus = (line: string): void => {
	const message = `${formatNowISO8601()} INFO ${line}`;
	console.log(message);
	appendLogLine(message);
};

const markRouteDirty = (): void => {
	syncVerificationIndicator();
};

studentIdInput.addEventListener("input", markRouteDirty);
destInput.addEventListener("input", markRouteDirty);

verifyBtn.addEventListener("click", () => {
	void (async () => {
		const studentId = studentIdInput.value.trim();
		const normalizedStudentId = normalizeStationId(studentId);
		const normalizedDestination = normalizeStationId(destInput.value);
		if (normalizedStudentId === null || normalizedDestination === null) {
			setVerificationIndicator("invalid", "Verification failed: enter a valid student ID/callsign and a destination callsign like VK3ABC or VK3ABC-0.");
			appendStatus("Verification failed: enter a valid student ID/callsign and a destination callsign like VK3ABC or VK3ABC-0.");
			return;
		}

		try {
			const verifiedSourceCallsign = await socketClient.verifyStudentId(normalizedStudentId);
			verifiedStudentId = verifiedSourceCallsign;
			verifiedSource = verifiedSourceCallsign;
			verifiedDestination = normalizedDestination;
			socketClient.setRoute(verifiedSourceCallsign, normalizedDestination);
			setVerificationIndicator("verified", `Student ID ${verifiedSourceCallsign} verified.`);
			appendStatus(`Verified student ID ${verifiedSourceCallsign} for destination ${normalizedDestination}.`);
		} catch (error) {
			verifiedStudentId = null;
			verifiedSource = null;
			verifiedDestination = null;
			const message = error instanceof Error ? error.message : String(error);
			setVerificationIndicator("invalid", `Verification failed: ${message}`);
			appendStatus(`Verification failed: ${message}`);
		}
	})();
});

outboundInput.addEventListener("keydown", (event) => {
	if (event.key !== "Enter") {
		return;
	}

	event.preventDefault();
	const text = outboundInput.value.trim();
	if (text === "") {
		return;
	}

	if (!currentRouteIsVerified() || verificationState !== "verified") {
		appendStatus("Verify the student ID before sending.");
		return;
	}

	socketClient.sendText(text);
	outboundInput.value = "";
});

syncVerificationIndicator();

window.addEventListener("beforeunload", () => {
	socketClient.dispose();
});
