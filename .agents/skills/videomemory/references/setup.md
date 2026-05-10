# VideoMemory Setup

## Readiness Checks

Check the server:

```bash
node .agents/skills/videomemory/scripts/ensure-server.mjs --json
```

Check model and webhook settings:

```bash
curl -fsSL http://127.0.0.1:5050/api/settings
```

Model readiness rules:

- `local-vllm` needs a reachable `LOCAL_MODEL_BASE_URL`, defaulting to `http://localhost:8100`.
- `gpt-4o-mini` and `gpt-4.1-nano` need `OPENAI_API_KEY`.
- Claude models need `ANTHROPIC_API_KEY`.
- Gemini models need `GOOGLE_API_KEY`.
- OpenRouter models need `OPENROUTER_API_KEY`.

Set settings through HTTP:

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/VIDEO_INGESTOR_MODEL \
  -H 'Content-Type: application/json' \
  -d '{"value":"gpt-4o-mini"}'
```

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/OPENAI_API_KEY \
  -H 'Content-Type: application/json' \
  -d '{"value":"sk-..."}'
```

## Webhook Wakeups

VideoMemory posts `task_update` events to `VIDEOMEMORY_OPENCLAW_WEBHOOK_URL`.

For a local OpenClaw gateway:

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL \
  -H 'Content-Type: application/json' \
  -d '{"value":"http://127.0.0.1:18789/hooks/videomemory-alert"}'
```

The token should match `hooks.token` in `~/.openclaw/openclaw.json`:

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN \
  -H 'Content-Type: application/json' \
  -d '{"value":"<hooks.token>"}'
```

Also set the self URL used in event payloads:

```bash
curl -fsSL -X PUT http://127.0.0.1:5050/api/settings/VIDEOMEMORY_SELF_BASE_URL \
  -H 'Content-Type: application/json' \
  -d '{"value":"http://127.0.0.1:5050"}'
```

## Codex Plugin Boundary

The Codex plugin can create monitors and configure webhooks, but Codex does not currently expose a native local inbound webhook endpoint to wake a Codex chat from VideoMemory. Event wakeups should be tested through OpenClaw, Telegram, or a purpose-built webhook receiver.
