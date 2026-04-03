# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream.

## Quick Start

To launch both Openclaw and Videomemory in docker containers on your computer, use
```bash
ANTHROPIC_API_KEY=<YOUR ANTHROPIC API KEY> \
VIDEO_INGESTOR_MODEL=claude-sonnet-4-6 \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```
Then Openclaw UI: http://127.0.0.1:18889/chat?session=agent%3Amain%3Amain
Videomemory UI: http://127.0.0.1:5050/device
You can set up telegram in openclaw.

To launch just Videomemory (no openclaw)
```bash
./start.sh
```

This starts VideoMemory for local development. Open http://localhost:5050. Set your model API key in the **Settings** tab, then use the **Devices** and **Tasks** pages to manage ingestion and monitoring.



## OpenClaw Quickstart

### I already have OpenClaw on a VM, server, or computer

Run this on the same machine where OpenClaw runs:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/codex/openclaw-trigger-action-split/docs/openclaw-bootstrap.sh)
```

What it does:
- clones or reuses VideoMemory
- starts VideoMemory in Docker if needed
- installs the OpenClaw helper, skill, and webhook transform
- merges the OpenClaw hook config

After that, use OpenClaw normally. It should be able to:
- create/list/edit/stop/delete VideoMemory tasks
- answer one-off camera questions like `what do you see on camera?`
- use trigger/action splits for `when X happens, do Y`

### I already have OpenClaw in Docker

1. Start VideoMemory on the host:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/codex/openclaw-trigger-action-split/docs/install-videomemory.sh)
```

2. Send this exact message to OpenClaw:

```text
Please install and onboard VideoMemory by running VIDEOMEMORY_BASE=http://host.docker.internal:5050 bash <(curl -fsSL http://host.docker.internal:5050/openclaw/bootstrap.sh). Then use VideoMemory from http://host.docker.internal:5050/openclaw/skill.md and use the videomemory task helper for any "when X happens, do Y" request.
```

If `host.docker.internal` does not resolve on Linux, relaunch the OpenClaw container with:

```bash
--add-host=host.docker.internal:host-gateway
```

### I want both OpenClaw and VideoMemory in Docker

This is the bundled two-container setup for **OpenClaw + VideoMemory**:

```bash
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

If you want a single launch command with model setup, use the helper script:

```bash
ANTHROPIC_API_KEY=your_key_here \
TELEGRAM_BOT_TOKEN=your_bot_token_here \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash docs/launch-openclaw-real.sh
```

If `OPENCLAW_TELEGRAM_OWNER_ID` is not set, the script will try to discover it automatically from the bot's recent Telegram updates. Send any message to your bot once before running it.

To find `OPENCLAW_TELEGRAM_OWNER_ID` yourself:

1. Send any message to your Telegram bot.
2. Run:

```bash
curl -fsSL "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates"
```

3. Copy the `message.chat.id` value from the latest update. That is your `OPENCLAW_TELEGRAM_OWNER_ID`.

Example explicit launch:

```bash
ANTHROPIC_API_KEY=your_key_here \
TELEGRAM_BOT_TOKEN=your_bot_token_here \
OPENCLAW_TELEGRAM_OWNER_ID=123456789 \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash docs/launch-openclaw-real.sh
```

You can also launch with raw `docker compose`. The bundled compose file forwards launch-time keys to both **OpenClaw** and **VideoMemory**:

```bash
ANTHROPIC_API_KEY=your_key_here \
VIDEO_INGESTOR_MODEL=claude-sonnet-4-6 \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

Or use OpenAI for both OpenClaw and VideoMemory:

```bash
OPENAI_API_KEY=your_key_here \
VIDEO_INGESTOR_MODEL=gpt-4o-mini \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

Then open:
- VideoMemory: `http://localhost:5050/devices`
- OpenClaw: `http://localhost:18889/`

Gateway token:

```text
openclaw-real-dev-token
```

After the stack starts, add your own camera in the VideoMemory Devices page, then try these in OpenClaw:

```text
what do you see on camera
```

```text
when you see a red marker, notify me
```

## Docker

### Core only

```bash
docker compose -f docker-compose.core.yml up --build
```

This starts VideoMemory. Open http://localhost:5050.

### Bundled real OpenClaw + VideoMemory

Launch the bundled Docker setup:

