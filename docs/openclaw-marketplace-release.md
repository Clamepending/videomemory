# VideoMemory OpenClaw Marketplace Release

This repo now contains the two pieces needed for the desired OpenClaw setup flow:

- the installable host CLI package at `openclaw-plugin/`
- the ClawHub skill folder at `clawhub-skill/videomemory/`

## Why there are two artifacts

The npm package is still useful as an explicit host-CLI fallback and for update commands.
The ClawHub skill is the smoother chat-first path: it is instruction-only so it installs cleanly, then points OpenClaw at the published host CLI.

So the release flow is intentionally:

1. Publish the npm package `@clamepending/videomemory`
2. Publish the ClawHub skill `clawhub-skill/videomemory`
3. The ClawHub skill is immediately eligible after install because it does not bundle host-mutating launcher scripts
4. The skill tells OpenClaw to inspect the safe onboarding plan from the published host CLI
5. The host CLI starts VideoMemory directly on the host and installs the OpenClaw bridge files

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
clawhub publish . --slug videomemory --name "VideoMemory" --version 0.1.12
```

If browser login fails, use an API token instead:

```bash
clawhub login --token YOUR_TOKEN --no-browser
```

The skill instructions point at the pinned npm package:

```text
@clamepending/videomemory
```

## Expected user flow after both are published

From OpenClaw setup / Skills UI:

1. Select `VideoMemory`
2. OpenClaw installs the instruction-only ClawHub skill folder
3. When the user says `install videomemory please` or `Install the VideoMemory skill from ClawHub and send me the UI`, the skill tells OpenClaw to run:

```bash
npx -y @clamepending/videomemory@0.1.3 onboard --safe --repo-ref v0.1.2 --explain
npx -y @clamepending/videomemory@0.1.3 onboard --safe --repo-ref v0.1.2
```

That command:

- bootstraps VideoMemory on the host
- uses the published VideoMemory host CLI
- avoids Tailscale setup, model API-key copying, Telegram notifications, and sudo-requiring setup paths in safe mode
- returns the user-facing UI link

## Local verification already completed in this repo

- `npm pack`
- `node cli.mjs onboard --help`
- `node cli.mjs status --videomemory-base http://localhost:5051 --json`

## Why this avoids the security scanner block

The ClawHub skill no longer bundles scripts that clone, install, run services, or modify OpenClaw config during skill installation.
Instead, `clawhub install videomemory` installs a small instruction-only skill; the host-side work happens only when the user asks OpenClaw to run the published CLI, with `--safe --explain` shown first.
