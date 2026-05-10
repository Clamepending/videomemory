# VideoMemory

VideoMemory is a small HTTP service that lets agents monitor video streams.
An agent creates a natural-language task such as "tell me when a phone is held
up", VideoMemory watches the camera with a vision-language model, then emits a
webhook when the task note changes.

Supported inputs:

- USB or built-in cameras
- RTSP / HTTP video streams
- Android phone snapshot streams
- Browser camera frames posted into VideoMemory

## Quick Start

Run the core service:

```bash
uv run flask_app/app.py
```

Open [http://localhost:5050](http://localhost:5050), set a model API key in
Settings, add or select a device, then create a task.

Core-only Docker:

```bash
docker compose -f docker-compose.core.yml up --build
```

Health and discovery:

```bash
curl -fsSL http://localhost:5050/api/health
curl -fsSL http://localhost:5050/api/devices
curl -fsSL http://localhost:5050/openapi.json
```

`/api/health` only proves the server is up. Before expecting monitors to
analyze frames, confirm model and webhook readiness:

```bash
node .agents/skills/videomemory/scripts/ensure-server.mjs --json
```

If the model is `local-vllm`, start the configured local model server or switch
`VIDEO_INGESTOR_MODEL` to a cloud model and set the matching API key. On macOS,
the terminal or app that launches Python may also need Camera permission before
USB/built-in cameras can produce frames.

## Agent Wakeups

VideoMemory is the perception engine. The external agent owns conversation,
policy, delivery, and follow-up actions.

For "when X happens, do Y":

1. Put only the visual condition in the VideoMemory task.
2. Store the follow-up action in the agent runtime.
3. Configure `VIDEOMEMORY_OPENCLAW_WEBHOOK_URL` or another compatible webhook.
4. Use saved `note_frame_api_url` / `note_video_api_url` from the webhook when
   responding. Do not take a fresh snapshot unless the user asked for current
   state.

Create a task directly:

```bash
curl -fsSL -X POST http://localhost:5050/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "io_id": "0",
    "task_description": "Watch for a phone visibly held up in the user hand.",
    "bot_id": "my-agent",
    "semantic_filter_keywords": "phone, smartphone, hand, person",
    "save_note_frames": true,
    "save_note_videos": true
  }'
```

Configure a generic webhook receiver:

```bash
curl -fsSL -X PUT http://localhost:5050/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL \
  -H 'Content-Type: application/json' \
  -d '{"value":"http://127.0.0.1:18789/hooks/videomemory-alert"}'

curl -fsSL -X PUT http://localhost:5050/api/settings/VIDEOMEMORY_SELF_BASE_URL \
  -H 'Content-Type: application/json' \
  -d '{"value":"http://127.0.0.1:5050"}'
```

To test a webhook receiver without waiting for a real detection:

```bash
node .agents/skills/videomemory/scripts/simulate-webhook-event.mjs \
  --task-id 0 \
  --confirm true \
  --json
```

The simulator uses the saved `VIDEOMEMORY_OPENCLAW_WEBHOOK_URL` by default; pass
`--webhook-url` to override it for a dummy local receiver. If the receiver
requires a bearer token, pass `--webhook-token` because the settings API masks
saved secrets.

## OpenClaw

The maintained OpenClaw package is the easiest current end-to-end path for
agent wakeups:

```bash
openclaw plugins install @clamepending/videomemory@0.1.8
```

Restart the OpenClaw gateway, then run:

```text
/videomemory-onboard
```

Fallback CLI:

```bash
npx -y @clamepending/videomemory@0.1.8 onboard --safe --repo-ref v0.1.4 --explain
npx -y @clamepending/videomemory@0.1.8 onboard --safe --repo-ref v0.1.4
```

Bundled local OpenClaw + VideoMemory stack:

```bash
ANTHROPIC_API_KEY=your_key_here \
OPENCLAW_GATEWAY_TOKEN=choose-a-token \
bash ./launch_openclaw_with_videomemory.sh
```

The launcher prints both the VideoMemory UI and the OpenClaw dashboard URL.

## Claude Code

Claude Code wakeups use the experimental channel package in
`claude-videomemory-channel/`.

```bash
cd claude-videomemory-channel
npm install
npm run check
```

From the repo root:

```bash
CLAUDE_PLUGIN_ROOT=$PWD/claude-videomemory-channel \
claude \
  --mcp-config claude-videomemory-channel/.mcp.json \
  --dangerously-load-development-channels server:videomemory
```

Then point VideoMemory at the channel:

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL \
  -H 'Content-Type: application/json' \
  -d '{"value":"http://127.0.0.1:8791/videomemory-event"}'
```

See [docs/claude-code-channel.md](docs/claude-code-channel.md).

## Android Camera

Use the Android app as a wireless camera:

1. Run VideoMemory.
2. Open [android/README.md](android/README.md) and start the phone snapshot server.
3. Add the snapshot URL in the VideoMemory Devices page.
4. Create tasks for that network camera.

The phone and VideoMemory host must be mutually reachable, usually on the same
LAN or through Tailscale.

## API

Useful endpoints:

- `GET /api/health`
- `GET /api/devices`
- `POST /api/device/{io_id}/capture`
- `GET /api/device/{io_id}/preview`
- `POST /api/caption_frame`
- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/task/{task_id}`
- `PUT /api/task/{task_id}`
- `POST /api/task/{task_id}/stop`
- `DELETE /api/task/{task_id}`
- `GET /api/task-note/{note_id}/frame`
- `GET /api/task-note/{note_id}/video`
- `GET /openapi.json`

More integration detail:

- [AGENTS.md](AGENTS.md)
- [docs/agent-integration-contract.md](docs/agent-integration-contract.md)
- [docs/openclaw-skill.md](docs/openclaw-skill.md)

## Release

Current release line:

- Core app: `0.1.4`
- OpenClaw package: `@clamepending/videomemory@0.1.8`
- App tag expected by installers: `v0.1.4`

Release checklist:

```bash
uv run python -m unittest tests.test_openclaw_integration \
  tests.test_videomemory_alert_transform \
  tests.test_openclaw_plugin_scaffold \
  tests.test_videomemory_task_helper_original_request \
  tests.test_video_stream_ingestor_detection_callbacks \
  tests.test_task_note_videos \
  tests.test_task_note_video_api

cd openclaw-plugin && npm pack
```

Then tag `v0.1.4`, push the tag, publish the npm package, and publish GitHub
release notes.
