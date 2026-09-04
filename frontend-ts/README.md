# Web Client

Static site served locally by Caddy.

The frontend now uses a small websocket client in [src/websocketClient.ts](src/websocketClient.ts) so the page can verify a student ID/callsign, bind the normalized source station id returned by the server, send outbound text, and log inbound frames in one place.

The websocket endpoint is expected to be reachable via LAN. `server.py` is the public-facing websocket wrapper; Caddy simply proxies `/ws` to it so the browser can talk to the Python service directly without exposing Direwolf.

## Run

The current Caddyfile serves plain HTTP on `http://localhost:8080`.

then build the client:

```bash
pnpm build
```

then start the server:

```bash
pnpm serve
```

## Lighthouse

Build or start the server first, then run these Node-powered Lighthouse commands against the local HTTP endpoint at `http://localhost:8080`.

Desktop:

```bash
pnpx lighthouse http://localhost:8080 --preset=desktop --output html --output-path=./lighthouse-desktop.html
```

Mobile:

```bash
pnpx lighthouse http://localhost:8080 --form-factor=mobile --screenEmulation.mobile --screenEmulation.width=412 --screenEmulation.height=915 --screenEmulation.deviceScaleFactor=2 --output html --output-path=./lighthouse-mobile.html
```
