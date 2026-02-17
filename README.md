# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream — counting events, detecting conditions, and triggering actions like Discord notifications.

## Quick Start

```bash
uv run flask_app/app.py
```

Open http://localhost:5050. Set your model API key in the **Settings** tab. Chat with the admin agent in the **Chat** tab to manage the system through natural conversation, or browse your cameras and monitoring tasks directly in the **Devices** and **Tasks** tabs.

## CLI Mode

```bash
uv run main.py
```

Same admin agent, but in your terminal. Requires a `GOOGLE_API_KEY` environment variable or `.env` file.

---

## OpenClaw Agent Setup

1. Install [OpenClaw](https://openclaw.ai/)
2. Tell your agent:

> Clone https://github.com/Clamepending/videomemory and read the `AGENTS.md` file to onboard to the VideoMemory system.
