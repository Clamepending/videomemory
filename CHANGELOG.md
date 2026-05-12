# Changelog

## 0.1.6 - 2026-05-12

Release focus: make the Claude Code plugin path public and friend-installable.

- Added a repo-root Claude plugin marketplace manifest so Claude Code can
  install `videomemory@videomemory` from the public GitHub repo.
- Added a `setup_local` Claude MCP tool that starts/checks VideoMemory, wires
  the webhook, opens the browser FaceTime camera bridge, and reports readiness
  blockers.
- Added binary true/false video monitors for fast "done when criterion is met"
  use cases.
- Added camera readiness checks for browser camera feeds and task creation.
- Updated the npm CLI default repo ref to `v0.1.6` so
  `@clamepending/videomemory@0.1.9` installs the current Claude plugin path by
  default.

## 0.1.5 - 2026-05-10

Release focus: make Claude Code onboarding a first-class path without adding a
second runtime.

- Added `videomemory claude install`, `videomemory claude doctor`,
  `videomemory claude launch`, and `videomemory claude test-event` to the
  published npm CLI.
- Added a `videomemory` binary alias while keeping `videomemory-openclaw`.
- Added Claude channel MCP tools to create monitor tasks and configure the
  channel webhook from Claude.
- Updated Claude channel instructions so Claude can create a monitor, stop, and
  wait for VideoMemory's push event instead of polling.
- Updated OpenClaw package metadata to `@clamepending/videomemory@0.1.9`.

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
