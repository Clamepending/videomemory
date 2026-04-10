---
name: videomemory_http
description: Use VideoMemory over HTTP from OpenClaw, especially for local or private endpoints and long-running camera monitoring tasks.
---

# VideoMemory

Use this skill when OpenClaw needs to:
- answer one-off camera questions
- create or manage VideoMemory monitoring tasks
- relaunch or onboard a local VideoMemory install

When this plugin is enabled, prefer the built-in tools:
- `videomemory_onboard`
- `videomemory_relaunch`
- `videomemory_status`

## Base URL rules

- Inside the bundled Docker stack, prefer `http://videomemory:5050`.
- If OpenClaw is in Docker and VideoMemory is on the host, prefer `http://host.docker.internal:5050`.
- From the host machine, prefer `http://127.0.0.1:5050` or `http://localhost:5050`.
- If the user pastes `localhost` while OpenClaw is running in Docker, rewrite it to `host.docker.internal` first.
- Do not use generic web fetch for private/local VideoMemory URLs. Use shell `curl`.

## Onboarding

Prefer the `videomemory_onboard` tool first. It wraps the current bootstrap flow and returns the user-facing UI link.

What it does:
- clones or reuses the VideoMemory repo
- launches VideoMemory locally without Docker
- installs the OpenClaw helper and hook assets used by the current integration path
- copies model API keys when present
- prefers a Tailscale UI link when available

If the tool is unavailable, fall back to the GitHub-hosted bootstrap script.

## Relaunch / upgrade

Prefer the `videomemory_relaunch` tool first. It wraps the current relaunch flow and returns the UI link plus repo commit.

After it succeeds, reply with:
- the VideoMemory UI link
- the running repo commit shown by the script

## One-off camera questions

Prefer `/api/caption_frame` over downloading a frame and using a separate vision tool.

```bash
curl -fsSL -X POST http://videomemory:5050/api/caption_frame \
  -H 'Content-Type: application/json' \
  -d '{"io_id":"net0","prompt":"Describe what is visible in this camera frame in detail."}'
```

## Devices

List devices:

```bash
curl -fsSL http://videomemory:5050/api/devices
```

Add a network camera:

```bash
curl -fsSL -X POST http://videomemory:5050/api/devices/network \
  -H 'Content-Type: application/json' \
  -d '{"url":"http://camera.local:8080/snapshot.jpg","name":"Front Door Camera"}'
```

For Android phone cameras:
- if the phone is outside the local LAN, install Tailscale on both devices first
- treat `100.x.y.z` camera addresses as Tailscale addresses
- DroidCam defaults:
  - snapshot: `http://<phone-ip>:4747/jpeg`
  - mjpeg: `http://<phone-ip>:4747/mjpegfeed`

## Tasks

Create a plain monitoring task:

```bash
curl -fsSL -X POST http://videomemory:5050/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"io_id":"net0","task_description":"Watch for a backpack and record when it appears.","bot_id":"openclaw"}'
```

If the request is “when X happens, do Y”, prefer the helper so OpenClaw keeps the follow-up action locally:

```bash
node ~/.openclaw/hooks/bin/videomemory-task-helper.mjs create \
  --io-id net0 \
  --trigger 'Watch for a backpack in the frame.' \
  --action 'Tell one short backpack joke when a backpack is newly visible.' \
  --delivery telegram \
  --original-request 'When you see a backpack in the frame, tell one backpack joke.' \
  --bot-id openclaw
```

To stop but keep history:

```bash
curl -fsSL -X POST http://videomemory:5050/api/task/0/stop
```

To delete entirely:

```bash
curl -fsSL -X DELETE http://videomemory:5050/api/task/0
```

## Ground rules

- Treat VideoMemory as the source of truth for device discovery and task state.
- If there is exactly one camera and the user did not specify otherwise, use it.
- Report the actual failing command or stderr when bootstrap/relaunch fails.
- Prefer the current GitHub-hosted scripts over stale local assumptions.
- Do not put the user-facing follow-up action directly into `task_description` when OpenClaw should perform it later.
