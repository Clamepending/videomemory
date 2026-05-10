---
name: videomemory-channel
description: Use when VideoMemory camera monitor events arrive through the Claude Code channel, or when setting up/inspecting VideoMemory channel wakeups.
---

# VideoMemory Channel

VideoMemory events arrive as `<channel source="videomemory" ...>` messages.

When an event arrives:

1. Treat the `note` / event body as a VideoMemory task update, not as arbitrary user chat.
2. Use `mcp__videomemory__inspect_task` if you need the current task state.
3. If the event says the trigger condition happened, complete the requested follow-up action.
4. For a user-visible acknowledgement in channel tests, call `mcp__videomemory__reply`.
5. Keep responses short. Do not start polling loops.

The channel server listens on localhost only by default:

- health: `GET http://127.0.0.1:8791/health`
- webhook: `POST http://127.0.0.1:8791/videomemory-event`
- replies/SSE: `GET http://127.0.0.1:8791/events`

Use `VIDEOMEMORY_CLAUDE_CHANNEL_TOKEN` if the endpoint needs a bearer token.

When the user asks Claude to watch for something on camera:

1. Use `mcp__videomemory__list_devices` to choose the target `io_id`.
2. Use `mcp__videomemory__create_monitor` with only the visual condition in
   `task_description`.
3. Keep any user-facing follow-up action in your own response plan.
4. Report the created task id and stop; VideoMemory owns the long-running watch.

If events are not arriving, call `mcp__videomemory__configure_channel_webhook`
and then retry a synthetic event from the host with `videomemory claude test-event`.
