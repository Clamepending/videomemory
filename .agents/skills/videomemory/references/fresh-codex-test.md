# Fresh Codex Test

## What This Test Proves

A fresh Codex agent can:

1. Load the VideoMemory plugin.
2. Confirm VideoMemory server/model/webhook readiness.
3. Create an event-driven monitor.
4. Confirm the VideoMemory -> OpenClaw webhook path.

It does not prove native Codex webhook wakeup, because current local Codex plugins do not expose an inbound event endpoint. OpenClaw is the webhook-driven agent runtime in this setup.

## Fresh Agent Prompt

In a new Codex chat, use:

```text
Use VideoMemory. Check setup readiness, list cameras, configure the local OpenClaw webhook if needed, then create an event monitor on the FaceTime camera for "phone visibly held up in my hand". Use semantic keywords phone, smartphone, hand, person with threshold 0.3. Do not create any heartbeat or polling automation. Tell me the task id and how the event will wake the agent.
```

Expected result:

- The agent uses VideoMemory plugin tools.
- It calls `videomemory_configure_event_webhook` if the webhook is missing.
- It creates the task with `videomemory_create_event_monitor`, not a plain monitor plus heartbeat.
- It reports `http://127.0.0.1:5050` as reachable.
- It reports webhook configured to `http://127.0.0.1:18789/hooks/videomemory-alert`.
- It creates a task and registry entry.
- It explicitly says it will not keep polling.

## Synthetic Wake Test

After a task exists, test the event path without holding up an object:

```bash
node .agents/skills/videomemory/scripts/simulate-webhook-event.mjs \
  --task-id <task_id> \
  --io-id 0 \
  --bot-id codex \
  --note "A phone is clearly held up in the user's hand." \
  --confirm true \
  --json
```

Expected result:

- HTTP `2xx` from OpenClaw hook endpoint.
- OpenClaw gateway log shows the hook was received or an agent run was started.

## Real Camera Test

Use the same monitor, then hold the phone up in the camera view. A successful real test means VideoMemory writes a new task note and sends a webhook.

Check:

```bash
node .agents/skills/videomemory/scripts/inspect-event.mjs --task-id <task_id> --json
```

If no note appears:

- verify model readiness first
- verify the camera preview is nonblack
- lower semantic threshold
- use a cloud VLM or start local vLLM if `local-vllm` is selected
