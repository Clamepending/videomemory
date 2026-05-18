# VideoMemory Voice Agent Example

Minimal local example of a live voice/video agent that can:

- talk with the user through OpenAI Realtime voice,
- send browser camera frames into VideoMemory,
- create VideoMemory monitors from conversation tools,
- receive VideoMemory webhooks,
- speak only when a registered monitor actually fires.

The important separation is:

- VideoMemory owns long-running visual perception.
- The voice agent owns conversation, tool calls, follow-up actions, and memory.

## Files

- `server.mjs` - HTTP server, OpenAI Realtime token minting, VideoMemory webhook receiver, local tool implementations.
- `lib.mjs` - readable monitor planning, lifecycle inference, ledger parsing, wakeup-message helpers.
- `public/` - browser UI, camera/mic capture, WebRTC Realtime client, frame relay to VideoMemory.
- `test/` - fake VideoMemory/OpenAI servers plus regression tests for webhook behavior.

## Run

Start VideoMemory from the repo root:

```bash
uv run flask_app/app.py
```

Configure a VideoMemory model key in the Settings tab, or by API:

```bash
curl -X PUT http://127.0.0.1:5050/api/settings/GOOGLE_API_KEY \
  -H "Content-Type: application/json" \
  -d '{"value":"..."}'
```

Start the example:

```bash
cd examples/voice-agent-demo
OPENAI_API_KEY=sk-... npm start
```

Open:

```text
http://127.0.0.1:8899
```

Optional environment variables:

- `VIDEOMEMORY_BASE_URL` - defaults to `http://127.0.0.1:5050`.
- `VOICE_AGENT_DEMO_PORT` - defaults to `8899`.
- `VOICE_AGENT_DEMO_HOST` - defaults to `127.0.0.1`; set to `0.0.0.0` when deploying in a container.
- `VOICE_AGENT_DEMO_STATE_DIR` - defaults to repo-level `data/voice-agent-demo`.
- `VOICE_AGENT_DEMO_MAX_SESSIONS_PER_HOUR` - defaults to `20` Realtime sessions per browser/IP.
- `VOICE_AGENT_DEMO_MIN_SESSION_INTERVAL_MS` - defaults to `10000` between Realtime session starts.

Click `Start live agent`, grant camera/mic permission, and speak normally.

Useful test prompt:

```text
Tell me when a phone is visible.
```

Apple-shopkeeper prompt:

```text
Be a shopkeeper. Watch these apples. If someone walks up or takes an apple, ask for their name, charge $1 per apple, and keep a ledger.
```

## Behavior

The example creates `general` VideoMemory monitors by default. It does not enable
semantic filter fields.

Monitor lifecycles:

- `one_shot`: fire once, then stop. Example: `Tell me when a phone is visible.`
- `persistent`: re-arm after every trigger. Example: `Count whenever I walk past.`

For repeated stateful prompts such as `each time`, `every time`, `whenever`,
`keep track`, or `running total`, the example uses a visual-memory loop:

1. VideoMemory detects the visual event.
2. The voice agent asks VideoMemory to extract the observation from the frame.
3. The voice agent updates local state silently.
4. The monitor is re-armed for the next occurrence.

The webhook receiver intentionally ignores:

- duplicate event IDs,
- task notes for unregistered tasks,
- events from another bot,
- negative or unclear active-task notes.

It accepts:

- completed VideoMemory tasks,
- affirmative active-task notes that match the registered trigger.

This handles the normal general-ingestor case where VideoMemory writes a useful
note such as `A phone is visible in frame 4` but leaves the task status `active`.

## Debug

Inspect the local tool trace:

```bash
curl http://127.0.0.1:8899/api/tool-calls
```

Inspect the full debug snapshot:

```bash
curl http://127.0.0.1:8899/api/debug
```

The UI also has an `Advanced/debug` section with the active task, wakeup state,
fake camera controls, and ledger.

## Hugging Face Space

The demo can run as a CPU-only Docker Space. The container starts VideoMemory on
localhost port `5050` and exposes the voice-agent UI on the Space port.

Set these Space secrets:

- `OPENAI_API_KEY` for OpenAI Realtime voice.
- `GOOGLE_API_KEY` for VideoMemory's default Gemini vision model.

Use `Dockerfile.huggingface` as the Space Dockerfile and
`start-huggingface.sh` as the container entrypoint.

## Fake Camera

The example serves a fake snapshot camera at:

```text
http://127.0.0.1:8899/fake-camera/snapshot.ppm
```

Use fake camera mode before creating a monitor, or click `Register fake camera`.
For a full wakeup-loop test without waiting for model inference, create a monitor
and click `Simulate wakeup`.

## Test

```bash
cd examples/voice-agent-demo
npm run check
npm test
```
