# VideoMemory - Agent Integration Guide

VideoMemory is a video monitoring system. You create **tasks** for camera input devices, and the system analyses the video feed using vision-language models to fulfil those tasks (counting events, detecting conditions, triggering actions, etc.).

This document describes how to run the VideoMemory **core service** and interact with it via HTTP/MCP from an external agent or gateway.

## Quick Start

If the server is not already running, start it:

```bash
uv run flask_app/app.py
```

The server is available at `http://localhost:5050` (or at the host's IP on port 5050 if deployed on a remote machine like a Raspberry Pi). API keys are configured via the Settings tab in the web UI, or via `PUT /api/settings/{key}` (see Configuration section below).

For local integration testing, choose one stack:

- Core only: `docker compose -f docker-compose.core.yml up --build`
- Core + OpenClaw: `docker compose -f docker-compose.openclaw.yml up --build`
- Core + SimpleAgent (sibling repo): `docker compose -f docker-compose.adminagent.yml up --build`

## OpenAPI Spec

A machine-readable OpenAPI 3.1 spec is served at:

```
GET http://localhost:5050/openapi.json
```

Use this to auto-discover all available endpoints and their schemas.

## Health Check

```
GET /api/health
```

Returns `{"status": "ok", ...}` when the server is running.

---

## API Reference

All endpoints accept and return JSON. Set `Content-Type: application/json` for POST/PUT requests.

### Devices

#### List input devices

```
GET /api/devices
```

Returns available cameras and other input devices grouped by category. Each device has an `io_id` you'll need when creating tasks.

**Example response:**
```json
{
  "devices": {
    "camera": [
      {"io_id": "0", "name": "FaceTime HD Camera"},
      {"io_id": "1", "name": "USB Webcam"}
    ]
  }
}
```

---

### Tasks

#### List all tasks

```
GET /api/tasks
GET /api/tasks?io_id=0
```

Returns all tasks. Optionally filter by `io_id`.

#### Add a task

```
POST /api/tasks
```

**Body:**
```json
{
  "io_id": "0",
  "task_description": "Count the number of people entering the room"
}
```

1. First call `GET /api/devices` to find the `io_id` of the camera you want.
2. Then create a task with a natural-language description of what to monitor.

The system will begin analysing the video stream according to the task description.

#### Get task details

```
GET /api/task/{task_id}
```

Returns detailed information including the task's **notes** (observations from video analysis) and current status (`active`, `done`, or `terminated`).

#### Edit a task

```
PUT /api/task/{task_id}
```

**Body:**
```json
{
  "new_description": "Count claps and send email to user@test.com when count reaches 5"
}
```

Updates the task description while keeping its notes and status. Useful for adding action triggers to an existing detection task.

#### Stop a task

```
POST /api/task/{task_id}/stop
```

Stops video processing for a task. The task and all its notes remain visible in the task list (status becomes `done`). Use this when you want to stop monitoring but keep the history.

#### Delete a task

```
DELETE /api/task/{task_id}
```

Permanently removes a task and all its notes. Only use when you want to erase a task entirely.

---

### External agent integration

Run your conversational SimpleAgent separately and have it call VideoMemory APIs.

- HTTP contract and examples: `docs/agent-integration-contract.md`
- OpenAPI schema: `GET /openapi.json`

---

## Typical Workflow

1. **Check health:** `GET /api/health`
2. **Configure API keys:** `GET /api/settings` to check what's set, then `PUT /api/settings/GOOGLE_API_KEY` (or other keys) if needed.
3. **List devices:** `GET /api/devices` to discover cameras and their `io_id`s.
4. **Create a task:** `POST /api/tasks` with an `io_id` and `task_description`.
5. **Monitor progress:** `GET /api/task/{task_id}` to read the notes (video analysis results).
6. **Edit if needed:** `PUT /api/task/{task_id}` to amend the task description (e.g., add an action trigger).
7. **Handle external actions:** If you need notifications or messaging channels, use an external agent service.
8. **Stop or delete:** `POST /api/task/{task_id}/stop` or `DELETE /api/task/{task_id}`.

## Error Format

All error responses follow:

```json
{
  "status": "error",
  "error": "Human-readable error message"
}
```

HTTP status codes: `400` for validation errors, `404` for not found, `500` for server errors.

## Configuration & API Keys

The system needs at least one model API key to function. You should configure this **before** creating any tasks.

#### Set an API key

```
PUT /api/settings/GOOGLE_API_KEY
```

**Body:**
```json
{"value": "AIzaSy...your-key-here"}
```

After setting a model key, it is applied immediately at runtime (no restart required).

#### Check current settings

```
GET /api/settings
```

Returns all settings with their status. Sensitive values are masked — check the `is_set` field to see if a key is configured.

**Example response:**
```json
{
  "settings": {
    "GOOGLE_API_KEY": {"value": "****abcd", "is_set": true, "source": "database"},
    "OPENAI_API_KEY": {"value": "", "is_set": false, "source": "unset"}
  }
}
```

#### Available setting keys

| Key | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Google Gemini models (default and recommended) |
| `OPENAI_API_KEY` | OpenAI models (alternative) |
| `OPENROUTER_API_KEY` | OpenRouter models (alternative) |
| `ANTHROPIC_API_KEY` | Anthropic models (alternative) |
| `VIDEO_INGESTOR_MODEL` | Which model to use for video analysis (default: `gemini-2.5-flash`) |

#### Onboarding: setting keys on behalf of the user

If you have access to the user's API keys (e.g. from their environment or config), you can transfer them to VideoMemory during setup:

```bash
curl -X PUT http://localhost:5050/api/settings/GOOGLE_API_KEY \
  -H "Content-Type: application/json" \
  -d '{"value": "the-key"}'
```

Set whichever keys are available. At minimum, `GOOGLE_API_KEY` is needed for the default configuration.
