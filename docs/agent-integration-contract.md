# VideoMemory Core <-> Agent Contract

This document defines the integration contract between **VideoMemory Core** and any external agent service (e.g. SimpleAgent).

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
- `POST /api/devices/network`
- `POST /api/devices/network/rtmp`
- `DELETE /api/devices/network/{io_id}`
- `GET /api/tasks`
- `POST /api/tasks` (body may include optional `bot_id` for multi-bot / debug)
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

## Docker Compose stacks

- Core only: `docker compose -f docker-compose.core.yml up --build`
- Core + SimpleAgent: `docker compose -f docker-compose.simpleagent.yml up --build`

SimpleAgent connects to VideoMemory via plain HTTP API at `http://videomemory:5050`.
