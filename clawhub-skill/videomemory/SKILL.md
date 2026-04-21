---
name: videomemory
description: Install the VideoMemory host CLI package, onboard VideoMemory on the host, and manage relaunch/status from one skill.
homepage: https://github.com/Clamepending/videomemory
metadata: {"openclaw":{"emoji":"📹","requires":{"bins":["videomemory-openclaw","openclaw"]},"install":[{"id":"node","kind":"node","package":"@clamepending/videomemory","bins":["videomemory-openclaw"],"label":"Install VideoMemory host CLI (npm)"}]}}
---

# VideoMemory Setup

Use this skill when the user wants to install, onboard, relaunch, or check VideoMemory from OpenClaw.

## Preferred commands

Inspect the host onboarding plan first:

```bash
videomemory-openclaw onboard --safe --repo-ref v0.1.2 --explain
```

If the plan looks safe and matches the user's request, onboard VideoMemory:

```bash
videomemory-openclaw onboard --safe --repo-ref v0.1.2
```

Relaunch / upgrade:

```bash
videomemory-openclaw relaunch
```

Check status:

```bash
videomemory-openclaw status
```

## What `onboard` does

- runs the current VideoMemory bootstrap flow on the host
- starts VideoMemory without Docker
- installs the current OpenClaw bridge files needed by the existing integration path
- returns the user-facing VideoMemory UI link

In `--safe` mode, onboarding does not install/configure Tailscale, does not copy model provider API keys, does not send Telegram notifications, and avoids sudo-requiring setup paths.

## Useful flags

```bash
videomemory-openclaw onboard --repo-dir ~/videomemory --repo-ref v0.1.2
videomemory-openclaw onboard --safe --explain
videomemory-openclaw onboard --tailscale-authkey tskey-auth-...
videomemory-openclaw onboard --skip-tailscale
videomemory-openclaw relaunch --videomemory-base http://127.0.0.1:5050
videomemory-openclaw status --videomemory-base http://127.0.0.1:5050
```

## Ground rules

- Prefer the packaged `videomemory-openclaw` command over hand-written bootstrap commands.
- Prefer `--safe --explain` before running host onboarding, especially when acting from chat.
- This npm package is a host CLI, not an in-process OpenClaw plugin.
- If onboarding or relaunch fails, report the actual stderr instead of guessing.
- After a successful onboarding or relaunch, reply with the returned UI link.
