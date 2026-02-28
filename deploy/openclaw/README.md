# OpenClaw + VideoMemory Integration

This folder contains a working webhook wake-up config example and a compose stack (`/Users/mark/Desktop/projects/videomemory/docker-compose.openclaw.yml`) that runs:

- `videomemory` (Flask API + MediaMTX RTMP/RTSP + VideoMemory MCP HTTP sidecar in the same container)
- `openclaw` (gateway container)
- `openclaw-adapter` (compatibility shim that keeps VideoMemory webhook contract stable while OpenClaw hook endpoints evolve)

## What works today

- VideoMemory can wake OpenClaw via `POST /hooks/videomemory-alert` whenever a task gets a new detection note.
- VideoMemory exposes an MCP server (`http://videomemory:8765/mcp`) for tool/resource access.
- Android RTMP push is supported via MediaMTX (`rtmp://HOST:1935/live/...`), while VideoMemory pulls via RTSP (`:8554`) automatically.
- SRT ingest is exposed on `srt://HOST:8890?...` (lower latency / more resilient uplink).
- WebRTC/WHIP ingest is exposed on `http://HOST:8889/<path>/whip` (very low latency; configure public ICE candidates for internet deployments).

## OpenClaw webhook setup

1. Start the stack:

```bash
docker-compose -f docker-compose.openclaw.yml up --build
```

2. Copy the hooks fragment from `/Users/mark/Desktop/projects/videomemory/deploy/openclaw/openclaw.webhooks.example.json5` into your OpenClaw config (`~/.openclaw/openclaw.json` inside the OpenClaw container/home volume).

3. Set `OPENCLAW_HOOKS_TOKEN` in your compose `.env` and restart OpenClaw.

### Telegram bot token via Docker env

This OpenClaw build accepts Telegram token from environment variable:

```bash
TELEGRAM_BOT_TOKEN=<your-bot-token> docker compose -f docker-compose.openclaw.yml up -d
```

or in a `.env` file next to compose:

```bash
TELEGRAM_BOT_TOKEN=<your-bot-token>
```

Then restart:

```bash
docker compose -f docker-compose.openclaw.yml up -d openclaw
```

## Streaming mode demo preflight (phone + OpenClaw)

Use the helper script to verify stack health, adapter forwarding, MCP connectivity, and generate a phone RTMP URL:

```bash
LAPTOP_HOST=<your-laptop-lan-ip> bash deploy/test-openclaw-phone-demo.sh
```

Example:

```bash
LAPTOP_HOST=192.168.1.42 bash deploy/test-openclaw-phone-demo.sh
```

If the script warns that no OpenClaw model key is configured, set one of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `OPENROUTER_API_KEY` for the `openclaw` service before DM testing.

## MCP setup notes

OpenClaw MCP support/config syntax has changed across releases. Two paths:

- Native MCP (if your OpenClaw build supports it): register `http://videomemory:8765/mcp`.
- MCP bridge/plugin path: point the bridge to `http://videomemory:8765/mcp`.

If your OpenClaw build does not support native MCP yet, the webhook wake-up still works immediately and the MCP server remains usable from other MCP clients.

## Event Mode (Cloud VideoMemory Server + OpenClaw)

For Event Mode, OpenClaw should talk to the **Cloud VideoMemory Server** MCP endpoint (not the edge server):

- MCP URL: `http://cloud-videomemory:8785/mcp` (inside `docker-compose.eventmode.yml`)
- Dashboard/UI: `http://localhost:8785/`

What this gives OpenClaw:

- list known edge devices (`list_edges`)
- enqueue edge commands (`enqueue_edge_command`)
- inspect recent triggers/results (`list_recent_triggers`, `list_recent_results`)

Smoke tests:

- Queue/HTTP path: `bash deploy/test-eventmode-cloud.sh`
- MCP enqueue path: `bash deploy/test-eventmode-mcp.sh`

If you enable cloud auth (`VIDEOMEMORY_CLOUD_TOKEN`), export the same token before running the smoke scripts so they include the Bearer header.

## Ingest protocol choices (phone -> cloud)

- `RTMP` easiest compatibility path (many Android apps)
- `SRT` better resilience and latency over poor networks
- `WHIP/WebRTC` best latency and future bidirectional control path

VideoMemory stores the ingest URL and derives an RTSP pull URL internally for processing workers.
