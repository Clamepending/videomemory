# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream — counting events, detecting conditions, and triggering actions like Discord notifications.

## Quick Start

```bash
uv run flask_app/app.py
```

That's it. Open http://localhost:5050, then go to the **Settings** tab to enter your model API key (e.g. Google Gemini, OpenAI, or OpenRouter).

---

## Standalone Usage

### Web UI

```bash
uv run flask_app/app.py
```

Open http://localhost:5050 in your browser. The web UI includes a chat interface, task management, device previews, and a settings page for API keys.

### CLI mode

```bash
uv run main.py
```

Chat directly with the admin agent in your terminal. The agent can list your cameras, create monitoring tasks, check task status, and more through natural conversation. Requires a `GOOGLE_API_KEY` environment variable or `.env` file.

### Monitoring logs

```bash
tail -f videomemory/logs/info.log
```

---

## OpenClaw Agent Setup

After installing [OpenClaw](https://openclaw.ai/), start the VideoMemory server (`uv run flask_app/app.py`) and set your API key in the Settings tab. Then tell your agent:

> Clone https://github.com/Clamepending/videomemory and read the `AGENTS.md` file to onboard to the VideoMemory system. The server is running at http://localhost:5050.
