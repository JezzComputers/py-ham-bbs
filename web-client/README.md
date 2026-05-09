# test_site

Static site served by Caddy from the project root.

The frontend now uses a small websocket client in [src/websocketClient.ts](src/websocketClient.ts) so the page can bind the callsign pair, send outbound text, and log inbound frames in one place.

## Run

The current Caddyfile serves plain HTTP on `http://localhost:8080` and HTTPS on `https://localhost:8443`.

then build the client:

```bash
pnpm build
```

then start the server:

```bash
pnpm serve
```

## Lighthouse

Build or start the server first, then run these Node-powered Lighthouse commands against the local HTTPS endpoint.

Desktop, browser prefers dark mode:

```bash
pnpx lighthouse https://localhost:8443 --preset=desktop --chrome-flags="--ignore-certificate-errors --force-dark-mode" --output html --output-path=./lighthouse-desktop-dark.html
```

Desktop, browser prefers light mode:

```bash
pnpx lighthouse https://localhost:8443 --preset=desktop --chrome-flags="--ignore-certificate-errors --disable-features=WebContentsForceDark" --output html --output-path=./lighthouse-desktop-light.html
```

Mobile, browser prefers dark mode:

```bash
pnpx lighthouse https://localhost:8443 --preset=mobile --chrome-flags="--ignore-certificate-errors --force-dark-mode" --output html --output-path=./lighthouse-mobile-dark.html
```

Mobile, browser prefers light mode:

```bash
pnpx lighthouse https://localhost:8443 --preset=mobile --chrome-flags="--ignore-certificate-errors --disable-features=WebContentsForceDark" --output html --output-path=./lighthouse-mobile-light.html
```
