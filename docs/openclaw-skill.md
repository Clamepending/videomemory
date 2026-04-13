---
name: videomemory_http
description: Use VideoMemory over HTTP from OpenClaw, especially for Docker-local/private endpoints and webhook-driven monitoring tasks.
---

# VideoMemory HTTP Skill For OpenClaw

Use this skill when OpenClaw needs to manage VideoMemory over plain HTTP instead of MCP.

## Local URL rules

- Inside the bundled Docker stack, the canonical VideoMemory base URL is `http://videomemory:5050`.
- If OpenClaw is running in its own Docker container while VideoMemory is running on the host, the canonical VideoMemory base URL is `http://host.docker.internal:5050`.
- If the user pastes `http://localhost:5050/...` or `http://127.0.0.1:5050/...` while OpenClaw is running in Docker, first rewrite it to `http://host.docker.internal:5050/...`. If that host alias is unavailable but a shared Docker service name exists, retry with `http://videomemory:5050/...`.
- Do not ask the user to paste the skill contents just because the URL is private or local.
- Do not use `web_fetch` for private/local VideoMemory URLs. Use `curl` through the shell instead.

## Base URLs

- Inside the Docker network: `http://videomemory:5050`
- From a Dockerized OpenClaw to a host-run VideoMemory: `http://host.docker.internal:5050`
- From the host machine: `http://localhost:5050`

Start by fetching this skill:

```bash
curl -fsSL http://videomemory:5050/openclaw/skill.md
```

If OpenClaw is in Docker and VideoMemory is on the host:

```bash
curl -fsSL http://host.docker.internal:5050/openclaw/skill.md
```

## One-shot bootstrap

If OpenClaw's `exec` environment has `git` plus either `uv` or `python3`, it can bootstrap VideoMemory and the integration in one shell step:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/openclaw-bootstrap.sh)
```

If OpenClaw is in Docker and the human already started VideoMemory on the host, bootstrap against the host alias:

```bash
VIDEOMEMORY_BASE=http://host.docker.internal:5050 bash <(curl -fsSL http://host.docker.internal:5050/openclaw/bootstrap.sh)
```

If VideoMemory is not running yet and you already cloned the repo, use the repo copy of the script:

```bash
git clone https://github.com/Clamepending/videomemory.git
cd videomemory
bash docs/openclaw-bootstrap.sh
```

What this bootstrap does:
- clones or reuses the VideoMemory repo
- launches VideoMemory locally with `uv` or a Python virtualenv if it is not already reachable
- installs Tailscale on Linux when possible, and prefers a Tailscale UI link for the user
- installs the OpenClaw helper, hook transform, and local skill
- merges the VideoMemory webhook mapping into `~/.openclaw/openclaw.json`
- copies any model API keys present in the shell environment into VideoMemory settings
- prints a user-facing VideoMemory UI link, and sends it over Telegram too when a bot token plus chat id are available
- prints a setup warning when the selected model still needs a provider API key so the user can finish setup in the Settings tab

If you already have a reusable Tailscale auth key, pass it in so onboarding can connect noninteractively:

```bash
VIDEOMEMORY_TAILSCALE_AUTHKEY=tskey-auth-... \
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/openclaw-bootstrap.sh)
```

## Relaunch / upgrade

If the user asks to relaunch, restart, or update VideoMemory, do not improvise with ad hoc `git pull` plus process commands.
Run the current relaunch script from GitHub so the repo is upgraded first, the local host-managed process is restarted, and the user gets the current UI link plus commit:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/relaunch-videomemory.sh)
```

What this relaunch does:
- upgrades the local repo to the latest fast-forward commit on the configured ref when the checkout is clean
- refreshes the Python runtime
- restarts the host-managed VideoMemory process from the bootstrap/install path
- waits for `/api/health`
- prints the user-facing UI link and the running repo commit

After it succeeds, reply to the user with:
- the user-facing VideoMemory UI link
- the running repo commit shown by the script

If the relaunch script says the repo has local changes or that VideoMemory is running outside the managed PID path, report that exact message instead of claiming the update succeeded.

If OpenClaw needs to handle "watch for X, then do Y" requests, install the helper once:

```bash
mkdir -p ~/.openclaw/hooks/bin
curl -fsSL http://videomemory:5050/openclaw/videomemory-task-helper.mjs \
  -o ~/.openclaw/hooks/bin/videomemory-task-helper.mjs
```

The helper auto-detects the reachable VideoMemory base URL across `videomemory`, `host.docker.internal`, `127.0.0.1`, and `localhost`. You can still force a base URL with `--base-url ...` if needed.

If the follow-up action should happen later when the trigger fires and it depends on fresh information or tools, keep that as a future instruction in `--action`.
Examples: web search, current weather, latest prices, reading a file, or checking a live status.
Do not precompute those results during setup unless the user explicitly asked for a snapshot taken now.

