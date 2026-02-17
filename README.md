# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream — counting events, detecting conditions, and triggering actions like Discord notifications.

## Prerequisites

- Python 3.10+
- A Google API key (for Gemini models) — get one at https://aistudio.google.com/apikey
- A camera connected to your machine

## Setup

### 1. Install dependencies

```bash
cd videomemory
pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file in the `videomemory/` directory:

```
GOOGLE_API_KEY=your-google-api-key-here
```

Optional settings (can also be configured at runtime via the web UI or API):

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
OPENAI_API_KEY=...
OPENROUTER_API_KEY=...
VIDEO_INGESTOR_MODEL=...
```

---

## Standalone Setup

### CLI mode

Chat directly with the admin agent in your terminal:

```bash
python main.py
```

The agent can list your cameras, create monitoring tasks, check task status, and more — all through natural conversation.

### Web UI mode

Run the Flask server for a browser-based interface:

```bash
python flask_app/app.py
```

Open http://localhost:5050 in your browser. The web UI includes a chat interface, task management pages, device previews, and settings.

### Monitoring logs

In a separate terminal:

```bash
tail -f videomemory/logs/info.log
```

---

## OpenClaw Agent Setup

VideoMemory exposes a full REST API that any AI agent can use as a stand-in for the built-in admin agent. After installing [OpenClaw](https://openclaw.ai/), you can point it at this repository and let it manage your video monitoring tasks autonomously.

### 1. Start the VideoMemory server

```bash
cd videomemory
pip install -r requirements.txt
python flask_app/app.py
```

The API is now running at `http://localhost:5050`. The full OpenAPI spec is at `http://localhost:5050/openapi.json`.

### 2. Tell the OpenClaw agent

Once the server is running, give OpenClaw (or any agent) these instructions:

> VideoMemory is running at http://localhost:5050. It is a video monitoring system — you create tasks for cameras and the system analyses the video feed.
>
> Read the file `AGENTS.md` in the repository root for the full API reference, or fetch `http://localhost:5050/openapi.json` for the machine-readable OpenAPI spec.
>
> **Typical workflow:**
> 1. `GET /api/health` — verify the server is up.
> 2. `GET /api/devices` — discover available cameras and their `io_id`s.
> 3. `POST /api/tasks` with `{"io_id": "0", "task_description": "..."}` — create a monitoring task.
> 4. `GET /api/task/{task_id}` — check task notes (the system's observations from the video feed).
> 5. `PUT /api/task/{task_id}` — edit a task's description.
> 6. `POST /api/task/{task_id}/stop` — stop a task (keeps history).
> 7. `DELETE /api/task/{task_id}` — permanently delete a task.
>
> All requests and responses are JSON. Errors return `{"status": "error", "error": "..."}`.

The agent can then discover cameras, create and manage monitoring tasks, and read the video analysis results — all through HTTP calls.

### Key files for agents

| File | Purpose |
|---|---|
| `AGENTS.md` | Full API reference with examples and typical workflow |
| `http://localhost:5050/openapi.json` | Machine-readable OpenAPI 3.1 spec (served by the running app) |
