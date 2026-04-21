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

First inspect the onboarding plan:

```bash
npx -y @clamepending/videomemory@0.1.2 onboard --safe --repo-ref v0.1.2 --explain
```

If the plan matches the user's request, run onboarding:

```bash
npx -y @clamepending/videomemory@0.1.2 onboard --safe --repo-ref v0.1.2
```

Relaunch / upgrade:

```bash
npx -y @clamepending/videomemory@0.1.2 relaunch --repo-ref v0.1.2
```

Check status:

```bash
npx -y @clamepending/videomemory@0.1.2 status
```

## What `onboard` does

- uses the packaged VideoMemory bootstrap flow
- starts VideoMemory without Docker
- installs the OpenClaw bridge files used by VideoMemory
- returns the user-facing VideoMemory UI link

In `--safe` mode, onboarding avoids network-exposure setup, provider credential import, chat notifications, and privileged setup paths.

## Useful flags

```bash
npx -y @clamepending/videomemory@0.1.2 onboard --repo-dir ~/videomemory --repo-ref v0.1.2
npx -y @clamepending/videomemory@0.1.2 onboard --safe --explain
npx -y @clamepending/videomemory@0.1.2 relaunch --repo-ref v0.1.2 --videomemory-base http://127.0.0.1:5050
npx -y @clamepending/videomemory@0.1.2 status --videomemory-base http://127.0.0.1:5050
```

## Ground rules

- Prefer the packaged `npx -y @clamepending/videomemory@0.1.2 ...` command over hand-written bootstrap commands.
- If `videomemory-openclaw` is already installed and on PATH, it is also safe to use the equivalent `videomemory-openclaw ...` command.
- Prefer `--safe --explain` before running host onboarding, especially when acting from chat.
- This npm package is a host CLI, not an in-process OpenClaw plugin.
- If onboarding or relaunch fails, report the actual stderr instead of guessing.
- After a successful onboarding or relaunch, reply with the returned UI link.
