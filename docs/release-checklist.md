# Release Checklist

This checklist prepares the public `v0.1.6` VideoMemory release.

## Verify

```bash
uv run python -m unittest discover -s tests
node --check scripts/agent/common.mjs
node --check scripts/agent/ensure-server.mjs
node --check scripts/agent/simulate-webhook-event.mjs
npm run check --prefix claude-videomemory-channel
node --check videomemory-package/cli.mjs
cd videomemory-package && npm pack --dry-run
```

## Publish Order

1. Confirm `main` is clean and pushed.
2. Create and push tag `v0.1.6`.
3. Publish GitHub release notes from `CHANGELOG.md`.
4. Publish `@clamepending/videomemory@0.1.9` from `videomemory-package/`.
5. Verify npm shows `0.1.9`.
6. Verify the installer dry run:

```bash
npx -y @clamepending/videomemory@0.1.9 onboard --safe --repo-ref v0.1.6 --explain
```

## NPM Auth

`npm whoami` must succeed before publishing. If it returns `401`, refresh auth:

```bash
npm login
```
