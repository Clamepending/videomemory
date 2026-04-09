# VideoMemory

Use vision language models to let your openclaw see and monitor cameras (USB, RTSP, Android devices)

You or your agent creates a **tasks** describing what to watch for, and the system continuously analyses the video stream.

## Quick Start

### I want OpenClaw + VIdeomemory on a VM, raspberry pi, or computer

1. [Install OpenClaw](https://docs.openclaw.ai/install)

This path now starts VideoMemory directly on that machine with `uv` or `python3`. It does not use Docker.

Send this message to OpenClaw:

```text
Please run this to install and onboard VideoMemory locally: bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/openclaw-bootstrap.sh)
```
After that, your OpenClaw should be able to:
- create/list/edit/stop/delete VideoMemory tasks
- answer one-off camera questions like `what do you see on camera?`
- Monitor cameras like `when X happens in camera Y, do Z`
Hint: You can set up telegram in openclaw.
Install Tailscale to stream video to videomemory over the android app.

### I want to launch both OpenClaw and VideoMemory in containers (useful for local development)
```bash
ANTHROPIC_API_KEY=<YOUR ANTHROPIC API KEY> \
OPENCLAW_GATEWAY_TOKEN=chooseyourowntoken \
bash ./launch_openclaw_with_videomemory.sh
```
(OPENAI_API_KEY, GOOGLE_API_KEY, and OPENROUTER_API_KEY are supported too)

It prints:
- a ready-to-open OpenClaw dashboard link
- the VideoMemory UI link

The bundled stack already includes the OpenClaw config that wires VideoMemory webhooks.

Supported bundled provider keys:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY` or `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`

The launcher auto-selects matching default models for both VideoMemory and OpenClaw based on whichever of those keys you provide.
To launch just Videomemory (no openclaw)
```bash
./start.sh
```
This starts VideoMemory for local development. Open http://localhost:5050. Set your model API key in the **Settings** tab, then use the **Devices** and **Tasks** pages to manage ingestion and monitoring.

### I already have OpenClaw in a container

1. Start VideoMemory on the host:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/install-videomemory.sh)
```

That script launches VideoMemory directly on the host machine and leaves Docker out of the host-side install.

2. Send this message to OpenClaw:

```text
Please install and onboard VideoMemory by running VIDEOMEMORY_BASE=http://host.docker.internal:5050 bash <(curl -fsSL http://host.docker.internal:5050/openclaw/bootstrap.sh). Then use VideoMemory from http://host.docker.internal:5050/openclaw/skill.md and use the videomemory task helper for any "when X happens, do Y" request.
```

If `host.docker.internal` does not resolve on Linux, relaunch the OpenClaw container with:

```bash
--add-host=host.docker.internal:host-gateway
```

## Mobile camera (Android)

Use your Android phone as a wireless camera: the phone serves the latest frame over a simple **HTTP snapshot** endpoint, and VideoMemory pulls from that URL.

**Setup:**
1. Run VideoMemory (locally or via Docker).
2. Open the [Android app](android/README.md) and tap **Start Server**.
3. Copy the snapshot URL shown on the phone.
4. In the videomemory web app: **Devices** -> **Add Network Camera** -> paste that URL.
5. Create tasks for that device as usual.

You can also just ask your openclaw to add a device and it will help you.

IMPORTANT:
Phone and VideoMemory should be on the same LAN, or both connected with [Tailscale](https://tailscale.com/download) so VideoMemory can reach the phone's snapshot URL directly.

## I want both OpenClaw and VideoMemory in Docker

This is the bundled two-container setup for **OpenClaw + VideoMemory**:

```bash
ANTHROPIC_API_KEY=your_key_here \
TELEGRAM_BOT_TOKEN=your_bot_token_here \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash ./launch_openclaw_with_videomemory.sh
```

Gemini / Google AI Studio:

```bash
GOOGLE_API_KEY=your_key_here \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
bash ./launch_openclaw_with_videomemory.sh
```

OpenRouter:

```bash
OPENROUTER_API_KEY=your_key_here \
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
OPENCLAW_FALLBACK_MODEL_1=anthropic/claude-haiku-4-5 \
OPENCLAW_FALLBACK_MODEL_2=anthropic/claude-haiku-4-5 \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

Or use OpenAI for both OpenClaw and VideoMemory:

```bash
OPENAI_API_KEY=your_key_here \
VIDEO_INGESTOR_MODEL=gpt-4o-mini \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
OPENCLAW_FALLBACK_MODEL_1=openai/gpt-5-mini \
OPENCLAW_FALLBACK_MODEL_2=openai/gpt-5-mini \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

Or use Gemini for both:

```bash
GOOGLE_API_KEY=your_key_here \
GEMINI_API_KEY=your_key_here \
VIDEO_INGESTOR_MODEL=gemini-2.5-flash \
OPENCLAW_PRIMARY_MODEL=google/gemini-3-flash-preview \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
OPENCLAW_FALLBACK_MODEL_1=google/gemini-3-pro-preview \
OPENCLAW_FALLBACK_MODEL_2=google/gemini-3-pro-preview \
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

Or use OpenRouter for both:

```bash
OPENROUTER_API_KEY=your_key_here \
VIDEO_INGESTOR_MODEL=qwen3-vl-8b \
OPENCLAW_PRIMARY_MODEL=openrouter/anthropic/claude-sonnet-4-5 \
OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token \
OPENCLAW_FALLBACK_MODEL_1=openrouter/google/gemini-2.0-flash-vision:free \
OPENCLAW_FALLBACK_MODEL_2=openrouter/google/gemini-2.0-flash-vision:free \
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
