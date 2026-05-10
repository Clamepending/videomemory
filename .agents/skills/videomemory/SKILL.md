---
name: videomemory
description: Manage VideoMemory camera devices, event-driven monitors, semantic filters, evidence frames/videos, OpenClaw webhooks, and Codex plugin setup.
---

# VideoMemory

Use this skill when an agent needs to operate VideoMemory, configure monitoring, answer camera questions, inspect detections, or set up event-driven wakeups.

## Mental Model

- VideoMemory is the perception runtime. It owns cameras, ingestors, semantic frame filtering, VLM calls, tasks, notes, saved frames, and saved videos.
- A VideoMemory task is a monitor. Once a task is created, VideoMemory watches the feed; the agent should not poll or create timer heartbeats unless explicitly asked for status checks.
- External agents are woken by VideoMemory webhooks when a task note is created or a task is completed.
- Codex plugins are control-plane tools. They can configure VideoMemory and create tasks, but current Codex plugins do not provide a native inbound webhook surface. Use OpenClaw or another webhook-capable agent runtime for true event wakeups.

## Default Assumptions

- Local base URL: `http://127.0.0.1:5050`
- Local OpenClaw gateway: `http://127.0.0.1:18789`
- Default semantic filter backend: `dino_clip_adapter`
- Default semantic threshold: `0.3`
- Default semantic reduce mode: `max`
- Default monitor `bot_id`: `codex` for Codex-created monitors, `openclaw` for OpenClaw-created monitors.

## Workflow

1. Read `references/setup.md` for service/model/webhook readiness.
2. Use `scripts/ensure-server.mjs` or the Codex plugin server tools to confirm VideoMemory is reachable.
3. Use `GET /api/settings` or the Codex plugin setup tool before creating monitors.
   - If `VIDEO_INGESTOR_MODEL` is `local-vllm`, verify `LOCAL_MODEL_BASE_URL` is reachable.
   - If a cloud model is selected, verify its provider API key is configured.
   - Verify `VIDEOMEMORY_OPENCLAW_WEBHOOK_URL` is set when event wakeups are expected.
4. Use `GET /api/devices` or the plugin device tool to choose an `io_id`.
5. For plain recording/monitoring tasks, create a task directly.
6. For "when X happens, do Y" tasks, create an event monitor with a registry entry:
   - trigger condition goes into VideoMemory `task_description`
   - follow-up action stays in the agent registry
   - delivery mode is `telegram`, `session`, or `internal`
7. Do not continue watching in the agent after monitor creation. Report the task id and the configured event path.
8. When an event arrives, inspect it with `scripts/inspect-event.mjs` or `GET /api/task/{task_id}` and use saved evidence URLs when present.

## Progressive References

- `references/setup.md` - service readiness, model API keys, local vLLM, OpenClaw webhook configuration, and Codex plugin setup.
- `references/monitors.md` - task semantics, event monitor registry entries, and delivery modes.
- `references/semantic-filter.md` - DINO/CLIP semantic frame filtering and threshold tuning.
- `references/evidence-and-replay.md` - saved notes, frames, videos, and event inspection.
- `references/fresh-codex-test.md` - how to test a fresh Codex agent and what counts as a successful wakeup.

## Ground Rules

- Do not put the user-facing follow-up action directly into `task_description` when another agent should perform that action later.
- Do not use a generic or heartbeat-owned session key for session delivery. If the real originating chat session key is unavailable, use `internal` or `telegram`.
- Do not claim Codex will be woken by VideoMemory unless a Codex-native inbound trigger exists. Today, local event wakeups route through OpenClaw or another webhook receiver.
- Prefer saved triggering evidence over a fresh snapshot when responding to an event.
- Report the actual failing URL, command, or readiness field when setup fails.
