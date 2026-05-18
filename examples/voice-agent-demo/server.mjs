#!/usr/bin/env node

import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BOT_ID,
  buildFakeCameraFrame,
  buildTaskPlan,
  buildVideoMemoryTaskPayload,
  buildWakeupMessage,
  cleanText,
  fakeCameraPreviewSvg,
  inferConversationContext,
  isSetupCommand,
  normalizeEventId,
  parseLedgerEntry,
  parseVisualMemoryObservation,
  summarizeLedger,
  summarizeVisualMemory,
  visualMemoryTriggerCondition,
} from "./lib.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = join(__dirname, "public");
const DEFAULT_PORT = 8899;
const DEFAULT_STATE_DIR = resolve(__dirname, "..", "..", "data", "voice-agent-demo");
const DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1";

const REALTIME_TOOLS = [
  {
    type: "function",
    name: "set_videomemory_monitor",
    description: "Create a VideoMemory visual wakeup monitor on the live browser camera. Use this when the user asks you to watch, monitor, wake up, or act later based on what the camera sees.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        instruction: {
          type: "string",
          description: "The user's full visual monitoring instruction, including the condition and what the assistant should do when VideoMemory wakes it.",
        },
        lifecycle: {
          type: "string",
          enum: ["auto", "one_shot", "persistent"],
          description: "Use one_shot for a monitor that should fire once. Use persistent for monitors that should keep running until stopped by re-arming after each trigger. Use auto when the user's wording is enough, e.g. 'when' is usually one_shot and 'whenever/every time/each time' is persistent.",
        },
      },
      required: ["instruction"],
    },
  },
  {
    type: "function",
    name: "record_ledger_entry",
    description: "Record an apple-shopkeeper ledger entry after a VideoMemory wakeup when the customer gives their name and apple count.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        name: { type: "string", description: "Customer name." },
        apple_count: { type: "integer", minimum: 1, description: "Number of apples taken." },
      },
      required: ["name", "apple_count"],
    },
  },
  {
    type: "function",
    name: "answer_ledger",
    description: "Read the current shopkeeper ledger summary.",
    parameters: { type: "object", additionalProperties: false, properties: {} },
  },
  {
    type: "function",
    name: "answer_visual_memory",
    description: "Read the current summary for the active repeated visual-memory monitor, including totals or logged observations.",
    parameters: { type: "object", additionalProperties: false, properties: {} },
  },
  {
    type: "function",
    name: "get_videomemory_status",
    description: "Check whether VideoMemory is reachable and what monitor, if any, is armed.",
    parameters: { type: "object", additionalProperties: false, properties: {} },
  },
  {
    type: "function",
    name: "reset_demo",
    description: "Clear the demo ledger, wakeup history, and remembered monitors.",
    parameters: { type: "object", additionalProperties: false, properties: {} },
  },
];

const REALTIME_INSTRUCTIONS = `You are the VideoMemory live voice agent.

You hear the user through the microphone, speak back with audio, and receive camera snapshots as conversation context. Treat the snapshots as the current video view, but do not claim you have continuous native video; VideoMemory is the long-running visual monitor.

Default behavior:
- Stay conversational and concise.
- Do not arm any visual monitor unless the user asks you to watch, monitor, wake up, notify, or remember to act based on video.
- When the user asks to set a visual condition, call set_videomemory_monitor with the complete instruction. After the tool returns, tell the user whether the monitor is armed.
- For the apple shopkeeper demo, arm a monitor when asked to be a shopkeeper or watch apples. When VideoMemory later wakes you, ask the customer for their name and how many apples they took, then call record_ledger_entry once both are known.
- If the user asks about the ledger, call answer_ledger.
- When calling set_videomemory_monitor, set lifecycle to one_shot for "when/remind me once" tasks and persistent for "whenever/every time/each time/until stopped" tasks. Use auto only if the wording is unambiguous.
- For repeated stateful visual tasks such as "each time X happens, count/add/record/keep track", call set_videomemory_monitor with lifecycle persistent. The local tool will create a repeatable visual-memory monitor, extract observations on wakeup, update state silently, and re-arm. When the user asks for the total, log, or state so far, call answer_visual_memory.
- If the conversation receives an "External VideoMemory wakeup event received" message, treat it as authoritative. The monitor has already fired; speak the event message instead of saying you have not seen the condition or that you are merely armed.
- If the user asks what you can see, answer from the latest camera snapshot already in the conversation.`;

function jsonResponse(res, statusCode, body, headers = {}) {
  const payload = JSON.stringify(body, null, 2);
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    ...headers,
  });
  res.end(payload);
}

function textResponse(res, statusCode, body, contentType = "text/plain; charset=utf-8") {
  res.writeHead(statusCode, {
    "Content-Type": contentType,
    "Cache-Control": "no-store",
  });
  res.end(body);
}

async function readJsonBody(req, maxBytes = 512 * 1024) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > maxBytes) {
      throw new Error("Request body is too large.");
    }
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error("Request body must be valid JSON.");
  }
}

async function readRawBody(req, maxBytes = 2 * 1024 * 1024) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > maxBytes) {
      throw new Error("Request body is too large.");
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let body = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { raw: text };
  }
  if (!response.ok) {
    const message = cleanText(body.error || body.message || body.raw) || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function loadState(statePath) {
  try {
    return JSON.parse(await readFile(statePath, "utf8"));
  } catch {
    return {
      registry: {},
      ledger: [],
      events: [],
      ignored_events: [],
      seen_event_ids: [],
      pending_sale: null,
      fake_camera: { scene: "apple_counter" },
      agent_context: {},
      visual_memory: null,
      tool_calls: [],
    };
  }
}

async function saveState(statePath, state) {
  await mkdir(dirname(statePath), { recursive: true });
  await writeFile(statePath, `${JSON.stringify(state, null, 2)}\n`);
}

function publicBaseFromRequest(req, configuredBaseUrl) {
  if (configuredBaseUrl) return configuredBaseUrl.replace(/\/+$/, "");
  const host = req.headers.host || `127.0.0.1:${DEFAULT_PORT}`;
  return `http://${host}`;
}

function getTaskId(taskResponse) {
  return cleanText(taskResponse?.task_id || taskResponse?.task?.task_id || taskResponse?.task?.id || taskResponse?.id);
}

function contentTypeFor(pathname) {
  const ext = extname(pathname);
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".svg") return "image/svg+xml";
  return "application/octet-stream";
}

const NOTE_TOKEN_STOPWORDS = new Set([
  "about",
  "after",
  "again",
  "agent",
  "also",
  "ambigu",
  "ambiguous",
  "and",
  "any",
  "are",
  "ask",
  "camera",
  "clear",
  "clearly",
  "complete",
  "condition",
  "detected",
  "does",
  "done",
  "event",
  "frame",
  "frames",
  "happen",
  "happens",
  "has",
  "have",
  "image",
  "into",
  "keep",
  "mark",
  "monitor",
  "note",
  "not",
  "notify",
  "observation",
  "partially",
  "please",
  "requested",
  "satisfied",
  "seen",
  "set",
  "task",
  "tell",
  "that",
  "the",
  "then",
  "this",
  "trigger",
  "true",
  "unclear",
  "unchanged",
  "user",
  "view",
  "visible",
  "visual",
  "wake",
  "when",
  "with",
]);

const WEAK_TRIGGER_TOKENS = new Set([
  "black",
  "blue",
  "brown",
  "gray",
  "green",
  "grey",
  "orange",
  "pink",
  "purple",
  "red",
  "white",
  "yellow",
  "left",
  "right",
  "front",
  "back",
  "near",
  "next",
]);

