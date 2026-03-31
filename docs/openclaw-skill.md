---
name: videomemory_http
description: Use VideoMemory over HTTP from OpenClaw, especially for Docker-local/private endpoints and webhook-driven monitoring tasks.
---

# VideoMemory HTTP Skill For OpenClaw

Use this skill when OpenClaw needs to manage VideoMemory over plain HTTP instead of MCP.

## Local URL rules

- Inside the bundled Docker stack, the canonical VideoMemory base URL is `http://videomemory:5050`.
- If the user pastes `http://localhost:5050/...` or `http://127.0.0.1:5050/...` while OpenClaw is running in Docker, rewrite it to `http://videomemory:5050/...` before calling anything.
- Do not ask the user to paste the skill contents just because the URL is private or local.
- Do not use `web_fetch` for private/local VideoMemory URLs. Use `curl` through the shell instead.

## Base URLs

- Inside the Docker network: `http://videomemory:5050`
- From the host machine: `http://localhost:5050`

Start by fetching this skill:

```bash
curl -fsSL http://videomemory:5050/openclaw/skill.md
```

## One-shot bootstrap

If OpenClaw's `exec` environment has `git`, `node`, and Docker access, it can bootstrap VideoMemory and the integration in one shell step:

```bash
bash <(curl -fsSL http://videomemory:5050/openclaw/bootstrap.sh)
```

If VideoMemory is not running yet, use the repo copy of the script after cloning the repo:

```bash
git clone https://github.com/Clamepending/videomemory.git
cd videomemory
bash docs/openclaw-bootstrap.sh
```

What this bootstrap does:
- clones or reuses the VideoMemory repo
- launches `docker-compose.core.yml` if VideoMemory is not already reachable
- installs the OpenClaw helper, hook transform, and local skill
- merges the VideoMemory webhook mapping into `~/.openclaw/openclaw.json`
- copies any model API keys present in the shell environment into VideoMemory settings

If OpenClaw needs to handle "watch for X, then do Y" requests, install the helper once:

```bash
mkdir -p ~/.openclaw/hooks/bin
curl -fsSL http://videomemory:5050/openclaw/videomemory-task-helper.mjs \
  -o ~/.openclaw/hooks/bin/videomemory-task-helper.mjs
```

## Ground rules

- Prefer the container-internal base URL when OpenClaw is running in Docker.
- If the pasted URL uses `localhost` or `127.0.0.1`, normalize it to the canonical Docker URL first.
- Treat VideoMemory as the source of truth for device discovery and task state.
- Include `Content-Type: application/json` on `POST`, `PUT`, and `DELETE` calls that send JSON.
- When the user wants monitoring to stop but keep history, call `POST /api/task/{task_id}/stop`.
- When the user explicitly wants a task erased, call `DELETE /api/task/{task_id}`.
- If there is exactly one available camera, use it unless the user asked for a different one.
- Do not put follow-up actions like jokes, Telegram sends, or texting instructions directly into VideoMemory's `task_description` when OpenClaw should perform that action later.
- If Docker is unavailable in the OpenClaw execution environment, the bootstrap can still install the integration pieces, but it cannot launch a new VideoMemory container by itself.

## Basic checks

Health:

```bash
curl -fsSL http://videomemory:5050/api/health
```

List devices:

```bash
curl -fsSL http://videomemory:5050/api/devices
```

## Cameras

Add a network camera:

```bash
curl -fsSL -X POST http://videomemory:5050/api/devices/network \
  -H 'Content-Type: application/json' \
  -d '{"url":"http://demo-camera:8080/snapshot.jpg","name":"Demo Red Marker Camera"}'
```

Remove a network camera:

```bash
curl -fsSL -X DELETE http://videomemory:5050/api/devices/network/net0
```

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
  --delivery telegram \
  --original-request 'When you see a backpack in the frame, tell a backpack joke.' \
  --bot-id openclaw
```

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

Edit a task:

```bash
node ~/.openclaw/hooks/bin/videomemory-task-helper.mjs update \
  --task-id 0 \
  --trigger 'Watch for a backpack in the frame. Add a note only when a backpack appears, disappears, or the visible backpack count changes.' \
  --action 'Tell one short backpack joke when a backpack is newly visible.' \
  --delivery telegram
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
  - `event_id`

## Suggested OpenClaw workflow

1. Normalize any pasted local URL to `http://videomemory:5050/...` when running in Docker.
2. Fetch this skill with `curl`.
3. Check `/api/health`.
4. Call `/api/devices`.
5. If no suitable camera exists, add one with `/api/devices/network`.
6. If the user wants record-only monitoring, use `/api/tasks` directly with a neutral condition-only description.
7. If the user wants "when X happens, do Y", use `videomemory-task-helper.mjs` so OpenClaw keeps `do Y` locally and VideoMemory only sees `watch for X`.
8. When a VideoMemory alert webhook arrives, use the stored action plus the latest note to decide whether to reply with `NO_REPLY` or a real user-facing message.
