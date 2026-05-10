# test_site

Static site served by Caddy from the project root.

The frontend now uses a small websocket client in [src/websocketClient.ts](src/websocketClient.ts) so the page can bind the callsign pair, send outbound text, and log inbound frames in one place.

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
