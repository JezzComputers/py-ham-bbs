# Web Client Protocol Console

React + TypeScript client for the py-ham-bbs WebSocket protocol subset.

## Features

- Sends protocol `type=message` frames with:
  - `client_msg_id` (optional)
  - `source`
  - `destination`
  - `ack_required` (`0`, `1`, or `2`)
  - KISS/AX.25 payload hex
- Displays inbound protocol traffic for all message types (`message`, `ack`, `control`, `error`).
- Tracks connection status and logs parse/transport errors.
- Keeps a local capped event history for quick debugging.

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
