#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const DIST_DIR = "/app/dist";
const OPENCLAW_HOME = "/home/node/.openclaw";
const GATEWAY_FILE_PATTERN = /^gateway-cli-.*\.js$/;
const MAIN_SESSION_KEY_PATTERN = /^agent:[^:]+:main$/i;

function log(message) {
  process.stdout.write(`[openclaw-runtime-patch] ${message}\n`);
}

function findGatewayBundle() {
  const entry = fs.readdirSync(DIST_DIR).find((name) => GATEWAY_FILE_PATTERN.test(name));
  if (!entry) {
    throw new Error(`Could not find gateway bundle in ${DIST_DIR}`);
  }
  return path.join(DIST_DIR, entry);
}

function patchGatewayBundle() {
  const bundlePath = findGatewayBundle();
  let source = fs.readFileSync(bundlePath, "utf8");

  if (source.includes("const hookSharedSessionTarget =")) {
    log(`Gateway bundle already patched: ${bundlePath}`);
    return;
  }

  const anchor = `const mainSessionKey = resolveMainSessionKeyFromConfig();
\t\tconst jobId = randomUUID();
\t\tconst now = Date.now();`;
  const replacement = `const mainSessionKey = resolveMainSessionKeyFromConfig();
\t\tconst jobId = randomUUID();
\t\tconst now = Date.now();
\t\tconst normalizedSessionKey = sessionKey.trim().toLowerCase();
\t\tconst hookSharedSessionTarget = normalizedSessionKey.length > 0 && !normalizedSessionKey.startsWith("hook:") && !normalizedSessionKey.startsWith("cron:");
\t\tconst sessionTarget = hookSharedSessionTarget ? "shared" : "isolated";`;

  if (!source.includes(anchor)) {
    throw new Error("Could not find dispatchAgentHook anchor in gateway bundle");
  }
  source = source.replace(anchor, replacement);

  const isolatedLine = `\t\t\tsessionTarget: "isolated",`;
  if (!source.includes(isolatedLine)) {
    throw new Error('Could not find `sessionTarget: "isolated"` in gateway bundle');
  }
  source = source.replace(isolatedLine, `\t\t\tsessionTarget,`);

  fs.writeFileSync(bundlePath, source, "utf8");
  log(`Patched gateway bundle: ${bundlePath}`);
}

function backupFile(filePath) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const backupPath = `${filePath}.bak-${timestamp}`;
  fs.copyFileSync(filePath, backupPath);
  return backupPath;
}

function repairMainSessionStore(storePath) {
  const raw = fs.readFileSync(storePath, "utf8");
  const store = JSON.parse(raw);
  let changed = false;

  for (const [sessionKey, entry] of Object.entries(store)) {
    if (!MAIN_SESSION_KEY_PATTERN.test(sessionKey)) continue;
    if (!entry || typeof entry !== "object") continue;

    const sessionFile = typeof entry.sessionFile === "string" ? entry.sessionFile.trim() : "";
    if (!sessionFile) continue;

    const baseName = path.basename(sessionFile);
    if (!baseName.endsWith(".jsonl")) continue;

    const derivedSessionId = baseName.slice(0, -".jsonl".length).trim();
    if (!derivedSessionId) continue;
    if (derivedSessionId === entry.sessionId) continue;

    const sessionsDir = path.dirname(storePath);
    const expectedCanonicalPath = path.join(sessionsDir, `${derivedSessionId}.jsonl`);
    if (path.resolve(sessionFile) !== path.resolve(expectedCanonicalPath)) continue;

    entry.sessionId = derivedSessionId;
    delete entry.sessionFile;
    changed = true;
    log(`Repaired ${sessionKey} to sessionId ${derivedSessionId}`);
  }

  if (!changed) return;

  const backupPath = backupFile(storePath);
  fs.writeFileSync(storePath, `${JSON.stringify(store, null, 2)}\n`, "utf8");
  log(`Updated session store ${storePath} (backup: ${backupPath})`);
}

function repairMainSessions() {
  const agentsDir = path.join(OPENCLAW_HOME, "agents");
  if (!fs.existsSync(agentsDir)) return;

  for (const agentId of fs.readdirSync(agentsDir)) {
    const storePath = path.join(agentsDir, agentId, "sessions", "sessions.json");
    if (!fs.existsSync(storePath)) continue;
    repairMainSessionStore(storePath);
  }
}

function main() {
  patchGatewayBundle();
  repairMainSessions();
}

try {
  main();
} catch (error) {
  console.error(`[openclaw-runtime-patch] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
