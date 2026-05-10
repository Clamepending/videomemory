# Evidence And Replay

Task notes may include saved evidence:

- `frame_url` / `note_frame_api_url`
- `video_url` / `note_video_api_url`
- `note_id`
- `timestamp`

Inspect latest task evidence:

```bash
node scripts/agent/inspect-event.mjs --task-id 1 --json
```

Fetch a saved triggering frame:

```bash
curl -fsSL http://127.0.0.1:5050/api/task-note/42/frame -o triggering-frame.jpg
```

Fetch a saved triggering clip:

```bash
curl -fsSL http://127.0.0.1:5050/api/task-note/42/video -o triggering-clip.mp4
```

When responding to a webhook, use the saved evidence URL from the webhook payload if present. Do not take a fresh snapshot unless the user asked for current state rather than triggering evidence.
