# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream.

## Quick Start

```bash
./start.sh
```

This starts VideoMemory for local development. Open http://localhost:5050. Set your model API key in the **Settings** tab, then use the **Devices** and **Tasks** pages to manage ingestion and monitoring.

## Docker

### Core only

```bash
docker compose -f docker-compose.core.yml up --build
```

This starts VideoMemory. Open http://localhost:5050.

### Core + SimpleAgent (for testing)

Clone [SimpleAgent](https://github.com/Clamepending/simpleagent) as a sibling directory:

```bash
cd ..
git clone https://github.com/Clamepending/simpleagent.git
cd videomemory
```

Then launch both services:

```bash
docker compose -f docker-compose.simpleagent.yml up --build
```

This starts:
- **VideoMemory** on `http://localhost:5050` (UI + API)
- **SimpleAgent** on `http://localhost:18889` (Chat UI + API)

SimpleAgent connects to VideoMemory via HTTP API at `http://videomemory:5050`.

## Integration

VideoMemory exposes a stable HTTP API for external agents:

- Integration contract: [docs/agent-integration-contract.md](docs/agent-integration-contract.md)
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
