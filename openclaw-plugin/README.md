# OpenClaw VideoMemory Host CLI

This directory now contains the npm package published as `@clamepending/videomemory`.

What the package does:
- exposes the `videomemory-openclaw` host CLI
- runs the maintained VideoMemory onboarding and relaunch scripts bundled inside this npm package version
- keeps the OpenClaw marketplace install path simple: the ClawHub skill installs this package, then runs the CLI

Why it is a plain CLI package instead of a native OpenClaw plugin:
- OpenClaw's plugin security scanner correctly treats host-management code, shell execution, and hook assets as high trust
- publishing the onboarding flow as a plugin caused installs to be blocked before onboarding could run
- the safer path is a skill + host CLI split, where OpenClaw installs a normal npm binary and the binary manages VideoMemory on the host

Current source-of-truth split:
- VideoMemory host install and relaunch remain in `docs/openclaw-bootstrap.sh` and `docs/relaunch-videomemory.sh`
- `npm pack` runs `scripts/sync-bundled-scripts.mjs` so those scripts are copied into `bundled/` before publish
- the current OpenClaw bridge files still live in the repo under `docs/` and `deploy/openclaw-real-home/`
- the ClawHub skill lives separately under `clawhub-skill/videomemory/`

Typical flow:
1. OpenClaw installs `@clamepending/videomemory`
2. The `videomemory-openclaw` binary becomes available on the gateway host
3. The skill tells OpenClaw to inspect `videomemory-openclaw onboard --safe --explain`
4. After inspection, OpenClaw runs `videomemory-openclaw onboard --safe`
5. The CLI bootstraps VideoMemory without Docker and returns the UI link

Safe mode:
- disables automatic Tailscale setup
- disables model API-key copying
- disables Telegram notification side effects
- avoids sudo-requiring setup paths