## Ground rules

- Prefer the container-internal base URL when OpenClaw is running in Docker.
- If the pasted URL uses `localhost` or `127.0.0.1`, normalize it to the canonical Docker URL first.
- Treat VideoMemory as the source of truth for device discovery and task state.
- During onboarding, if the user wants to use an Android phone camera from outside the same local network, tell them to install Tailscale on both the VideoMemory machine and the phone first.
- If the user provides a `100.x.y.z` phone address, treat it as a Tailscale address and check that Tailscale is installed and connected on the VideoMemory host before trying to use that phone camera.
- After successful onboarding, reply to the user with the user-facing VideoMemory UI link from bootstrap output. Prefer the Tailscale UI URL when one is available.
- If bootstrap prints a configuration warning about a missing provider key, relay that warning to the user and tell them to open the Settings tab before creating tasks.
- If the user asks for a relaunch or restart, use the current `relaunch-videomemory.sh` script from GitHub so the command upgrades before restarting.
- If the user asks to rerun the bootstrap or install step, fetch and execute the current script instead of assuming an earlier failure still applies.
- When a bootstrap or install command fails, report the actual failing command or stderr before proposing a fix.
- If `POST /api/tasks` fails because the selected model is not configured, surface that error directly instead of pretending the task was created.
- Include `Content-Type: application/json` on `POST`, `PUT`, and `DELETE` calls that send JSON.
- When the user wants monitoring to stop but keep history, call `POST /api/task/{task_id}/stop`.
- When the user explicitly wants a task erased, call `DELETE /api/task/{task_id}`.
- If there is exactly one available camera, use it unless the user asked for a different one.
- Do not put follow-up actions like jokes, Telegram sends, or texting instructions directly into VideoMemory's `task_description` when OpenClaw should perform that action later.
- The bootstrap does not require Docker. It prefers a direct local launch on the same machine as OpenClaw.
- On Linux, `host.docker.internal` may require the OpenClaw container to be started with `--add-host=host.docker.internal:host-gateway`.

## Basic checks

Health:

```bash
curl -fsSL http://videomemory:5050/api/health
```

List devices:

```bash
curl -fsSL http://videomemory:5050/api/devices
```

## One-off camera questions

For prompts like `what do you see on camera`, `describe the current frame`, `is anyone visible`, or `what color is the marker`, use VideoMemory's one-off frame analysis endpoint instead of downloading the snapshot and using a generic image tool.

First list devices and pick the camera `io_id`, then call:

```bash
curl -fsSL -X POST http://videomemory:5050/api/caption_frame \
  -H 'Content-Type: application/json' \
  -d '{"io_id":"net0","prompt":"Describe what is visible in this camera frame in detail."}'
```

For targeted checks, change only the prompt text. Examples:

```bash
curl -fsSL -X POST http://videomemory:5050/api/caption_frame \
  -H 'Content-Type: application/json' \
  -d '{"io_id":"net0","prompt":"Are any people visible? If so, count them and describe where they are."}'

curl -fsSL -X POST http://videomemory:5050/api/caption_frame \
  -H 'Content-Type: application/json' \
  -d '{"io_id":"net0","prompt":"Describe what is visible in this camera frame."}'
```

Prefer `/api/caption_frame` for one-off camera descriptions. Only fall back to raw snapshot download plus another tool if `/api/caption_frame` is unavailable or returns an error.

## Current image requests

For prompts like `send me a picture of the camera`, `show me the current frame`, `attach the latest camera image`, `can you send a photo from the webcam`, `capture a photo from the USB camera`, or `send a snapshot right now`, use VideoMemory's fresh capture endpoint instead of asking VideoMemory to describe it in text.

Treat these as image-delivery requests, not caption requests. If the user's primary ask is for the image itself, you must return or attach the image rather than substituting a textual description.

The most reliable path for Telegram image replies is a direct helper command that captures and sends the JPEG. Prefer it over `read` when the user wants the image itself.

First list devices and pick the camera `io_id`, then fetch:

```bash
~/.openclaw/workspace/bin/openclaw_send_current_camera_image.sh \
  --target "<sender_id>" \
  --reply-to "<message_id>" \
  --io-id 0 \
  --base-url http://127.0.0.1:5050
```

Important:
- Use the current Telegram/direct-message metadata for `<sender_id>` and `<message_id>`.
- Do not use `read` on the JPEG unless you need to analyze the image contents. For pure attachment requests, send the image directly.
- Do not replace a direct image request with a textual description unless the user explicitly asked for description instead, or the preview endpoint fails and you need to explain the failure.
- The helper tries VideoMemory fresh capture first, then falls back to VideoMemory preview, then direct `ffmpeg` capture if needed.
- The helper tries a Telegram reply with `--reply-to` first and falls back to a plain media send if reply-mode stalls.

