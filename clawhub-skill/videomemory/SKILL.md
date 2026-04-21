---
name: videomemory
description: Install the VideoMemory host CLI, start VideoMemory safely, and return the local UI link.
homepage: https://github.com/Clamepending/videomemory
metadata: {"openclaw":{"emoji":"camera","install":[{"id":"node","kind":"node","package":"@clamepending/videomemory@0.1.2","bins":["videomemory-openclaw"],"label":"Install VideoMemory host CLI for faster repeat use"}]}}
---

# VideoMemory Setup

Use this skill when the user wants OpenClaw to install, start, relaunch, or check VideoMemory.

For requests like "Install the VideoMemory skill from ClawHub and send me the UI", do the safe onboarding flow and reply with the returned UI link.

## Preferred commands

If the helper command is missing, install the host CLI dependency declared in this skill's metadata. If you are acting from a shell and the user explicitly asked you to install VideoMemory, this command installs the same pinned helper:

```bash
npm install -g @clamepending/videomemory@0.1.2
```

Then inspect the onboarding plan:

```bash
videomemory-openclaw onboard --safe --repo-ref v0.1.2 --explain
```

If the plan matches the user's request, run onboarding:

```bash
videomemory-openclaw onboard --safe --repo-ref v0.1.2
```

Relaunch / upgrade:

```bash
videomemory-openclaw relaunch --repo-ref v0.1.2
```

Check status:

```bash
videomemory-openclaw status
```

## What `onboard` does

- uses the packaged VideoMemory bootstrap flow
- starts VideoMemory without Docker
- installs the OpenClaw bridge files used by VideoMemory
- returns the user-facing VideoMemory UI link

In `--safe` mode, onboarding avoids network-exposure setup, provider credential import, chat notifications, and privileged setup paths.

## Useful flags

```bash
videomemory-openclaw onboard --repo-dir ~/videomemory --repo-ref v0.1.2
videomemory-openclaw onboard --safe --explain
videomemory-openclaw relaunch --repo-ref v0.1.2 --videomemory-base http://127.0.0.1:5050
videomemory-openclaw status --videomemory-base http://127.0.0.1:5050
```

## Ground rules

- Prefer the packaged `videomemory-openclaw` command over hand-written bootstrap commands.
- Prefer `--safe --explain` before running host onboarding, especially when acting from chat.
- This npm package is a host CLI, not an in-process OpenClaw plugin.
- If onboarding or relaunch fails, report the actual stderr instead of guessing.
- After a successful onboarding or relaunch, reply with the returned UI link.
