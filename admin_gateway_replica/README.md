# Admin Gateway Replica (OpenClaw-like Test Harness)

This service is a safe test replacement for the OpenClaw gateway webhook path.

It accepts VideoMemory detection hook POSTs, renders a message, and forwards that
message into VideoMemory's existing Google ADK admin agent via `/chat`.

## Why this exists

- Test VideoMemory wakeup behavior without running OpenClaw
- Keep the original VideoMemory frontend/API workflow intact
- Validate webhook auth, payloads, and end-to-end forwarding logic

## Run (via compose)

Use `/Users/mark/Desktop/projects/videomemory/docker-compose.replica.yml`.

## Key endpoints

- `GET /health`
- `GET /api/events`
- `POST /api/trigger` (manual test)
- `POST /hooks/videomemory-alert` (VideoMemory notifier target)
