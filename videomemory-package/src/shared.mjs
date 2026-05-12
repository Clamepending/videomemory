import { spawn } from "node:child_process";
import { closeSync, openSync } from "node:fs";
import { access, mkdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const DEFAULTS = {
  repoUrl: "https://github.com/Clamepending/videomemory.git",
  repoRef: "v0.1.6",
  repoDir: path.join(os.homedir(), "videomemory"),
  openclawHome: path.join(os.homedir(), ".openclaw"),
  videomemoryBase: "http://127.0.0.1:5050",
  botId: "openclaw",
  claudeRepoDir: path.join(os.homedir(), ".videomemory", "claude", "videomemory"),
  claudeChannelHost: "127.0.0.1",
  claudeChannelPort: "8791",
};

const CLAUDE_VIDEOMEMORY_ALLOWED_TOOLS = [
  "mcp__videomemory__setup_local",
  "mcp__videomemory__reply",
  "mcp__videomemory__inspect_task",
  "mcp__videomemory__inspect_device",
  "mcp__videomemory__list_devices",
  "mcp__videomemory__list_monitors",
  "mcp__videomemory__create_monitor",
  "mcp__videomemory__configure_channel_webhook",
];

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
  const { env, cwd, stdio = ["ignore", "pipe", "pipe"], timeoutMs = 0 } = options;
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: env ? { ...process.env, ...env } : process.env,
      stdio,
    });

    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let timer = null;

    if (timeoutMs > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        child.kill("SIGTERM");
      }, timeoutMs);
    }

    child.stdout?.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("error", reject);
    child.on("close", (code) => {
      if (timer) {
        clearTimeout(timer);
      }
      resolve({
        code: timedOut ? 124 : (code ?? 0),
        stdout,
        stderr: timedOut ? `${stderr}\nTimed out after ${timeoutMs}ms` : stderr,
      });
    });
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function startDetachedProcess(command, args, options = {}) {
  const { cwd, env, logPath } = options;
  if (logPath) {
    await mkdir(path.dirname(logPath), { recursive: true });
  }
  const outFd = logPath ? openSync(logPath, "a") : "ignore";
  const errFd = logPath ? openSync(logPath, "a") : "ignore";
  try {
    const child = spawn(command, args, {
      cwd,
      env: env ? { ...process.env, ...env } : process.env,
      detached: true,
      stdio: ["ignore", outFd, errFd],
    });
    child.unref();
    return { pid: child.pid || 0 };
  } finally {
    if (typeof outFd === "number") closeSync(outFd);
    if (typeof errFd === "number" && errFd !== outFd) closeSync(errFd);
  }
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

async function pathExists(targetPath) {
  try {
    await access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function commandCheck(command, args = ["--version"], timeoutMs = 5000) {
  try {
    const result = await runProcess(command, args, { timeoutMs });
    return {
      ok: result.code === 0,
      command,
      output: cleanText(result.stdout || result.stderr),
      error: result.code === 0 ? "" : summarizeFailure(result.stderr, result.stdout),
    };
  } catch (error) {
    return {
      ok: false,
      command,
      output: "",
      error: cleanText(error?.message) || String(error),
    };
  }
}

function claudeRepoDir(options = {}) {
  return cleanText(options.repoDir) || cleanText(options.claudeRepoDir) || DEFAULTS.claudeRepoDir;
}

function claudeChannelDir(options = {}) {
  return cleanText(options.channelDir) || path.join(claudeRepoDir(options), "claude-videomemory-channel");
}

function claudeChannelHost(options = {}) {
  return cleanText(options.claudeChannelHost) || DEFAULTS.claudeChannelHost;
}

function claudeChannelPort(options = {}) {
  return cleanText(options.claudeChannelPort) || DEFAULTS.claudeChannelPort;
}

function claudeChannelUrl(options = {}) {
  return `http://${claudeChannelHost(options)}:${claudeChannelPort(options)}/videomemory-event`;
}

function claudeMcpConfigPath(options = {}) {
  return path.join(claudeChannelDir(options), ".mcp.json");
}

async function requestJson(url, init = {}) {
  const response = await fetch(url, init);
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { text };
    }
  }
  if (!response.ok) {
    const detail = cleanText(payload.error || payload.message || payload.text) || response.statusText;
    throw new Error(`HTTP ${response.status} from ${url}: ${detail}`);
  }
  return payload;
}

async function maybeRequestJson(url, init = {}) {
  try {
    return { ok: true, payload: await requestJson(url, init) };
  } catch (error) {
    return { ok: false, error: cleanText(error?.message) || String(error) };
  }
}

async function waitForVideoMemory(baseUrl, timeoutMs = 20000) {
  const startedAt = Date.now();
  let lastError = "";
  while (Date.now() - startedAt < timeoutMs) {
    const health = await maybeRequestJson(`${baseUrl}/api/health`);
    if (health.ok) {
      return { ok: true, payload: health.payload };
    }
    lastError = health.error;
    await sleep(500);
  }
  return { ok: false, error: lastError || `Timed out waiting for ${baseUrl}/api/health` };
}

async function putVideomemorySetting(baseUrl, key, value) {
  return await requestJson(`${baseUrl}/api/settings/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
}

async function ensureClaudeRepo(options = {}) {
  const repoDir = claudeRepoDir(options);
  const channelDir = claudeChannelDir(options);
  const packagePath = path.join(channelDir, "package.json");
  if (await pathExists(packagePath)) {
    return { repoDir, channelDir, cloned: false, reused: true };
  }
  if (await pathExists(repoDir)) {
    throw new Error(
      `Claude repo dir exists but is missing ${path.relative(repoDir, packagePath)}: ${repoDir}`,
    );
  }

  const clone = await runProcess(
    "git",
    [
      "clone",
      "--depth",
      "1",
      "--branch",
      cleanText(options.repoRef) || DEFAULTS.repoRef,
      cleanText(options.repoUrl) || DEFAULTS.repoUrl,
      repoDir,
    ],
    { timeoutMs: 120000 },
  );
  if (clone.code !== 0) {
    throw new Error(`VideoMemory clone failed:\n${summarizeFailure(clone.stderr, clone.stdout)}`);
  }
  if (!(await pathExists(packagePath))) {
    throw new Error(`Clone completed but Claude channel package is missing: ${packagePath}`);
  }
  return { repoDir, channelDir, cloned: true, reused: false };
}

async function chooseVideoMemoryServerCommand(repoDir) {
  const venvPython = path.join(repoDir, ".venv", "bin", "python");
  if (await pathExists(venvPython)) {
    return { command: venvPython, args: ["flask_app/app.py"], label: ".venv/bin/python flask_app/app.py" };
  }
  const uv = await commandCheck("uv", ["--version"], 5000);
  if (uv.ok) {
    return { command: "uv", args: ["run", "flask_app/app.py"], label: "uv run flask_app/app.py" };
  }
  return { command: "python3", args: ["flask_app/app.py"], label: "python3 flask_app/app.py" };
}

async function ensureVideoMemoryServer(options = {}) {
  const baseUrl = cleanText(options.videomemoryBase) || DEFAULTS.videomemoryBase;
  const existing = await maybeRequestJson(`${baseUrl}/api/health`);
  if (existing.ok) {
    return { started: false, ready: true, baseUrl, health: existing.payload };
  }
  if (truthyFlag(options.skipStart)) {
    return { started: false, ready: false, baseUrl, error: existing.error };
  }

  const repoDir = claudeRepoDir(options);
  if (!(await pathExists(path.join(repoDir, "flask_app", "app.py")))) {
    return {
      started: false,
      ready: false,
      baseUrl,
      error: `Cannot start VideoMemory because flask_app/app.py is missing under ${repoDir}`,
    };
  }

  const serverCommand = await chooseVideoMemoryServerCommand(repoDir);
  const logPath = path.join(os.homedir(), ".videomemory", "claude", "videomemory-server.log");
  const started = await startDetachedProcess(serverCommand.command, serverCommand.args, {
    cwd: repoDir,
    logPath,
  });
  const ready = await waitForVideoMemory(baseUrl, 30000);
  return {
    started: true,
    ready: ready.ok,
    baseUrl,
    command: serverCommand.label,
    pid: started.pid,
    logPath,
    ...(ready.ok ? { health: ready.payload } : { error: ready.error }),
  };
}

async function configureClaudeWebhook(options = {}) {
  const baseUrl = cleanText(options.videomemoryBase) || DEFAULTS.videomemoryBase;
  const webhookUrl = claudeChannelUrl(options);
  await putVideomemorySetting(baseUrl, "VIDEOMEMORY_OPENCLAW_WEBHOOK_URL", webhookUrl);
  await putVideomemorySetting(baseUrl, "VIDEOMEMORY_SELF_BASE_URL", baseUrl);
  if (cleanText(options.webhookToken)) {
    await putVideomemorySetting(baseUrl, "VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN", cleanText(options.webhookToken));
  } else if (!truthyFlag(options.keepWebhookToken)) {
    await putVideomemorySetting(baseUrl, "VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN", "");
  }
  return {
    configured: true,
    videomemoryBase: baseUrl,
    webhookUrl,
    tokenConfigured: Boolean(cleanText(options.webhookToken)),
  };
}

export async function installClaudeCode(options = {}) {
  const repo = await ensureClaudeRepo(options);
  const install = await runProcess("npm", ["install"], {
    cwd: repo.channelDir,
    timeoutMs: 120000,
  });
  if (install.code !== 0) {
    throw new Error(`Claude channel npm install failed:\n${summarizeFailure(install.stderr, install.stdout)}`);
  }

  const check = await runProcess("npm", ["run", "check"], {
    cwd: repo.channelDir,
    timeoutMs: 30000,
  });
  if (check.code !== 0) {
    throw new Error(`Claude channel check failed:\n${summarizeFailure(check.stderr, check.stdout)}`);
  }

  let webhook = { configured: false, error: "Skipped." };
  if (!truthyFlag(options.skipWebhook)) {
    const health = await maybeRequestJson(`${cleanText(options.videomemoryBase) || DEFAULTS.videomemoryBase}/api/health`);
    if (health.ok) {
      try {
        webhook = await configureClaudeWebhook(options);
      } catch (error) {
        webhook = { configured: false, error: cleanText(error?.message) || String(error) };
      }
    } else {
      webhook = { configured: false, error: health.error };
    }
  }

  return {
    success: true,
    repoDir: repo.repoDir,
    channelDir: repo.channelDir,
    cloned: repo.cloned,
    reused: repo.reused,
    mcpConfig: claudeMcpConfigPath(options),
    webhookUrl: claudeChannelUrl(options),
    webhook,
  };
}

export async function doctorClaudeCode(options = {}) {
  const baseUrl = cleanText(options.videomemoryBase) || DEFAULTS.videomemoryBase;
  const channelDir = claudeChannelDir(options);
  const webhookUrl = claudeChannelUrl(options);
  const checks = [];

  const add = (name, ok, detail = "") => {
    checks.push({ name, ok: Boolean(ok), detail: cleanText(detail) });
  };

  for (const command of ["node", "npm", "git", "claude"]) {
    const result = await commandCheck(command);
    add(command, result.ok, result.output || result.error);
  }

  add("channel package", await pathExists(path.join(channelDir, "package.json")), channelDir);
  if (await pathExists(path.join(channelDir, "package.json"))) {
    const check = await runProcess("npm", ["run", "check"], { cwd: channelDir, timeoutMs: 30000 });
    add("channel syntax", check.code === 0, check.code === 0 ? "ok" : summarizeFailure(check.stderr, check.stdout));
  }

  const health = await maybeRequestJson(`${baseUrl}/api/health`);
  add("VideoMemory health", health.ok, health.ok ? `${baseUrl}/api/health` : health.error);

  const devices = await maybeRequestJson(`${baseUrl}/api/devices`);
  const deviceGroups = devices.ok && typeof devices.payload?.devices === "object" ? devices.payload.devices : {};
  const deviceCount = Object.values(deviceGroups).reduce(
    (count, group) => count + (Array.isArray(group) ? group.length : 0),
    0,
  );
  add("VideoMemory devices", devices.ok && deviceCount > 0, devices.ok ? `${deviceCount} device(s)` : devices.error);

  const settings = await maybeRequestJson(`${baseUrl}/api/settings`);
  const savedWebhook = cleanText(settings.payload?.settings?.VIDEOMEMORY_OPENCLAW_WEBHOOK_URL?.value);
  add(
    "VideoMemory webhook",
    settings.ok && savedWebhook === webhookUrl,
    settings.ok ? (savedWebhook || "not set") : settings.error,
  );

  const channelHealth = await maybeRequestJson(
    `http://${claudeChannelHost(options)}:${claudeChannelPort(options)}/health`,
  );
  add("Claude channel server", channelHealth.ok, channelHealth.ok ? "running" : channelHealth.error);

  if (!truthyFlag(options.skipAuth)) {
    const auth = await runProcess("claude", ["-p", "Respond with exactly ok"], { timeoutMs: 30000 });
    add("Claude auth", auth.code === 0, auth.code === 0 ? cleanText(auth.stdout) : summarizeFailure(auth.stderr, auth.stdout));
  }

  return {
    success: checks.every((check) => check.ok),
    videomemoryBase: baseUrl,
    channelDir,
    webhookUrl,
    checks,
  };
}

export async function launchClaudeCode(options = {}) {
  const channelDir = claudeChannelDir(options);
  const mcpConfig = claudeMcpConfigPath(options);
  if (!(await pathExists(mcpConfig))) {
    throw new Error(`Missing Claude MCP config: ${mcpConfig}. Run "videomemory claude install" first.`);
  }
  const env = {
    CLAUDE_PLUGIN_ROOT: channelDir,
    VIDEOMEMORY_BASE_URL: cleanText(options.videomemoryBase) || DEFAULTS.videomemoryBase,
    VIDEOMEMORY_CLAUDE_CHANNEL_HOST: claudeChannelHost(options),
    VIDEOMEMORY_CLAUDE_CHANNEL_PORT: claudeChannelPort(options),
  };
  if (cleanText(options.webhookToken)) {
    env.VIDEOMEMORY_CLAUDE_CHANNEL_TOKEN = cleanText(options.webhookToken);
  }
  const channelArgs = truthyFlag(options.devChannel)
    ? ["--dangerously-load-development-channels", "server:videomemory"]
    : ["--channels", "server:videomemory"];
  const toolArgs = truthyFlag(options.noToolAllowlist)
    ? []
    : ["--allowedTools", CLAUDE_VIDEOMEMORY_ALLOWED_TOOLS.join(",")];
  return await runProcess(
    "claude",
    [
      "--mcp-config",
      mcpConfig,
      ...channelArgs,
      ...toolArgs,
    ],
    {
      env,
      cwd: claudeRepoDir(options),
      stdio: "inherit",
    },
  );
}

async function checkClaudeAuth() {
  const auth = await runProcess("claude", ["-p", "Respond with exactly ok"], { timeoutMs: 30000 });
  return {
    ok: auth.code === 0,
    detail: auth.code === 0 ? cleanText(auth.stdout) : summarizeFailure(auth.stderr, auth.stdout),
  };
}

async function openBrowserCameraBridge(options = {}) {
  const baseUrl = cleanText(options.videomemoryBase) || DEFAULTS.videomemoryBase;
  const url = `${baseUrl.replace(/\/+$/, "")}/browser-camera/facetime`;
  if (process.platform !== "darwin") {
    return { opened: false, url, reason: "automatic browser opening is only implemented on macOS" };
  }
  const result = await runProcess("open", [url], { timeoutMs: 5000 });
  return {
    opened: result.code === 0,
    url,
    ...(result.code === 0 ? {} : { error: summarizeFailure(result.stderr, result.stdout) }),
  };
}

export async function upClaudeCode(options = {}) {
  const repo = await ensureClaudeRepo(options);
  const effectiveOptions = {
    ...options,
    repoDir: repo.repoDir,
  };
  const server = await ensureVideoMemoryServer(effectiveOptions);
  if (!server.ready) {
    return {
      success: false,
      stage: "videomemory-server",
      repoDir: repo.repoDir,
      channelDir: repo.channelDir,
      server,
      next: server.error || "Start VideoMemory, then rerun the VideoMemory Claude setup command.",
    };
  }

  const install = await installClaudeCode(effectiveOptions);

  let auth = { ok: true, detail: "skipped" };
  if (!truthyFlag(options.skipAuth)) {
    auth = await checkClaudeAuth();
    if (!auth.ok) {
      return {
        success: false,
        stage: "claude-auth",
        repoDir: repo.repoDir,
        channelDir: repo.channelDir,
        server,
        install,
        camera: { opened: false, skipped: true, reason: "Claude auth failed before camera setup." },
        auth,
        next: "Run `claude auth login`, then rerun the VideoMemory Claude setup command.",
      };
    }
  }

  const camera = truthyFlag(options.noOpenCamera)
    ? { opened: false, skipped: true }
    : await openBrowserCameraBridge(effectiveOptions);

  const ready = {
    success: true,
    repoDir: repo.repoDir,
    channelDir: repo.channelDir,
    server,
    install,
    camera,
    auth,
    launch: {
      skipped: truthyFlag(options.noLaunch),
      command: "claude with VideoMemory channel and MCP tools",
    },
  };
  if (truthyFlag(options.noLaunch)) {
    return ready;
  }

  const launch = await launchClaudeCode(effectiveOptions);
  return {
    ...ready,
    launch: {
      skipped: false,
      exitCode: launch.code,
      success: launch.code === 0,
    },
  };
}

export async function testClaudeCodeEvent(options = {}) {
  const webhookUrl = claudeChannelUrl(options);
  const now = new Date();
  const eventId = cleanText(options.eventId) || `vm-claude-test-${Date.now()}`;
  const payload = {
    service: "videomemory",
    event_type: "task_update",
    event_id: eventId,
    bot_id: "claude",
    io_id: cleanText(options.ioId) || "0",
    task_id: cleanText(options.taskId) || "manual",
    task_description:
      cleanText(options.taskDescription) || "Watch for a phone visibly held up in the user hand.",
    note: cleanText(options.note) || "Synthetic VideoMemory event for Claude channel testing.",
    action_instruction:
      cleanText(options.actionInstruction) ||
      "Reply through the VideoMemory channel test surface with exactly: VideoMemory channel test received.",
    observed_at: now.toISOString(),
  };
  let response;
  try {
    response = await fetch(webhookUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(cleanText(options.webhookToken) ? { Authorization: `Bearer ${cleanText(options.webhookToken)}` } : {}),
      },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    return {
      success: false,
      webhookUrl,
      responseStatus: 0,
      response: { error: cleanText(error?.message) || String(error) },
      payload,
    };
  }
  const text = await response.text();
  let body = text;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    // Keep raw response text.
  }
  return {
    success: response.ok,
    webhookUrl,
    responseStatus: response.status,
    response: body,
    payload,
  };
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
