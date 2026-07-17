# Use a pinned Python Alpine base for a small, repeatable image.
FROM python:3.13-alpine AS builder

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev

# Create and use a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies first (own layer, cached until pyproject.toml changes)
COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install -e .[server,schema,remote]

# Copy the source code and install the package itself
COPY . .
RUN pip install --no-cache-dir .[server,schema,remote]

# Create a non-privileged system user and group for running the application
RUN addgroup -S nacho && \
    adduser -S -G nacho -s /sbin/nologin -h /app -g "Non-privileged app user" nacho

# Create a runtime stage to minimize the final image size
FROM python:3.13-alpine AS runtime

# Add image metadata
LABEL org.opencontainers.image.description="Nacho: lightweight schema-first dynamic configuration" \
      org.opencontainers.image.source="https://github.com/Nya-Foundation/nacho" \
      org.opencontainers.image.licenses="MIT"


# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Create the same user in the runtime image
RUN addgroup -S nacho && \
    adduser -S -G nacho -s /sbin/nologin -h /app -g "Non-privileged app user" nacho

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy the application from the builder stage
COPY --from=builder /app /app

# Set proper ownership
RUN chown -R nacho:nacho /app

# Switch to non-root user
USER nacho

# Expose the Nacho API port
EXPOSE 8000

# Container-level health probe against the public /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# Command to run the application with the correct module path.
# --host 0.0.0.0 is required inside a container (the CLI default is loopback).
ENTRYPOINT ["nacho"]
CMD ["server", "--host", "0.0.0.0", "--config", "config.yaml"]