If `POST /api/device/{io_id}/capture` fails, fall back to `GET /api/device/{io_id}/preview`. If both fail for a local USB camera, fall back to a direct capture and send that file instead:

```bash
mkdir -p ~/.openclaw/workspace
ffmpeg -f v4l2 -i /dev/video0 -frames:v 1 -update 1 -y ~/.openclaw/workspace/videomemory-preview.jpg
```

Only use the final `MEDIA:` reply format when you are in a context where direct channel send is unavailable. If you do use it, do not `read` the JPEG first.

## Cameras

Add a network camera:

```bash
curl -fsSL -X POST http://videomemory:5050/api/devices/network \
  -H 'Content-Type: application/json' \
  -d '{"url":"http://camera.local:8080/snapshot.jpg","name":"Front Door Camera"}'
```

Remove a network camera:

```bash
curl -fsSL -X DELETE http://videomemory:5050/api/devices/network/net0
```

## Android phone cameras

- First decide whether the phone and the VideoMemory machine are on the same LAN.
- If they are not on the same LAN, install Tailscale on both devices before trying to use the phone camera URL.
- If the user gives a `100.x.y.z` address, that is usually a Tailscale address, so the VideoMemory host must also have Tailscale installed and connected.
- If the user does not want to install Tailscale, ask for the phone's local Wi-Fi IP instead and use that only when both devices are on the same LAN.
- For DroidCam, common URLs are:
  - Snapshot: `http://<phone-ip>:4747/jpeg`
  - MJPEG stream: `http://<phone-ip>:4747/mjpegfeed`

## Tasks

Create a plain record-only task:

```bash
curl -fsSL -X POST http://videomemory:5050/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"io_id":"net0","task_description":"Watch for a red marker and record it, but do not notify anyone.","bot_id":"openclaw"}'
```

Create a split trigger-plus-action task:

```bash
node ~/.openclaw/hooks/bin/videomemory-task-helper.mjs create \
  --io-id net0 \
  --trigger 'Watch for a backpack in the frame. Add a note only when a backpack appears, disappears, or the visible backpack count changes.' \
  --action 'Tell one short backpack joke when a backpack is newly visible.' \
  --include-frame false \
  --delivery telegram \
  --original-request 'When you see a backpack in the frame, tell a backpack joke.' \
  --bot-id openclaw
```

Create a split trigger-plus-action task that replies back into the current OpenClaw chat session:

```bash
node ~/.openclaw/hooks/bin/videomemory-task-helper.mjs create \
  --io-id net0 \
  --trigger 'Watch for a card in the frame. Add a note only when a card appears, disappears, or the visible card count changes.' \
  --action 'Tell me one concise sentence when a card is visible.' \
  --include-frame false \
  --delivery webchat \
  --session-key '<current_session_key>' \
  --original-request 'Can you let me know here when you see a card?' \
  --bot-id openclaw
```

Important:
- Replace `<current_session_key>` with the actual originating OpenClaw chat session key from runtime metadata or `OPENCLAW_SESSION_KEY`.
- Never hardcode `agent:main:main` as a generic fallback. On newer OpenClaw installs that key may belong to heartbeat or another internal automation session.
- If you do not have the real current session key, do not silently switch to `webchat` just to make the helper succeed.
- For Telegram-originated requests, prefer `--delivery telegram --to <sender_id>` instead of `webchat`.

List all tasks:

```bash
curl -fsSL http://videomemory:5050/api/tasks
```

List tasks for one device:

```bash
curl -fsSL 'http://videomemory:5050/api/tasks?io_id=net0'
```

Get one task:

```bash
curl -fsSL http://videomemory:5050/api/task/0
```

Saved note media:

- `GET /api/task/{task_id}` returns note entries that can include `frame_url` and `video_url`.
- Fetch the exact saved frame for one note:

```bash
curl -fsSL -o trigger-frame.jpg http://videomemory:5050/api/task-note/42/frame
```

- Fetch the exact saved evidence clip for one note:

```bash
curl -fsSL -o trigger-clip.mp4 http://videomemory:5050/api/task-note/42/video
```

- When the user explicitly wants the exact triggering media later, create or update the task through the helper with `--include-frame true` and/or `--include-video true`. The helper will request that VideoMemory save that evidence on the task and the later webhook will point at the exact triggering note media URLs when they exist.

Edit a task:

