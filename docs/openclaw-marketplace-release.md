# VideoMemory OpenClaw Marketplace Release

This repo now contains the two pieces needed for the desired OpenClaw setup flow:

- the installable OpenClaw package at `openclaw-plugin/`
- the ClawHub skill folder at `clawhub-skill/videomemory/`

## Why there are two artifacts

The OpenClaw Skills UI installs skill dependencies through `metadata.openclaw.install`.
That installer can install node packages, but it does not directly install OpenClaw plugins by itself.

So the release flow is intentionally hybrid:

1. Publish the npm package `@clamepending/videomemory`
2. Publish the ClawHub skill `clawhub-skill/videomemory`
3. The ClawHub skill installs the npm package and exposes the `videomemory-openclaw` host CLI
4. That CLI installs/enables the OpenClaw plugin and runs VideoMemory onboarding

## Artifact 1: npm package

Package root:

```bash
cd openclaw-plugin
```

Validate locally:

```bash
npm pack
node cli.mjs ensure-plugin --json
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
clawhub publish . --slug videomemory --name "VideoMemory" --version 0.1.0
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
videomemory-openclaw onboard
```

That command:

- ensures the OpenClaw plugin is installed and enabled
- bootstraps VideoMemory on the host
- returns the user-facing UI link

## Local verification already completed in this repo

- `node cli.mjs ensure-plugin --openclaw-home <tmp> --json`
- `openclaw plugins install <packed-tgz>`
- `openclaw plugins info videomemory --json`
- `openclaw skills list` shows the bundled plugin skill
- `node cli.mjs status --videomemory-base http://localhost:5051 --json`

## Future cleanup

The plugin still reuses the existing GitHub-hosted bootstrap/relaunch scripts under `docs/`.
That is enough for the marketplace flow, but a later cleanup can move more of that logic into the plugin runtime itself.
