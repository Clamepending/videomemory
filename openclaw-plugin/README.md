# OpenClaw VideoMemory Plugin

This directory is the phase 1 scaffold for publishing VideoMemory as a native OpenClaw plugin.

What exists here today:
- a native `openclaw.plugin.json` manifest
- package metadata for future ClawHub/npm publication
- a native OpenClaw plugin that registers VideoMemory onboarding tools
- a package CLI (`videomemory-openclaw`) that can install/enable the plugin and run onboarding outside the plugin runtime
- a bundled VideoMemory skill
- a bundled `openclaw-videomemory-task-helper.mjs`
- a bundled `videomemory-alert.mjs` transform asset for the future plugin-managed webhook path

What is intentionally not finished yet:
- no plugin-managed webhook route registration yet
- no automatic migration from the current bootstrap-installed OpenClaw home layout

Current source-of-truth split:
- VideoMemory host install/relaunch remains in `docs/openclaw-bootstrap.sh` and `docs/relaunch-videomemory.sh`
- the legacy OpenClaw home wiring still lives under `deploy/openclaw-real-home/`
- this plugin package is now the new home for the OpenClaw-side assets we want to publish and eventually manage directly
- the plugin and CLI currently reuse the existing GitHub-hosted bootstrap/relaunch scripts instead of reimplementing host install logic

Planned phase 2:
- replace shell-based OpenClaw config patching with plugin-owned setup/runtime wiring
- add a real setup surface so users can select VideoMemory during OpenClaw setup
- make this package the canonical source for the skill, helper, and webhook integration
