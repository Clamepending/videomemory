FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY videomemory ./videomemory
COPY flask_app ./flask_app
COPY rtmp-server ./rtmp-server
COPY deploy ./deploy
COPY tests ./tests

RUN uv sync --frozen --no-dev

ARG MEDIAMTX_VERSION=1.16.2
ARG TARGETARCH
RUN set -eux; \
    arch="${TARGETARCH:-}"; \
    if [ -z "$arch" ]; then \
      arch="$(uname -m)"; \
      case "$arch" in \
        x86_64|amd64) arch="amd64" ;; \
        aarch64|arm64) arch="arm64" ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
      esac; \
    fi; \
    curl -fsSL "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_linux_${arch}.tar.gz" \
      | tar -xz -C /usr/local/bin mediamtx

RUN chmod +x /usr/local/bin/mediamtx /app/deploy/start-cloud.sh /app/deploy/start-with-mcp.sh

EXPOSE 5050 8765 1935 8554 8889 8890 8189/udp

CMD ["bash", "/app/deploy/start-cloud.sh"]
