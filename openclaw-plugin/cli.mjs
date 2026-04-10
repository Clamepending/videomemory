#!/usr/bin/env node

import {
  ensurePluginInstalled,
  getPackageRoot,
  getVideomemoryStatus,
  onboardVideomemory,
  relaunchVideomemory,
} from "./src/shared.mjs";

function usage() {
  return [
    "Usage:",
    "  videomemory-openclaw ensure-plugin [--openclaw-home DIR]",
    "  videomemory-openclaw onboard [--openclaw-home DIR] [--repo-dir DIR] [--repo-ref REF] [--repo-url URL] [--videomemory-base URL] [--bot-id ID] [--tailscale-authkey KEY] [--skip-start] [--skip-keys] [--skip-tailscale]",
    "  videomemory-openclaw relaunch [--repo-dir DIR] [--repo-ref REF] [--repo-url URL] [--videomemory-base URL] [--skip-keys]",
    "  videomemory-openclaw status [--videomemory-base URL]",
    "",
    "Notes:",
    "  onboard automatically ensures the VideoMemory OpenClaw plugin is installed and enabled first.",
    "  --json prints the full result object.",
  ].join("\n");
}

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function parseArgs(argv) {
  const [command = "", ...rest] = argv;
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
    skipStart: Boolean(options["skip-start"]),
    skipKeys: Boolean(options["skip-keys"]),
    skipTailscale: Boolean(options["skip-tailscale"]),
    packageRoot: getPackageRoot(),
  };
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  if (!command || command === "help" || command === "--help" || command === "-h") {
    process.stdout.write(`${usage()}\n`);
    return;
  }

  const normalized = normalizeOptions(options);
  let result;

  if (command === "ensure-plugin") {
    result = await ensurePluginInstalled(normalized);
  } else if (command === "onboard") {
    await ensurePluginInstalled(normalized);
    result = await onboardVideomemory(normalized);
  } else if (command === "relaunch") {
    result = await relaunchVideomemory(normalized);
  } else if (command === "status") {
    result = await getVideomemoryStatus(normalized);
  } else {
    throw new Error(`Unknown command: ${command}\n\n${usage()}`);
  }

  if (options.json) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
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
