#!/usr/bin/env node

import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const candidateBaseUrls = [
  process.env.VIDEOMEMORY_BASE_URL,
  process.env.VIDEOMEMORY_BASE,
  "http://videomemory:5050",
  "http://host.docker.internal:5050",
  "http://127.0.0.1:5050",
  "http://localhost:5050",
].filter(Boolean);
const registryPath =
  process.env.OPENCLAW_VIDEOMEMORY_REGISTRY_PATH ||
  path.join(os.homedir(), ".openclaw", "hooks", "state", "videomemory-task-actions.json");

function usage() {
  return [
    "Usage:",
    "  node openclaw-videomemory-task-helper.mjs create --io-id net0 --trigger 'Watch for backpacks...' --action 'Tell one short backpack joke when a backpack is newly seen.' [--delivery telegram|internal] [--original-request 'When you see a backpack, tell a backpack joke.'] [--bot-id openclaw] [--base-url http://videomemory:5050]",
    "  node openclaw-videomemory-task-helper.mjs update --task-id 0 --trigger 'Watch for backpacks...' [--action 'Tell one short backpack joke...'] [--delivery telegram|internal] [--original-request '...'] [--bot-id openclaw] [--base-url http://videomemory:5050]",
    "  node openclaw-videomemory-task-helper.mjs stop --task-id 0 [--base-url http://videomemory:5050]",
    "  node openclaw-videomemory-task-helper.mjs delete --task-id 0 [--base-url http://videomemory:5050]",
  ].join("\n");
}

function parseArgs(argv) {
  const [command, ...rest] = argv;
  const options = {};
  for (let i = 0; i < rest.length; i += 1) {
    const token = rest[i];
    if (!token.startsWith("--")) {
      throw new Error(`Unexpected argument: ${token}`);
    }
    const key = token.slice(2);
    const value = rest[i + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for --${key}`);
    }
    options[key] = value;
    i += 1;
  }
  return { command: command || "", options };
}

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function requireOption(options, key) {
  const value = cleanText(options[key]);
  if (!value) {
    throw new Error(`Missing required option --${key}`);
  }
  return value;
}

function normalizeDelivery(rawValue) {
  const value = cleanText(rawValue || "telegram").toLowerCase();
  if (value === "telegram" || value === "internal") {
    return value;
  }
  throw new Error(`Unsupported delivery mode: ${rawValue}`);
}

function makeRegistryKey(botId, ioId, taskId) {
  return [cleanText(botId), cleanText(ioId), cleanText(taskId)].join("|");
}

async function loadRegistry() {
  try {
    const raw = await fs.readFile(registryPath, "utf8");
    const parsed = JSON.parse(raw);
    if (typeof parsed === "object" && parsed) {
      return parsed;
    }
  } catch {
    // Ignore missing or invalid registry files and rebuild.
  }
  return { version: 1, tasks: {} };
}

async function saveRegistry(registry) {
  await fs.mkdir(path.dirname(registryPath), { recursive: true });
  await fs.writeFile(registryPath, `${JSON.stringify(registry, null, 2)}\n`, "utf8");
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
    const detail = cleanText(payload?.error || payload?.message || payload?.text) || response.statusText;
    throw new Error(`HTTP ${response.status} from ${url}: ${detail}`);
  }
  return payload;
}

async function resolveBaseUrl(explicitBaseUrl) {
  const direct = cleanText(explicitBaseUrl);
  if (direct) {
    return direct;
  }

  for (const candidate of candidateBaseUrls) {
    try {
      await requestJson(`${candidate}/api/health`);
      return candidate;
    } catch {
      // Try the next candidate.
    }
  }

  return "http://videomemory:5050";
}

async function getTask(baseUrl, taskId) {
  return requestJson(`${baseUrl}/api/task/${encodeURIComponent(taskId)}`);
}

function upsertEntry(registry, entry) {
  if (typeof registry.tasks !== "object" || !registry.tasks) {
    registry.tasks = {};
  }
  const key = makeRegistryKey(entry.bot_id, entry.io_id, entry.task_id);
  registry.tasks[key] = entry;
  return key;
}

function removeEntry(registry, taskId) {
  if (typeof registry.tasks !== "object" || !registry.tasks) {
    registry.tasks = {};
    return null;
  }
  const targetTaskId = cleanText(taskId);
  for (const [key, entry] of Object.entries(registry.tasks)) {
    if (cleanText(entry?.task_id) === targetTaskId) {
      delete registry.tasks[key];
      return key;
    }
  }
  return null;
}

async function createTask(options) {
  const baseUrl = await resolveBaseUrl(options["base-url"]);
  const ioId = requireOption(options, "io-id");
  const trigger = requireOption(options, "trigger");
  const action = requireOption(options, "action");
  const botId = cleanText(options["bot-id"]) || "openclaw";
  const deliveryMode = normalizeDelivery(options.delivery);
  const originalRequest = cleanText(options["original-request"]);

  const created = await requestJson(`${baseUrl}/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      io_id: ioId,
      task_description: trigger,
      bot_id: botId,
    }),
  });

  const registry = await loadRegistry();
  const now = new Date().toISOString();
  const entry = {
    task_id: cleanText(created.task_id),
    io_id: ioId,
    bot_id: botId,
    task_description: trigger,
    trigger_condition: trigger,
    action_instruction: action,
    delivery_mode: deliveryMode,
    original_request: originalRequest || trigger,
    created_at: now,
    updated_at: now,
  };
  const registryKey = upsertEntry(registry, entry);
  await saveRegistry(registry);

  process.stdout.write(
    `${JSON.stringify({ status: "success", task: created, registry_key: registryKey, registry_entry: entry }, null, 2)}\n`,
  );
}

