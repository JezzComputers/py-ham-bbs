FROM astral/uv:python3.14-trixie-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_DEV=1

COPY backend-py/pyproject.toml backend-py/uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --frozen --no-install-project

COPY backend-py/ ./

RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --frozen


FROM astral/uv:python3.14-trixie-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app/.venv /app/.venv
COPY backend-py/ ./

ARG APP_GID=1000
RUN chgrp ${APP_GID} /app && chmod g+w /app

EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
	CMD python3 -c "import socket, sys; \
	s = socket.socket(); s.settimeout(2); \
	s.connect(('127.0.0.1', 8080)); \
	sys.exit(0 if b'200 OK' in s.recv(1024) else 1)"

ENTRYPOINT ["python3", "src/server.py"]
