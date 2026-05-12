#!/usr/bin/env node

import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(packageRoot, "..");
const bundledDir = path.join(packageRoot, "bundled");

const scripts = [
  ["docs/openclaw-bootstrap.sh", "openclaw-bootstrap.sh"],
  ["docs/relaunch-videomemory.sh", "relaunch-videomemory.sh"],
];

await mkdir(bundledDir, { recursive: true });

for (const [sourceRelativePath, targetName] of scripts) {
  await copyFile(
    path.join(repoRoot, sourceRelativePath),
    path.join(bundledDir, targetName),
  );
}
