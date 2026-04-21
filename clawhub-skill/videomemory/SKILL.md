---
name: videomemory
description: Start VideoMemory safely from OpenClaw and return the local UI link.
homepage: https://github.com/Clamepending/videomemory
metadata: {"openclaw":{"emoji":"camera"}}
---

# VideoMemory Setup

Use this skill when the user wants OpenClaw to install, start, relaunch, or check VideoMemory.

For requests like "Install the VideoMemory skill from ClawHub and send me the UI", do the safe onboarding flow and reply with the returned UI link.

## Preferred commands

From the OpenClaw workspace root after `clawhub install videomemory`, inspect the onboarding plan:

```bash
bash skills/videomemory/scripts/onboard.sh --safe --repo-ref v0.1.2 --explain
```

If the plan matches the user's request, run onboarding:

```bash
bash skills/videomemory/scripts/onboard.sh --safe --repo-ref v0.1.2
```

Relaunch / upgrade:

```bash
bash skills/videomemory/scripts/relaunch.sh --repo-ref v0.1.2
```

Check status:

```bash
curl -fsS http://127.0.0.1:5050/api/health
```

## What `onboard` does

- uses the packaged VideoMemory bootstrap flow
- starts VideoMemory without Docker
- installs the OpenClaw bridge files used by VideoMemory
- returns the user-facing VideoMemory UI link

In `--safe` mode, onboarding avoids network-exposure setup, provider credential import, chat notifications, and privileged setup paths.

## Useful flags

```bash
bash skills/videomemory/scripts/onboard.sh --repo-dir ~/videomemory --repo-ref v0.1.2
bash skills/videomemory/scripts/onboard.sh --safe --explain
bash skills/videomemory/scripts/relaunch.sh --repo-ref v0.1.2 --videomemory-base http://127.0.0.1:5050
curl -fsS http://127.0.0.1:5050/api/health
```

## Ground rules

- Prefer the bundled launcher scripts over hand-written bootstrap commands.
- Prefer `--safe --explain` before running host onboarding, especially when acting from chat.
- The launcher verifies the pinned `v0.1.2` commit before running the repo's reviewed onboarding script.
- If onboarding or relaunch fails, report the actual stderr instead of guessing.
- After a successful onboarding or relaunch, reply with the returned UI link.
