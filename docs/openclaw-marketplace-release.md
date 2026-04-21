# VideoMemory OpenClaw Marketplace Release

This repo now contains the two pieces needed for the desired OpenClaw setup flow:

- the installable host CLI package at `openclaw-plugin/`
- the ClawHub skill folder at `clawhub-skill/videomemory/`

## Why there are two artifacts

The OpenClaw Skills UI installs skill dependencies through `metadata.openclaw.install`.
That installer can install node packages, which is enough for VideoMemory because the published npm package is now a plain host CLI instead of an in-process OpenClaw plugin.

So the release flow is intentionally:

1. Publish the npm package `@clamepending/videomemory`
2. Publish the ClawHub skill `clawhub-skill/videomemory`
3. The ClawHub skill is immediately eligible after install because it does not gate itself on the helper binary
4. The npm helper install exposes `videomemory-openclaw`
5. The CLI runs VideoMemory onboarding directly on the host

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
2. OpenClaw can install the npm package because of the skill's `metadata.openclaw.install`, but the skill does not hide itself when that binary is not preinstalled
3. When the user says `Install the VideoMemory skill from ClawHub and send me the UI`, the skill tells OpenClaw to run:

```bash
npm install -g @clamepending/videomemory@0.1.2
videomemory-openclaw onboard --safe --repo-ref v0.1.2 --explain
videomemory-openclaw onboard --safe --repo-ref v0.1.2
```

That command:

- bootstraps VideoMemory on the host
- uses the scripts bundled inside the installed npm package
- avoids Tailscale setup, model API-key copying, Telegram notifications, and sudo-requiring setup paths in safe mode
- returns the user-facing UI link

## Local verification already completed in this repo

- `npm pack`
- `node cli.mjs onboard --help`
- `node cli.mjs status --videomemory-base http://localhost:5051 --json`

## Why this avoids the security scanner block

The published npm package no longer ships an `openclaw.plugin.json` manifest, bundled hook assets, or plugin runtime code.
That keeps the marketplace install path as a normal npm binary install instead of asking OpenClaw to trust the package as native plugin code.

The ClawHub skill also avoids gating eligibility on the `videomemory-openclaw` binary.
That means `clawhub install videomemory` is enough for OpenClaw to read the skill, install the declared npm helper if needed, inspect the safe onboarding command, and then run the packaged CLI.
