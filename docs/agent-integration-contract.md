# VideoMemory Core <-> Agent Contract

This document defines the integration contract between **VideoMemory Core** and any external agent service (e.g. OpenClaw).

## Scope and boundary

- **VideoMemory Core owns**
  - device discovery and stream registration
  - task lifecycle and video ingestion
  - VLM-based detection loop and task notes
- **External Agent owns**
  - user conversation and orchestration
  - policy, memory, authz/authn, and tool planning
  - translating user intent into VideoMemory API calls

## Core HTTP API contract (agent -> core)

Use these stable endpoints from your external agent:

- `GET /api/health`
- `GET /api/devices`
- `POST /api/device/{io_id}/capture`
- `GET /api/device/{io_id}/preview`
- `GET /api/captures/{capture_id}`
- `POST /api/devices/network`
- `DELETE /api/devices/network/{io_id}`
- `GET /api/tasks`
- `POST /api/tasks` (body may include optional `bot_id` for multi-bot / debug and `semantic_filter_keywords` / `required_keywords` to gate VLM calls with the local semantic filter)
- `GET /api/task/{task_id}`
- `PUT /api/task/{task_id}`
- `POST /api/task/{task_id}/stop`
- `DELETE /api/task/{task_id}`
- `GET /api/settings`
- `PUT /api/settings/{key}`

Machine-readable schema:

- `GET /openapi.json`
- `GET /openclaw/skill.md` for a curl-oriented OpenClaw skill document

Error shape:

```json
{
  "status": "error",
  "error": "Human-readable error message"
}
```

## Docker Compose stacks

- Core only: `docker compose -f docker-compose.core.yml up --build`
- Core + OpenClaw: `docker compose -f docker-compose.openclaw.yml up --build`

OpenClaw connects to VideoMemory via plain HTTP API.
In the bundled stack it should fetch `http://videomemory:5050/openclaw/skill.md` and use the documented HTTP endpoints with `curl`.
If OpenClaw is in Docker and VideoMemory is running on the host, use `http://host.docker.internal:5050/openclaw/skill.md` instead.
