import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const DEFAULTS = {
  repoUrl: "https://github.com/Clamepending/videomemory.git",
  repoRef: "v0.1.3",
  repoDir: path.join(os.homedir(), "videomemory"),
  openclawHome: path.join(os.homedir(), ".openclaw"),
  videomemoryBase: "http://127.0.0.1:5050",
  botId: "openclaw",
};

const SCRIPT_PATHS = {
  bootstrap: path.join(PACKAGE_ROOT, "bundled", "openclaw-bootstrap.sh"),
  relaunch: path.join(PACKAGE_ROOT, "bundled", "relaunch-videomemory.sh"),
};

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function truthyFlag(value) {
  return value === true || value === "true" || value === "1" || value === 1;
}

function parseUiUrl(output) {
  const match = output.match(/User-facing VideoMemory UI:\s*(\S+)/);
  return match ? match[1] : "";
}

function parseVideomemoryBase(output) {
  const match = output.match(/VideoMemory base:\s*(\S+)/);
  return match ? match[1] : "";
}

function parseRepoCommit(output) {
  const match = output.match(/Running repo commit:\s*([0-9a-f]+)/i);
  return match ? match[1] : "";
}

function parseReplyUrl(output) {
  const match = output.match(/Reply to the user with this VideoMemory UI link:\s*(\S+)/);
  return match ? match[1] : "";
}

function summarizeFailure(stderr, stdout) {
  const combined = [stderr, stdout].map(cleanText).filter(Boolean).join("\n");
  const lines = combined.split("\n").map((line) => line.trim()).filter(Boolean);
  return lines.slice(-6).join("\n");
}

function runProcess(command, args, options = {}) {
  const { env, cwd } = options;
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: env ? { ...process.env, ...env } : process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code: code ?? 0, stdout, stderr });
    });
  });
}

async function runBundledScript(scriptPath, args = [], env = {}) {
  try {
    await access(scriptPath);
  } catch {
    throw new Error(
      `Bundled VideoMemory script is missing: ${scriptPath}. Reinstall @clamepending/videomemory.`,
    );
  }
  return await runProcess("bash", [scriptPath, ...args], { env, cwd: PACKAGE_ROOT });
}

function scriptCommand(scriptPath, args = []) {
  const relativeScriptPath = path.relative(PACKAGE_ROOT, scriptPath) || scriptPath;
  return ["bash", relativeScriptPath, ...args].join(" ");
}

async function runPackagedScript(scriptPath, args = [], env = {}) {
  try {
    return await runBundledScript(scriptPath, args, env);
  } catch (error) {
    const message = cleanText(error?.message) || String(error);
    return {
      code: 1,
      stdout: "",
      stderr: message,
    };
  }
}

function toArgList(entries) {
  const args = [];
  for (const [flag, value] of entries) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    if (typeof value === "boolean") {
      if (value) {
        args.push(flag);
      }
      continue;
    }
    args.push(flag, String(value));
  }
  return args;
}

function buildBootstrapArgs(options = {}) {
  const explainOnly = truthyFlag(options.dryRun) || truthyFlag(options.explain);
  return toArgList([
    ["--repo-url", cleanText(options.repoUrl) || DEFAULTS.repoUrl],
    ["--repo-ref", cleanText(options.repoRef) || DEFAULTS.repoRef],
    ["--repo-dir", cleanText(options.repoDir) || DEFAULTS.repoDir],
    ["--openclaw-home", cleanText(options.openclawHome) || DEFAULTS.openclawHome],
    ["--videomemory-base", cleanText(options.videomemoryBase)],
    ["--bot-id", cleanText(options.botId) || DEFAULTS.botId],
    ["--skip-start", truthyFlag(options.skipStart)],
    ["--skip-keys", truthyFlag(options.skipKeys)],
    ["--skip-tailscale", truthyFlag(options.skipTailscale)],
    ["--skip-notify", truthyFlag(options.skipNotify)],
    ["--safe", truthyFlag(options.safe)],
    ["--dry-run", explainOnly],
    ["--tailscale-authkey", cleanText(options.tailscaleAuthKey)],
  ]);
}

