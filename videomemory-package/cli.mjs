#!/usr/bin/env node

import {
  doctorClaudeCode,
  getVideomemoryStatus,
  installClaudeCode,
  launchClaudeCode,
  onboardVideomemory,
  relaunchVideomemory,
  testClaudeCodeEvent,
  upClaudeCode,
} from "./src/shared.mjs";

function usage() {
  return [
    "Usage:",
    "  videomemory status [--videomemory-base URL]",
    "  videomemory claude [--repo-dir DIR] [--videomemory-base URL] [--skip-auth] [--no-open-camera] [--no-launch]",
    "  videomemory claude install [--repo-dir DIR] [--repo-ref REF] [--repo-url URL] [--videomemory-base URL] [--skip-webhook]",
    "  videomemory claude doctor [--repo-dir DIR] [--videomemory-base URL] [--skip-auth]",
    "  videomemory claude up [--repo-dir DIR] [--videomemory-base URL] [--skip-auth] [--no-open-camera] [--no-launch] [--dev] [--no-tool-allowlist]",
    "  videomemory claude launch [--repo-dir DIR] [--videomemory-base URL] [--dev] [--no-tool-allowlist]",
    "  videomemory claude test-event [--webhook-token TOKEN]",
    "  videomemory onboard [--safe] [--dry-run|--explain] [--openclaw-home DIR] [--repo-dir DIR] [--repo-ref REF] [--repo-url URL] [--videomemory-base URL] [--bot-id ID] [--tailscale-authkey KEY] [--skip-start] [--skip-keys] [--skip-tailscale] [--skip-notify]",
    "  videomemory relaunch [--dry-run|--explain] [--openclaw-home DIR] [--repo-dir DIR] [--repo-ref REF] [--repo-url URL] [--videomemory-base URL] [--skip-keys]",
    "",
    "Notes:",
    "  claude is the normal local Claude Code path: start/check VideoMemory, wire the channel, open the FaceTime camera bridge, then launch Claude.",
    "  onboard/relaunch are legacy OpenClaw-oriented host setup commands.",
    "  --safe disables Tailscale setup, model API-key sync, Telegram notify, and sudo-requiring setup.",
    "  --dry-run and --explain print the exact plan without making changes.",
    "  claude install downloads the VideoMemory repo channel package, installs deps, and wires VideoMemory to it when the server is running.",
    "  claude up is the one-command local Claude Code path: start/check VideoMemory, wire the channel, open the camera bridge, then launch Claude.",
    "  claude launch uses the approved Claude channel path by default; pass --dev only while developing the channel locally.",
    "  --json prints the full result object.",
  ].join("\n");
}

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function parseArgs(argv) {
  const commandParts = [];
  let start = 0;
  while (start < argv.length && !argv[start].startsWith("--") && commandParts.length < 2) {
    commandParts.push(argv[start]);
    start += 1;
  }
  const command = commandParts.join(":");
  const rest = argv.slice(start);
  const options = {};
  for (let i = 0; i < rest.length; i += 1) {
    const token = rest[i];
    if (token === "--json") {
      options.json = true;
      continue;
    }
    if (!token.startsWith("--")) {
      throw new Error(`Unexpected argument: ${token}`);
    }
    const key = token.slice(2);
    const next = rest[i + 1];
    if (!next || next.startsWith("--")) {
      options[key] = true;
      continue;
    }
    options[key] = next;
    i += 1;
  }
  return { command, options };
}