```bash
node ~/.openclaw/hooks/bin/videomemory-task-helper.mjs update \
  --task-id 0 \
  --trigger 'Watch for a backpack in the frame. Add a note only when a backpack appears, disappears, or the visible backpack count changes.' \
  --action 'Tell one short backpack joke when a backpack is newly visible.' \
  --include-frame false \
  --include-video false \
  --delivery telegram \
  --original-request 'When you see a backpack in the frame, tell a backpack joke.' \
  --bot-id openclaw
```

Stop a task but keep history:

```bash
node ~/.openclaw/hooks/bin/videomemory-task-helper.mjs stop --task-id 0
```

Delete a task permanently:

```bash
node ~/.openclaw/hooks/bin/videomemory-task-helper.mjs delete --task-id 0
```

## Settings

List settings:

```bash
curl -fsSL http://videomemory:5050/api/settings
```

Set a model key:

```bash
curl -fsSL -X PUT http://videomemory:5050/api/settings/GOOGLE_API_KEY \
  -H 'Content-Type: application/json' \
  -d '{"value":"your-key"}'
```

Set the active model:

```bash
curl -fsSL -X PUT http://videomemory:5050/api/settings/VIDEO_INGESTOR_MODEL \
  -H 'Content-Type: application/json' \
  -d '{"value":"claude-sonnet-4-6"}'
```

## Task phrasing tips

- Never put follow-up actions like `tell a joke`, `search the web`, or `send Telegram` directly into the raw VideoMemory monitoring description when OpenClaw should do that later.
- Split the request into:
  - Trigger for VideoMemory: `Watch for a backpack in the frame. Add a note only when a backpack appears, disappears, or the visible backpack count changes.`
  - Action for OpenClaw: `Tell one short backpack joke when a backpack is newly visible.`
- If the follow-up action needs fresh data or tools at trigger time, store that future work directly in `--action`.
  - Good: `--action 'When a glass of water is visible, search the web for "hello" and tell the user the first result.'`
  - Avoid: searching now during setup and baking a stale result into the task unless the user explicitly asked for the result as of setup time.
- When updating an existing watcher, always pass the full new user intent through `--original-request` if the follow-up action changed. This keeps stale earlier phrasing from biasing the later hook execution.

## Webhook behavior

- VideoMemory will POST task-note changes to the configured OpenClaw webhook URL.
- Expected hook path in the bundled stack: `http://openclaw:18789/hooks/videomemory-alert`
- In the bundled Docker stack, this webhook is configured at container startup. OpenClaw does not need to ask the user to wire it manually.
- When tasks are created through the helper, OpenClaw stores the follow-up action locally and only sends the raw monitoring condition to VideoMemory.
- Payload fields include:
  - `bot_id`
  - `io_id`
  - `task_id`
  - `task_description`
  - `task_status`
  - `task_done`
  - `note`
  - `note_id`
  - `task_api_url`
  - `note_has_frame`
  - `note_frame_api_url`
  - `note_has_video`
  - `note_video_api_url`
  - `event_id`

## Suggested OpenClaw workflow

1. If Docker access is available on the same VM/host, run the raw GitHub bootstrap script.
2. If OpenClaw is in Docker and VideoMemory is already running on the host, run the served bootstrap script with `VIDEOMEMORY_BASE=http://host.docker.internal:5050`.
3. Normalize any pasted local URL to the reachable Docker-safe base before calling it.
4. Fetch this skill with `curl`.
5. Check `/api/health`.
6. Call `/api/devices`.
7. If no suitable camera exists, add one with `/api/devices/network`.
8. If the user asks a one-off camera question, call `/api/caption_frame`.
9. If the user wants record-only monitoring, use `/api/tasks` directly with a neutral condition-only description.
10. If the user wants "when X happens, do Y", use `videomemory-task-helper.mjs` so OpenClaw keeps `do Y` locally and VideoMemory only sees `watch for X`.
11. Use `--delivery webchat` for "tell me here/in this chat" requests only when you know the actual originating OpenClaw session key.
12. Never hardcode `agent:main:main` as a generic "main chat" fallback for `--session-key`; it may point at heartbeat/internal traffic on current OpenClaw builds.
13. Use `--delivery telegram` when the user explicitly wants Telegram or the current interaction already came from Telegram. Pass `--to <sender_id>` from the current Telegram metadata.
14. If Telegram delivery setup fails, do not silently downgrade to `webchat` unless you also have the real current chat session key.
15. Use `--include-frame true` only when the user explicitly wants the saved triggering image or photo to be used later. Do not infer that from wording at alert time.
16. Use `--include-video true` only when the user explicitly wants the saved triggering clip to be used later.
17. When a VideoMemory alert webhook arrives, prefer `note_frame_api_url` or `note_video_api_url` from that webhook over taking a new snapshot.
18. When a VideoMemory alert webhook arrives, use the stored action plus the latest note to decide whether to reply with `NO_REPLY` or a real user-facing message.
