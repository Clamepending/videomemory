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
COPY deploy ./deploy
COPY tests ./tests

RUN uv sync --frozen --no-dev

RUN chmod +x /app/deploy/start-cloud.sh

EXPOSE 5050

CMD ["bash", "/app/deploy/start-cloud.sh"]