async function updateTask(options) {
  const baseUrl = await resolveBaseUrl(options["base-url"]);
  const taskId = requireOption(options, "task-id");
  const trigger = requireOption(options, "trigger");
  const action = cleanText(options.action);
  const deliveryOption = cleanText(options.delivery);
  const originalRequest = cleanText(options["original-request"]);
  const botIdOverride = cleanText(options["bot-id"]);

  const task = await getTask(baseUrl, taskId);
  const updated = await requestJson(`${baseUrl}/api/task/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_description: trigger }),
  });

  const registry = await loadRegistry();
  const previousEntry = Object.values(registry.tasks || {}).find(
    (entry) => cleanText(entry?.task_id) === cleanText(taskId),
  );
  removeEntry(registry, taskId);

  const now = new Date().toISOString();
  const entry = {
    task_id: taskId,
    io_id: cleanText(task?.io_id),
    bot_id: botIdOverride || cleanText(task?.bot_id) || "openclaw",
    task_description: trigger,
    trigger_condition: trigger,
    action_instruction: action || cleanText(previousEntry?.action_instruction),
    delivery_mode: deliveryOption
      ? normalizeDelivery(deliveryOption)
      : normalizeDelivery(previousEntry?.delivery_mode || "telegram"),
    original_request: originalRequest || cleanText(previousEntry?.original_request) || trigger,
    created_at: cleanText(previousEntry?.created_at) || now,
    updated_at: now,
  };

  if (entry.action_instruction) {
    const registryKey = upsertEntry(registry, entry);
    await saveRegistry(registry);
    process.stdout.write(
      `${JSON.stringify({ status: "success", task: updated, registry_key: registryKey, registry_entry: entry }, null, 2)}\n`,
    );
    return;
  }

  await saveRegistry(registry);
  process.stdout.write(`${JSON.stringify({ status: "success", task: updated, registry_removed: true }, null, 2)}\n`);
}

async function stopTask(options) {
  const baseUrl = await resolveBaseUrl(options["base-url"]);
  const taskId = requireOption(options, "task-id");
  const stopped = await requestJson(`${baseUrl}/api/task/${encodeURIComponent(taskId)}/stop`, {
    method: "POST",
  });
  const registry = await loadRegistry();
  const removedKey = removeEntry(registry, taskId);
  await saveRegistry(registry);
  process.stdout.write(
    `${JSON.stringify({ status: "success", task: stopped, registry_removed: Boolean(removedKey) }, null, 2)}\n`,
  );
}

async function deleteTask(options) {
  const baseUrl = await resolveBaseUrl(options["base-url"]);
  const taskId = requireOption(options, "task-id");
  const removed = await requestJson(`${baseUrl}/api/task/${encodeURIComponent(taskId)}`, {
    method: "DELETE",
  });
  const registry = await loadRegistry();
  const removedKey = removeEntry(registry, taskId);
  await saveRegistry(registry);
  process.stdout.write(
    `${JSON.stringify({ status: "success", task: removed, registry_removed: Boolean(removedKey) }, null, 2)}\n`,
  );
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  if (!command) {
    throw new Error(usage());
  }
  if (command === "create") {
    await createTask(options);
    return;
  }
  if (command === "update") {
    await updateTask(options);
    return;
  }
  if (command === "stop") {
    await stopTask(options);
    return;
  }
  if (command === "delete") {
    await deleteTask(options);
    return;
  }
  throw new Error(`Unknown command: ${command}\n\n${usage()}`);
}

main().catch((error) => {
  const message = cleanText(error?.message) || String(error);
  process.stderr.write(`${JSON.stringify({ status: "error", error: message }, null, 2)}\n`);
  process.exitCode = 1;
});
