# Changelog

## 0.1.4 - 2026-05-10

Release focus: make VideoMemory usable as a compact open-source video monitor
for external agents.

- Added MIT license metadata for the core repo and OpenClaw package.
- Reduced the tracked source tree by removing generated DB fragments, macOS
  metadata, old eval datasets, and experimental bulk.
- Added neutral agent helper scripts under `scripts/agent/`:
  - `ensure-server.mjs`
  - `simulate-webhook-event.mjs`
  - `inspect-event.mjs`
- Added Claude Code channel package under `claude-videomemory-channel/` for
  push-style camera monitor events into a running Claude session.
- Added saved video evidence fields to task-update webhook payloads:
  - `note_has_video`
  - `note_video_api_path`
  - `note_video_api_url`
- Clarified the monitor contract: VideoMemory owns visual detection; the agent
  runtime owns follow-up actions and delivery.
- Clarified monitor readiness checks for model runtime/API keys and local camera
  permission.
- Updated OpenClaw package metadata to `@clamepending/videomemory@0.1.8`.

Known release note: the tracked tree is compact, but old large assets still
exist in Git history. Fresh source archives are small; full clones remain larger
until history is rewritten or a fresh public repo is created.
