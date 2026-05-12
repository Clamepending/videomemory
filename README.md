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

## Quick Start: Claude Code

Install the VideoMemory Claude plugin:

```bash
claude auth login
claude plugin marketplace add https://github.com/Clamepending/videomemory
claude plugin install videomemory@videomemory
```

Then ask Claude Code:

```text
Use VideoMemory to watch my pet dog from my FaceTime camera. Wake me when the dog is visible.
```

Claude will start/check VideoMemory, open the FaceTime browser camera bridge,
ask you to grant camera permission if needed, create a fast binary monitor, and
wake up when the visual condition is met. Keep the opened camera tab running
while the monitor is active.

For a different stream, ask naturally:

```text
Use VideoMemory to watch the RTSP stream at rtsp://... and tell me when a person enters.
```

Until the next public package release, local development can use:

```bash
node videomemory-package/cli.mjs claude --repo-dir "$PWD"
```

## Core Service Quick Start

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
node scripts/agent/ensure-server.mjs --json
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
node scripts/agent/simulate-webhook-event.mjs \
  --task-id 0 \
  --confirm true \
  --json
```

The simulator uses the saved `VIDEOMEMORY_OPENCLAW_WEBHOOK_URL` by default; pass
`--webhook-url` to override it for a dummy local receiver. If the receiver
requires a bearer token, pass `--webhook-token` because the settings API masks
saved secrets.

## Claude Code

VideoMemory is meant to feel like a Claude Code capability, not a separate
agent platform. From this checkout, the local path is:

```bash
node videomemory-package/cli.mjs claude --repo-dir "$PWD"
```

After the npm package is republished, the same flow should be available as
`videomemory claude`.

The command starts or checks VideoMemory, installs/checks the channel package,
wires the VideoMemory webhook to Claude, opens the browser camera bridge on
macOS, checks Claude auth, and launches Claude Code with the VideoMemory
channel and MCP tools enabled.

If Claude auth is stale, run `claude auth login` once and rerun
the command.

With the Claude plugin installed, the target UX is natural language:

```text
Download VideoMemory and watch my pet dog from my FaceTime camera.
```

Claude should call VideoMemory setup, open the FaceTime browser camera bridge,
ask you to grant camera permission if needed, then create a binary monitor for
the visual condition.

For direct installation from this repo as a Claude Code plugin:

```bash
claude plugin marketplace add https://github.com/Clamepending/videomemory
claude plugin install videomemory@videomemory
```

Then in Claude:

```text
Use VideoMemory to watch my pet dog from my FaceTime camera.
```

The channel exposes MCP tools for device discovery, monitor creation, task
inspection, and webhook configuration. If you are developing from the repo, the
equivalent manual launch after `videomemory claude install` is:

```bash
CLAUDE_PLUGIN_ROOT=$PWD/claude-videomemory-channel \
claude \
  --mcp-config claude-videomemory-channel/.mcp.json \
  --channels server:videomemory \
  --allowedTools mcp__videomemory__setup_local,mcp__videomemory__reply,mcp__videomemory__inspect_task,mcp__videomemory__inspect_device,mcp__videomemory__list_devices,mcp__videomemory__list_monitors,mcp__videomemory__create_monitor,mcp__videomemory__configure_channel_webhook
```

Use `videomemory claude launch --dev` only while developing the local channel
package; it will trigger Claude Code's local-development channel confirmation.

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
- `GET /api/device/{io_id}/readiness`
- `POST /api/caption_frame`
- `GET /api/tasks`
- `POST /api/tasks` (`monitor_type` can be `general` or `binary`)
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
- [docs/claude-code-channel.md](docs/claude-code-channel.md)
- [docs/openclaw-skill.md](docs/openclaw-skill.md) for legacy OpenClaw integration

## Release

Current release line:

- Core app: `0.1.6`
- npm package: `@clamepending/videomemory@0.1.9`
- App tag expected by installers: `v0.1.6`

## Legacy OpenClaw

The npm package still includes an OpenClaw integration for existing users:

```bash
openclaw plugins install @clamepending/videomemory@0.1.9
```

Restart the OpenClaw gateway, then run `/videomemory-onboard`.

Release checklist:

- [CHANGELOG.md](CHANGELOG.md)
- [docs/release-checklist.md](docs/release-checklist.md)
