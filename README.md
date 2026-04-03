# VideoMemory

Use vision language models to let your openclaw see and monitor cameras (USB, RTSP, Android devices)
A video monitoring system that uses vision-language models to analyse camera feeds. You or your agent creates a **tasks** describing what to watch for, and the system continuously analyses the video stream.

## Quick Start

To launch both OpenClaw and VideoMemory in Docker, use:
```bash
bash ./launch_openclaw_with_videomemory.sh --anthropic-api-key <YOUR_ANTHROPIC_API_KEY>
```

It prints:
- a ready-to-open OpenClaw dashboard link with `?token=...` already included
- the VideoMemory UI link

The bundled stack already includes the OpenClaw config that wires VideoMemory webhooks.
To launch just Videomemory (no openclaw)
```bash
./start.sh
```
This starts VideoMemory for local development. Open http://localhost:5050. Set your model API key in the **Settings** tab, then use the **Devices** and **Tasks** pages to manage ingestion and monitoring.

## OpenClaw Quickstart

### I want to launch openclaw with videomemory

```bash
ANTHROPIC_API_KEY=<YOUR ANTHROPIC API KEY> \
VIDEO_INGESTOR_MODEL=claude-sonnet-4-6 \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```
Hint: You can set up telegram in openclaw.
Install Tailscale to stream video to videomemory over the android app.


### I already have OpenClaw on a VM, server, or computer

Send this message to OpenClaw:

```text
Please Run this and onboard: bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/openclaw-bootstrap.sh)
```
After that, your OpenClaw should be able to:
- create/list/edit/stop/delete VideoMemory tasks
- answer one-off camera questions like `what do you see on camera?`
- Monitor cameras like `when X happens in camera Y, do Z`

### I already have OpenClaw in a container

1. Start VideoMemory on the host:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/install-videomemory.sh)
```

2. Send this message to OpenClaw:

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
bash ./launch_openclaw_with_videomemory.sh --anthropic-api-key your_key_here
```

If you prefer environment variables, this is equivalent:

```bash
ANTHROPIC_API_KEY=your_key_here \
TELEGRAM_BOT_TOKEN=your_bot_token_here \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash ./launch_openclaw_with_videomemory.sh
```

On macOS, the launcher will try to open Docker Desktop automatically if the daemon is not ready yet.

After launch, the script prints:
- `VideoMemory UI: http://localhost:5050/devices`
- `OpenClaw dashboard: http://localhost:18889/?token=...`

That OpenClaw dashboard link already includes the gateway token, so you can open it directly without pasting the token manually.

If you want the terminal UI, keep it as two commands:

```bash
ANTHROPIC_API_KEY=your_key_here \
TELEGRAM_BOT_TOKEN=your_bot_token_here \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash ./launch_openclaw_with_videomemory.sh

OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash docs/launch-openclaw-real-tui.sh
```

If you want Telegram alerts, set `OPENCLAW_TELEGRAM_OWNER_ID` yourself:

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
bash ./launch_openclaw_with_videomemory.sh
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

Then open the printed links from the launcher output.

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

To launch the stack and then attach directly to `openclaw tui` inside the running container, use two commands:

```bash
ANTHROPIC_API_KEY=your_key_here \
TELEGRAM_BOT_TOKEN=your_bot_token_here \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash docs/launch-openclaw-real.sh

OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash docs/launch-openclaw-real-tui.sh
```

The TUI helper is intentionally very small. It just finds the running `openclaw` container and runs:

```bash
docker exec -e TERM="$TERM" -it <openclaw-container> \
  sh -lc 'exec openclaw tui --url ws://127.0.0.1:18789 --token "$OPENCLAW_GATEWAY_TOKEN" --session main'
```

If you want Telegram alerts, fetch the chat id yourself:

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