```bash
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

For the easiest single-command launch, use:

```bash
ANTHROPIC_API_KEY=your_key_here \
TELEGRAM_BOT_TOKEN=your_bot_token_here \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash docs/launch-openclaw-real.sh
```

If the Telegram owner chat id is not already set, the helper script will try to resolve it from the bot's recent updates. Send your bot one message first so it has an update to read.

You can also fetch the chat id yourself:

```bash
curl -fsSL "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates"
```

Use the `message.chat.id` from the latest update as `OPENCLAW_TELEGRAM_OWNER_ID`.

To inject model keys directly at launch time, without configuring them in the web UI:

```bash
ANTHROPIC_API_KEY=your_key_here \
VIDEO_INGESTOR_MODEL=claude-sonnet-4-6 \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

To include Telegram in the raw compose launch:

```bash
ANTHROPIC_API_KEY=your_key_here \
TELEGRAM_BOT_TOKEN=your_bot_token_here \
OPENCLAW_TELEGRAM_OWNER_ID=your_chat_id_here \
VIDEO_INGESTOR_MODEL=claude-sonnet-4-6 \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

The bundled compose file passes launch-time model keys into both containers:
- **VideoMemory** uses them for `/api/caption_frame` and monitoring tasks
- **OpenClaw** uses them for chat, tool use, and webhook wakeups

This starts:
- **VideoMemory** on `http://localhost:5050` (UI + API)
- **OpenClaw** on `http://localhost:18889` (real OpenClaw UI + gateway)

OpenClaw connects to VideoMemory via plain HTTP API at `http://videomemory:5050`.
It should fetch the skill from `http://videomemory:5050/openclaw/skill.md` before making task/device calls.

The bundled Docker stack does not add a demo camera anymore. Add your own camera from the VideoMemory Devices page or with `POST /api/devices/network`.

Gateway token:

```text
openclaw-real-dev-token
```

### Legacy stand-in stack

If you specifically want the older SimpleAgent-backed stand-in stack for debugging:

1. Clone [SimpleAgent](https://github.com/Clamepending/simpleagent) as a sibling directory.
2. Run:

```bash
docker compose -f docker-compose.openclaw.yml up --build
```

## Integration

VideoMemory exposes a stable HTTP API for external agents:

- Integration contract: [docs/agent-integration-contract.md](docs/agent-integration-contract.md)
- OpenClaw skill: [docs/openclaw-skill.md](docs/openclaw-skill.md)
- Agent guide: [AGENTS.md](AGENTS.md)
- OpenAPI spec: `GET /openapi.json`

## Mobile camera (Android)

Use your Android phone as a wireless camera: the phone serves the latest frame over a simple **HTTP snapshot** endpoint, and VideoMemory pulls from that URL.

**Architecture:** Phone (Android app) -> `http://phone:8080/snapshot.jpg` -> VideoMemory pulls the latest frame when it wants one.

**Setup:**
1. Run VideoMemory (locally or via Docker).
2. Open the [Android app](android/README.md) and tap **Start Server**.
3. Copy the snapshot URL shown on the phone.
4. In the web app: **Devices** -> **Add Network Camera** -> paste that URL.
5. Create tasks for that device as usual.

Phone and VideoMemory should be on the same LAN, or both connected with [Tailscale](https://tailscale.com/download) so VideoMemory can reach the phone's snapshot URL directly.

## One-click cloud deployment (Fly.io)

[![Deploy to Fly.io](https://fly.io/button.svg)](https://fly.io/apps/new?repo=https://github.com/Clamepending/videomemory)

After deployment:
1. Open your Fly app URL.
2. Go to **Settings** and set `GOOGLE_API_KEY` (or another supported provider key).
3. Start the Android app's snapshot server and make sure the Fly machine can reach the phone, typically via Tailscale.
4. Go to **Devices** -> **Add Network Camera** and paste the phone's snapshot URL.
5. Create tasks for that camera through the VideoMemory UI or API.

## Raspberry Pi Deployment

SSH into your Pi and run:

```bash
curl -sSL https://raw.githubusercontent.com/Clamepending/videomemory/main/deploy/setup-pi.sh | bash
```

This installs VideoMemory as a background service that starts on boot. When it finishes it prints the URL (e.g. `http://192.168.1.42:5050`). Open it and set your API key in the **Settings** tab.

```bash
sudo systemctl status videomemory     # check status
sudo systemctl restart videomemory    # restart
sudo journalctl -u videomemory -f     # view logs
```
