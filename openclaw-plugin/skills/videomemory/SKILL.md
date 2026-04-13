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

## Current image requests

For prompts like `send me a picture of the camera`, `show me the current frame`, `attach the latest camera image`, `capture a photo from the USB camera`, or `send a webcam snapshot right now`, use the fresh capture endpoint instead of `/api/caption_frame`.

Treat these as image-delivery requests. If the user asked for the image itself, attach or display the JPEG rather than replacing it with a textual description.

The most reliable path for Telegram image replies is a direct helper command that captures and sends the JPEG. Prefer it over `read` when the user wants the image itself.

```bash
~/.openclaw/workspace/bin/openclaw_send_current_camera_image.sh \
  --target "<sender_id>" \
  --reply-to "<message_id>" \
  --io-id 0 \
  --base-url http://127.0.0.1:5050
```

Important:
- Use the current Telegram/direct-message metadata for `<sender_id>` and `<message_id>`.
- Save the file under `~/.openclaw/workspace/` or another allowed OpenClaw media root, not `/tmp`, before attaching it.
- Do not use `read` on the JPEG unless you need to analyze the image contents. For pure attachment requests, send the image directly.
- Only substitute a textual description when the user asked for description or the preview fetch fails.
- The helper tries VideoMemory fresh capture first, then falls back to VideoMemory preview, then direct `ffmpeg` capture if needed.
- The helper tries a Telegram reply with `--reply-to` first and falls back to a plain media send if reply-mode stalls.
- If `POST /api/device/{io_id}/capture` fails and `GET /api/device/{io_id}/preview` also fails for a local USB camera, capture one frame directly and send that file instead:

```bash
mkdir -p ~/.openclaw/workspace
ffmpeg -f v4l2 -i /dev/video0 -frames:v 1 -update 1 -y ~/.openclaw/workspace/videomemory-preview.jpg
```

Only use the final `MEDIA:` reply format when direct channel send is unavailable. If you do use it, do not `read` the JPEG first.

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
  --include-frame false \
  --include-video false \
  --delivery telegram \
  --original-request 'When you see a backpack in the frame, tell one backpack joke.' \
  --bot-id openclaw
```

For "tell me here/in this chat" requests:
- Use `--delivery webchat` only when you know the real originating OpenClaw session key.
- Pass `--session-key '<current_session_key>'`, not a hardcoded `agent:main:main`.
- If the current interaction already came from Telegram, prefer `--delivery telegram --to <sender_id>`.
- If Telegram delivery setup fails, do not silently downgrade to `webchat` unless you also have the real current chat session key.

## Saved media

- `GET /api/task/{task_id}` returns note entries that can include `frame_url` and `video_url`.
- Fetch one saved frame with `GET /api/task-note/{note_id}/frame`.
- Fetch one saved evidence clip with `GET /api/task-note/{note_id}/video`.
- Use `--include-frame true` only when the user explicitly wants the exact triggering image later.
- Use `--include-video true` only when the user explicitly wants the exact triggering clip later.
- When a VideoMemory webhook includes `note_frame_api_url` or `note_video_api_url`, prefer those exact URLs over taking a new snapshot.

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
