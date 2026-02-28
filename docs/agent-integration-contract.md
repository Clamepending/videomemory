# VideoMemory Core <-> Agent Contract

This document defines the integration contract between **VideoMemory Core** and any external agent/gateway service (OpenClaw-compatible or custom).

Supported deployment modes:

- **Event Mode (primary):** `VideoMemory` runs on the edge/local app host and emits triggers to a cloud OpenClaw/gateway.
- **Streaming Mode (preserved fallback):** `VideoMemory` runs in the cloud and devices stream to it directly (RTMP/SRT/WHIP).

See also: [docs/edge-cloud-architecture.md](docs/edge-cloud-architecture.md)

Terminology used in this document:

- **Edge VideoMemory Server**: local/on-device VideoMemory instance doing ingestion/analysis.
- **Cloud VideoMemory Server**: server-side control plane used in Event Mode (queue + trigger intake + MCP endpoint).

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

This webhook path is the recommended **trigger/event path** in **Event Mode**.

## Inbound command path (gateway/agent -> edge core)

In cloud deployments where VideoMemory is directly reachable, the agent can call the core HTTP API and/or MCP endpoint directly.

In **Event Mode** (NAT/private LAN), use a cloud-friendly return path for commands:

- edge-initiated long-poll command queue, or
- edge-initiated websocket/SSE control channel

VideoMemory now includes an optional **edge-initiated long-poll command poller** (disabled by default) configured with:

- `VIDEOMEMORY_OPENCLAW_COMMAND_PULL_URL` (required to enable)
- `VIDEOMEMORY_OPENCLAW_COMMAND_RESULT_URL` (optional; can also be provided per-command via `reply_url`)
- `VIDEOMEMORY_OPENCLAW_COMMAND_TOKEN` (optional bearer token; falls back to `VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN`)
- `VIDEOMEMORY_OPENCLAW_EDGE_ID` (optional edge identity string)
- `VIDEOMEMORY_OPENCLAW_COMMAND_POLL_INTERVAL_S` (default `2`)
- `VIDEOMEMORY_OPENCLAW_COMMAND_TIMEOUT_S` (default `10`)
- `VIDEOMEMORY_OPENCLAW_COMMAND_MAX_PER_POLL` (default `1`)
- `VIDEOMEMORY_EDGE_LOCAL_API_BASE_URL` (default `http://127.0.0.1:${PORT:-5050}`)

The command payloads should map to existing VideoMemory API/MCP actions (create task, edit task, stop task, list devices, etc.).

Example command envelope (conceptual):

```json
{
  "request_id": "cmd_123",
  "action": "create_task",
  "args": {
    "io_id": "0",
    "task_description": "Watch front door for package deliveries"
  }
}
```

The poller also accepts a single command object response (not only `{ "commands": [...] }`) for simpler cloud implementations.

### Cloud VideoMemory Server (reference implementation in this repo)

For Event Mode, this repo now includes a lightweight cloud control-plane service:

- start command: `python -m videomemory.cloud_event_server`
- health: `GET /api/health`
- trigger intake: `POST /api/event/triggers`
- command enqueue: `POST /api/event/commands`
- edge command pull: `POST /api/event/commands/pull`
- command result intake: `POST /api/event/commands/result`
- MCP HTTP endpoint: `POST /mcp`

Cloud server auth (optional):

- `VIDEOMEMORY_CLOUD_TOKEN` (Bearer token for HTTP + MCP endpoints)

Example result envelope (conceptual):

```json
{
  "request_id": "cmd_123",
  "status": "success",
  "result": {
    "task_id": "42"
  }
}
```

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

For **Event Mode**, expose MCP in the cloud alongside OpenClaw and bridge commands back to the edge VideoMemory node via the inbound command path above.

Convenience local stacks in this repo:

- `docker-compose.openclaw.yml` for OpenClaw integration tests
- `docker-compose.adminagent.yml` for the sibling `../adminagent` project
