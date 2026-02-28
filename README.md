# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream.

## Quick Start

```bash
./start.sh
```

This launches MediaMTX and VideoMemory together for local development. Open http://localhost:5050. Set your model API key in the **Settings** tab, then use the **Devices** and **Tasks** pages to manage ingestion and monitoring.

## Core + external agent architecture

VideoMemory is the **core ingest/task service**. Run your conversational/admin agent separately and integrate it using the VideoMemory HTTP API, webhook callbacks, and MCP server.

Two supported runtime modes:

- **Event Mode (primary):** run `VideoMemory` on the local app/device/edge box (ingest + analysis), and run `OpenClaw`/MCP in the cloud for orchestration. Best for centralized cloud control across many apps/devices.
- **Streaming Mode (fallback):** run `VideoMemory` in the cloud and stream devices to it via RTMP/SRT/WHIP. Best for self-hosters/DIY users and simple all-in-one deployments.

Architecture details:

- [docs/edge-cloud-architecture.md](docs/edge-cloud-architecture.md)

Integration contract:

- [docs/agent-integration-contract.md](docs/agent-integration-contract.md)

Run VideoMemory core with MCP:

```bash
docker compose -f docker-compose.core.yml up --build
```

Then launch OpenClaw (or your own admin gateway/agent) separately and connect it to VideoMemory.

### Testing flow options

- **Full end-to-end suite (recommended):**
  - `bash deploy/test-e2e-suite.sh`
  - Optional flags: `--skip-unit`, `--skip-docker`, `--skip-phone-demo`, `--no-build`, `--keep-stacks`
- **Core only (bring your own external service):**
  - `docker compose -f docker-compose.core.yml up --build`
- **Core + OpenClaw:**
  - `docker compose -f docker-compose.openclaw.yml up --build`
  - `bash deploy/test-openclaw-stack.sh`
- **Core + local AdminAgent (from sibling repo `../adminagent`):**
  - `docker compose -f docker-compose.adminagent.yml up --build`
  - `bash deploy/test-adminagent-stack.sh`

AdminAgent repository: `https://github.com/Clamepending/adminagent.git`

### Edge mode command return path (cloud -> edge)

VideoMemory already supports `edge -> cloud` triggers via webhook. For `cloud -> edge` requests when VideoMemory is behind NAT/private LAN, configure the optional edge-initiated command poller (disabled by default):

- `VIDEOMEMORY_OPENCLAW_COMMAND_PULL_URL` (enable switch)
- `VIDEOMEMORY_OPENCLAW_COMMAND_RESULT_URL` (optional)
- `VIDEOMEMORY_OPENCLAW_COMMAND_TOKEN` (optional bearer token)
- `VIDEOMEMORY_OPENCLAW_EDGE_ID` (optional edge identity)

The poller fetches commands from the cloud, executes them against the local VideoMemory HTTP API, and posts results back. See `docs/agent-integration-contract.md` for the command envelope.

## Event Mode (End-to-End)

Terminology:

- **Edge VideoMemory Server**: VideoMemory running on-device / on a local host doing ingestion loops and visualizing sensors.
- **Cloud VideoMemory Server**: lightweight cloud control plane (queue + trigger intake + MCP for OpenClaw).

Transport between edge and cloud:

- **Streaming Mode**: raw video streams (RTMP/SRT/WHIP)
- **Event Mode**: triggers + command polling + command results

### Cloud stack (OpenClaw + Cloud VideoMemory Server)

Start the server-side stack:

```bash
docker compose -f docker-compose.eventmode.yml up --build
```

This starts:

- Cloud VideoMemory Server on `http://localhost:8785`
- Cloud VideoMemory MCP endpoint on `http://localhost:8785/mcp`
- OpenClaw gateway on `http://localhost:18789`
- Minimal Event Mode dashboard UI on `http://localhost:8785/`

Optional smoke test for the cloud control plane:

```bash
bash deploy/test-eventmode-cloud.sh
```

Optional MCP smoke test (OpenClaw-compatible command enqueue path):

```bash
bash deploy/test-eventmode-mcp.sh
```

### Phone demo (Android app -> Cloud UI)

