import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const DEFAULT_BASE_URL = "http://127.0.0.1:5050";

export function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

export function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      throw new Error(`Unexpected argument: ${token}`);
    }
    const key = token.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      options[key] = "true";
      continue;
    }
    options[key] = next;
    index += 1;
  }
  return options;
}

export function truthy(value) {
  const text = cleanText(String(value ?? "")).toLowerCase();
  return text === "1" || text === "true" || text === "yes" || text === "on";
}

export function getBaseUrl(options = {}) {
  return (
    cleanText(options["base-url"]) ||
    cleanText(process.env.VIDEOMEMORY_BASE_URL) ||
    DEFAULT_BASE_URL
  ).replace(/\/+$/, "");
}

export async function requestJson(url, init = {}) {
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

export async function maybeRequestJson(url, init = {}) {
  try {
    return { ok: true, payload: await requestJson(url, init) };
  } catch (error) {
    return { ok: false, error: cleanText(error?.message) || String(error) };
  }
}

export async function readJsonFile(filePath, fallback = {}) {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export async function writeJsonFile(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export function openClawConfigPath(options = {}) {
  return (
    cleanText(options["openclaw-config"]) ||
    cleanText(process.env.OPENCLAW_CONFIG_PATH) ||
    path.join(os.homedir(), ".openclaw", "openclaw.json")
  );
}

export function openClawRegistryPath(options = {}) {
  return (
    cleanText(options["registry-path"]) ||
    cleanText(process.env.OPENCLAW_VIDEOMEMORY_REGISTRY_PATH) ||
    path.join(os.homedir(), ".openclaw", "hooks", "state", "videomemory-task-actions.json")
  );
}

export function settingValue(settings, key) {
  const info = settings?.[key];
  if (!info || typeof info !== "object") {
    return "";
  }
  return cleanText(info.value);
}

async function videoMemoryWebhookSettings(options = {}) {
  const baseUrl = getBaseUrl(options);
  const result = await maybeRequestJson(`${baseUrl}/api/settings`);
  if (!result.ok) {
    return {};
  }
  const settings = result.payload?.settings || {};
  return {
    url: settingValue(settings, "VIDEOMEMORY_OPENCLAW_WEBHOOK_URL"),
    token: settingValue(settings, "VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN"),
  };
}

function usableToken(value) {
  const token = cleanText(value);
  return token && !token.includes("*") ? token : "";
}

export async function inferOpenClawWebhook(options = {}) {
  const configured = await videoMemoryWebhookSettings(options);
  const configPath = openClawConfigPath(options);
  const config = await readJsonFile(configPath, {});
  const gatewayPort = Number(config?.gateway?.port || 18789);
  const hookRoot = cleanText(config?.hooks?.path || "/hooks").replace(/^\/?/, "/").replace(/\/+$/, "");
  const mappingPath = cleanText(options["mapping-path"]) || "videomemory-alert";
  const explicitUrl = cleanText(options["webhook-url"]);
  const configuredUrl = cleanText(configured.url);
  const fallbackUrl = `http://127.0.0.1:${gatewayPort}${hookRoot}/${encodeURIComponent(mappingPath)}`;
  const url = explicitUrl || configuredUrl || fallbackUrl;
  const token =
    cleanText(options["webhook-token"]) ||
    usableToken(configured.token) ||
    (!explicitUrl && !configuredUrl ? cleanText(config?.hooks?.token) : "");
  return { url, token, configPath, mappingPath };
}

export function summarizeTask(taskPayload) {
  const task = taskPayload?.task && typeof taskPayload.task === "object" ? taskPayload.task : taskPayload;
  const notes = Array.isArray(task?.task_note)
    ? task.task_note
    : Array.isArray(task?.notes)
      ? task.notes
      : [];
  const latest = notes.length ? notes[notes.length - 1] : null;
  return {
    task_id: cleanText(task?.task_id ?? task?.id),
    io_id: cleanText(task?.io_id),
    bot_id: cleanText(task?.bot_id),
    status: cleanText(task?.status),
    done: Boolean(task?.done),
    task_description: cleanText(task?.task_desc ?? task?.task_description),
    notes_count: notes.length,
    latest_note: latest,
  };
}
