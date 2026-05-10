import { createSocketClient, normalizeStationId, formatNowISO8601 } from "./websocketClient";

const srcInput = document.getElementById("source-callsign") as HTMLInputElement | null;
const destInput = document.getElementById("destination-callsign") as HTMLInputElement | null;
const outboundInput = document.getElementById("outbound-message") as HTMLInputElement | null;
const verifyBtn = document.getElementById("verify-button") as HTMLButtonElement | null;
const verifyStatus = document.getElementById("verify-status") as HTMLSpanElement | null;
const logArea = document.getElementById("packet-log") as HTMLTextAreaElement | null;
const MAX_LOG_LINES = 300;

if (!srcInput || !destInput || !outboundInput || !verifyBtn || !verifyStatus || !logArea) {
	throw new Error("App controls were not found in the page markup.");
}

const socketProtocol = location.protocol === "https:" ? "wss" : "ws";
const socketUrl = `${socketProtocol}://${location.host}/ws`;
let logBuffer = "";
let verifiedSource: string | null = null;
let verifiedDestination: string | null = null;

type VerificationState = "idle" | "verified" | "invalid";

const verificationLabels: Record<VerificationState, string> = {
	idle: "Route not verified.",
	verified: "Route verified.",
	invalid: "Verification failed.",
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
	const currentSource = normalizeStationId(srcInput.value);
	const currentDestination = normalizeStationId(destInput.value);

	if (verifiedSource !== null && verifiedDestination !== null && currentSource === verifiedSource && currentDestination === verifiedDestination) {
		setVerificationIndicator("verified", `Route verified as ${verifiedSource} to ${verifiedDestination}.`);
		return;
	}

	setVerificationIndicator("idle");
};

const currentRouteIsVerified = (): boolean => {
	const currentSource = normalizeStationId(srcInput.value);
	const currentDestination = normalizeStationId(destInput.value);
	return verifiedSource !== null && verifiedDestination !== null && currentSource === verifiedSource && currentDestination === verifiedDestination;
};

const socketClient = createSocketClient(socketUrl, srcInput.value, destInput.value, {
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

srcInput.addEventListener("input", markRouteDirty);
destInput.addEventListener("input", markRouteDirty);

verifyBtn.addEventListener("click", () => {
	const normalizedSource = normalizeStationId(srcInput.value);
	const normalizedDestination = normalizeStationId(destInput.value);
	if (normalizedSource === null || normalizedDestination === null) {
		setVerificationIndicator("invalid", "Verification failed: source and destination must include a callsign and SSID like VK3ABC-0.");
		appendStatus("Verification failed: source and destination must include a callsign and SSID like VK3ABC-0.");
		return;
	}

	verifiedSource = normalizedSource;
	verifiedDestination = normalizedDestination;
	srcInput.value = normalizedSource;
	destInput.value = normalizedDestination;
	socketClient.setRoute(normalizedSource, normalizedDestination);
	setVerificationIndicator("verified", `Route verified as ${normalizedSource} to ${normalizedDestination}.`);
	appendStatus(`Verified route: source ${normalizedSource}, destination ${normalizedDestination}.`);
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
		appendStatus("Verify the callsigns before sending.");
		return;
	}

	socketClient.sendText(text);
	outboundInput.value = "";
});

syncVerificationIndicator();

window.addEventListener("beforeunload", () => {
	socketClient.dispose();
});
