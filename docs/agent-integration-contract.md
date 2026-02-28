# VideoMemory Core <-> Agent Contract

This document defines the integration contract between **VideoMemory Core** and any external agent/gateway service (OpenClaw-compatible or custom).

## Scope and boundary

- **VideoMemory Core owns**
  - device discovery and stream registration
  - task lifecycle and video ingestion
  - VLM-based detection loop and task notes
  - outbound event notifications (webhook)
  - MCP server for tool-style API access
- **External Agent/Gateway owns**
  - user conversation and orchestration
  - policy, memory, authz/authn, and tool planning
  - translating user intent into VideoMemory API calls
  - optional event intake endpoint for VideoMemory webhook callbacks

## Core HTTP API contract (agent -> core)

Use these stable endpoints from your external agent:

- `GET /api/health`
- `GET /api/devices`
- `POST /api/devices/network`
- `POST /api/devices/network/rtmp`
- `DELETE /api/devices/network/{io_id}`
- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/task/{task_id}`
- `PUT /api/task/{task_id}`
- `POST /api/task/{task_id}/stop`
- `DELETE /api/task/{task_id}`
- `GET /api/settings`
- `PUT /api/settings/{key}`

Machine-readable schema:

- `GET /openapi.json`

Error shape:

```json
{
  "status": "error",
  "error": "Human-readable error message"
}
```

## Outbound webhook contract (core -> gateway/agent)

Configure VideoMemory Core with:

- `VIDEOMEMORY_OPENCLAW_WEBHOOK_URL`
- `VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN` (optional Bearer token)

When a task update is emitted, VideoMemory sends `POST` JSON:

```json
{
  "source": "videomemory",
  "event_type": "task_update",
  "task_id": "0",
  "task_number": 1,
  "io_id": "0",
  "task_description": "Count people entering the room",
  "task_done": false,
  "task_status": "active",
  "note": "Detected one person near doorway",
  "note_timestamp": 1735200000.123,
  "sent_at": 1735200001.456
}
```

Headers:

- `Content-Type: application/json`
- `Authorization: Bearer <token>` (only when `VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN` is set)

Delivery characteristics:

- best-effort (no retries guaranteed by contract)
- optional dedupe/throttling via:
  - `VIDEOMEMORY_OPENCLAW_DEDUPE_TTL_S`
  - `VIDEOMEMORY_OPENCLAW_MIN_INTERVAL_S`

## MCP contract

VideoMemory exposes an MCP HTTP server (started by `deploy/start-with-mcp.sh`):

- host: `0.0.0.0`
- port: `${VIDEOMEMORY_MCP_PORT:-8765}`
- api base URL internally points to `http://127.0.0.1:${PORT:-5050}`

Run VideoMemory core+MCP:

```bash
docker compose -f docker-compose.core.yml up --build
```

Then run your agent/gateway service separately (OpenClaw or custom) and connect it to VideoMemory through HTTP and/or MCP.

Convenience local stacks in this repo:

- `docker-compose.openclaw.yml` for OpenClaw integration tests
- `docker-compose.adminagent.yml` for the sibling `../adminagent` project
