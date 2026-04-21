# VideoMemory OpenClaw Marketplace Release

This repo now contains the pieces needed for the desired OpenClaw setup flow:

- the first-class OpenClaw plugin / hook-pack / host CLI package at `openclaw-plugin/`
- the ClawHub skill folder at `clawhub-skill/videomemory/`

## Why there are two artifacts

The npm package is the primary first-class artifact. It declares:

- `openclaw.extensions` for `openclaw plugins install @clamepending/videomemory`
- `openclaw.hooks` for `openclaw hooks install @clamepending/videomemory`
- a safe host CLI fallback at `videomemory-openclaw`

The ClawHub skill remains useful as a chat-first discovery path. It is instruction-only so it installs cleanly, then points OpenClaw at the published plugin package and falls back to the safe CLI when needed.

So the release flow is intentionally:

1. Publish the npm package `@clamepending/videomemory`
2. Publish the ClawHub package metadata for the plugin package
3. Publish the ClawHub skill `clawhub-skill/videomemory`
4. The ClawHub skill is immediately eligible after install because it does not bundle host-mutating launcher scripts
5. The skill tells OpenClaw to install the plugin package, or inspect the safe onboarding plan from the CLI fallback
6. The plugin/CLI starts VideoMemory directly on the host and installs the OpenClaw bridge files

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

Validate the published package through OpenClaw:

```bash
openclaw plugins install @clamepending/videomemory@0.1.6
openclaw hooks install @clamepending/videomemory@0.1.6
openclaw plugins doctor
openclaw hooks check
openclaw videomemory onboard --explain
```

## Artifact 2: ClawHub package metadata

Package root:

```bash
cd openclaw-plugin
```

Publish package metadata:

```bash
clawhub package publish . \
  --family code-plugin \
  --name @clamepending/videomemory \
  --display-name "VideoMemory" \
  --version 0.1.6 \
  --source-repo Clamepending/videomemory \
  --source-ref main \
  --source-path openclaw-plugin
```

## Artifact 3: ClawHub skill

Skill root:

```bash
cd clawhub-skill/videomemory
```

Publish to ClawHub:

```bash
clawhub login
clawhub publish . --slug videomemory --name "VideoMemory" --version 0.1.14
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
2. OpenClaw installs the instruction-only ClawHub skill folder or the plugin package
3. When the user says `install videomemory please` or `Install the VideoMemory skill from ClawHub and send me the UI`, the skill first tries:

```bash
openclaw plugins install @clamepending/videomemory@0.1.6
```

After a gateway restart, the plugin exposes:

```text
videomemory_onboard
videomemory_relaunch
videomemory_status
/videomemory-onboard
/videomemory-relaunch
/videomemory-status
```

If plugin installation is unavailable, the skill falls back to:

```bash
npx -y @clamepending/videomemory@0.1.6 onboard --safe --repo-ref v0.1.2 --explain
npx -y @clamepending/videomemory@0.1.6 onboard --safe --repo-ref v0.1.2
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
- `openclaw plugins install /path/to/openclaw-plugin`
- `openclaw hooks install /path/to/openclaw-plugin`
- `openclaw plugins install clamepending-videomemory-0.1.6.tgz`
- `openclaw hooks install clamepending-videomemory-0.1.6.tgz`
- `openclaw plugins install @clamepending/videomemory@0.1.6`
- `openclaw hooks install @clamepending/videomemory@0.1.6`
- `openclaw plugins doctor`
- `openclaw hooks check`
- `openclaw videomemory onboard --explain`

## Why this avoids the security scanner block

The ClawHub skill no longer bundles scripts that clone, install, run services, or modify OpenClaw config during skill installation.
Instead, `clawhub install videomemory` installs a small instruction-only skill; the host-side work happens only when the user asks OpenClaw to run the published CLI, with `--safe --explain` shown first.
