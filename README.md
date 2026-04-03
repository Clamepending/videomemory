# VideoMemory

Use vision language models to let your openclaw see and monitor cameras (USB, RTSP, Android devices)

You or your agent creates a **tasks** describing what to watch for, and the system continuously analyses the video stream.

## Quick Start

To launch both OpenClaw and VideoMemory in containers, use:
```bash
ANTHROPIC_API_KEY=<YOUR ANTHROPIC API KEY> \
OPENCLAW_GATEWAY_TOKEN=chooseyourowntoken \
bash ./launch_openclaw_with_videomemory.sh
```
(OPENAI_API_KEY, GOOGLE_API_KEY, and OPENROUTER_API_KEY are supported too)

It prints:
- a ready-to-open OpenClaw dashboard link
- the VideoMemory UI link

To launch just Videomemory (no openclaw)
```bash
./start.sh
```
This starts VideoMemory for local development. Open http://localhost:5050. Set your model API key in the **Settings** tab, then use the **Devices** and **Tasks** pages to manage ingestion and monitoring.

## I already have OpenClaw on a VM, server, or computer

Send this message to OpenClaw:

```text
Please Run this and onboard: bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/openclaw-bootstrap.sh)
```
After that, your OpenClaw should be able to:
- create/list/edit/stop/delete VideoMemory tasks
- answer one-off camera questions like `what do you see on camera?`
- Monitor cameras like `when X happens in camera Y, do Z`
Hint: You can set up telegram in openclaw.
Install Tailscale to stream video to videomemory over the android app.

## I already have OpenClaw in a container

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

## Integration

VideoMemory exposes a stable HTTP API for external agents:

- Integration contract: [docs/agent-integration-contract.md](docs/agent-integration-contract.md)
- OpenClaw skill: [docs/openclaw-skill.md](docs/openclaw-skill.md)
- Agent guide: [AGENTS.md](AGENTS.md)
- OpenAPI spec: `GET /openapi.json`
