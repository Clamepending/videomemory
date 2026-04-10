# OpenClaw VideoMemory Host CLI

This directory now contains the npm package published as `@clamepending/videomemory`.

What the package does:
- exposes the `videomemory-openclaw` host CLI
- downloads and runs the maintained VideoMemory onboarding and relaunch scripts from this repo
- keeps the OpenClaw marketplace install path simple: the ClawHub skill installs this package, then runs the CLI

Why it is a plain CLI package instead of a native OpenClaw plugin:
- OpenClaw's plugin security scanner correctly treats host-management code, shell execution, and hook assets as high trust
- publishing the onboarding flow as a plugin caused installs to be blocked before onboarding could run
- the safer path is a skill + host CLI split, where OpenClaw installs a normal npm binary and the binary manages VideoMemory on the host

Current source-of-truth split:
- VideoMemory host install and relaunch remain in `docs/openclaw-bootstrap.sh` and `docs/relaunch-videomemory.sh`
- the current OpenClaw bridge files still live in the repo under `docs/` and `deploy/openclaw-real-home/`
- the ClawHub skill lives separately under `clawhub-skill/videomemory/`

Typical flow:
1. OpenClaw installs `@clamepending/videomemory`
2. The `videomemory-openclaw` binary becomes available on the gateway host
3. The skill tells OpenClaw to run `videomemory-openclaw onboard`
4. The CLI bootstraps VideoMemory without Docker and returns the UI link
