FROM node:26-alpine AS builder

WORKDIR /app

RUN npm install -g pnpm

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

COPY pnpm-lock.yaml pnpm-workspace.yaml* package.json tsconfig.json vite.config.ts ./
RUN pnpm install --frozen-lockfile

COPY src ./src
COPY css ./css
COPY images ./images
COPY index.html ./

RUN pnpm build

FROM caddy:2.11-alpine

WORKDIR /srv

RUN apk add --no-cache curl

COPY Caddyfile ./Caddyfile

COPY --from=builder /app/dist ./dist

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
	CMD curl -fsI --max-time=3 http://localhost:8080/ || exit 1

ENTRYPOINT ["caddy", "run", "--config", "Caddyfile", "--adapter", "caddyfile"]
