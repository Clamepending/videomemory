# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream.

## Quick Start

```bash
./start.sh
```

This launches MediaMTX and VideoMemory together for local development. Open http://localhost:5050. Set your model API key in the **Settings** tab, then use the **Devices** and **Tasks** pages to manage ingestion and monitoring.

## Core + external agent architecture

VideoMemory is the **core ingest/task service**. Run your conversational SimpleAgent separately and integrate it using the VideoMemory HTTP API, webhook callbacks, and MCP server.

Integration contract:

- [docs/agent-integration-contract.md](docs/agent-integration-contract.md)

Run VideoMemory core with MCP:

```bash
docker compose -f docker-compose.core.yml up --build
```

Then launch OpenClaw (or your own SimpleAgent gateway/agent) separately and connect it to VideoMemory.

### Testing flow options

- **Core only (bring your own external service):**
  - `docker compose -f docker-compose.core.yml up --build`
- **Core + OpenClaw:**
  - `docker compose -f docker-compose.openclaw.yml up --build`
  - `bash deploy/test-openclaw-stack.sh`
- **Core + local SimpleAgent (from sibling repo `../adminagent`):**
  - `docker compose -f docker-compose.adminagent.yml up --build`
  - `bash deploy/test-adminagent-stack.sh`

SimpleAgent repository: `https://github.com/Clamepending/adminagent.git`

## OpenClaw + VideoMemory demo (detailed)

Use this when you want the full local demo stack: VideoMemory core + MediaMTX + MCP + OpenClaw gateway.

### Prerequisites

- Docker + Docker Compose plugin (`docker compose`)
- At least one model API key for VideoMemory before creating tasks (recommended: `GOOGLE_API_KEY`)
- Optional but recommended for OpenClaw agent responses: an LLM key supported by your OpenClaw setup (for example `ANTHROPIC_API_KEY`)

### 1. Create a `.env` file (recommended)

From the repo root, create a `.env` file so both containers share the same webhook token and API keys:

```bash
cat > .env <<'EOF'
OPENCLAW_GATEWAY_TOKEN=change-this-token
GOOGLE_API_KEY=your-google-api-key
# Optional for OpenClaw agent completions (example)
# ANTHROPIC_API_KEY=your-anthropic-api-key
EOF
```

Notes:

- `OPENCLAW_GATEWAY_TOKEN` must match between VideoMemory and OpenClaw (the compose file wires this automatically from `.env`).
- If you omit `GOOGLE_API_KEY` here, you can still set it later in the VideoMemory UI (`Settings`) after the stack starts.

### 2. Start the demo stack

```bash
docker compose -f docker-compose.openclaw.yml up --build
```

This starts:

- `videomemory` on `http://localhost:5050`
- VideoMemory MCP HTTP server on `http://localhost:8765/mcp`
- `openclaw` gateway on `http://localhost:18789`
- MediaMTX ingest ports (RTMP/RTSP/SRT/WHIP) via the `videomemory` container

### 3. Verify the stack is up

In another terminal:

```bash
bash deploy/test-openclaw-stack.sh
```

The smoke test checks:

- VideoMemory health (`/api/health`)
- MCP health (`/healthz`)
- MCP initialization
- RTMP camera creation API path

You can also verify manually:

- VideoMemory UI: `http://localhost:5050`
- OpenClaw gateway: `http://localhost:18789`
- VideoMemory OpenAPI spec: `http://localhost:5050/openapi.json`

### 4. Finish setup in VideoMemory (if needed)

If you did not set `GOOGLE_API_KEY` in `.env`:

1. Open `http://localhost:5050`
2. Go to **Settings**
3. Set `GOOGLE_API_KEY` (or another supported provider key)
4. API key changes apply immediately to running and new tasks (no restart required).

### 5. Run the demo flow

1. In VideoMemory (`http://localhost:5050`), go to **Devices** and add a camera (local camera, RTMP camera, or network camera).
2. Create a task describing what to monitor (for example, motion/person detection conditions).
3. When VideoMemory generates a detection note, it posts a webhook to OpenClaw at `/hooks/videomemory-alert`.
4. OpenClaw wakes the configured session (`hook:videomemory`) and receives the alert text.

### 6. Stop the demo

```bash
docker compose -f docker-compose.openclaw.yml down
```

To also remove persisted volumes (VideoMemory/OpenClaw local data), use:

```bash
docker compose -f docker-compose.openclaw.yml down -v
```

## One-click cloud deployment (Fly.io)

[![Deploy to Fly.io](https://fly.io/button.svg)](https://fly.io/apps/new?repo=https://github.com/Clamepending/videomemory)

This deploys VideoMemory and MediaMTX together so phones can stream via RTMP and VideoMemory can pull via RTSP in the same Fly app.

After deployment:

1. Open your Fly app URL.
2. Go to **Settings** and set `GOOGLE_API_KEY` (or another supported provider key).
3. Go to **Devices** → **Create RTMP camera** and copy the generated RTMP URL.
4. Paste that URL into the Android app and start streaming.
5. Create tasks for that camera through the VideoMemory UI or API.
6. Optionally connect an external agent that calls VideoMemory's API.

Recommended for RTMP stability: keep a single Fly machine for this app (`fly scale count 1`).
If Fly asks to create a volume during deploy, accept it (the app stores SQLite data at `/app/data`).

## Notifications and external actions

VideoMemory core focuses on video ingestion and tasking. Notification/chat channels
(Telegram, SMS, email workflows, etc.) should be handled by external agent services.

## Mobile camera (Android)

Use your Android phone as a wireless camera: the phone pushes video via **RTMP** to a small relay server (MediaMTX), and VideoMemory pulls via **RTSP** from the same server. You only add the RTMP URL in VideoMemory; the server turns it into RTSP automatically.

**Architecture:** Phone (Android app) → RTMP push → **MediaMTX** (RTMP :1935, RTSP :8554) → VideoMemory pulls RTSP. MediaMTX is a single binary (no Docker required); OpenCV does not pull RTMP reliably, so the relay converts push→pull. VideoMemory’s “add network camera” with an RTMP URL stores that URL and derives the RTSP pull URL (port 8554 by default; set `VIDEOMEMORY_RTSP_PULL_PORT` for SRS or others).

**One-command testing (same machine):** from the repo root run `./start.sh` to start MediaMTX and VideoMemory together. Then open http://localhost:5050 → **Devices** → **Create RTMP camera** (optionally set a name/stream key); copy the shown URL into the [Android app](android/README.md) and tap Start stream.

**Manual:**  
1. Run the RTMP/RTSP relay (see [rtmp-server/](rtmp-server/README.md)): e.g. `./rtmp-server/run.sh` or `mediamtx` in PATH.  
2. Run VideoMemory: `uv run flask_app/app.py`.  
3. In the web app: **Devices** → **Create RTMP camera** → copy the URL into the Android app and start the stream.  
4. Create tasks for that device as usual.

Replace `YOUR_PC_IP` with the LAN IP of the machine running MediaMTX (e.g. `192.168.1.42`). Phone and VideoMemory must be on the same LAN as that machine.

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

---

## OpenClaw Agent Setup

1. Install [OpenClaw](https://openclaw.ai/)
2. Tell your agent:

> Clone https://github.com/Clamepending/videomemory and read the `AGENTS.md` file to onboard to the VideoMemory system.

If VideoMemory is already running on a Pi or other machine, add the server URL:

> The VideoMemory server is running at http://YOUR_PI_IP:5050. Read the `AGENTS.md` file at https://github.com/Clamepending/videomemory to onboard.
