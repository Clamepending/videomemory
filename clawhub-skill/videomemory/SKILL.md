---
name: videomemory
description: Install the VideoMemory OpenClaw package, onboard VideoMemory on the host, and manage relaunch/status from one skill.
homepage: https://github.com/Clamepending/videomemory
metadata: {"openclaw":{"emoji":"📹","requires":{"bins":["videomemory-openclaw","openclaw"]},"install":[{"id":"node","kind":"node","package":"@clamepending/videomemory","bins":["videomemory-openclaw"],"label":"Install VideoMemory OpenClaw package (npm)"}]}}
---

# VideoMemory Setup

Use this skill when the user wants to install, onboard, relaunch, or check VideoMemory from OpenClaw.

## Preferred commands

Onboard VideoMemory end to end:

```bash
videomemory-openclaw onboard
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

- ensures the VideoMemory OpenClaw plugin is installed and enabled
- runs the current VideoMemory bootstrap flow on the host
- starts VideoMemory without Docker
- installs the current OpenClaw bridge files needed by the existing integration path
- returns the user-facing VideoMemory UI link

## Useful flags

```bash
videomemory-openclaw onboard --repo-dir ~/videomemory --repo-ref main
videomemory-openclaw onboard --tailscale-authkey tskey-auth-...
videomemory-openclaw onboard --skip-tailscale
videomemory-openclaw relaunch --videomemory-base http://127.0.0.1:5050
videomemory-openclaw status --videomemory-base http://127.0.0.1:5050
```

## Ground rules

- Prefer the packaged `videomemory-openclaw` command over hand-written bootstrap commands.
- If onboarding or relaunch fails, report the actual stderr instead of guessing.
- After a successful onboarding or relaunch, reply with the returned UI link.
