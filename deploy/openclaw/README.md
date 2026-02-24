# OpenClaw + VideoMemory Integration

This folder contains a working webhook wake-up config example and a compose stack (`/Users/mark/Desktop/projects/videomemory/docker-compose.openclaw.yml`) that runs:

- `videomemory` (Flask API + MediaMTX RTMP/RTSP + VideoMemory MCP HTTP sidecar in the same container)
- `openclaw` (gateway container)

## What works today

- VideoMemory can wake OpenClaw via `POST /hooks/videomemory-alert` whenever a task gets a new detection note.
- VideoMemory exposes an MCP server (`http://videomemory:8765/mcp`) for tool/resource access.
- Android RTMP push is supported via MediaMTX (`rtmp://HOST:1935/live/...`), while VideoMemory pulls via RTSP (`:8554`) automatically.

## OpenClaw webhook setup

1. Start the stack:

```bash
docker compose -f docker-compose.openclaw.yml up --build
```

2. Copy the hooks fragment from `/Users/mark/Desktop/projects/videomemory/deploy/openclaw/openclaw.webhooks.example.json5` into your OpenClaw config (`~/.openclaw/openclaw.json` inside the OpenClaw container/home volume).

3. Set `OPENCLAW_HOOKS_TOKEN` in your compose `.env` and restart OpenClaw.

## MCP setup notes

OpenClaw MCP support/config syntax has changed across releases. Two paths:

- Native MCP (if your OpenClaw build supports it): register `http://videomemory:8765/mcp`.
- MCP bridge/plugin path: point the bridge to `http://videomemory:8765/mcp`.

If your OpenClaw build does not support native MCP yet, the webhook wake-up still works immediately and the MCP server remains usable from other MCP clients.
