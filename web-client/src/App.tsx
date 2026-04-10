import { useMemo, useState, type KeyboardEvent } from "react";

import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";
import { usePlainSocket } from "./websocketHook";

const CALLSIGN_WITH_SSID_RE = /^([A-Z0-9]{1,6})-(\d{1,2})$/;

function normalizeCallsign(value: string): string {
  return value.trim().toUpperCase();
}

function isCallsignValid(value: string): boolean {
  const match = CALLSIGN_WITH_SSID_RE.exec(value);
  if (match === null) {
    return false;
  }
  const ssid = Number.parseInt(match[2], 10);
  return ssid >= 0 && ssid <= 15;
}

function App() {
  const [sourceCallsignDraft, setSourceCallsignDraft] = useState("VK3ABC-0");
  const [destinationCallsignDraft, setDestinationCallsignDraft] = useState("VK3XYZ-0");
  const [assignedSourceCallsign, setAssignedSourceCallsign] = useState("VK3ABC-0");
  const [assignedDestinationCallsign, setAssignedDestinationCallsign] = useState("VK3XYZ-0");
  const [callsignError, setCallsignError] = useState("");

  const socketUrl = useMemo(() => {
    const envUrl = import.meta.env.VITE_WS_URL;
    if (typeof envUrl === "string" && envUrl.trim() !== "") {
      return envUrl;
    }
    return "ws://127.0.0.1:8765";
  }, []);

  const { inboundText, sendText } = usePlainSocket(socketUrl, assignedSourceCallsign, assignedDestinationCallsign);

  const [outboundText, setOutboundText] = useState("");

  const assignCallsigns = (): void => {
    const normalizedSourceCallsign = normalizeCallsign(sourceCallsignDraft);
    const normalizedDestinationCallsign = normalizeCallsign(destinationCallsignDraft);
    if (!isCallsignValid(normalizedSourceCallsign)) {
      setCallsignError("Source callsign must be CALL-SSID, for example VK3XYZ-0.");
      return;
    }

    if (!isCallsignValid(normalizedDestinationCallsign)) {
      setCallsignError("Destination callsign must be CALL-SSID, for example VK3ABC-0.");
      return;
    }

    setCallsignError("");
    setSourceCallsignDraft(normalizedSourceCallsign);
    setDestinationCallsignDraft(normalizedDestinationCallsign);
    setAssignedSourceCallsign(normalizedSourceCallsign);
    setAssignedDestinationCallsign(normalizedDestinationCallsign);
  };

  const onSourceCallsignKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    assignCallsigns();
  };

  const onDestinationCallsignKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    assignCallsigns();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== "Enter") {
      return;
    }

    event.preventDefault();
    if (outboundText.trim() === "") {
      return;
    }

    sendText(outboundText);
    setOutboundText("");
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-2xl space-y-3">
        <div className="flex gap-2">
          <Input
            value={sourceCallsignDraft}
            onChange={(event) => setSourceCallsignDraft(event.target.value)}
            onKeyDown={onSourceCallsignKeyDown}
            placeholder="Source callsign (CALL-SSID)"
          />
          <Input
            value={destinationCallsignDraft}
            onChange={(event) => setDestinationCallsignDraft(event.target.value)}
            onKeyDown={onDestinationCallsignKeyDown}
            placeholder="Destination callsign (CALL-SSID)"
          />
          <Button onClick={assignCallsigns}>Assign</Button>
        </div>
        {callsignError !== "" ? <p className="text-sm text-red-600">{callsignError}</p> : null}
        <Input
          value={outboundText}
          onChange={(event) => setOutboundText(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={`Type text as ${assignedSourceCallsign} to ${assignedDestinationCallsign} and press Enter`}
        />
        <Textarea value={inboundText} readOnly placeholder="Packet log" className="min-h-[320px] resize-none" />
      </div>
    </main>
  );
}

export default App;