Use this for a quick demo of Event Mode transport before wiring full edge ingestion on mobile:

1. Start the cloud stack: `docker compose -f docker-compose.eventmode.yml up --build`
2. Open the dashboard on your computer: `http://localhost:8785/`
3. Build/install the Android app (`android/app/build/outputs/apk/debug/app-debug.apk`) and launch it
4. Switch the app to **Event Mode**
5. Enter your computer's LAN endpoint:
   - `http://YOUR_PC_IP:8785/api/event/triggers`
6. Tap **Start**

The app will keep local camera preview active and send periodic trigger/heartbeat events to the Cloud VideoMemory Server. The dashboard should show:

- a new `edge_id` under **Edges**
- incoming records under **Recent Triggers (Edge -> Cloud)**

Secured local demo (optional):

- Start cloud stack with a token, for example:
  - `VIDEOMEMORY_CLOUD_TOKEN=demo-token docker compose -f docker-compose.eventmode.yml up --build`
- In the Android app Event Mode screen, fill **Optional cloud token (Bearer)** with `demo-token`
- Export `VIDEOMEMORY_CLOUD_TOKEN=demo-token` before running `deploy/test-eventmode-cloud.sh` or `deploy/test-eventmode-mcp.sh`

### Demo queued commands from the cloud UI

From the dashboard (`http://localhost:8785/`), use **Queue Command (Manual Demo)** with the phone's `edge_id`.

Mobile demo actions currently supported by the Android app in Event Mode:

- `ping` (returns `{ "pong": true }`)
- `show_toast` with args JSON like `{ "message": "hello from cloud" }`
- `emit_test_event` (phone emits an immediate test trigger)
- `list_devices` (returns a demo mobile preview device list)
- `list_tasks` (returns local edge task list from the phone)
- `get_task` with args JSON like `{ "task_id": "1" }`
- `create_task` with args JSON like `{ "io_id": "phone-camera-0", "task_description": "Watch the driveway" }`
- `update_task` / `edit_task` with args JSON like `{ "task_id": "1", "new_description": "Watch for package deliveries" }`
- `stop_task` with args JSON like `{ "task_id": "1" }`
- `delete_task` with args JSON like `{ "task_id": "1" }`

You should then see:

- command fetch/processing in the phone's **Event Mode Log**
- task updates in the phone's **Edge Server State (Demo)** panel
- rows appear in the cloud dashboard **Recent Results (Edge -> Cloud)**
- `task_update` events appear in **Recent Triggers (Edge -> Cloud)** when cloud commands change tasks

### Edge VideoMemory Server setup (Event Mode)

Run VideoMemory on the edge/local machine (the one doing ingest/analysis), and set:

```bash
export VIDEOMEMORY_DEPLOYMENT_MODE=event
export VIDEOMEMORY_OPENCLAW_EDGE_ID=edge-lab-1
export VIDEOMEMORY_OPENCLAW_WEBHOOK_URL=http://YOUR_CLOUD_HOST:8785/api/event/triggers
export VIDEOMEMORY_OPENCLAW_COMMAND_PULL_URL=http://YOUR_CLOUD_HOST:8785/api/event/commands/pull
export VIDEOMEMORY_OPENCLAW_COMMAND_RESULT_URL=http://YOUR_CLOUD_HOST:8785/api/event/commands/result
export VIDEOMEMORY_OPENCLAW_COMMAND_TOKEN=change-me
uv run flask_app/app.py
```

In Event Mode, the **Edge VideoMemory Server UI** remains the main local visualization for ingestors:

- `http://EDGE_HOST:5050/devices`
- `http://EDGE_HOST:5050/device/<io_id>/debug`

This preserves the monolithic-style sensor/ingestor visibility while moving orchestration to the cloud.

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
docker-compose -f docker-compose.openclaw.yml up --build
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

For end-to-end phone + DM preflight (includes adapter forwarding and prints a phone RTMP URL):

```bash
LAPTOP_HOST=<your-laptop-lan-ip> bash deploy/test-openclaw-phone-demo.sh
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
4. Changes apply immediately; no restart is required.

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

This is **Streaming Mode** (cloud-ingest fallback mode, kept intentionally in case you want to revert from edge processing).

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
