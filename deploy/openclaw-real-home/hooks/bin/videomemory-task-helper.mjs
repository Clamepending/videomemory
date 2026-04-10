#!/usr/bin/env node

import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const defaultBaseUrl = process.env.VIDEOMEMORY_BASE_URL || "http://videomemory:5050";
const registryPath =
  process.env.OPENCLAW_VIDEOMEMORY_REGISTRY_PATH ||
  path.join(os.homedir(), ".openclaw", "hooks", "state", "videomemory-task-actions.json");

function usage() {
  return [
    "Usage:",
    "  node videomemory-task-helper.mjs create --io-id net0 --trigger 'Watch for backpacks...' --action 'Tell one short backpack joke when a backpack is newly seen.' [--delivery telegram|session|webchat|internal] [--include-frame true|false] [--session-key agent:main:main] [--to 123456789] [--source webchat|telegram] [--sender-id 123456789] [--original-request 'When you see a backpack, tell a backpack joke.'] [--bot-id openclaw] [--base-url http://videomemory:5050]",
    "  node videomemory-task-helper.mjs update --task-id 0 --trigger 'Watch for backpacks...' [--action 'Tell one short backpack joke...'] [--delivery telegram|session|webchat|internal] [--include-frame true|false] [--session-key agent:main:main] [--to 123456789] [--source webchat|telegram] [--sender-id 123456789] [--original-request '...'] [--bot-id openclaw] [--base-url http://videomemory:5050]",
    "  node videomemory-task-helper.mjs stop --task-id 0 [--base-url http://videomemory:5050]",
    "  node videomemory-task-helper.mjs delete --task-id 0 [--base-url http://videomemory:5050]",
    "",
    "Notes:",
    "  telegram sends an external user alert through Telegram.",
    "  session routes the follow-up action into a specific OpenClaw session without external channel delivery.",
    "  webchat is an alias for session delivery and should point at the originating OpenClaw session.",
    "  internal keeps the follow-up action inside the hook flow and does not reply in the current web chat.",
    "  --include-frame true explicitly tells OpenClaw to fetch and use the saved triggering note frame.",
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
  const value = cleanText(rawValue).toLowerCase();
  if (!value || value === "auto") {
    return "";
  }
  if (value === "telegram" || value === "internal" || value === "session") {
    return value;
  }
  if (value === "webchat") {
    return "session";
  }
  throw new Error(
    `Unsupported delivery mode: ${rawValue}. Supported modes are telegram, session, webchat, or internal.`,
  );
}

function parseBooleanOption(rawValue, fallback = false) {
  const value = cleanText(rawValue).toLowerCase();
  if (!value) {
    return fallback;
  }
  if (value === "1" || value === "true" || value === "yes" || value === "on") {
    return true;
  }
  if (value === "0" || value === "false" || value === "no" || value === "off") {
    return false;
  }
  throw new Error(`Unsupported boolean value: ${rawValue}. Use true or false.`);
}

function resolveCommandSource(options, previousEntry) {
  const explicitDelivery = cleanText(options.delivery).toLowerCase();
  if (explicitDelivery === "webchat") {
    return "webchat";
  }
  if (explicitDelivery === "telegram") {
    return "telegram";
  }
  const candidates = [
    options.source,
    options["command-source"],
    previousEntry?.delivery_source,
    process.env.OPENCLAW_COMMAND_SOURCE,
    process.env.COMMAND_SOURCE,
  ];
  for (const candidate of candidates) {
    const value = cleanText(candidate).toLowerCase();
    if (value) {
      return value;
    }
  }
  return "";
}

function resolveSenderId(options, previousEntry) {
  const candidates = [
    options["sender-id"],
    previousEntry?.delivery_sender_id,
    process.env.OPENCLAW_SENDER_ID,
    process.env.SENDER_ID,
  ];
  for (const candidate of candidates) {
    const value = cleanText(candidate);
    if (value) {
      return value;
    }
  }
  return "";
}

function fallbackSessionKey() {
  return cleanText(process.env.OPENCLAW_DEFAULT_SESSION_KEY) || "agent:main:main";
}

function resolveSessionKey(options, previousEntry) {
  const candidates = [
    options["session-key"],
    previousEntry?.delivery_session_key,
    process.env.OPENCLAW_SESSION_KEY,
    process.env.SESSION_KEY,
    fallbackSessionKey(),
  ];
  for (const candidate of candidates) {
    const value = cleanText(candidate);
    if (value) {
      return value;
    }
  }
  return "";
}

function resolveTelegramTarget(options, previousEntry, source, senderId) {
  const candidates = [
    options.to,
    options["delivery-target"],
    previousEntry?.delivery_target,
    source === "telegram" ? senderId : "",
    process.env.OPENCLAW_TELEGRAM_OWNER_ID,
  ];
  for (const candidate of candidates) {
    const value = cleanText(candidate);
    if (value) {
      return value;
    }
  }
  return "";
}

function inferDeliveryMode(options, previousEntry) {
  const explicit = normalizeDelivery(options.delivery);
  if (explicit) {
    return explicit;
  }

  const previous = normalizeDelivery(previousEntry?.delivery_mode);
  if (previous) {
    return previous;
  }

  const source = resolveCommandSource(options, previousEntry);
  if (source === "telegram") {
    return "telegram";
  }
  if (
    source === "webchat" ||
    source === "ui" ||
    source === "controlui" ||
    source === "control-ui" ||
    cleanText(options["session-key"]) ||
    cleanText(process.env.OPENCLAW_SESSION_KEY)
  ) {
    return "session";
  }

  return "session";
}

function buildDeliveryConfig(options, previousEntry) {
  const source = resolveCommandSource(options, previousEntry);
  const senderId = resolveSenderId(options, previousEntry);
  const mode = inferDeliveryMode(options, previousEntry);

  if (mode === "telegram") {
    return {
      mode,
      source,
      senderId,
      target: resolveTelegramTarget(options, previousEntry, source, senderId),
      sessionKey: "",
    };
  }

  if (mode === "session") {
    return {
      mode,
      source,
      senderId,
      target: "",
      sessionKey: resolveSessionKey(options, previousEntry),
    };
  }

  return {
    mode,
    source,
    senderId,
    target: "",
    sessionKey: "",
  };
}

function validateDeliveryConfig(delivery) {
  const deliveryMode = delivery.mode;
  if (deliveryMode !== "telegram") {
    if (deliveryMode === "session" && !cleanText(delivery.sessionKey)) {
      throw new Error(
        "Session delivery requires a session key. Pass --session-key or set OPENCLAW_SESSION_KEY.",
      );
    }
    return delivery;
  }

  const botToken = cleanText(process.env.TELEGRAM_BOT_TOKEN);
  const target = cleanText(delivery.target);
  if (botToken && target) {
    return delivery;
  }

  throw new Error(
    "Telegram delivery requires TELEGRAM_BOT_TOKEN and a target chat id. Pass --to, set OPENCLAW_TELEGRAM_OWNER_ID, or provide the current Telegram sender id.",
  );
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
    const detailParts = [
      cleanText(payload?.error || payload?.message || payload?.text),
      cleanText(payload?.hint),
    ].filter(Boolean);
    const detail = detailParts.join(" ") || response.statusText;
    throw new Error(`HTTP ${response.status} from ${url}: ${detail}`);
  }
  return payload;
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

function buildOriginalRequestContext(trigger, action, explicitOriginalRequest, previousEntry) {
  const explicit = cleanText(explicitOriginalRequest);
  if (explicit) {
    return explicit;
  }

  const normalizedTrigger = cleanText(trigger);
  const normalizedAction = cleanText(action);
  if (normalizedTrigger && normalizedAction) {
    return `Trigger condition: ${normalizedTrigger}\nFollow-up action: ${normalizedAction}`;
  }

  return cleanText(previousEntry?.original_request) || normalizedTrigger;
}

function resolveIncludeFrame(options, previousEntry) {
  if (Object.prototype.hasOwnProperty.call(options, "include-frame")) {
    return parseBooleanOption(options["include-frame"], false);
  }
  return Boolean(previousEntry?.include_note_frame);
}

async function createTask(options) {
  const ioId = requireOption(options, "io-id");
  const trigger = requireOption(options, "trigger");
  const action = requireOption(options, "action");
  const botId = cleanText(options["bot-id"]) || "openclaw";
  const delivery = validateDeliveryConfig(buildDeliveryConfig(options));
  const originalRequest = cleanText(options["original-request"]);
  const baseUrl = cleanText(options["base-url"]) || defaultBaseUrl;
  const includeFrame = resolveIncludeFrame(options, null);

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
    delivery_mode: delivery.mode,
    delivery_source: delivery.source,
    delivery_sender_id: delivery.senderId,
    delivery_target: delivery.target,
    delivery_session_key: delivery.sessionKey,
    include_note_frame: includeFrame,
    original_request: buildOriginalRequestContext(trigger, action, originalRequest),
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
  const baseUrl = cleanText(options["base-url"]) || defaultBaseUrl;
  const taskId = requireOption(options, "task-id");
  const trigger = requireOption(options, "trigger");
  const action = cleanText(options.action);
  const originalRequest = cleanText(options["original-request"]);
  const botIdOverride = cleanText(options["bot-id"]);

  const taskResponse = await getTask(baseUrl, taskId);
  const task = typeof taskResponse?.task === "object" && taskResponse.task ? taskResponse.task : taskResponse;
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
  const delivery = validateDeliveryConfig(buildDeliveryConfig(options, previousEntry));
  const includeFrame = resolveIncludeFrame(options, previousEntry);
  const entry = {
    task_id: taskId,
    io_id: cleanText(task?.io_id),
    bot_id: botIdOverride || cleanText(task?.bot_id) || "openclaw",
    task_description: trigger,
    trigger_condition: trigger,
    action_instruction: action || cleanText(previousEntry?.action_instruction),
    delivery_mode: delivery.mode,
    delivery_source: delivery.source,
    delivery_sender_id: delivery.senderId,
    delivery_target: delivery.target,
    delivery_session_key: delivery.sessionKey,
    include_note_frame: includeFrame,
    original_request: buildOriginalRequestContext(trigger, action, originalRequest, previousEntry),
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
  const baseUrl = cleanText(options["base-url"]) || defaultBaseUrl;
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
  const baseUrl = cleanText(options["base-url"]) || defaultBaseUrl;
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
