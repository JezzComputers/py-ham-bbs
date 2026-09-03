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

HEALTHCHECK --interval=1m --timeout=3s --start-period=10s --retries=3 \
	CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8765/healthz', timeout=2).status==200 else 1)"

ENTRYPOINT ["python3", "src/server.py"]