function buildRelaunchArgs(options = {}) {
  const explainOnly = truthyFlag(options.dryRun) || truthyFlag(options.explain);
  return toArgList([
    ["--repo-url", cleanText(options.repoUrl) || DEFAULTS.repoUrl],
    ["--repo-ref", cleanText(options.repoRef) || DEFAULTS.repoRef],
    ["--repo-dir", cleanText(options.repoDir) || DEFAULTS.repoDir],
    ["--openclaw-home", cleanText(options.openclawHome) || DEFAULTS.openclawHome],
    ["--videomemory-base", cleanText(options.videomemoryBase) || DEFAULTS.videomemoryBase],
    ["--skip-keys", truthyFlag(options.skipKeys)],
    ["--dry-run", explainOnly],
  ]);
}

function buildScriptEnv(options = {}) {
  const env = {};
  if (cleanText(options.tailscaleAuthKey)) {
    env.VIDEOMEMORY_TAILSCALE_AUTHKEY = cleanText(options.tailscaleAuthKey);
  }
  if (cleanText(options.videoIngestorModel)) {
    env.VIDEO_INGESTOR_MODEL = cleanText(options.videoIngestorModel);
  }
  for (const key of [
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
  ]) {
    if (cleanText(options[key])) {
      env[key] = cleanText(options[key]);
    }
  }
  return env;
}

function buildResult(command, runResult, metadata = {}) {
  const mergedOutput = [runResult.stdout, runResult.stderr].filter(Boolean).join("\n");
  const dryRun = Boolean(metadata.dryRun);
  const uiUrl = dryRun ? "" : parseReplyUrl(mergedOutput) || parseUiUrl(mergedOutput);
  return {
    command,
    exitCode: runResult.code,
    success: runResult.code === 0,
    ...metadata,
    uiUrl,
    videomemoryBase: dryRun ? "" : parseVideomemoryBase(mergedOutput),
    repoCommit: dryRun ? "" : parseRepoCommit(mergedOutput),
    stdout: runResult.stdout,
    stderr: runResult.stderr,
  };
}

function ensureSuccess(result, label) {
  if (result.success) {
    return result;
  }
  const summary = summarizeFailure(result.stderr, result.stdout);
  throw new Error(`${label} failed${summary ? `:\n${summary}` : "."}`);
}

export async function onboardVideomemory(options = {}) {
  const args = buildBootstrapArgs(options);
  const env = buildScriptEnv(options);
  const explainOnly = truthyFlag(options.dryRun) || truthyFlag(options.explain);
  const result = buildResult(
    scriptCommand(SCRIPT_PATHS.bootstrap, args),
    await runPackagedScript(SCRIPT_PATHS.bootstrap, args, env),
    {
      bundledScript: path.relative(PACKAGE_ROOT, SCRIPT_PATHS.bootstrap),
      dryRun: explainOnly,
      safe: truthyFlag(options.safe),
    },
  );
  return ensureSuccess(result, "VideoMemory onboarding");
}

export async function relaunchVideomemory(options = {}) {
  const args = buildRelaunchArgs(options);
  const env = buildScriptEnv(options);
  const explainOnly = truthyFlag(options.dryRun) || truthyFlag(options.explain);
  const result = buildResult(
    scriptCommand(SCRIPT_PATHS.relaunch, args),
    await runPackagedScript(SCRIPT_PATHS.relaunch, args, env),
    {
      bundledScript: path.relative(PACKAGE_ROOT, SCRIPT_PATHS.relaunch),
      dryRun: explainOnly,
    },
  );
  return ensureSuccess(result, "VideoMemory relaunch");
}

export async function getVideomemoryStatus(options = {}) {
  const baseUrl = cleanText(options.videomemoryBase) || DEFAULTS.videomemoryBase;
  let response;
  try {
    response = await fetch(`${baseUrl}/api/health`);
  } catch (error) {
    const message = cleanText(error?.message) || String(error);
    throw new Error(`VideoMemory health check failed at ${baseUrl}/api/health: ${message}`);
  }
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text };
    }
  }
  if (!response.ok) {
    throw new Error(
      `VideoMemory health check failed at ${baseUrl}/api/health: HTTP ${response.status}`,
    );
  }
  return {
    success: true,
    videomemoryBase: baseUrl,
    uiUrl: `${baseUrl}/devices`,
    health: payload,
  };
}

export function summarizeOnboardResult(result) {
  const parts = [];
  if (result.uiUrl) {
    parts.push(`UI: ${result.uiUrl}`);
  }
  if (result.repoCommit) {
    parts.push(`commit: ${result.repoCommit}`);
  }
  if (!parts.length) {
    parts.push("VideoMemory completed successfully.");
  }
  return parts.join(" | ");
}

export { DEFAULTS };
