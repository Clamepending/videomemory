# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream.

## Quick Start

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

After that, use OpenClaw normally and ask it to create monitoring tasks.

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

```bash
docker compose -f docker-compose.real-openclaw.yml up -d --build
```

Then open:
- VideoMemory: `http://localhost:5050/devices`
- OpenClaw: `http://localhost:18889/`

Gateway token:

```text
openclaw-real-dev-token
```

## Docker

### Core only

```bash
docker compose -f docker-compose.core.yml up --build
```

This starts VideoMemory. Open http://localhost:5050.

### Core + OpenClaw (for testing)

Clone [SimpleAgent](https://github.com/Clamepending/simpleagent) as a sibling directory:

```bash
cd ..
git clone https://github.com/Clamepending/simpleagent.git
cd videomemory
```

Then launch both services:

```bash
docker compose -f docker-compose.openclaw.yml up --build
```

This starts:
- **VideoMemory** on `http://localhost:5050` (UI + API)
- **OpenClaw** on `http://localhost:18789` (Chat UI + API)
- **Demo Camera** on `http://localhost:18080/snapshot.jpg` (for red-marker testing)

OpenClaw connects to VideoMemory via plain HTTP API at `http://videomemory:5050`.
It should fetch the skill from `http://videomemory:5050/openclaw/skill.md` before making task/device calls.

## Integration

VideoMemory exposes a stable HTTP API for external agents:

- Integration contract: [docs/agent-integration-contract.md](docs/agent-integration-contract.md)
- OpenClaw skill: [docs/openclaw-skill.md](docs/openclaw-skill.md)
- Agent guide: [AGENTS.md](AGENTS.md)
- OpenAPI spec: `GET /openapi.json`

## Human Setup

### VM or host OpenClaw: one command

If OpenClaw runs directly on a VM or host machine and that machine has Docker access, this one command installs VideoMemory, starts it if needed, installs the OpenClaw integration, and configures OpenClaw:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/codex/openclaw-trigger-action-split/docs/openclaw-bootstrap.sh)
```

### Docker OpenClaw: one host command, then one chat message

First start VideoMemory on the host:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/codex/openclaw-trigger-action-split/docs/install-videomemory.sh)
```

Then send this exact message to your OpenClaw:

```text
Please install and onboard VideoMemory by running VIDEOMEMORY_BASE=http://host.docker.internal:5050 bash <(curl -fsSL http://host.docker.internal:5050/openclaw/bootstrap.sh). Then use VideoMemory from http://host.docker.internal:5050/openclaw/skill.md and use the videomemory task helper for any "when X happens, do Y" request.
```

If you just want the simple repo handoff, this still works too:

```text
please download and run the videomemory system via this link: https://github.com/Clamepending/videomemory
```

If you do not already have an OpenClaw container, start from the official image:

- Docker image: [`alpine/openclaw:latest`](https://hub.docker.com/r/alpine/openclaw)

On Linux, make sure the OpenClaw container can reach the host at `host.docker.internal`. The usual Docker flag is:

```bash
--add-host=host.docker.internal:host-gateway
```

## Agent Setup

These instructions assume the reader is OpenClaw and that it is onboarding itself to VideoMemory.

### If OpenClaw is on the same VM/host as Docker

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/codex/openclaw-trigger-action-split/docs/openclaw-bootstrap.sh)
```

This one command should:
- clone or reuse the VideoMemory repo
- start `docker-compose.core.yml` if VideoMemory is not already running
- install the helper, webhook transform, and local skill into `~/.openclaw`
- merge the VideoMemory hook mapping into `~/.openclaw/openclaw.json`
- copy model API keys from the shell environment into VideoMemory settings when present

### If OpenClaw is itself running inside Docker

1. Ask the human to start VideoMemory on the host:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/codex/openclaw-trigger-action-split/docs/install-videomemory.sh)
```

2. Then run this from OpenClaw:

```bash
VIDEOMEMORY_BASE=http://host.docker.internal:5050 bash <(curl -fsSL http://host.docker.internal:5050/openclaw/bootstrap.sh)
```

3. When you need the skill URL from inside that container, use:

```bash
curl -fsSL http://host.docker.internal:5050/openclaw/skill.md
```

If `host.docker.internal` does not resolve, ask the human to relaunch the OpenClaw container with `--add-host=host.docker.internal:host-gateway`.

### General rules

1. Do not use `web_fetch` for `localhost`, `127.0.0.1`, `host.docker.internal`, or `videomemory` URLs. Use `curl` through shell/exec instead.
2. Verify VideoMemory before creating tasks:

```bash
curl -fsSL "$VIDEOMEMORY_BASE/api/health"
curl -fsSL "$VIDEOMEMORY_BASE/api/devices"
```

3. Create tasks with `bot_id: "openclaw"` so webhook wakeups can be traced cleanly.
4. Use the `videomemory-task-helper` for any "when X happens, do Y" request so VideoMemory only stores the trigger condition.
5. Expect VideoMemory to wake OpenClaw at `/hooks/videomemory-alert` when a monitored task note changes.

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
