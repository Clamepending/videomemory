# VideoMemory Monitors

## Plain Monitor

Use a plain monitor when VideoMemory only needs to collect task notes:

```bash
curl -fsSL -X POST http://127.0.0.1:5050/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "io_id": "0",
    "task_description": "Watch for a phone being held up in the frame.",
    "bot_id": "codex",
    "semantic_filter_keywords": "phone, smartphone, hand",
    "semantic_filter_threshold": 0.3
  }'
```

After this succeeds, do not poll unless the user asked for status.

## Event Monitor

Use an event monitor for "when X happens, do Y".

The split is mandatory:

- `trigger_condition`: what VideoMemory should observe and write as notes.
- `action_instruction`: what the agent should do when the note/event arrives.

OpenClaw stores the action in `~/.openclaw/hooks/state/videomemory-task-actions.json`.

Delivery modes:

- `telegram`: sends a user-facing alert through Telegram. Requires a target chat id.
- `session`: routes into a specific OpenClaw session. Requires the real current session key.
- `internal`: wakes OpenClaw but does not externally deliver a message.

Do not use `agent:main:main` as a generic session key. It may be an internal or heartbeat-owned session and will be rejected by the helper.

## Event Payload

VideoMemory emits:

```json
{
  "service": "videomemory",
  "event_type": "task_update",
  "event_id": "vm-...",
  "bot_id": "codex",
  "io_id": "0",
  "task_id": "1",
  "task_description": "Watch for a phone being held up.",
  "note": "A phone is visibly held up in the user's hand.",
  "task_api_url": "http://127.0.0.1:5050/api/task/1",
  "note_frame_api_url": "http://127.0.0.1:5050/api/task-note/42/frame"
}
```

OpenClaw uses `(bot_id, io_id, task_id)` to find the action registry entry.
