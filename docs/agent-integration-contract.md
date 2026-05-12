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
  - follow-up actions and delivery routing for "when X happens, do Y" monitors

For event workflows, treat VideoMemory as the perception engine and the external
agent as the action engine. Store the visual condition in the VideoMemory task.
Store the follow-up instruction, destination, and delivery policy in a
webhook-capable agent runtime such as Claude Code Channels, OpenClaw, or your
own local receiver.

## Core HTTP API contract (agent -> core)

Use these stable endpoints from your external agent:

- `GET /api/health`
- `GET /api/devices`
- `POST /api/device/{io_id}/capture`
- `GET /api/device/{io_id}/preview`
- `GET /api/device/{io_id}/readiness`
- `GET /api/captures/{capture_id}`
- `POST /api/devices/network`
- `DELETE /api/devices/network/{io_id}`
- `GET /api/tasks`
- `POST /api/tasks` (body may include optional `bot_id`, `monitor_type`, and `semantic_filter_keywords` / `required_keywords` to gate VLM calls with the local semantic filter)
- `GET /api/task/{task_id}`
- `PUT /api/task/{task_id}`
- `POST /api/task/{task_id}/stop`
- `DELETE /api/task/{task_id}`
- `GET /api/settings`
- `PUT /api/settings/{key}`

Machine-readable schema:

- `GET /openapi.json`
- `GET /openclaw/skill.md` for a curl-oriented OpenClaw skill document

## Device readiness contract

Agents should call `GET /api/device/{io_id}/readiness` for camera diagnostics
and inspect readiness immediately after creating a monitor. A successfully
created task is not the same thing as a usable camera feed. Before any monitor
exists, `ready:false` can simply mean no ingestor has been started yet; after
task creation, it means the agent should report or fix the blocker.

The endpoint returns HTTP 200 when the device is registered and HTTP 404 when
the `io_id` is unknown. In both cases, the body is machine-readable:

```json
{
  "status": "ready",
  "ready": true,
  "io_id": "browser_facetime",
  "device_exists": true,
  "ingestor": {
    "exists": true,
    "running": true,
    "has_frame": true,
    "frame_age_ms": 110.5
  },
  "browser_camera": {
    "has_fresh_frame": true,
    "stale": false
  },
  "binary_monitor": {
    "enabled": true,
    "condition": "a human is visible"
  },
  "semantic_filter": {
    "enabled": false
  },
  "warnings": []
}
```

If `ready` is false, agents must report the warning instead of saying the
monitor is fully armed. Common blockers are missing browser-camera frames,
macOS camera permission, a stale network snapshot URL, or an unregistered
device id.

## Binary monitor contract

Use `monitor_type: "binary"` for simple done/not-done visual criteria:

```json
{
  "io_id": "browser_facetime",
  "task_description": "a human is visible",
  "monitor_type": "binary",
  "bot_id": "claude-code"
}
```

The binary monitor is designed for local agentic systems that need a fast
boolean trigger, not a rich narrative note. It uses the local FastVLM true/false
path, defaults to a `0.5` true threshold, and requires 2 true votes out of the
last 3 evaluated frames before marking the task done.

Use `monitor_type: "general"` or omit `monitor_type` for the older chunked VLM
monitor that writes richer task notes and may require a configured provider API
key.

## Event monitor contract

For a user request like "tell me when I hold my phone up":

- VideoMemory task description: "Watch for a phone visibly held up in the user's hand."
- Semantic filter keywords: `phone`, `smartphone`, `hand`, `person`
- Follow-up action in agent registry: "Tell the user that the phone is held up."
- Default semantic threshold: `0.3`

OpenClaw-compatible action registry path:

```text
~/.openclaw/hooks/state/videomemory-task-actions.json
```

Registry entries are keyed by `(bot_id, io_id, task_id)` and include:

```json
{
  "task_id": "1",
  "io_id": "0",
  "bot_id": "my-agent",
  "monitor_type": "binary",
  "trigger_condition": "Watch for a phone visibly held up in the user's hand.",
  "action_instruction": "Tell the user that the phone is held up.",
  "delivery_mode": "internal",
  "delivery_target": "",
  "delivery_session_key": "",
  "include_note_frame": false,
  "include_note_video": false
}
```

OpenClaw webhook settings:

- `VIDEOMEMORY_OPENCLAW_WEBHOOK_URL`, for example `http://127.0.0.1:18789/hooks/videomemory-alert`
- `VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN`, matching `hooks.token` in the OpenClaw config
- `VIDEOMEMORY_SELF_BASE_URL`, for task/note URLs inside event payloads

Task-update webhooks include saved evidence URLs when the task note has them:

- `note_frame_api_url`
- `note_video_api_url`

Use those exact URLs for follow-up actions. They point at the triggering note,
not a later live camera snapshot.

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
