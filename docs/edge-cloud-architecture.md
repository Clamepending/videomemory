# VideoMemory Edge + Cloud Architecture (Primary)

This document defines the preferred deployment architecture going forward:

- **Primary (recommended):** `VideoMemory` runs on the local app/device (edge) and performs stream ingest + video analysis locally.
- **Cloud role:** `OpenClaw` (and MCP/orchestration) runs in the cloud and handles triggers, policy, chat, and follow-up actions.
- **Fallback (preserved):** `VideoMemory` can still be deployed in the cloud with RTMP ingest for phones/devices.

## Why this architecture

The cloud should process **events/triggers**, not continuous video streams, for the common case:

- lower cloud bandwidth/compute cost
- better privacy (video stays local unless explicitly shared)
- better resilience during internet interruptions (local ingest continues)
- simpler cloud orchestration (same trigger handling path as cron/DM/webhooks)

## Primary topology (edge ingest + cloud orchestration)

```text
Camera / Phone / RTMP source
        |
        v
  Edge VideoMemory (local app / Pi / mini PC)
  - MediaMTX (optional local RTMP/SRT/WHIP relay)
  - Video ingest + VLM detection
  - Task state + notes
  - Outbound trigger emitter
  - Outbound control-channel client (for cloud->edge requests)
        |
        | HTTPS (outbound only, NAT-friendly)
        v
  Cloud OpenClaw + MCP / Gateway
  - agent orchestration
  - memory + auth + policies
  - user conversations
  - trigger intake
  - command dispatch back to edge
```

## Control plane responsibilities

### Edge VideoMemory owns

- device discovery and local stream ingestion
- RTMP/SRT/WHIP registration and RTSP pull conversion
- task execution and note generation
- local persistence
- trigger emission to cloud
- executing cloud-issued commands against local VideoMemory APIs

### Cloud OpenClaw/MCP owns

- user-facing conversation and orchestration
- trigger handling and dedupe/business logic
- decisioning (what to do next)
- command generation for the edge node
- optional fleet management for multiple edge nodes

## Command flow (cloud -> edge)

For the primary mode, cloud-to-edge requests should be **NAT-friendly**. Prefer an outbound-initiated channel from edge:

- long-poll command queue (`edge` polls cloud for pending commands), or
- websocket/SSE control channel initiated by edge, or
- HTTPS callback only when edge is publicly reachable (secondary option)

Recommended command envelope (conceptual):

```json
{
  "request_id": "cmd_123",
  "target": "videomemory-edge",
  "action": "create_task",
  "args": {
    "io_id": "0",
    "task_description": "Watch front door for package deliveries"
  },
  "reply_mode": "async_result"
}
```

Recommended result envelope (conceptual):

```json
{
  "request_id": "cmd_123",
  "status": "success",
  "result": {
    "task_id": "42"
  },
  "sent_at": 1735200001.456
}
```

## Trigger flow (edge -> cloud)

This already exists today via webhook (`OpenClawWakeNotifier`) and remains the default trigger path:

- `task_update` events are emitted from VideoMemory to the cloud gateway
- cloud OpenClaw wakes the relevant session/workflow
- cloud decides whether to send follow-up commands back to edge

## Deployment modes to keep supported

### Event Mode (Primary): Edge VideoMemory + Cloud OpenClaw

- VideoMemory runs on the user’s app host/device/Pi
- OpenClaw runs in cloud
- Video stays local by default
- Cloud handles triggers and commands
- Intended for: central cloud orchestration across many apps/devices

### Streaming Mode (Fallback): Cloud VideoMemory + Cloud OpenClaw + RTMP ingest

- VideoMemory runs in cloud with MediaMTX
- Devices push RTMP/SRT/WHIP to cloud
- OpenClaw runs alongside/in front of VideoMemory
- Useful for rapid demos, centralized ops, or when local compute is unavailable
- Intended for: self-hosters/DIY setups and simple single-deployment installs

This mode is intentionally preserved so deployment can be reverted without redesign.

## Implementation notes (incremental)

1. Keep existing webhook trigger path (`VideoMemory -> OpenClaw`) as-is.
2. Add a cloud-safe command return path (`OpenClaw -> edge VideoMemory`) using edge-initiated polling/websocket.
3. Introduce edge identity + auth token for cloud command routing.
4. Treat command execution as wrappers around existing VideoMemory HTTP/MCP actions.
5. Preserve direct HTTP/MCP access when VideoMemory is publicly reachable (optional fast path).
