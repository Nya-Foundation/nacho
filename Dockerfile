# Build stage: resolve locked dependencies with uv, install into /opt/venv.
FROM python:3.14-alpine AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Dependency layer — cached until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    --extra server --extra schema

# Project layer — non-editable install so the venv is fully self-contained.
COPY . .
RUN uv sync --frozen --no-dev --no-editable \
    --extra server --extra schema

# Runtime stage: just Python, the venv, and a non-root user.
FROM python:3.14-alpine AS runtime

LABEL org.opencontainers.image.description="Nacho: lightweight schema-first dynamic configuration" \
      org.opencontainers.image.source="https://github.com/Nya-Foundation/nacho" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN addgroup -S nacho && \
    adduser -S -G nacho -s /sbin/nologin -h /app -g "Non-privileged app user" nacho

COPY --from=builder /opt/venv /opt/venv

# Empty writable workdir: the default command creates config.yaml here, and
# users mount their own config over it.
WORKDIR /app
RUN chown nacho:nacho /app
USER nacho

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# --host 0.0.0.0 is required inside a container (the CLI default is loopback).
ENTRYPOINT ["nacho"]
CMD ["server", "--host", "0.0.0.0", "--config", "config.yaml"]
