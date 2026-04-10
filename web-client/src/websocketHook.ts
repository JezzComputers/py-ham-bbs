import { useCallback, useEffect, useRef, useState } from "react";

export interface PlainSocketState {
  inboundText: string;
  sendText: (text: string) => void;
}

export function usePlainSocket(url: string): PlainSocketState {
  const websocketRef = useRef<WebSocket | null>(null);
  const [inboundText, setInboundText] = useState("");

  const sendText = useCallback((text: string): void => {
    const websocket = websocketRef.current;
    if (websocket === null || websocket.readyState !== WebSocket.OPEN) {
      return;
    }

    websocket.send(text);
  }, []);

  useEffect(() => {
    const websocket = new WebSocket(url);
    websocketRef.current = websocket;

    websocket.onmessage = (event) => {
      if (typeof event.data !== "string") {
        return;
      }

      setInboundText((current) => (current === "" ? event.data : `${current}\n${event.data}`));
    };

    return () => {
      websocket.close();
      websocketRef.current = null;
    };
  }, [url]);

  return {
    inboundText,
    sendText,
  };
}

