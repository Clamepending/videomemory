# Claude VideoMemory Channel

This is a Claude Code channel for VideoMemory monitor events.

It starts a localhost HTTP server and forwards VideoMemory `task_update`
webhooks into the running Claude Code session as channel messages.

## Launch

From the VideoMemory repo:

```bash
CLAUDE_PLUGIN_ROOT=$PWD/claude-videomemory-channel \
claude \
  --mcp-config claude-videomemory-channel/.mcp.json \
  --dangerously-load-development-channels server:videomemory
```

Claude Code channels are a research preview. The development flag is required
for this local custom channel unless it is installed from an approved channel
marketplace.

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
