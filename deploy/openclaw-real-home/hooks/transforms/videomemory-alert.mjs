import fsSync from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const stateDir = path.resolve(__dirname, "..", "state");
const statePath = path.join(stateDir, "videomemory-alert-dedupe.json");
const registryPath = path.join(stateDir, "videomemory-task-actions.json");
const legacyRegistryPath = path.join(
  os.homedir(),
  ".openclaw",
  "hooks",
  "state",
  "videomemory-task-actions.json",
);
const sessionStorePath =
  process.env.OPENCLAW_SESSION_STORE_PATH ||
  path.join(os.homedir(), ".openclaw", "agents", "main", "sessions", "sessions.json");
const ttlSeconds = Number.parseFloat(
  process.env.OPENCLAW_VIDEOMEMORY_HOOK_DEDUPE_TTL_S || "300",
);
const notifyPattern =
  /\b(telegram|text me|notify me|message me|send me a text|send me an alert|sms|ping me)\b/i;

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function wantsTelegramNotification(payload) {
  const combined = [payload?.task_description, payload?.note].map(cleanText).join("\n");
  return notifyPattern.test(combined);
}

function makeRegistryKey(botId, ioId, taskId) {
  return [cleanText(botId), cleanText(ioId), cleanText(taskId)].join("|");
}

async function readRegistry() {
  for (const candidate of [registryPath, legacyRegistryPath]) {
    try {
      const raw = await fs.readFile(candidate, "utf8");
      const parsed = JSON.parse(raw);
      if (typeof parsed === "object" && parsed) {
        return parsed;
      }
    } catch {
      // Keep looking.
    }
  }
  return { version: 1, tasks: {} };
}

async function loadTaskAction(payload) {
  const registry = await readRegistry();
  const tasks = typeof registry?.tasks === "object" && registry?.tasks ? registry.tasks : {};
  const exactKey = makeRegistryKey(payload?.bot_id, payload?.io_id, payload?.task_id);
  if (tasks[exactKey]) {
    return tasks[exactKey];
  }

  for (const entry of Object.values(tasks)) {
    if (
      cleanText(entry?.task_id) === cleanText(payload?.task_id) &&
      cleanText(entry?.io_id) === cleanText(payload?.io_id)
    ) {
      return entry;
    }
  }
  return null;
}

function wantsExternalDelivery(entry) {
  return normalizeDeliveryMode(entry) === "telegram";
}

