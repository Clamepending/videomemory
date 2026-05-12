# VideoMemory for Claude Code

This repo includes a Claude Code plugin at `claude-videomemory-channel/`. It
lets Claude set up local VideoMemory, open the FaceTime browser camera bridge,
create visual monitors, and receive monitor events as push-style Claude channel
messages.

The target user flow is:

```text
Download VideoMemory and watch my pet dog from my FaceTime camera.
```

Claude should handle setup, camera readiness, monitor creation, and later wakeup
without exposing the user to Flask/webhook/MCP details.

## What This Enables

```text
VideoMemory monitor task
  -> task note / detection
  -> POST http://127.0.0.1:8791/videomemory-event
  -> Claude Code channel
  -> running Claude Code session receives <channel source="videomemory" ...>
```

This is true push-style event delivery into Claude Code. Generic HTTP polling
or control-plane tools can create VideoMemory tasks, but they do not wake a
running Claude session unless a channel or webhook receiver is active.

## One-Command Local Path

Install from this repo as a Claude Code plugin:

```bash
claude plugin marketplace add https://github.com/Clamepending/videomemory
claude plugin install videomemory@videomemory
```

From this checkout:

```bash
node videomemory-package/cli.mjs claude --repo-dir "$PWD"
```

After the npm package is republished, the same flow should be available as:

```bash
videomemory claude
```

This is the normal onboarding and launch path. It starts or checks VideoMemory,
installs/checks the channel package, points VideoMemory at
`http://127.0.0.1:8791/videomemory-event`, opens the browser camera bridge on
macOS, checks Claude auth, and launches Claude Code with the VideoMemory channel
and MCP tools enabled.

If it stops at Claude auth, run:

```bash
claude auth login
node videomemory-package/cli.mjs claude --repo-dir "$PWD"
```

For CI/debugging without launching Claude:

```bash
node videomemory-package/cli.mjs claude --repo-dir "$PWD" --no-launch --no-open-camera --skip-auth --json
```

Lower-level commands remain available:

```bash
videomemory claude install
videomemory claude doctor
videomemory claude launch
```

Manual repo install:

```bash
cd claude-videomemory-channel
npm install
npm run check
```

## Launch Claude With The Channel

From the VideoMemory repo:

```bash
CLAUDE_PLUGIN_ROOT=$PWD/claude-videomemory-channel \
claude \
  --mcp-config claude-videomemory-channel/.mcp.json \
  --channels server:videomemory \
  --allowedTools mcp__videomemory__setup_local,mcp__videomemory__reply,mcp__videomemory__inspect_task,mcp__videomemory__inspect_device,mcp__videomemory__list_devices,mcp__videomemory__list_monitors,mcp__videomemory__create_monitor,mcp__videomemory__configure_channel_webhook
```

Use `videomemory claude launch --dev` only while developing the local channel
package. That mode uses `--dangerously-load-development-channels` and Claude
Code will ask you to confirm local development.

The channel server binds to:

```text
http://127.0.0.1:8791/videomemory-event
```

Health check:

```bash
curl -fsSL http://127.0.0.1:8791/health
```

Inside Claude, a simple local true/false request can use the binary monitor:

```text
Use the binary monitor on the FaceTime camera and wake up when a human is visible.
```

## Configure VideoMemory

Point VideoMemory's existing webhook setting at the Claude channel:

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL \
  -H 'Content-Type: application/json' \
  -d '{"value":"http://127.0.0.1:8791/videomemory-event"}'
```

Clear any previous bearer token unless you set `VIDEOMEMORY_CLAUDE_CHANNEL_TOKEN`:

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN \
  -H 'Content-Type: application/json' \
  -d '{"value":""}'
```

The setting name still says `OPENCLAW` because it is the existing VideoMemory
server setting. The value can point at any compatible receiver.

## Synthetic Event Test

With Claude running:

```bash
curl -fsSL -X POST http://127.0.0.1:8791/videomemory-event \
  -H 'Content-Type: application/json' \
  -d '{
    "service":"videomemory",
    "event_type":"task_update",
    "event_id":"manual-claude-channel-test",
    "bot_id":"claude",
    "io_id":"0",
    "task_id":"manual",
    "task_description":"Watch for a phone visibly held up in the user hand.",
    "note":"A phone is clearly held up in the user hand.",
    "action_instruction":"Reply through the VideoMemory channel test surface with exactly: VideoMemory saw the phone held up."
  }'
```

Optional: watch replies from Claude's `mcp__videomemory__reply` tool:

```bash
curl -N http://127.0.0.1:8791/events
```

The released CLI can send the same synthetic event:

```bash
videomemory claude test-event
```

## Claude Tools

The channel exposes these MCP tools to Claude:

- `mcp__videomemory__setup_local`
- `mcp__videomemory__list_devices`
- `mcp__videomemory__create_monitor`
- `mcp__videomemory__inspect_task`
- `mcp__videomemory__inspect_device`
- `mcp__videomemory__list_monitors`
- `mcp__videomemory__configure_channel_webhook`
- `mcp__videomemory__reply`

For "watch for X" requests, Claude should create a monitor and stop. VideoMemory
owns the long-running watch and pushes the next task event back through the
channel.

`mcp__videomemory__create_monitor` accepts `monitor_type: "binary"` for the local
FastVLM true/false monitor, or `monitor_type: "general"` for chunked VLM
reasoning.

`mcp__videomemory__create_monitor` also returns a `readiness` object. If
`readiness.ready` is false, the task exists but the camera feed is not ready.
Agents should surface the readiness warning instead of claiming the monitor is
fully armed.

## Expected Test Result

When the channel starts successfully, Claude Code reports:

```text
Listening for channel messages from: server:videomemory
```

Posting a synthetic VideoMemory event should return HTTP `202`, and Claude
should receive the inbound `videomemory` channel event.

If Claude receives the event but does not answer, verify auth with:

```bash
claude -p 'Respond with exactly ok'
```

If that command fails with `401`, run `/login` inside Claude Code, then repeat
the synthetic event test.
