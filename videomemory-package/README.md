# VideoMemory npm Package

This directory now contains the npm package published as `@clamepending/videomemory`.

What the package does:
- exposes the `videomemory` host CLI plus the backward-compatible `videomemory-openclaw` alias
- provides `videomemory claude`, the one-command Claude Code setup/launch path
- runs the maintained VideoMemory onboarding and relaunch scripts bundled inside this npm package version
- still declares the legacy OpenClaw plugin/hook pack for existing OpenClaw users

Claude Code flow:

```bash
videomemory claude
```

The Claude flow starts or checks VideoMemory, installs/checks the repo channel
package, configures VideoMemory's webhook, opens the browser camera bridge on
macOS, checks Claude auth, launches through Claude Code's approved channel path,
allowlists the VideoMemory MCP tools used for wakeup replies, and exposes MCP
tools so Claude can create monitor tasks itself. Use `videomemory claude launch
--dev` only for local channel development.

Legacy OpenClaw install:

```bash
openclaw plugins install @clamepending/videomemory
```

After restarting the gateway, OpenClaw can call the plugin tools directly. A user can also run:

```text
/videomemory-onboard --explain
/videomemory-onboard
```

Hook-pack install, for setups that want only gateway-startup checks:

```bash
openclaw hooks install @clamepending/videomemory
```

The startup hook does not auto-start VideoMemory unless `VIDEOMEMORY_OPENCLAW_AUTOSTART=1`
or hook config `autoStart: true` is set.

Current source-of-truth split:
- VideoMemory host install and relaunch remain in `docs/openclaw-bootstrap.sh` and `docs/relaunch-videomemory.sh`
- `npm pack` runs `scripts/sync-bundled-scripts.mjs` so those scripts are copied into `bundled/` before publish
- the current OpenClaw bridge files still live in the repo under `docs/` and `deploy/openclaw-real-home/`
- the ClawHub skill lives separately under `clawhub-skill/videomemory/`

Legacy OpenClaw CLI flow:
1. `videomemory-openclaw onboard --safe --explain`
2. `videomemory-openclaw onboard --safe`
3. The CLI bootstraps VideoMemory without Docker and returns the UI link

Safe mode:
- disables automatic Tailscale setup
- disables model API-key copying
- disables Telegram notification side effects
- avoids sudo-requiring setup paths
