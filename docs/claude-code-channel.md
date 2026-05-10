# Claude Code Channel for VideoMemory

This repo includes a Claude Code channel server at `claude-videomemory-channel/`.
It receives VideoMemory task-update webhooks and pushes them into a running
Claude Code session.

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

## One-Time Install

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
  --dangerously-load-development-channels server:videomemory
```

When prompted, choose `I am using this for local development`.

The channel server binds to:

```text
http://127.0.0.1:8791/videomemory-event
```

Health check:

```bash
curl -fsSL http://127.0.0.1:8791/health
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
