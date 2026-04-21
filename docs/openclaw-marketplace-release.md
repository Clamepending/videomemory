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
3. The ClawHub skill installs the npm package and exposes the `videomemory-openclaw` host CLI
4. That CLI runs VideoMemory onboarding directly on the host

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
2. OpenClaw installs the npm package because of the skill's `metadata.openclaw.install`
3. The `videomemory-openclaw` command becomes available on the gateway host
4. When the user says `onboard to videomemory`, the skill tells OpenClaw to run:

```bash
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
