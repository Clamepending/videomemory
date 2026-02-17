# VideoMemory - Agent Integration Guide

VideoMemory is a video monitoring system. You create **tasks** for camera input devices, and the system analyses the video feed using vision-language models to fulfil those tasks (counting events, detecting conditions, triggering actions, etc.).

This document describes how to run the server and interact with it via HTTP to act as a **stand-in for the admin agent**.

## Quick Start

```bash
# 1. Install dependencies
cd videomemory
pip install -r requirements.txt

# 2. Set required environment variable
export GOOGLE_API_KEY=<your-key>

# 3. Start the HTTP server (runs on port 5050)
python flask_app/app.py
```

The server is now available at `http://localhost:5050`.

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

### Actions

#### Send Discord notification

```
POST /api/actions/discord
```

**Body:** `{"message": "Alert: motion detected", "username": "VideoMemory"}`

Requires `DISCORD_WEBHOOK_URL` to be configured (via settings API or environment variable).

---

### Chat (Admin Agent Proxy)

If you want to send a natural-language message to the LLM-powered admin agent (instead of calling the tool endpoints directly), use:

```
POST /chat
```

**Body:** `{"message": "Add a task to count people on camera 0", "session_id": "my_session"}`

You must first create a session:

```
POST /api/sessions/new  ->  {"session_id": "chat_abc123"}
```

---

## Typical Workflow

1. **Check health:** `GET /api/health`
2. **List devices:** `GET /api/devices` to discover cameras and their `io_id`s.
3. **Create a task:** `POST /api/tasks` with an `io_id` and `task_description`.
4. **Monitor progress:** `GET /api/task/{task_id}` to read the notes (video analysis results).
5. **Edit if needed:** `PUT /api/task/{task_id}` to amend the task description (e.g., add an action trigger).
6. **Take actions:** Use `POST /api/actions/discord` to send Discord notifications.
7. **Stop or delete:** `POST /api/task/{task_id}/stop` or `DELETE /api/task/{task_id}`.

## Error Format

All error responses follow:

```json
{
  "status": "error",
  "error": "Human-readable error message"
}
```

HTTP status codes: `400` for validation errors, `404` for not found, `500` for server errors.

## Configuration

Settings can be viewed and updated at runtime:

```
GET  /api/settings              # List all settings (sensitive values masked)
PUT  /api/settings/{key}        # Update a setting: {"value": "new_value"}
```

Known setting keys: `DISCORD_WEBHOOK_URL`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `VIDEO_INGESTOR_MODEL`.
