import { useMemo, useState, type KeyboardEvent } from "react";

import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";
import { usePlainSocket } from "./websocketHook";

function App() {
  const socketUrl = useMemo(() => {
    const envUrl = import.meta.env.VITE_WS_URL;
    if (typeof envUrl === "string" && envUrl.trim() !== "") {
      return envUrl;
    }
    return "ws://localhost:8765";
  }, []);

  const { inboundText, sendText } = usePlainSocket(socketUrl);

  const [outboundText, setOutboundText] = useState("");

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
        <Input
          value={outboundText}
          onChange={(event) => setOutboundText(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type text and press Enter"
        />
        <Textarea value={inboundText} readOnly placeholder="Incoming data" className="min-h-[320px] resize-none" />
      </div>
    </main>
  );
}

export default App;