function normalizeOptions(options) {
  return {
    openclawHome: cleanText(options["openclaw-home"]),
    repoDir: cleanText(options["repo-dir"]),
    repoRef: cleanText(options["repo-ref"]),
    repoUrl: cleanText(options["repo-url"]),
    videomemoryBase: cleanText(options["videomemory-base"]),
    botId: cleanText(options["bot-id"]),
    tailscaleAuthKey: cleanText(options["tailscale-authkey"]),
    channelDir: cleanText(options["channel-dir"]),
    claudeChannelHost: cleanText(options["channel-host"]),
    claudeChannelPort: cleanText(options["channel-port"]),
    webhookToken: cleanText(options["webhook-token"]),
    eventId: cleanText(options["event-id"]),
    ioId: cleanText(options["io-id"]),
    taskId: cleanText(options["task-id"]),
    taskDescription: cleanText(options["task-description"]),
    note: cleanText(options.note),
    actionInstruction: cleanText(options["action-instruction"]),
    safe: Boolean(options.safe),
    dryRun: Boolean(options["dry-run"]),
    explain: Boolean(options.explain),
    skipStart: Boolean(options["skip-start"]),
    skipKeys: Boolean(options["skip-keys"]),
    skipTailscale: Boolean(options["skip-tailscale"]),
    skipNotify: Boolean(options["skip-notify"]),
    skipWebhook: Boolean(options["skip-webhook"]),
    keepWebhookToken: Boolean(options["keep-webhook-token"]),
    skipAuth: Boolean(options["skip-auth"]),
    noOpenCamera: Boolean(options["no-open-camera"]),
    noLaunch: Boolean(options["no-launch"]),
    devChannel: Boolean(options.dev),
    noToolAllowlist: Boolean(options["no-tool-allowlist"]),
  };
}

function printClaudeInstall(result) {
  process.stdout.write(
    [
      `Claude channel: ${result.channelDir}`,
      `MCP config: ${result.mcpConfig}`,
      `Webhook URL: ${result.webhookUrl}`,
      result.webhook?.configured
        ? "VideoMemory webhook: configured"
        : `VideoMemory webhook: not configured (${result.webhook?.error || "server not reachable"})`,
      "",
      "Next:",
      "  videomemory claude doctor",
      "  videomemory claude launch",
    ].join("\n") + "\n",
  );
}

function printClaudeDoctor(result) {
  for (const check of result.checks || []) {
    const mark = check.ok ? "ok" : "fail";
    process.stdout.write(`${mark.padEnd(5)} ${check.name}${check.detail ? ` - ${check.detail}` : ""}\n`);
  }
  process.stdout.write(`\n${result.success ? "ready" : "not ready"}\n`);
}

function printClaudeTestEvent(result) {
  process.stdout.write(
    [
      `Webhook URL: ${result.webhookUrl}`,
      `Response: HTTP ${result.responseStatus}`,
      `Status: ${result.success ? "ok" : "error"}`,
    ].join("\n") + "\n",
  );
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  if (!command || command === "help" || command === "--help" || command === "-h") {
    process.stdout.write(`${usage()}\n`);
    return;
  }

  const normalized = normalizeOptions(options);
  let result;

  if (command === "onboard") {
    result = await onboardVideomemory(normalized);
  } else if (command === "relaunch") {
    result = await relaunchVideomemory(normalized);
  } else if (command === "status") {
    result = await getVideomemoryStatus(normalized);
  } else if (command === "claude" || command === "claude:up") {
    result = await upClaudeCode(normalized);
  } else if (command === "claude:install") {
    result = await installClaudeCode(normalized);
  } else if (command === "claude:doctor") {
    result = await doctorClaudeCode(normalized);
  } else if (command === "claude:launch") {
    result = await launchClaudeCode(normalized);
  } else if (command === "claude:test-event") {
    result = await testClaudeCodeEvent(normalized);
  } else {
    throw new Error(`Unknown command: ${command}\n\n${usage()}`);
  }

  if (options.json) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return;
  }

  if (result?.dryRun && result?.stdout) {
    process.stdout.write(result.stdout.endsWith("\n") ? result.stdout : `${result.stdout}\n`);
    return;
  }

  if (command === "claude:install") {
    printClaudeInstall(result);
    return;
  }

  if (command === "claude:doctor") {
    printClaudeDoctor(result);
    process.exitCode = result.success ? 0 : 1;
    return;
  }

  if (command === "claude:test-event") {
    printClaudeTestEvent(result);
    process.exitCode = result.success ? 0 : 1;
    return;
  }

  if (result?.uiUrl) {
    process.stdout.write(`${result.uiUrl}\n`);
    return;
  }

  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

main().catch((error) => {
  const message = cleanText(error?.message) || String(error);
  process.stderr.write(`${JSON.stringify({ status: "error", error: message }, null, 2)}\n`);
  process.exitCode = 1;
});