function wantsFrameAttachment(entry) {
  if (typeof entry?.include_note_frame === "boolean") {
    return entry.include_note_frame;
  }
  const value = cleanText(String(entry?.include_note_frame || "")).toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

function wantsVideoAttachment(entry) {
  if (typeof entry?.include_note_video === "boolean") {
    return entry.include_note_video;
  }
  const value = cleanText(String(entry?.include_note_video || "")).toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

function normalizeDeliveryMode(entry) {
  const value = cleanText(entry?.delivery_mode || "session").toLowerCase();
  if (value === "webchat") {
    return "session";
  }
  if (value === "telegram" || value === "internal" || value === "session") {
    return value;
  }
  return "session";
}

function fallbackSessionKey() {
  return "";
}

function loadSessionStoreEntry(sessionKey) {
  const normalizedKey = cleanText(sessionKey);
  if (!normalizedKey) {
    return null;
  }

  try {
    const raw = fsSync.readFileSync(sessionStorePath, "utf8");
    const parsed = JSON.parse(raw);
    const entry = parsed?.[normalizedKey];
    return typeof entry === "object" && entry ? entry : null;
  } catch {
    return null;
  }
}

function isHeartbeatOwnedSessionKey(sessionKey) {
  const entry = loadSessionStoreEntry(sessionKey);
  return cleanText(entry?.origin?.provider).toLowerCase() === "heartbeat";
}

function resolveSessionDelivery(entry) {
  const sessionKey = cleanText(entry?.delivery_session_key) || fallbackSessionKey();
  if (!sessionKey) {
    return "";
  }
  if (isHeartbeatOwnedSessionKey(sessionKey)) {
    return "";
  }
  return sessionKey;
}

function resolveTelegramTarget(entry) {
  return cleanText(entry?.delivery_target) || cleanText(process.env.OPENCLAW_TELEGRAM_OWNER_ID);
}

function noteIndicatesAbsence(note) {
  const value = cleanText(note);
  if (!value) {
    return false;
  }

  return [
    /\bno\b[\s\S]{0,80}\bvisible\b/i,
    /\bno\b[\s\S]{0,80}\bpresent\b/i,
    /\bno longer\b[\s\S]{0,40}\bvisible\b/i,
    /\bnot\b[\s\S]{0,30}\bvisible\b/i,
    /\bno\b[\s\S]{0,120}\b(?:card|cards|marker|markers|backpack|backpacks|bin|bins|person|people)\b[\s\S]{0,40}\b(?:visible|present)\b/i,
  ].some((pattern) => pattern.test(value));
}

function actionWantsAbsence(entry) {
  const preferred = [entry?.action_instruction, entry?.original_request]
    .map(cleanText)
    .filter(Boolean)
    .join("\n");
  const fallback = [entry?.trigger_condition, entry?.task_description]
    .map(cleanText)
    .filter(Boolean)
    .join("\n");
  const combined = preferred || fallback;

  if (!combined) {
    return false;
  }

  return /\b(disappear|disappears|disappeared|disappearance|gone|missing|not visible|no longer visible|left|leave|leaves|left the frame|out of frame|removed|remove|removal|stops? being visible|isn'?t visible|is not visible)\b/i.test(
    combined,
  );
}

function shouldSuppressRegistryDrivenEvent(payload, entry) {
  const note = cleanText(payload?.note);
  if (!noteIndicatesAbsence(note)) {
    return false;
  }

  return !actionWantsAbsence(entry);
}

function buildSavedMediaContext(payload, entry) {
  const lines = [];
  const taskApiUrl = cleanText(payload?.task_api_url);
  const noteId =
    payload?.note_id === 0 || payload?.note_id
      ? cleanText(String(payload.note_id))
      : "";
  const noteHasFrame =
    payload?.note_has_frame === true ||
    Boolean(cleanText(payload?.note_frame_api_url || payload?.note_frame_api_path));
  const noteFrameUrl = cleanText(payload?.note_frame_api_url);
  const noteHasVideo =
    payload?.note_has_video === true ||
    Boolean(cleanText(payload?.note_video_api_url || payload?.note_video_api_path));
  const noteVideoUrl = cleanText(payload?.note_video_api_url);

  if (taskApiUrl) {
    lines.push(`Task API URL: ${taskApiUrl}`);
  }
  if (noteId) {
    lines.push(`Triggering note ID: ${noteId}`);
  }

  const wantsFrame = wantsFrameAttachment(entry);
  const wantsVideo = wantsVideoAttachment(entry);
  if (!wantsFrame && !wantsVideo) {
    return lines;
  }

  if (wantsVideo && noteHasVideo && noteVideoUrl) {
    lines.push(`Saved triggering video URL: ${noteVideoUrl}`);
    lines.push(
      "This task explicitly requested the saved triggering evidence clip. Fetch that exact saved clip and use it in the follow-up instead of taking a new live snapshot.",
    );
    lines.push(
      "If your delivery path supports media, attach the saved clip. Otherwise mention that a saved clip is available at the URL.",
    );
  } else if (wantsVideo) {
    lines.push(
      "This task explicitly requested the saved triggering evidence clip, but this webhook did not include a saved video URL for the triggering note.",
    );
  }

  if (wantsFrame && noteHasFrame && noteFrameUrl) {
    lines.push(`Saved triggering frame URL: ${noteFrameUrl}`);
    lines.push(
      "This task explicitly requested the saved triggering frame. Fetch that exact saved frame and use it in the follow-up instead of taking a new live snapshot.",
    );
    lines.push(
      "If your delivery path supports media, attach the saved frame. Otherwise mention that a saved frame is available at the URL.",
    );
  } else if (wantsFrame) {
    lines.push(
      "This task explicitly requested the saved triggering frame, but this webhook did not include a saved frame URL for the triggering note.",
    );
  }
  return lines;
}

function buildRegistryDrivenMessage(payload, entry, options = {}) {
  const originalRequest =
    cleanText(entry?.original_request) || cleanText(payload?.task_description) || "VideoMemory task";
  const triggerCondition =
    cleanText(entry?.trigger_condition) ||
    cleanText(entry?.task_description) ||
    cleanText(payload?.task_description) ||
    "Watch for the requested visual condition.";
  const actionInstruction =
    cleanText(entry?.action_instruction) || "Send one concise user-facing alert.";
  const note = cleanText(payload?.note) || "VideoMemory reported an update.";
  const ioId = cleanText(payload?.io_id) || "unknown device";
  const taskId = cleanText(payload?.task_id) || "unknown";
  const savedFrameContext = buildSavedMediaContext(payload, entry);
  const actionNeedsFreshLookup = /\b(search|web search|look up|lookup|find|fetch|check|inspect|get the latest|current|today|now|price|weather|news|headline|first result|top result)\b/i.test(
    actionInstruction,
  );
  const externalDelivery = options.externalDelivery === true;

  return [
    "A VideoMemory trigger evaluation is requested.",
    `Original request context: ${originalRequest}`,
    `Trigger condition: ${triggerCondition}`,
    `Authoritative requested action if the trigger happened now: ${actionInstruction}`,
    `Observation: ${note}`,
    `Device: ${ioId}`,
    `Task ID: ${taskId}`,
    ...savedFrameContext,
    "If the authoritative requested action differs from the original request context, follow the authoritative requested action.",
    "You may use tools if needed to perform the requested action right now.",
    actionNeedsFreshLookup
      ? "This requested action appears to require a fresh lookup. Use tools now instead of relying on any earlier or stale setup-time result."
      : "If the requested action already contains specific facts or wording to relay, include those details instead of replacing them with a generic alert.",
    "Reply with exactly NO_REPLY if the observation does not show the trigger condition happening now.",
    "Ignore unrelated scene details or correction-only notes that do not affect the trigger condition.",
    externalDelivery
      ? "Your reply will be delivered to the end user automatically."
      : "Your reply will stay inside OpenClaw unless the routing layer says otherwise.",
    externalDelivery
      ? "If the trigger condition is satisfied now, reply with exactly one short user-facing alert sentence and nothing else."
      : "If the trigger condition is satisfied now, complete the requested action for the user. Keep it brief, but do not omit required details. One or two sentences is fine if needed.",
    externalDelivery
      ? "Do not mention Telegram, chat routing, tools, internal context, or that delivery is automatic."
      : "Do not add internal workflow commentary.",
  ].join("\n");
}

function buildExplicitMessage(payload) {
  const taskDescription = cleanText(payload?.task_description) || "VideoMemory task";
  const note = cleanText(payload?.note) || "VideoMemory reported an update.";
  const ioId = cleanText(payload?.io_id) || "unknown device";
  const taskId = cleanText(payload?.task_id) || "unknown";
  const savedFrameContext = buildSavedMediaContext(payload, null);
  return [
    "A VideoMemory detection requires a Telegram notification.",
    `Task: ${taskDescription}`,
    `Observation: ${note}`,
    `Device: ${ioId}`,
    `Task ID: ${taskId}`,
    ...savedFrameContext,
    "Reply with exactly one short user-facing alert sentence.",
  ].join("\n");
}

function buildNeutralMessage(payload) {
  const taskDescription = cleanText(payload?.task_description) || "VideoMemory task";
  const note = cleanText(payload?.note) || "VideoMemory reported an update.";
  const ioId = cleanText(payload?.io_id) || "unknown device";
  const taskId = cleanText(payload?.task_id) || "unknown";
  return [
    "A VideoMemory detection arrived that does not explicitly request user messaging.",
    `Task: ${taskDescription}`,
    `Observation: ${note}`,
    `Device: ${ioId}`,
    `Task ID: ${taskId}`,
    "Reply with exactly one short internal acknowledgement sentence.",
  ].join("\n");
}

async function readState() {
  try {
    const raw = await fs.readFile(statePath, "utf8");
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed ? parsed : {};
  } catch {
    return {};
  }
}

async function writeState(state) {
  await fs.mkdir(stateDir, { recursive: true });
  await fs.writeFile(statePath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

async function rememberEvent(eventId) {
  if (!eventId) {
    return false;
  }
  const now = Date.now();
  const ttlMs = Number.isFinite(ttlSeconds) && ttlSeconds > 0 ? ttlSeconds * 1000 : 0;
  const state = await readState();
  const nextState = {};
  for (const [key, seenAt] of Object.entries(state)) {
    if (!ttlMs || typeof seenAt !== "number" || now - seenAt <= ttlMs) {
      nextState[key] = seenAt;
    }
  }
  if (typeof nextState[eventId] === "number") {
    await writeState(nextState);
    return true;
  }
  nextState[eventId] = now;
  await writeState(nextState);
  return false;
}

export default async function videomemoryAlertTransform(ctx) {
  const payload = ctx?.payload ?? {};
  const eventId = cleanText(payload?.event_id);
  if (await rememberEvent(eventId)) {
    return null;
  }

  const taskAction = await loadTaskAction(payload);
  if (taskAction) {
    if (shouldSuppressRegistryDrivenEvent(payload, taskAction)) {
      return null;
    }

    const deliveryMode = normalizeDeliveryMode(taskAction);
    const deliverExternally = wantsExternalDelivery(taskAction);
    const sessionKey = deliveryMode === "session" ? resolveSessionDelivery(taskAction) : "";
    const telegramTarget = deliveryMode === "telegram" ? resolveTelegramTarget(taskAction) : "";
    return {
      kind: "agent",
      ...(sessionKey ? { sessionKey } : {}),
      deliver: deliverExternally,
      ...(deliverExternally
        ? {
            channel: "telegram",
            to: telegramTarget,
          }
        : {}),
      message: buildRegistryDrivenMessage(payload, taskAction, {
        externalDelivery: deliverExternally,
      }),
    };
  }

  if (wantsTelegramNotification(payload)) {
    return {
      kind: "agent",
      deliver: true,
      channel: "telegram",
      to: process.env.OPENCLAW_TELEGRAM_OWNER_ID,
      message: buildExplicitMessage(payload),
    };
  }

  return {
    kind: "agent",
    deliver: false,
    message: buildNeutralMessage(payload),
  };
}
