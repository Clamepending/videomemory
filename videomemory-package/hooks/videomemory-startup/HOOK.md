---
name: videomemory-startup
description: "Check or start VideoMemory when the OpenClaw gateway starts"
homepage: https://github.com/Clamepending/videomemory
metadata:
  {
    "openclaw":
      {
        "emoji": "camera",
        "events": ["gateway:startup"],
        "requires": { "bins": ["node", "git", "curl"], "anyBins": ["uv", "python3"], "os": ["darwin", "linux"] },
        "install": [{ "id": "npm", "kind": "npm", "package": "@clamepending/videomemory" }],
      },
  }
---

# VideoMemory Startup Hook

This hook is for the hook-pack install path:

```bash
openclaw hooks install @clamepending/videomemory
```

By default it only checks whether VideoMemory is reachable at `http://127.0.0.1:5050`.
Set `VIDEOMEMORY_OPENCLAW_AUTOSTART=1`, or configure this hook entry with
`autoStart: true`, to let it run safe host onboarding on gateway startup.

The preferred first-class path is the plugin install:

```bash
openclaw plugins install @clamepending/videomemory
```
