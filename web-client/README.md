# Web Client Protocol Console

React + TypeScript client for the py-ham-bbs WebSocket protocol subset.

## Features

- Sends protocol `type=message` frames with:
  - `source`
  - `destination`
  - `ack_required` (`0`, `1`, or `2`)
  - KISS/AX.25 payload hex
  - `client_msg_id` for outbound messages
- Sends a `control` bind frame on connect and auto-replies with `ack` when inbound messages request acknowledgements.
- Displays inbound protocol traffic for all message types (`message`, `ack`, `control`, `error`).
- Logs local drop events (socket not open, invalid callsign) alongside inbound/outbound packet formatting.
- Keeps a local capped event history for quick debugging.
- Does not implement explicit websocket `onclose`/`onerror` status tracking.

## Run Locally

From this directory:

```bash
pnpm install
pnpm dev
```

Default UI endpoint is `ws://localhost:8765`.

To use a different endpoint:

```bash
set VITE_WS_URL=ws://127.0.0.1:8765
pnpm dev
```

## Build and Lint

```bash
pnpm build
pnpm lint
```

## Notes

- This client subset only sends `type=message` frames.
- ACK, control, and error messages are fully visible in the stream pane when received.
- On connect, the client also sends a `control` bind frame for the source callsign.
- Outbound frames include `client_msg_id`; the hook does not implement explicit connection-status or transport/parse error logging (unhandled by websocket `onerror`/`onclose`).
