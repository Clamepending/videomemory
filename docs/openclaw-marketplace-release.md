# VideoMemory OpenClaw Marketplace Release

This repo now contains the two pieces needed for the desired OpenClaw setup flow:

- the installable host CLI package at `openclaw-plugin/`
- the ClawHub skill folder at `clawhub-skill/videomemory/`

## Why there are two artifacts

The npm package is still useful as an explicit host-CLI fallback and for update commands.
The ClawHub skill is the smoother chat-first path: it bundles local launcher scripts so OpenClaw can start VideoMemory without first installing a global package.

So the release flow is intentionally:

1. Publish the npm package `@clamepending/videomemory`
2. Publish the ClawHub skill `clawhub-skill/videomemory`
3. The ClawHub skill is immediately eligible after install because it does not gate itself on a helper binary
4. The bundled launcher clones the pinned VideoMemory repo and verifies the expected commit
5. The repo onboarding script starts VideoMemory directly on the host

## Artifact 1: npm package

Package root:

```bash
cd openclaw-plugin
```

Validate locally:

```bash
npm pack
node cli.mjs onboard --help
node cli.mjs status --videomemory-base http://127.0.0.1:5050 --json
```

Publish to npm:

```bash
npm publish --access public
```

Expected package name:

```text
@clamepending/videomemory
```

## Artifact 2: ClawHub skill

Skill root:

```bash
cd clawhub-skill/videomemory
```

Publish to ClawHub:

```bash
clawhub login
clawhub publish . --slug videomemory --name "VideoMemory" --version 0.1.2
```

If browser login fails, use an API token instead:

```bash
clawhub login --token YOUR_TOKEN --no-browser
```

The skill metadata already points at the npm package:

```text
@clamepending/videomemory
```

## Expected user flow after both are published

From OpenClaw setup / Skills UI:

1. Select `VideoMemory`
2. OpenClaw installs the ClawHub skill folder, including the bundled launcher scripts under `skills/videomemory/scripts`
3. When the user says `Install the VideoMemory skill from ClawHub and send me the UI`, the skill tells OpenClaw to run:

```bash
bash skills/videomemory/scripts/onboard.sh --safe --repo-ref v0.1.2 --explain
bash skills/videomemory/scripts/onboard.sh --safe --repo-ref v0.1.2
```

That command:

- bootstraps VideoMemory on the host
- uses the launcher scripts bundled inside the installed ClawHub skill
- avoids Tailscale setup, model API-key copying, Telegram notifications, and sudo-requiring setup paths in safe mode
- returns the user-facing UI link

## Local verification already completed in this repo

- `npm pack`
- `node cli.mjs onboard --help`
- `node cli.mjs status --videomemory-base http://localhost:5051 --json`

## Why this avoids the security scanner block

The ClawHub skill no longer asks the agent to install a third-party global npm binary during the first chat turn.
Instead, `clawhub install videomemory` gives OpenClaw a local, inspectable launcher that clones the pinned VideoMemory repo, verifies the expected commit, and then runs the repo's reviewed onboarding script.
