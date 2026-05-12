# VideoMemory for Claude Code

This is the Claude Code plugin for VideoMemory.

It gives Claude tools to start/check local VideoMemory, open the FaceTime
browser camera bridge, create camera monitors, and receive VideoMemory
`task_update` webhooks as channel messages.

After the plugin is installed, the intended user prompt is natural language:

```text
Download VideoMemory and watch my pet dog from my FaceTime camera.
```

## Launch

From the VideoMemory repo:

```bash
CLAUDE_PLUGIN_ROOT=$PWD/claude-videomemory-channel \
claude \
  --mcp-config claude-videomemory-channel/.mcp.json \
  --channels server:videomemory \
  --allowedTools mcp__videomemory__setup_local,mcp__videomemory__reply,mcp__videomemory__inspect_task,mcp__videomemory__inspect_device,mcp__videomemory__list_devices,mcp__videomemory__list_monitors,mcp__videomemory__create_monitor,mcp__videomemory__configure_channel_webhook
```

Use `videomemory claude launch --dev` only while developing the local channel
package. That mode uses Claude Code's development-channel flag and asks for
local-development confirmation.

The server uses Node.js and `@modelcontextprotocol/sdk`. Install once:

```bash
cd claude-videomemory-channel
npm install
```

## Configure VideoMemory

Point VideoMemory's webhook setting at the channel:

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL \
  -H 'Content-Type: application/json' \
  -d '{"value":"http://127.0.0.1:8791/videomemory-event"}'
```

The setting name still says `OPENCLAW` because that is the existing VideoMemory
server setting, but the URL can point at any compatible event receiver.

## Synthetic Test

With Claude running:

```bash
curl -fsSL -X POST http://127.0.0.1:8791/videomemory-event \
  -H 'Content-Type: application/json' \
  -d '{
    "service":"videomemory",
    "event_type":"task_update",
    "event_id":"manual-test-1",
    "bot_id":"claude",
    "io_id":"0",
    "task_id":"manual",
    "task_description":"Watch for a phone held up.",
    "note":"A phone is clearly held up in the user hand.",
    "task_api_url":"http://127.0.0.1:5050/api/task/manual"
  }'
```

To see replies emitted through the channel test surface:

```bash
curl -N http://127.0.0.1:8791/events
```

For simple true/false visual triggers, create monitors with
`monitor_type: "binary"`. The create-monitor tool returns a `readiness` object;
if `readiness.ready` is false, the task was created but the camera feed still
needs attention.
