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

COPY --from=builder /app/.venv /app/.venv

COPY backend-py/ ./

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["python3", "src/server.py"]
