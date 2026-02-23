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

RUN uv sync --frozen --no-dev

ARG MEDIAMTX_VERSION=1.15.3
RUN curl -fsSL "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/local/bin mediamtx

RUN chmod +x /usr/local/bin/mediamtx /app/deploy/start-cloud.sh

EXPOSE 5050 1935 8554

CMD ["bash", "/app/deploy/start-cloud.sh"]