function singularToken(token) {
  const text = cleanText(token).toLowerCase();
  if (text.length > 4 && text.endsWith("ies")) return `${text.slice(0, -3)}y`;
  if (text.length > 3 && text.endsWith("es")) return text.slice(0, -2);
  if (text.length > 3 && text.endsWith("s")) return text.slice(0, -1);
  return text;
}

function contentTokens(text) {
  const tokens = new Set();
  for (const raw of cleanText(text).toLowerCase().match(/[a-z0-9]+/g) || []) {
    const token = singularToken(raw);
    if (token.length < 3 || NOTE_TOKEN_STOPWORDS.has(token)) continue;
    tokens.add(token);
  }
  return tokens;
}

function tokenOverlap(a, b) {
  const overlap = [];
  for (const token of a) {
    if (b.has(token)) overlap.push(token);
  }
  return overlap;
}

function negativeObservationReason(note) {
  const lower = cleanText(note).toLowerCase();
  if (!lower) return "empty_note";
  const patterns = [
    /\b(?:no|none|neither)\b[^.?!]*(?:visible|seen|detected|present|shown|in view|in frame|in any|in the)/,
    /\b(?:not|isn't|isnt|aren't|arent|cannot|can't|cant|couldn't|couldnt|unable to)\b[^.?!]*(?:visible|seen|detected|present|identify|determine|tell|confirm|find|shown)/,
    /\b(?:does not|doesn't|doesnt|did not|didn't|didnt)\b[^.?!]*(?:appear|show|contain|include|meet|satisfy)/,
    /\b(?:unclear|ambiguous|obscured|blocked|partial|partially|not clear|hard to tell|cannot tell|can't tell|cant tell|no evidence|not enough evidence)\b/,
    /\b(?:condition|criterion|trigger|task)\b[^.?!]*(?:not met|not satisfied|not complete|not completed|false)\b/,
  ];
  const matched = patterns.find((pattern) => pattern.test(lower));
  return matched ? "negative_or_unclear_note" : "";
}

function positiveObservationReason(note) {
  const lower = cleanText(note).toLowerCase();
  if (!lower) return "";
  const patterns = [
    /\b(?:condition|criterion|trigger|task)\b[^.?!]*(?:met|satisfied|complete|completed|true)\b/,
    /\b(?:is|are|was|were|becomes|became|remains)\b[^.?!]*(?:visible|seen|present|detected|shown|in view|in frame)\b/,
    /\b(?:visible|seen|present|detected|shown)\b[^.?!]*(?:in|on|at|near|all|every|frame|view)\b/,
    /\b(?:there is|there are|appears|appeared|showing|holding|held up|walks up|walked up|takes|took|reaches|reached|removing|removed)\b/,
    /\b(?:count|total)\s*(?:is|:)\s*\d+\b/,
  ];
  const matched = patterns.find((pattern) => pattern.test(lower));
  return matched ? "affirmative_note" : "";
}

function classifyActiveGeneralNote(payload, registryEntry = {}) {
  const monitorType = cleanText(registryEntry.monitor_type || payload.monitor_type).toLowerCase();
  if (monitorType && monitorType !== "general") {
    return { satisfies: false, reason: "task_not_done", monitor_type: monitorType };
  }

  const note = cleanText(payload.note || payload.task_note || payload.observation);
  const negativeReason = negativeObservationReason(note);
  if (negativeReason) {
    return { satisfies: false, reason: negativeReason, note };
  }

  const positiveReason = positiveObservationReason(note);
  const triggerText = [
    registryEntry.trigger_condition,
    registryEntry.original_request,
    payload.task_description,
  ].map(cleanText).filter(Boolean).join(" ");
  const noteTokens = contentTokens(note);
  const triggerTokens = contentTokens(triggerText);
  const overlap = tokenOverlap(noteTokens, triggerTokens);
  const strongOverlap = overlap.filter((token) => !WEAK_TRIGGER_TOKENS.has(token));
  const saysConditionMet = /\b(?:condition|criterion|trigger|task)\b/i.test(note);

  if (positiveReason && (strongOverlap.length > 0 || overlap.length >= 2 || saysConditionMet)) {
    return {
      satisfies: true,
      reason: "general_note_satisfies_trigger",
      note,
      positive_reason: positiveReason,
      overlap,
      strong_overlap: strongOverlap,
    };
  }

  if (positiveReason && triggerTokens.size === 0) {
    return {
      satisfies: true,
      reason: "general_note_affirmative_without_registered_trigger",
      note,
      positive_reason: positiveReason,
      overlap,
      strong_overlap: strongOverlap,
    };
  }

  return {
    satisfies: false,
    reason: positiveReason ? "general_note_lacks_trigger_overlap" : "general_note_not_affirmative",
    note,
    positive_reason: positiveReason,
    overlap,
    strong_overlap: strongOverlap,
  };
}

function latestRegistryEntry(state) {
  const entries = Object.values(state.registry || {});
  entries.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  return entries[0] || null;
}

export function createVoiceDemoServer(options = {}) {
  const port = Number(options.port || process.env.VOICE_AGENT_DEMO_PORT || process.env.VOICE_DEMO_PORT || DEFAULT_PORT);
  const videomemoryBaseUrl = cleanText(options.videomemoryBaseUrl || process.env.VIDEOMEMORY_BASE_URL) || "http://127.0.0.1:5050";
  const configuredPublicBaseUrl = cleanText(options.publicBaseUrl || process.env.VOICE_AGENT_DEMO_PUBLIC_BASE_URL || process.env.VOICE_DEMO_PUBLIC_BASE_URL);
  const openaiApiKey = cleanText(options.openaiApiKey || process.env.OPENAI_API_KEY);
  const openaiBaseUrl = (cleanText(options.openaiBaseUrl || process.env.OPENAI_BASE_URL) || DEFAULT_OPENAI_BASE_URL).replace(/\/+$/, "");
  const realtimeModel = cleanText(options.realtimeModel || process.env.OPENAI_REALTIME_MODEL) || "gpt-realtime-2";
  const realtimeVoice = cleanText(options.realtimeVoice || process.env.OPENAI_REALTIME_VOICE) || "marin";
  const stateDir = resolve(cleanText(options.stateDir || process.env.VOICE_AGENT_DEMO_STATE_DIR || process.env.VOICE_DEMO_STATE_DIR) || DEFAULT_STATE_DIR);
  const statePath = join(stateDir, "state.json");
  const clients = new Set();
  const realtimeSessionStarts = new Map();
  let statePromise = loadState(statePath);

  async function getState() {
    const state = await statePromise;
    state.registry ||= {};
    state.ledger ||= [];
    state.events ||= [];
    state.ignored_events ||= [];
    state.seen_event_ids ||= [];
    state.fake_camera ||= { scene: "apple_counter" };
    state.agent_context ||= {};
    state.tool_calls ||= [];
    return state;
  }

  async function persist(state) {
    await saveState(statePath, state);
  }

  function broadcast(event) {
    const payload = `event: ${event.type || "message"}\ndata: ${JSON.stringify(event)}\n\n`;
    for (const client of [...clients]) {
      try {
        client.write(payload);
      } catch {
        clients.delete(client);
      }
    }
  }

  function recordToolCall(state, name, input = {}, output = {}, status = "success") {
    const call = {
      id: `tool-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name,
      status,
      input,
      output,
      at: new Date().toISOString(),
    };
    state.tool_calls.push(call);
    state.tool_calls = state.tool_calls.slice(-500);
    broadcast({ type: "tool_call", call, at: call.at });
    return call;
  }

  function parseBooleanLike(value) {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value === 1 ? true : value === 0 ? false : null;
    const normalized = cleanText(value).toLowerCase();
    if (["true", "1", "yes", "done", "completed", "complete"].includes(normalized)) return true;
    if (["false", "0", "no", "active", "running", "pending", "in_progress"].includes(normalized)) return false;
    return null;
  }

  function payloadCompletionState(payload) {
    const done = parseBooleanLike(payload.task_done ?? payload.done ?? payload.task?.done);
    if (done !== null) return done;
    const status = cleanText(payload.task_status || payload.status || payload.task?.status).toLowerCase();
    if (["done", "complete", "completed", "fulfilled"].includes(status)) return true;
    if (["active", "running", "pending", "in_progress"].includes(status)) return false;
    return null;
  }

  function ignoredVideoMemoryUpdate(payload, eventId, registryEntry, decision = {}) {
    return {
      type: "videomemory_note_ignored",
      event_id: eventId,
      task_id: cleanText(payload.task_id),
      io_id: cleanText(payload.io_id || registryEntry.io_id),
      reason: cleanText(decision.reason) || "task_not_done",
      task_status: cleanText(payload.task_status || payload.status || payload.task?.status),
      task_done: payload.task_done ?? payload.done ?? payload.task?.done ?? null,
      note: cleanText(payload.note),
      note_decision: decision,
      registry_entry: registryEntry,
      payload,
      at: new Date().toISOString(),
    };
  }

  async function stopAcceptedActiveMonitor(state, taskId, eventId, reason) {
    if (!taskId) {
      return { status: "skipped", reason: "missing_task_id" };
    }
    try {
      const result = await fetchJson(`${videomemoryBaseUrl}/api/task/${encodeURIComponent(taskId)}/stop`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      recordToolCall(state, "stop_triggered_active_monitor", {
        task_id: taskId,
        event_id: eventId,
        reason,
      }, result);
      return result;
    } catch (error) {
      const result = { status: "error", error: cleanText(error.message) };
      recordToolCall(state, "stop_triggered_active_monitor", {
        task_id: taskId,
        event_id: eventId,
        reason,
      }, result, "error");
      return result;
    }
  }

  async function configureWebhook(publicBaseUrl) {
    const webhookUrl = `${publicBaseUrl}/videomemory-event`;
    await fetchJson(`${videomemoryBaseUrl}/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL`, {
      method: "PUT",
      body: JSON.stringify({ value: webhookUrl }),
    });
    try {
      await fetchJson(`${videomemoryBaseUrl}/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN`, {
        method: "PUT",
        body: JSON.stringify({ value: "" }),
      });
    } catch {
      // Older servers may not expose this setting; the webhook URL is the important part.
    }
    return webhookUrl;
  }

  async function registerFakeCamera(publicBaseUrl) {
    const snapshotUrl = `${publicBaseUrl}/fake-camera/snapshot.ppm`;
    const body = await fetchJson(`${videomemoryBaseUrl}/api/devices/network`, {
      method: "POST",
      body: JSON.stringify({
        url: snapshotUrl,
        name: "Voice Agent Demo Fake Apple Counter",
      }),
    });
    return {
      device: body.device,
      snapshot_url: snapshotUrl,
      io_id: cleanText(body?.device?.io_id),
      warning: cleanText(body.warning),
    };
  }

  async function stopRememberedMonitors(state) {
    const stopped = [];
    const errors = [];
    const taskIds = Object.keys(state.registry || {});
    for (const taskId of taskIds) {
      try {
        await fetchJson(`${videomemoryBaseUrl}/api/task/${encodeURIComponent(taskId)}/stop`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        stopped.push(taskId);
      } catch (error) {
        errors.push({ task_id: taskId, error: cleanText(error.message) });
      }
    }
    return { stopped, errors };
  }

  async function resetDemoState({ stopMonitors = true } = {}) {
    const state = await getState();
    const stop_result = stopMonitors ? await stopRememberedMonitors(state) : { stopped: [], errors: [] };
    state.registry = {};
    state.ledger = [];
    state.events = [];
    state.seen_event_ids = [];
    state.pending_sale = null;
    state.agent_context = {};
    state.tool_calls = [];
    state.visual_memory = null;
    state.fake_camera = { scene: "apple_counter", updated_at: new Date().toISOString() };
    await persist(state);
    const result = {
      status: "success",
      stopped_task_ids: stop_result.stopped,
      stop_errors: stop_result.errors,
    };
    broadcast({ type: "reset", result, at: new Date().toISOString() });
    return result;
  }

  function realtimeSessionConfig() {
    return {
      expires_after: {
        anchor: "created_at",
        seconds: 600,
      },
      session: {
        type: "realtime",
        model: realtimeModel,
        output_modalities: ["audio"],
        instructions: REALTIME_INSTRUCTIONS,
        tools: REALTIME_TOOLS,
        tool_choice: "auto",
        audio: {
          input: {
            noise_reduction: { type: "near_field" },
            transcription: { model: "gpt-4o-mini-transcribe", language: "en" },
            turn_detection: {
              type: "server_vad",
              threshold: 0.5,
              prefix_padding_ms: 300,
              silence_duration_ms: 650,
            },
          },
          output: {
            voice: realtimeVoice,
          },
        },
      },
    };
  }

  async function createRealtimeClientSecret() {
    if (!openaiApiKey) {
      const error = new Error("OPENAI_API_KEY is not set for the live voice agent.");
      error.status = 428;
      throw error;
    }
    const response = await fetch(`${openaiBaseUrl}/realtime/client_secrets`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${openaiApiKey}`,
        "Content-Type": "application/json",
        "OpenAI-Safety-Identifier": "videomemory-voice-agent-demo-local",
      },
      body: JSON.stringify(realtimeSessionConfig()),
    });
    const text = await response.text();
    let body = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = { raw: text };
    }
    if (!response.ok) {
      const message = cleanText(body.error?.message || body.error || body.message || body.raw) || `OpenAI realtime token request failed: HTTP ${response.status}`;
      const error = new Error(message);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return {
      ...body,
      model: realtimeModel,
      voice: realtimeVoice,
    };
  }

  function clientRateLimitKey(req) {
    const forwarded = cleanText(req.headers["x-forwarded-for"]);
    if (forwarded) return forwarded.split(",")[0].trim();
    return cleanText(req.socket?.remoteAddress) || "unknown";
  }

  function enforceRealtimeSessionRateLimit(req) {
    const maxPerHour = Math.max(1, Number(process.env.VOICE_AGENT_DEMO_MAX_SESSIONS_PER_HOUR || 20));
    const minIntervalMs = Math.max(0, Number(process.env.VOICE_AGENT_DEMO_MIN_SESSION_INTERVAL_MS || 10000));
    const now = Date.now();
    const key = clientRateLimitKey(req);
    const recent = (realtimeSessionStarts.get(key) || []).filter((startedAt) => now - startedAt < 60 * 60 * 1000);
    const last = recent[recent.length - 1] || 0;
    if (minIntervalMs && now - last < minIntervalMs) {
      const error = new Error("Please wait a few seconds before starting another live voice session.");
      error.status = 429;
      throw error;
    }
    if (recent.length >= maxPerHour) {
      const error = new Error("Demo session limit reached for this browser/IP. Try again later.");
      error.status = 429;
      throw error;
    }
    recent.push(now);
    realtimeSessionStarts.set(key, recent);
  }

  async function readDeviceReadiness(ioId, attempts = 16, delayMs = 250) {
    let last = null;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        last = await fetchJson(`${videomemoryBaseUrl}/api/device/${encodeURIComponent(ioId)}/readiness`);
        if (last?.ready) return last;
      } catch (error) {
        last = {
          status: "not_ready",
          ready: false,
          warnings: [`Could not read readiness: ${cleanText(error.message)}`],
        };
      }
      if (attempt < attempts - 1) {
        await sleep(delayMs);
      }
    }
    return last || {
      status: "not_ready",
      ready: false,
      warnings: ["Readiness did not return a response."],
    };
  }

  function persistentTriggerCondition(registryEntry, previousValue = null) {
    if (registryEntry.persona === "visual_memory") {
      return visualMemoryTriggerCondition(registryEntry.visual_memory, previousValue);
    }
    const base = cleanText(registryEntry.trigger_condition) || "the requested visual condition is visible";
    return `${base} Treat this as a persistent monitor: complete only for a new occurrence after the previous wakeup, not merely because the same unchanged scene is still visible.`;
  }

  async function captionVisualMemoryObservation(ioId, registryEntry, memory = null) {
    const spec = registryEntry.visual_memory || memory || {};
    const prompt = [
      "Update a visual-memory state from the current camera frame.",
      `Original user request: ${cleanText(spec.original_request || registryEntry.original_request)}`,
      `Visual event to look for: ${cleanText(spec.event_condition || registryEntry.trigger_condition)}`,
      `Extraction rule: ${cleanText(spec.extraction_instruction) || "Extract the value or concise observation for this single event."}`,
      "Return JSON only with this exact shape: {\"observed\": boolean, \"value\": number|string|null, \"confidence\": \"high\"|\"medium\"|\"low\", \"reason\": string}.",
      "If the requested event is not clearly visible, unchanged from the prior observation, or ambiguous, return observed=false and value=null.",
      "For totals/counts/sums, value must be the numeric amount to add for this single observation, not the cumulative total.",
    ].join(" ");
    const response = await fetchJson(`${videomemoryBaseUrl}/api/caption_frame`, {
      method: "POST",
      body: JSON.stringify({ io_id: ioId, prompt }),
    });
    const text = cleanText(response.analysis || response.caption || response.description || response.text || response.result || response.raw);
    return {
      response,
      text,
      parsed: parseVisualMemoryObservation(text, spec),
    };
  }

  async function rearmPersistentMonitor(state, registryEntry, previousValue = null) {
    const nextPlan = {
      ...registryEntry,
      task_id: undefined,
      trigger_condition: persistentTriggerCondition(registryEntry, previousValue),
      rearm_on_wakeup: true,
      previous_task_id: cleanText(registryEntry.task_id),
      created_at: new Date().toISOString(),
    };
    const taskPayload = buildVideoMemoryTaskPayload(nextPlan);
    const task = await fetchJson(`${videomemoryBaseUrl}/api/tasks`, {
      method: "POST",
      body: JSON.stringify(taskPayload),
    });
    const taskId = getTaskId(task);
    if (!taskId) {
      throw new Error("VideoMemory re-armed the persistent monitor but did not return a task_id.");
    }
    const nextEntry = {
      ...nextPlan,
      task_id: taskId,
      created_at: new Date().toISOString(),
    };
    state.registry[taskId] = nextEntry;
    if (state.visual_memory && registryEntry.persona === "visual_memory") {
      state.visual_memory.active_task_id = taskId;
      state.visual_memory.last_rearmed_at = nextEntry.created_at;
    }
    recordToolCall(state, "rearm_persistent_monitor", taskPayload, { task_id: taskId, task });
    return nextEntry;
  }

  async function createMonitorFromText(req, body) {
    const publicBaseUrl = publicBaseFromRequest(req, configuredPublicBaseUrl);
    const state = await getState();
    let ioId = cleanText(body.io_id) || "browser_facetime";
    let fakeCamera = null;

    if (body.use_fake_camera === true || ioId === "fake") {
      fakeCamera = await registerFakeCamera(publicBaseUrl);
      recordToolCall(state, "register_fake_camera", { public_base_url: publicBaseUrl }, fakeCamera);
      if (!fakeCamera.io_id) {
        throw new Error("Fake camera registration did not return an io_id.");
      }
      ioId = fakeCamera.io_id;
    }

    const requestText = body.text || body.command || body.instruction;
    const plan = buildTaskPlan(requestText, { ioId, context: state.agent_context, lifecycle: body.lifecycle });
    state.agent_context = inferConversationContext(requestText, plan.conversation_context || state.agent_context);
    const webhookUrl = await configureWebhook(publicBaseUrl);
    recordToolCall(state, "configure_videomemory_webhook", { public_base_url: publicBaseUrl }, { webhook_url: webhookUrl });
    const taskPayload = buildVideoMemoryTaskPayload(plan);
    const task = await fetchJson(`${videomemoryBaseUrl}/api/tasks`, {
      method: "POST",
      body: JSON.stringify(taskPayload),
    });
    recordToolCall(state, "create_videomemory_monitor", taskPayload, task);
    const taskId = getTaskId(task);
    if (!taskId) {
      throw new Error("VideoMemory created a task but did not return a task_id.");
    }

    const readiness = await readDeviceReadiness(ioId);
    recordToolCall(state, "read_device_readiness", { io_id: ioId }, readiness);

    const registryEntry = {
      ...plan,
      task_id: taskId,
      io_id: ioId,
      webhook_url: webhookUrl,
      created_at: new Date().toISOString(),
      fake_camera: fakeCamera,
    };
    state.registry[taskId] = registryEntry;
    state.pending_sale = null;
    if (registryEntry.persona === "visual_memory") {
      state.visual_memory = {
        ...(registryEntry.visual_memory || {}),
        total: 0,
        observations: [],
        active_task_id: taskId,
        started_at: registryEntry.created_at,
        last_value: null,
      };
    }
    await persist(state);

    const result = {
      status: "success",
      reply: readiness?.ready
        ? "The visual wakeup is armed. I will stay quiet until VideoMemory sees the condition."
        : `I created the visual wakeup, but readiness is not clean yet: ${(readiness?.warnings || []).join(" ") || "unknown readiness warning"}`,
      task,
      task_payload: taskPayload,
      registry_entry: registryEntry,
      readiness,
      fake_camera: fakeCamera,
    };
    broadcast({ type: "monitor", result, at: new Date().toISOString() });
    return result;
  }

  async function recordLedgerEntryFromTool(args = {}) {
    const state = await getState();
    const name = cleanText(args.name);
    const appleCount = Number(args.apple_count);
    if (!name || !Number.isInteger(appleCount) || appleCount < 1) {
      const error = new Error("record_ledger_entry requires a name and a positive integer apple_count.");
      error.status = 400;
      throw error;
    }
    const pendingSale = state.pending_sale || {};
    const entry = {
      id: `ledger-${Date.now()}`,
      timestamp: new Date().toISOString(),
      name,
      apple_count: appleCount,
      amount_due: appleCount,
      evidence_url: cleanText(pendingSale.evidence_url),
      task_id: cleanText(pendingSale.task_id),
      event_id: cleanText(pendingSale.event_id),
    };
    state.ledger.push(entry);
    state.pending_sale = null;
    recordToolCall(state, "record_ledger_entry", { args, pending_sale: pendingSale }, entry);
    await persist(state);
    broadcast({ type: "ledger", entry, ledger: state.ledger, at: new Date().toISOString() });
    return { status: "success", entry, ledger: state.ledger, summary: summarizeLedger(state.ledger) };
  }

  async function realtimeStatusSnapshot(req) {
    const state = await getState();
    let health = null;
    let settings = null;
    try {
      health = await fetchJson(`${videomemoryBaseUrl}/api/health`);
    } catch (error) {
      health = { status: "error", error: cleanText(error.message) };
    }
    try {
      const settingsBody = await fetchJson(`${videomemoryBaseUrl}/api/settings`);
      const modelKeys = ["GOOGLE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"];
      settings = {
        model_key_configured: modelKeys.some((key) => Boolean(settingsBody.settings?.[key]?.is_set)),
        video_ingestor_model: cleanText(settingsBody.settings?.VIDEO_INGESTOR_MODEL?.value) || "default",
      };
    } catch (error) {
      settings = {
        model_key_configured: null,
        error: cleanText(error.message),
      };
    }
    return {
      status: "success",
      videomemory_base_url: videomemoryBaseUrl,
      public_base_url: publicBaseFromRequest(req, configuredPublicBaseUrl),
      webhook_url: `${publicBaseFromRequest(req, configuredPublicBaseUrl)}/videomemory-event`,
      active_monitors: Object.values(state.registry).length,
      latest_monitor: latestRegistryEntry(state),
      pending_sale: state.pending_sale,
      ledger_count: state.ledger.length,
      visual_memory: state.visual_memory,
      agent_context: state.agent_context,
      tool_calls_count: state.tool_calls.length,
      health,
      videomemory_settings: settings,
      realtime: {
        configured: Boolean(openaiApiKey),
        model: realtimeModel,
        voice: realtimeVoice,
      },
    };
  }

  function compactTask(task) {
    if (!task || typeof task !== "object") return task;
    const notes = task.notes || task.task_note || [];
    return {
      task_id: cleanText(task.task_id || task.id),
      io_id: cleanText(task.io_id),
      bot_id: cleanText(task.bot_id),
      status: cleanText(task.status),
      done: task.done === true,
      monitor_type: cleanText(task.monitor_type),
      task_description: cleanText(task.task_description || task.description || task.task_desc),
      notes_count: Array.isArray(notes) ? notes.length : 0,
      latest_note: Array.isArray(notes) && notes.length
        ? cleanText(notes[notes.length - 1]?.content || notes[notes.length - 1]?.note || notes[notes.length - 1])
        : "",
      created_at: cleanText(task.created_at),
      updated_at: cleanText(task.updated_at),
    };
  }

  function pushWarning(warnings, code, message, details = {}) {
    warnings.push({ code, message, details });
  }

  async function debugSnapshot(req) {
    const state = await getState();
    const warnings = [];
    const [status, browserStatus, browserReadiness, devices, tasks] = await Promise.all([
      realtimeStatusSnapshot(req).catch((error) => ({ status: "error", error: cleanText(error.message) })),
      fetchJson(`${videomemoryBaseUrl}/api/browser-camera/facetime/status`).catch((error) => ({ status: "error", error: cleanText(error.message) })),
      fetchJson(`${videomemoryBaseUrl}/api/device/browser_facetime/readiness`).catch((error) => ({ status: "not_ready", ready: false, warnings: [cleanText(error.message)] })),
      fetchJson(`${videomemoryBaseUrl}/api/devices`).catch((error) => ({ status: "error", error: cleanText(error.message) })),
      fetchJson(`${videomemoryBaseUrl}/api/tasks`).catch((error) => ({ status: "error", error: cleanText(error.message), tasks: [] })),
    ]);

    const taskList = Array.isArray(tasks.tasks) ? tasks.tasks : Object.values(tasks.tasks || {});
    const voiceTasks = taskList
      .map(compactTask)
      .filter((task) => task?.bot_id === BOT_ID || task?.bot_id === "voice-demo" || state.registry?.[task?.task_id])
      .slice(-25);
    const registryEntries = Object.values(state.registry || {});
    const latestMonitor = latestRegistryEntry(state);

    if (status?.realtime?.configured === false) {
      pushWarning(warnings, "realtime_key_missing", "OpenAI realtime is not configured.");
    }
    if (status?.videomemory_settings?.model_key_configured === false) {
      pushWarning(warnings, "videomemory_model_key_missing", "VideoMemory has no model key configured.");
    }
    if (browserReadiness?.ready === false) {
      pushWarning(warnings, "browser_camera_not_ready", "Browser camera is not ready or frames are stale.", {
        readiness_status: browserReadiness.status,
        warnings: browserReadiness.warnings || [],
        browser_camera: browserReadiness.browser_camera,
        ingestor: browserReadiness.ingestor,
      });
    }
    if (latestMonitor && status?.health?.active_tasks === 0) {
      pushWarning(warnings, "registry_has_no_active_videomemory_task", "The demo remembers a monitor, but VideoMemory reports no active tasks.", {
        latest_task_id: latestMonitor.task_id,
        latest_task_status: voiceTasks.find((task) => task.task_id === latestMonitor.task_id)?.status || "",
      });
    }
    if (state.events?.length && !state.tool_calls?.some((call) => call.name === "handle_videomemory_wakeup")) {
      pushWarning(warnings, "events_without_wakeup_tool_call", "Events exist but no wakeup tool call is recorded.");
    }

    return {
      status: "success",
      generated_at: new Date().toISOString(),
      warnings,
      current: {
        status_snapshot: status,
        latest_monitor: latestMonitor,
        registry_count: registryEntries.length,
        visual_memory: state.visual_memory,
        pending_sale: state.pending_sale,
        ledger_count: state.ledger.length,
      },
      browser_camera: {
        status: browserStatus,
        readiness: browserReadiness,
      },
      videomemory: {
        devices,
        voice_agent_tasks: voiceTasks,
      },
      recent: {
        tool_calls: (state.tool_calls || []).slice(-75),
        events: (state.events || []).slice(-50),
        ignored_events: (state.ignored_events || []).slice(-50),
        seen_event_ids: (state.seen_event_ids || []).slice(-25),
      },
      debug_urls: {
        status: `${publicBaseFromRequest(req, configuredPublicBaseUrl)}/api/status`,
        debug: `${publicBaseFromRequest(req, configuredPublicBaseUrl)}/api/debug`,
        tool_calls: `${publicBaseFromRequest(req, configuredPublicBaseUrl)}/api/tool-calls`,
        videomemory_tasks: `${videomemoryBaseUrl}/api/tasks`,
        browser_camera_readiness: `${videomemoryBaseUrl}/api/device/browser_facetime/readiness`,
      },
    };
  }

  function parseToolArguments(rawArgs) {
    if (!rawArgs) return {};
    if (typeof rawArgs === "object") return rawArgs;
    try {
      return JSON.parse(String(rawArgs));
    } catch {
      return {};
    }
  }

  async function runRealtimeTool(req, body) {
    const name = cleanText(body.name);
    const args = parseToolArguments(body.arguments);
    if (name === "set_videomemory_monitor") {
      return {
        tool: name,
        ...(await createMonitorFromText(req, {
          text: args.instruction,
          lifecycle: args.lifecycle,
          io_id: "browser_facetime",
          use_fake_camera: false,
        })),
      };
    }
    if (name === "record_ledger_entry") {
      return { tool: name, ...(await recordLedgerEntryFromTool(args)) };
    }
    if (name === "answer_ledger") {
      const state = await getState();
      recordToolCall(state, "answer_ledger", { via: "realtime" }, { summary: summarizeLedger(state.ledger) });
      await persist(state);
      return { tool: name, status: "success", summary: summarizeLedger(state.ledger), ledger: state.ledger };
    }
    if (name === "answer_visual_memory") {
      const state = await getState();
      const summary = summarizeVisualMemory(state.visual_memory);
      recordToolCall(state, "answer_visual_memory", { via: "realtime" }, { summary });
      await persist(state);
      return { tool: name, status: "success", summary, visual_memory: state.visual_memory };
    }
    if (name === "get_videomemory_status") {
      return { tool: name, ...(await realtimeStatusSnapshot(req)) };
    }
    if (name === "reset_demo") {
      return { tool: name, ...(await resetDemoState({ stopMonitors: true })) };
    }
    const error = new Error(`Unknown realtime tool: ${name || "missing name"}`);
    error.status = 400;
    throw error;
  }

  async function handleWakeup(payload, synthetic = false) {
    const state = await getState();
    const eventId = normalizeEventId(payload) || `${BOT_ID}-event-${Date.now()}`;
    if (state.seen_event_ids.includes(eventId)) {
      return { status: "duplicate", duplicate: true, event_id: eventId };
    }

    const taskId = cleanText(payload.task_id);
    const payloadBotId = cleanText(payload.bot_id);
    const registeredEntry = taskId ? state.registry[taskId] : null;
    if (taskId && !registeredEntry) {
      const decision = {
        satisfies: false,
        reason: payloadBotId && ![BOT_ID, "voice-demo"].includes(payloadBotId) ? "foreign_bot_event" : "unregistered_task_event",
        bot_id: payloadBotId,
      };
      state.seen_event_ids.push(eventId);
      state.seen_event_ids = state.seen_event_ids.slice(-200);
      const ignored = ignoredVideoMemoryUpdate(payload, eventId, {}, decision);
      state.ignored_events.push(ignored);
      state.ignored_events = state.ignored_events.slice(-200);
      recordToolCall(state, "ignore_videomemory_task_update", {
        event_id: eventId,
        task_id: taskId,
        bot_id: payloadBotId,
      }, {
        reason: ignored.reason,
        note: ignored.note,
      });
      await persist(state);
      broadcast({ type: "monitor", result: { status: "ignored", reason: ignored.reason }, event: ignored, at: ignored.at });
      return { status: "ignored", ignored: true, duplicate: false, event_id: eventId, reason: ignored.reason, event: ignored };
    }
    const registryEntry = registeredEntry || latestRegistryEntry(state) || {};
    const completionState = synthetic ? true : payloadCompletionState(payload);
    let activeGeneralNoteDecision = null;
    let acceptedActiveGeneralNote = false;
    if (completionState === false) {
      activeGeneralNoteDecision = classifyActiveGeneralNote(payload, registryEntry);
      recordToolCall(state, "classify_videomemory_note", {
        event_id: eventId,
        task_id: taskId,
        task_status: cleanText(payload.task_status || payload.status || payload.task?.status),
        task_done: payload.task_done ?? payload.done ?? payload.task?.done ?? null,
        monitor_type: cleanText(registryEntry.monitor_type || payload.monitor_type),
        trigger_condition: cleanText(registryEntry.trigger_condition || payload.task_description),
        note: cleanText(payload.note),
      }, activeGeneralNoteDecision);
      if (!activeGeneralNoteDecision.satisfies) {
        state.seen_event_ids.push(eventId);
        state.seen_event_ids = state.seen_event_ids.slice(-200);
        const ignored = ignoredVideoMemoryUpdate(payload, eventId, registryEntry, activeGeneralNoteDecision);
        state.ignored_events.push(ignored);
        state.ignored_events = state.ignored_events.slice(-200);
        recordToolCall(state, "ignore_videomemory_task_update", {
          event_id: eventId,
          task_id: taskId,
          task_status: ignored.task_status,
          task_done: ignored.task_done,
        }, {
          reason: ignored.reason,
          note: ignored.note,
          note_decision: activeGeneralNoteDecision,
        });
        await persist(state);
        broadcast({ type: "monitor", result: { status: "ignored", reason: ignored.reason }, event: ignored, at: ignored.at });
        return { status: "ignored", ignored: true, duplicate: false, event_id: eventId, reason: ignored.reason, event: ignored };
      }
      acceptedActiveGeneralNote = true;
      recordToolCall(state, "accept_active_videomemory_note", {
        event_id: eventId,
        task_id: taskId,
        task_status: cleanText(payload.task_status || payload.status || payload.task?.status),
        task_done: payload.task_done ?? payload.done ?? payload.task?.done ?? null,
      }, {
        reason: activeGeneralNoteDecision.reason,
        note: activeGeneralNoteDecision.note,
        overlap: activeGeneralNoteDecision.overlap,
      });
    }

    state.seen_event_ids.push(eventId);
    state.seen_event_ids = state.seen_event_ids.slice(-200);

    let message = buildWakeupMessage(registryEntry, payload);
    let visualMemoryResult = null;
    let stopActiveMonitorResult = null;
    if (registryEntry.persona === "visual_memory") {
      state.visual_memory ||= {
        ...(registryEntry.visual_memory || {}),
        total: 0,
        observations: [],
        active_task_id: taskId,
        started_at: new Date().toISOString(),
        last_value: null,
      };
      try {
        const caption = await captionVisualMemoryObservation(
          cleanText(payload.io_id || registryEntry.io_id) || "browser_facetime",
          registryEntry,
          state.visual_memory,
        );
        recordToolCall(state, "caption_visual_memory_observation", {
          task_id: taskId,
          io_id: cleanText(payload.io_id || registryEntry.io_id),
        }, {
          parsed: caption.parsed,
          text: caption.text,
        });
        if (caption.parsed.observed && caption.parsed.value !== null && caption.parsed.value !== undefined && caption.parsed.value !== "") {
          const observation = {
            id: `visual-${Date.now()}`,
            value: caption.parsed.value,
            confidence: caption.parsed.confidence,
            reason: caption.parsed.reason,
            evidence_url: cleanText(payload.note_frame_api_url || payload.note_video_api_url),
            task_id: taskId,
            event_id: eventId,
            caption: caption.text,
            at: new Date().toISOString(),
          };
          state.visual_memory.observations.push(observation);
          if ((state.visual_memory.mode || state.visual_memory.spec?.mode) === "numeric_total") {
            state.visual_memory.total = state.visual_memory.observations.reduce((sum, entry) => sum + Number(entry.value || 0), 0);
          }
          state.visual_memory.last_value = caption.parsed.value;
          state.visual_memory.last_observation_at = observation.at;
          visualMemoryResult = {
            status: "recorded",
            value: caption.parsed.value,
            total: state.visual_memory.total,
            observation,
          };
          message = summarizeVisualMemory(state.visual_memory);
          recordToolCall(state, "record_visual_memory_observation", {
            task_id: taskId,
            event_id: eventId,
          }, visualMemoryResult);
        } else {
          visualMemoryResult = {
            status: "unclear",
            value: null,
            total: state.visual_memory.total || 0,
            caption: caption.text,
            parsed: caption.parsed,
          };
          message = `Visual memory woke up, but the observation was unclear. ${summarizeVisualMemory(state.visual_memory)}`;
        }
      } catch (error) {
        visualMemoryResult = {
          status: "error",
          error: cleanText(error.message),
          total: state.visual_memory.total || 0,
        };
        message = `Visual memory woke up, but could not caption the frame: ${cleanText(error.message)}.`;
        recordToolCall(state, "caption_visual_memory_observation", {
          task_id: taskId,
          io_id: cleanText(payload.io_id || registryEntry.io_id),
        }, visualMemoryResult, "error");
      }
    }
    if (acceptedActiveGeneralNote) {
      stopActiveMonitorResult = await stopAcceptedActiveMonitor(
        state,
        taskId,
        eventId,
        activeGeneralNoteDecision?.reason || "general_note_satisfies_trigger",
      );
    }
    if (registryEntry.rearm_on_wakeup === true || registryEntry.lifecycle === "persistent") {
      try {
        const nextEntry = await rearmPersistentMonitor(state, registryEntry, state.visual_memory?.last_value);
        visualMemoryResult = registryEntry.persona === "visual_memory"
          ? {
            ...(visualMemoryResult || {}),
            rearmed_task_id: nextEntry.task_id,
          }
          : visualMemoryResult;
        if (registryEntry.persona !== "visual_memory") {
          recordToolCall(state, "rearm_persistent_monitor_result", {
            task_id: taskId,
          }, {
            rearmed_task_id: nextEntry.task_id,
          });
        }
      } catch (error) {
        visualMemoryResult = registryEntry.persona === "visual_memory"
          ? {
            ...(visualMemoryResult || {}),
            rearm_error: cleanText(error.message),
          }
          : visualMemoryResult;
        message = `${message} Re-arm failed: ${cleanText(error.message)}.`;
        recordToolCall(state, "rearm_persistent_monitor", {
          task_id: taskId,
        }, { error: cleanText(error.message) }, "error");
      }
    }
    const event = {
      type: "wakeup",
      event_id: eventId,
      synthetic,
      task_id: taskId,
      io_id: cleanText(payload.io_id || registryEntry.io_id),
      note: cleanText(payload.note),
      message,
      evidence: {
        frame_url: cleanText(payload.note_frame_api_url),
        video_url: cleanText(payload.note_video_api_url),
      },
      registry_entry: registryEntry,
      payload,
      silent: registryEntry.silent_wakeup === true,
      visual_memory: visualMemoryResult,
      active_general_note: activeGeneralNoteDecision,
      stopped_active_task: stopActiveMonitorResult,
      at: new Date().toISOString(),
    };
    state.events.push(event);
    state.events = state.events.slice(-200);
    recordToolCall(state, "handle_videomemory_wakeup", {
      event_id: eventId,
      task_id: taskId,
      synthetic,
    }, {
      message,
      visual_memory: visualMemoryResult,
      active_general_note: activeGeneralNoteDecision,
      stopped_active_task: stopActiveMonitorResult,
      opened_pending_sale: registryEntry.persona === "apple_shopkeeper",
    });
    if (registryEntry.persona === "apple_shopkeeper") {
      state.pending_sale = {
        task_id: taskId,
        event_id: eventId,
        name: "",
        apple_count: null,
        evidence_url: event.evidence.frame_url || event.evidence.video_url || "",
        opened_at: event.at,
      };
    }
    await persist(state);
    broadcast(event);
    return { status: "success", duplicate: false, event };
  }

  async function handleChat(req, body) {
    const text = cleanText(body.text);
    if (!text) {
      return { status: "error", error: "Enter something to say." };
    }
    const state = await getState();
    const lower = text.toLowerCase();

    if (state.visual_memory && /\b(total|count|so far|sum|log|summary|what happened|how many|observations?)\b/.test(lower) && !isSetupCommand(text)) {
      const summary = summarizeVisualMemory(state.visual_memory);
      recordToolCall(state, "answer_visual_memory", { text }, { summary });
      await persist(state);
      return { status: "success", kind: "visual_memory", reply: summary, visual_memory: state.visual_memory };
    }

    if (/\b(ledger|total|who owes|summary)\b/.test(lower) && !isSetupCommand(text)) {
      recordToolCall(state, "answer_ledger", { text }, { summary: summarizeLedger(state.ledger) });
      await persist(state);
      return { status: "success", kind: "ledger", reply: summarizeLedger(state.ledger), ledger: state.ledger };
    }

    if (isSetupCommand(text)) {
      return { ...(await createMonitorFromText(req, body)), kind: "monitor" };
    }

    if (state.pending_sale) {
      const parsed = parseLedgerEntry(text, state.pending_sale);
      if (parsed.error) {
        return { status: "error", error: parsed.error };
      }
      state.pending_sale = {
        ...state.pending_sale,
        name: parsed.name || state.pending_sale.name,
        apple_count: parsed.apple_count || state.pending_sale.apple_count,
      };
      if (!parsed.complete) {
        await persist(state);
        const missing = parsed.missing.includes("name") ? "your name" : "how many apples";
        return { status: "success", kind: "ledger_pending", reply: `I still need ${missing}.`, pending_sale: state.pending_sale };
      }
      const pendingSale = state.pending_sale;
      const entry = {
        id: `ledger-${Date.now()}`,
        timestamp: new Date().toISOString(),
        name: parsed.name,
        apple_count: parsed.apple_count,
        amount_due: parsed.amount_due,
        evidence_url: state.pending_sale.evidence_url || "",
        task_id: state.pending_sale.task_id || "",
        event_id: state.pending_sale.event_id || "",
      };
      state.ledger.push(entry);
      state.pending_sale = null;
      recordToolCall(state, "record_ledger_entry", {
        text,
        pending_sale: pendingSale,
      }, entry);
      await persist(state);
      const reply = `Thanks, ${entry.name}. I added ${entry.apple_count} apple${entry.apple_count === 1 ? "" : "s"} to the ledger. Amount due: $${entry.amount_due}.`;
      broadcast({ type: "ledger", entry, ledger: state.ledger, at: new Date().toISOString() });
      return { status: "success", kind: "ledger_entry", reply, entry, ledger: state.ledger };
    }

    return {
      status: "success",
      kind: "assistant",
      reply: "I can create a visual wakeup. Say something like: be a shopkeeper and watch these apples.",
    };
  }

  async function serveStatic(req, res, pathname) {
    const file = pathname === "/" ? join(PUBLIC_DIR, "index.html") : join(PUBLIC_DIR, pathname.replace(/^\/+/, ""));
    const resolved = resolve(file);
    if (!resolved.startsWith(PUBLIC_DIR) || !existsSync(resolved)) {
      jsonResponse(res, 404, { status: "error", error: "Not found" });
      return;
    }
    res.writeHead(200, {
      "Content-Type": contentTypeFor(resolved),
      "Cache-Control": "no-store",
    });
    createReadStream(resolved).pipe(res);
  }

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url || "/", `http://${req.headers.host || "127.0.0.1"}`);
      const pathname = url.pathname;

      if (req.method === "OPTIONS") {
        res.writeHead(204, {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "Content-Type, Authorization, Idempotency-Key",
          "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
        });
        res.end();
        return;
      }

      if (req.method === "GET" && pathname === "/events") {
        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-store",
          Connection: "keep-alive",
        });
        res.write("retry: 1000\n\n");
        clients.add(res);
        req.on("close", () => clients.delete(res));
        return;
      }

      if (req.method === "GET" && pathname === "/api/status") {
        jsonResponse(res, 200, await realtimeStatusSnapshot(req));
        return;
      }

      if (req.method === "GET" && pathname === "/api/debug") {
        jsonResponse(res, 200, await debugSnapshot(req));
        return;
      }

      if (req.method === "POST" && pathname === "/api/reset") {
        const result = await resetDemoState({ stopMonitors: true });
        jsonResponse(res, 200, result);
        return;
      }

      if (req.method === "POST" && pathname === "/api/realtime/client-secret") {
        enforceRealtimeSessionRateLimit(req);
        jsonResponse(res, 201, await createRealtimeClientSecret());
        return;
      }

      if (req.method === "POST" && pathname === "/api/realtime/tool") {
        const body = await readJsonBody(req);
        jsonResponse(res, 200, await runRealtimeTool(req, body));
        return;
      }

      if (req.method === "POST" && pathname === "/api/live-camera/register") {
        const body = await fetchJson(`${videomemoryBaseUrl}/api/browser-camera/facetime/register?client=${encodeURIComponent(BOT_ID)}`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        jsonResponse(res, 201, { status: "success", ...body });
        return;
      }

      if (req.method === "GET" && pathname === "/api/live-camera/status") {
        const [cameraStatus, readiness] = await Promise.all([
          fetchJson(`${videomemoryBaseUrl}/api/browser-camera/facetime/status`).catch((error) => ({ status: "error", error: cleanText(error.message) })),
          fetchJson(`${videomemoryBaseUrl}/api/device/browser_facetime/readiness`).catch((error) => ({ status: "not_ready", ready: false, warnings: [cleanText(error.message)] })),
        ]);
        jsonResponse(res, 200, { status: "success", camera: cameraStatus, readiness });
        return;
      }

      if (req.method === "POST" && pathname === "/api/live-camera/frame") {
        const frame = await readRawBody(req);
        if (frame.length === 0) {
          jsonResponse(res, 400, { status: "error", error: "JPEG frame body is required." });
          return;
        }
        const response = await fetch(`${videomemoryBaseUrl}/api/browser-camera/facetime/frame`, {
          method: "POST",
          headers: { "Content-Type": "image/jpeg" },
          body: frame,
        });
        const text = await response.text();
        let body = {};
        try {
          body = text ? JSON.parse(text) : {};
        } catch {
          body = { raw: text };
        }
        jsonResponse(res, response.ok ? 200 : response.status, body);
        return;
      }

      if (req.method === "GET" && pathname === "/api/ledger") {
        const state = await getState();
        jsonResponse(res, 200, { status: "success", ledger: state.ledger, summary: summarizeLedger(state.ledger) });
        return;
      }

      if (req.method === "GET" && pathname === "/api/tool-calls") {
        const state = await getState();
        jsonResponse(res, 200, { status: "success", tool_calls: state.tool_calls });
        return;
      }

      if (req.method === "DELETE" && pathname === "/api/tool-calls") {
        const state = await getState();
        state.tool_calls = [];
        await persist(state);
        jsonResponse(res, 200, { status: "success", tool_calls: [] });
        return;
      }

      if (req.method === "DELETE" && pathname === "/api/ledger") {
        const state = await getState();
        state.ledger = [];
        state.pending_sale = null;
        await persist(state);
        broadcast({ type: "ledger_reset", at: new Date().toISOString() });
        jsonResponse(res, 200, { status: "success", ledger: [] });
        return;
      }

      if (req.method === "POST" && pathname === "/api/ledger") {
        const body = await readJsonBody(req);
        const parsed = parseLedgerEntry(`${body.name || ""} took ${body.apple_count || ""} apples`);
        if (!parsed.complete) {
          jsonResponse(res, 400, { status: "error", error: "name and apple_count are required." });
          return;
        }
        const state = await getState();
        const entry = {
          id: `ledger-${Date.now()}`,
          timestamp: new Date().toISOString(),
          name: parsed.name,
          apple_count: parsed.apple_count,
          amount_due: parsed.amount_due,
          evidence_url: cleanText(body.evidence_url),
          task_id: cleanText(body.task_id),
          event_id: cleanText(body.event_id),
        };
        state.ledger.push(entry);
        await persist(state);
        broadcast({ type: "ledger", entry, ledger: state.ledger, at: new Date().toISOString() });
        jsonResponse(res, 201, { status: "success", entry, ledger: state.ledger });
        return;
      }

      if (req.method === "POST" && pathname === "/api/command") {
        const body = await readJsonBody(req);
        const result = await createMonitorFromText(req, body);
        jsonResponse(res, 201, result);
        return;
      }

      if (req.method === "POST" && pathname === "/api/chat") {
        const body = await readJsonBody(req);
        const result = await handleChat(req, body);
        jsonResponse(res, result.status === "error" ? 400 : 200, result);
        return;
      }

      if (req.method === "POST" && pathname === "/videomemory-event") {
        const payload = await readJsonBody(req, 2 * 1024 * 1024);
        const result = await handleWakeup(payload, false);
        jsonResponse(res, result.duplicate || result.ignored ? 200 : 202, result);
        return;
      }

      if (req.method === "POST" && pathname === "/api/simulate-event") {
        const body = await readJsonBody(req);
        const state = await getState();
        const entry = cleanText(body.task_id) ? state.registry[cleanText(body.task_id)] : latestRegistryEntry(state);
        if (!entry) {
          jsonResponse(res, 409, { status: "error", error: "Create a monitor before simulating a wakeup." });
          return;
        }
        const eventId = cleanText(body.event_id) || `${BOT_ID}-sim-${Date.now()}`;
        const payload = {
          service: "videomemory",
          event_type: "task_update",
          event_id: eventId,
          idempotency_key: eventId,
          bot_id: entry.bot_id,
          io_id: entry.io_id,
          task_id: entry.task_id,
          task_description: entry.trigger_condition,
          task_done: true,
          task_status: "done",
          note: cleanText(body.note) || "A customer is at the apple counter and appears to be taking an apple.",
          note_frame_api_url: cleanText(body.note_frame_api_url),
          note_video_api_url: cleanText(body.note_video_api_url),
          observed_at: new Date().toISOString(),
        };
        const result = await handleWakeup(payload, true);
        jsonResponse(res, 202, result);
        return;
      }

      if (req.method === "POST" && pathname === "/api/fake-camera/register") {
        const publicBaseUrl = publicBaseFromRequest(req, configuredPublicBaseUrl);
        const result = await registerFakeCamera(publicBaseUrl);
        jsonResponse(res, 201, { status: "success", ...result });
        return;
      }

      if (req.method === "POST" && pathname === "/api/fake-camera/scene") {
        const body = await readJsonBody(req);
        const state = await getState();
        const scene = cleanText(body.scene) || "apple_counter";
        if (!["apple_counter", "customer", "apple_taken"].includes(scene)) {
          jsonResponse(res, 400, { status: "error", error: "scene must be apple_counter, customer, or apple_taken." });
          return;
        }
        state.fake_camera = { scene, updated_at: new Date().toISOString() };
        await persist(state);
        broadcast({ type: "fake_camera", scene, at: new Date().toISOString() });
        jsonResponse(res, 200, { status: "success", fake_camera: state.fake_camera });
        return;
      }

      if (req.method === "GET" && pathname === "/fake-camera/snapshot.ppm") {
        const state = await getState();
        const frame = buildFakeCameraFrame({
          scene: state.fake_camera?.scene || "apple_counter",
          pulse: Math.floor(Date.now() / 1000) % 2 === 0,
        });
        res.writeHead(200, {
          "Content-Type": "image/x-portable-pixmap",
          "Cache-Control": "no-store",
          "Content-Length": String(frame.length),
        });
        res.end(frame);
        return;
      }

      if (req.method === "GET" && pathname === "/fake-camera/preview.svg") {
        const state = await getState();
        textResponse(res, 200, fakeCameraPreviewSvg(state.fake_camera?.scene || "apple_counter"), "image/svg+xml");
        return;
      }

      if (req.method === "GET") {
        await serveStatic(req, res, pathname);
        return;
      }

      jsonResponse(res, 404, { status: "error", error: "Not found" });
    } catch (error) {
      const status = Number(error.status || 500);
      jsonResponse(res, status >= 400 && status < 600 ? status : 500, {
        status: "error",
        error: cleanText(error.message) || String(error),
        body: error.body,
      });
    }
  });

  const heartbeat = setInterval(() => {
    for (const client of [...clients]) {
      try {
        client.write(`event: heartbeat\ndata: ${JSON.stringify({ type: "heartbeat", at: new Date().toISOString() })}\n\n`);
      } catch {
        clients.delete(client);
      }
    }
  }, 15000);
  heartbeat.unref();

  server.voiceDemo = {
    port,
    videomemoryBaseUrl,
    realtimeModel,
    statePath,
    getState,
    handleWakeup,
    resetDemoState,
    runRealtimeTool,
  };
  return server;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const server = createVoiceDemoServer();
  const port = Number(process.env.VOICE_AGENT_DEMO_PORT || process.env.VOICE_DEMO_PORT || DEFAULT_PORT);
  const host = cleanText(process.env.VOICE_AGENT_DEMO_HOST || process.env.VOICE_DEMO_HOST || "127.0.0.1");
  server.listen(port, host, () => {
    const address = server.address();
    const displayHost = host === "0.0.0.0" || host === "::" ? "127.0.0.1" : host;
    process.stdout.write(`VideoMemory voice demo: http://${displayHost}:${address.port}\n`);
    process.stdout.write(`VideoMemory base URL: ${server.voiceDemo.videomemoryBaseUrl}\n`);
    process.stdout.write(`Webhook receiver: http://${displayHost}:${address.port}/videomemory-event\n`);
  });
}
