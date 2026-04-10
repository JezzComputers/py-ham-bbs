import { useMemo, useState, type FormEvent } from "react";

import { type ProtocolFrame, type ProtocolLogEntry, useProtocolSocket } from "./websocketHook";

const STATION_PATTERN = /^([A-Z0-9]{1,6})-(\d{1,2})$/;
const HEX_PATTERN = /^[0-9A-Fa-f]+$/;
const DEFAULT_PAYLOAD = "c00086a240404040609c8e664040406003f048656c6c6fc0";

function normalizeStation(value: string): string {
  return value.trim().toUpperCase();
}

function isStationValid(value: string): boolean {
  const match = STATION_PATTERN.exec(value);
  if (match === null) {
    return false;
  }
  const ssid = Number.parseInt(match[2], 10);
  return ssid >= 0 && ssid <= 15;
}

function isPayloadValid(payload: string): boolean {
  if (payload.length < 2 || payload.length % 2 !== 0) {
    return false;
  }
  if (!HEX_PATTERN.test(payload)) {
    return false;
  }
  const lowered = payload.toLowerCase();
  return lowered.startsWith("c0") && lowered.endsWith("c0");
}

function formatClock(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function frameTag(entry: ProtocolLogEntry): string {
  if (entry.parsed === undefined) {
    return "unparsed";
  }
  return entry.parsed.type;
}

function App() {
  const socketUrl = useMemo(() => {
    const envUrl = import.meta.env.VITE_WS_URL;
    if (typeof envUrl === "string" && envUrl.trim() !== "") {
      return envUrl;
    }
    return "ws://localhost:8765";
  }, []);

  const { status, entries, lastError, sendFrame, clearEntries } = useProtocolSocket(socketUrl);

  const [clientMsgId, setClientMsgId] = useState("c1-0001");
  const [source, setSource] = useState("VK3XYZ-0");
  const [destination, setDestination] = useState("VK3ABC-0");
  const [ackRequired, setAckRequired] = useState("1");
  const [payload, setPayload] = useState(DEFAULT_PAYLOAD);
  const [formError, setFormError] = useState<string | null>(null);
  const [sentCount, setSentCount] = useState(0);

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setFormError(null);

    const normalizedSource = normalizeStation(source);
    const normalizedDestination = normalizeStation(destination);
    const normalizedPayload = payload.trim();
    const normalizedClientMsgId = clientMsgId.trim();
    const ackValue = Number.parseInt(ackRequired, 10);

    if (!isStationValid(normalizedSource)) {
      setFormError("Source must be a valid CALL-SSID value, for example VK3XYZ-0.");
      return;
    }

    if (!isStationValid(normalizedDestination)) {
      setFormError("Destination must be a valid CALL-SSID value, for example VK3ABC-0.");
      return;
    }

    if (!isPayloadValid(normalizedPayload)) {
      setFormError("Payload must be a valid hex string with leading and trailing C0 bytes.");
      return;
    }

    const frame: ProtocolFrame = {
      type: "message",
      source: normalizedSource,
      destination: normalizedDestination,
      ack_required: Number.isNaN(ackValue) ? 0 : ackValue,
      payload: normalizedPayload,
    };

    if (normalizedClientMsgId !== "") {
      frame.client_msg_id = normalizedClientMsgId;
    }

    const didSend = sendFrame(frame);
    if (!didSend) {
      setFormError("WebSocket is not open yet. Wait for connection before sending.");
      return;
    }

    setSentCount((current) => current + 1);
  };

  return (
    <main className="app-shell">
      <section className="panel hero-panel">
        <p className="eyebrow">WebSocket Message Protocol</p>
        <h1>AX.25 over WebSocket Console</h1>
        <p className="hero-copy">
          Compose message frames, observe ACK and error traffic, and validate server-side canonical id and timestamp handling.
        </p>
        <div className="status-row">
          <span className={`status-pill status-${status}`}>{status}</span>
          <span className="status-meta">Endpoint: {socketUrl}</span>
          <span className="status-meta">Sent: {sentCount}</span>
        </div>
        {lastError !== null ? <p className="alert">Last socket error: {lastError}</p> : null}
      </section>

      <section className="panel compose-panel">
        <div className="panel-head">
          <h2>Compose message frame</h2>
          <p>Server assigns authoritative id and timestamp after validation.</p>
        </div>
        <form onSubmit={onSubmit} className="compose-grid">
          <label>
            Client message id
            <input
              type="text"
              value={clientMsgId}
              onChange={(event) => setClientMsgId(event.target.value)}
              placeholder="c1-0001"
            />
          </label>
          <label>
            Source
            <input type="text" value={source} onChange={(event) => setSource(event.target.value)} placeholder="VK3XYZ-0" required />
          </label>
          <label>
            Destination
            <input
              type="text"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
              placeholder="VK3ABC-0"
              required
            />
          </label>
          <label>
            ACK required
            <select value={ackRequired} onChange={(event) => setAckRequired(event.target.value)}>
              <option value="0">0 - No ACK</option>
              <option value="1">1 - Primary destination ACK</option>
              <option value="2">2 - All recipients ACK</option>
            </select>
          </label>
          <label className="payload-field">
            Payload hex (KISS frame)
            <textarea
              value={payload}
              onChange={(event) => setPayload(event.target.value)}
              rows={5}
              spellCheck={false}
              placeholder="c00086...c0"
              required
            />
          </label>
          <div className="compose-actions">
            <button type="submit" disabled={status !== "open"}>
              Send message
            </button>
            <span>Only type=message is sent by this client subset.</span>
          </div>
          {formError !== null ? <p className="alert">{formError}</p> : null}
        </form>
      </section>

      <section className="panel stream-panel">
        <div className="panel-head stream-head">
          <div>
            <h2>Protocol stream</h2>
            <p>Inbound, outbound, and system events are capped to the latest 300 entries.</p>
          </div>
          <button type="button" className="clear-button" onClick={clearEntries}>
            Clear
          </button>
        </div>

        <ol className="event-list">
          {entries.length === 0 ? (
            <li className="event-empty">No frames yet. Send a message or wait for server traffic.</li>
          ) : (
            entries.map((entry) => (
              <li key={entry.sequence} className={`event-card direction-${entry.direction}`}>
                <div className="event-meta">
                  <span className="event-seq">#{entry.sequence}</span>
                  <span className="event-dir">{entry.direction}</span>
                  <span className="event-type">{frameTag(entry)}</span>
                  <span className="event-time">{formatClock(entry.receivedAt)}</span>
                </div>
                {entry.parseError !== undefined ? <p className="event-error">{entry.parseError}</p> : null}
                <pre>{entry.raw}</pre>
              </li>
            ))
          )}
        </ol>
      </section>
    </main>
  );
}

export default App;
