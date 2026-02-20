# VideoMemory - Agent Integration Guide

VideoMemory is a video monitoring system. You create **tasks** for camera input devices, and the system analyses the video feed using vision-language models to fulfil those tasks (counting events, detecting conditions, triggering actions, etc.).

This document describes how to run the server and interact with it via HTTP to act as a **stand-in for the admin agent**.

## Quick Start

If the server is not already running, start it:

```bash
uv run flask_app/app.py
```

The server is available at `http://localhost:5050` (or at the host's IP on port 5050 if deployed on a remote machine like a Raspberry Pi). API keys are configured via the Settings tab in the web UI, or via `PUT /api/settings/{key}` (see Configuration section below).

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

#### Send Telegram notification

```
POST /api/actions/telegram
```

**Body:** `{"message": "Alert: motion detected"}`

Requires `TELEGRAM_BOT_TOKEN`. The notification is sent to the chat where you last messaged the bot (no extra config). Optionally set `TELEGRAM_CHAT_ID` in the environment to fix the destination chat.

### Telegram two-way chat (admin agent)

Users can chat with the same admin agent through Telegram (same capabilities as the web Chat tab). Two options:

- **Long polling (default)** — If `TELEGRAM_BOT_TOKEN` is set, the server starts a background thread that polls Telegram for new messages. No public URL needed; restart the app after setting the token.
- **Webhook** — Set the bot’s webhook to `https://your-server/api/telegram/webhook`. Telegram will POST updates to that URL. Respond with 200 quickly; the server processes the message and sends the agent’s reply in the background.

Each Telegram chat gets its own session (conversation state). For one-way notifications (e.g. from task conditions), the app uses the chat where you last sent a message to the bot, so you only need the bot token.

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
2. **Configure API keys:** `GET /api/settings` to check what's set, then `PUT /api/settings/GOOGLE_API_KEY` (or other keys) if needed.
3. **List devices:** `GET /api/devices` to discover cameras and their `io_id`s.
4. **Create a task:** `POST /api/tasks` with an `io_id` and `task_description`.
5. **Monitor progress:** `GET /api/task/{task_id}` to read the notes (video analysis results).
6. **Edit if needed:** `PUT /api/task/{task_id}` to amend the task description (e.g., add an action trigger).
7. **Take actions:** Use `POST /api/actions/discord` or `POST /api/actions/telegram` to send notifications.
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

After setting a key, restart the service for it to take effect (or if running locally, restart the server).

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
| `DISCORD_WEBHOOK_URL` | Discord webhook for notifications |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token (from @BotFather); enables chat with the agent and one-way notifications to the chat where you messaged the bot (optional: set `TELEGRAM_CHAT_ID` in env to fix the notification chat) |

#### Onboarding: setting keys on behalf of the user

If you have access to the user's API keys (e.g. from their environment or config), you can transfer them to VideoMemory during setup:

```bash
curl -X PUT http://localhost:5050/api/settings/GOOGLE_API_KEY \
  -H "Content-Type: application/json" \
  -d '{"value": "the-key"}'
```

Set whichever keys are available. At minimum, `GOOGLE_API_KEY` is needed for the default configuration.
