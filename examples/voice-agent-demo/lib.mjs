export const BOT_ID = "voice-agent-demo";
const DEFAULT_IO_ID = "browser_facetime";
const DEFAULT_MONITOR_TYPE = "general";

const WORD_NUMBERS = new Map([
  ["zero", 0],
  ["one", 1],
  ["two", 2],
  ["three", 3],
  ["four", 4],
  ["five", 5],
  ["six", 6],
  ["seven", 7],
  ["eight", 8],
  ["nine", 9],
  ["ten", 10],
  ["eleven", 11],
  ["twelve", 12],
]);

export function cleanText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function isSetupCommand(text) {
  const value = cleanText(text).toLowerCase();
  if (!value) return false;
  return /\b(shopkeeper|wakeup|wake up|watch|monitor|when|if|your job|track|count|tally|record)\b/.test(value);
}

export function isVisualMemoryRequest(text) {
  const value = cleanText(text).toLowerCase();
  return (
    /\b(each time|every time|whenever|running total|total so far|keep track|tally|record each|record every|count each|count every)\b/.test(value) ||
    (/\b(watch|monitor|track|count|record|tally)\b/.test(value) && /\b(total|sum|running|each|every|whenever|so far)\b/.test(value))
  );
}

export function isFingerCounterRequest(text) {
  const value = cleanText(text).toLowerCase();
  return /\bfingers?\b/.test(value) && isVisualMemoryRequest(value);
}

export function normalizeMonitorLifecycle(value) {
  const normalized = cleanText(value).toLowerCase().replace(/[-\s]+/g, "_");
  if (["persistent", "repeat", "repeating", "until_stopped", "continuous"].includes(normalized)) return "persistent";
  if (["one_shot", "oneshot", "one_off", "once", "single"].includes(normalized)) return "one_shot";
  return "auto";
}

export function inferMonitorLifecycle(text, requested = "auto") {
  const explicit = normalizeMonitorLifecycle(requested);
  if (explicit !== "auto") return explicit;
  const lower = cleanText(text).toLowerCase();
  if (/\b(each time|every time|whenever|keep watching|keep monitoring|until i stop|until stopped|persist(?:ent)?|continuously|running total|keep track|tally)\b/.test(lower)) {
    return "persistent";
  }
  if (/\b(one time|once|one[-\s]?off|first time|single time|just once|remind me when|tell me when|wake me when)\b/.test(lower)) {
    return "one_shot";
  }
  if (isVisualMemoryRequest(lower)) return "persistent";
  return "one_shot";
}

function sentenceCase(value) {
  const text = cleanText(value);
  if (!text) return "";
  return text[0].toUpperCase() + text.slice(1);
}

function stripLeadIn(value) {
  return cleanText(value)
    .replace(/^(please\s+)?(watch|monitor|wake\s+up\s+when|wake\s+me\s+when|tell\s+me\s+when)\s+/i, "")
    .replace(/^(if|when)\s+/i, "")
    .replace(/[.?!]+$/g, "");
}

export function inferConversationContext(text, previousContext = {}) {
  const raw = cleanText(text);
  const lower = raw.toLowerCase();
  const next = { ...previousContext };
  if (/\bapple|apples|shopkeeper|customer|ledger|charge\b/.test(lower)) {
    next.persona = "apple_shopkeeper";
    next.domain = "apple_stand";
    next.unit_price = 1;
    next.item = "apple";
  }
  if (isVisualMemoryRequest(raw)) {
    next.persona = "visual_memory";
    next.domain = "visual_memory";
  }
  next.last_user_request = raw || cleanText(previousContext.last_user_request);
  return next;
}

function hasAppleContext(text, context = {}) {
  const lower = cleanText(text).toLowerCase();
  const explicitApple = /\bapple|apples|shopkeeper|customer|ledger|charge\b/.test(lower);
  const contextualApple =
    (context.persona === "apple_shopkeeper" || context.domain === "apple_stand" || context.item === "apple") &&
    /\b(one|them|visitor|customer|counter|walks?\s+up|takes?|taking|took|reaches?|removing|picked\s+up)\b/.test(lower) &&
    !/\b(cup|mug|door|phone|dog|cat|book|bottle|marker|package|person\s+wearing)\b/.test(lower);
  return (
    explicitApple ||
    contextualApple
  );
}

function extractCondition(text, context = {}) {
  const raw = cleanText(text);

  if (hasAppleContext(raw, context)) {
    return "Complete when a person is visibly at the apple stand, holding an apple, reaching for the apples, or removing an apple from the counter.";
  }

  if (isVisualMemoryRequest(raw)) {
    return visualMemoryTriggerCondition(buildVisualMemorySpec(raw));
  }

  const notifyWhenMatch = raw.match(/\b(?:notify|tell|alert)\s+(?:me|the user)?\s*(?:when|if)\s+(.+?)(?:[.?!]|,\s*(?:then|please)\b|\s+then\b|$)/i);
  if (notifyWhenMatch) {
    return `${sentenceCase(stripLeadIn(notifyWhenMatch[1]))}.`;
  }

  const whenMatch = raw.match(/\b(?:when|if)\s+(.+?)(?:[.?!]|,\s*(?:then|please)\b|\s+then\b|$)/i);
  if (whenMatch) {
    return `${sentenceCase(stripLeadIn(whenMatch[1]))}.`;
  }

  return `${sentenceCase(stripLeadIn(raw))}.`;
}

function extractAction(text, persona) {
  const raw = cleanText(text);
  if (persona === "apple_shopkeeper") {
    return "Greet the visitor as the apple shopkeeper, ask for their name, confirm how many apples they took, charge $1 per apple, and add the transaction to the ledger.";
  }
  if (persona === "visual_memory") {
    return "Silently extract the requested observation from the frame, update the local visual memory, and re-arm the monitor for the next new observation. Do not speak automatically.";
  }

  const thenMatch = raw.match(/\bthen\s+(.+)$/i);
  if (thenMatch) {
    return sentenceCase(thenMatch[1]);
  }

  const notifyThatMatch = raw.match(/\b(?:notify|tell|alert)\s+(?:me|the user)?\s*(?:once\s+)?that\s+(.+?)(?:[.?!]|$)/i);
  if (notifyThatMatch) {
    return sentenceCase(notifyThatMatch[1]);
  }

  const sayMatch = raw.match(/\bsay\s+(.+)$/i);
  if (sayMatch) {
    return `Say: ${cleanText(sayMatch[1])}`;
  }

  return "Tell the user that the visual condition happened.";
}

export function buildTaskPlan(text, options = {}) {
  const command = cleanText(text);
  if (!command) {
    throw new Error("Enter a spoken or typed instruction first.");
  }
  if (!isSetupCommand(command)) {
    throw new Error("That does not look like a wakeup condition. Include watch, when, if, wake up, or the shopkeeper setup.");
  }

  const context = options.context || {};
  const visualMemory = !hasAppleContext(command, context) && isVisualMemoryRequest(command)
    ? buildVisualMemorySpec(command)
    : null;
  const persona = visualMemory
    ? "visual_memory"
    : hasAppleContext(command, context)
    ? "apple_shopkeeper"
    : "generic";
  const triggerCondition = extractCondition(command, context);
  const actionInstruction = extractAction(command, persona);
  const lifecycle = inferMonitorLifecycle(command, options.lifecycle);
  const requestedMonitorType = cleanText(options.monitorType || options.monitor_type).toLowerCase();
  const monitorType = ["general", "binary"].includes(requestedMonitorType)
    ? requestedMonitorType
    : DEFAULT_MONITOR_TYPE;

  return {
    bot_id: BOT_ID,
    io_id: cleanText(options.ioId) || DEFAULT_IO_ID,
    persona,
    original_request: command,
    trigger_condition: triggerCondition,
    action_instruction: actionInstruction,
    lifecycle,
    monitor_type: monitorType,
    silent_wakeup: persona === "visual_memory",
    rearm_on_wakeup: lifecycle === "persistent",
    visual_memory: visualMemory,
    save_note_frames: true,
    save_note_videos: true,
    conversation_context: inferConversationContext(command, context),
  };
}

export function buildVideoMemoryTaskPayload(plan) {
  if (!plan || !cleanText(plan.io_id) || !cleanText(plan.trigger_condition)) {
    throw new Error("Missing io_id or trigger condition.");
  }
  const monitorType = cleanText(plan.monitor_type) || DEFAULT_MONITOR_TYPE;
  const triggerCondition = cleanText(plan.trigger_condition);
  const isVisualMemory = cleanText(plan.persona) === "visual_memory" && plan.visual_memory;
  const taskDescription = monitorType === "general" && isVisualMemory
    ? [
      `Visual trigger: ${triggerCondition}`,
      "Set task_done=true as soon as the visual trigger is clearly satisfied.",
      `Extraction rule: ${cleanText(plan.visual_memory.extraction_instruction) || "Extract the value or concise observation for this single event."}`,
      "When task_done=true, write task_note as JSON only with this exact shape: {\"observed\":true,\"value\":number|string,\"confidence\":\"high\"|\"medium\"|\"low\",\"reason\":string}.",
      "For totals/counts/sums, value must be the numeric amount for this single observation, not the cumulative total.",
      "If the trigger is absent, unclear, ambiguous, partially obscured, or unchanged, keep task_done=false and write a concise note about what is visible.",
    ].join(" ")
    : monitorType === "general"
    ? [
      `Visual trigger: ${triggerCondition}`,
      "Set task_done=true as soon as the visual trigger is clearly satisfied.",
      "If the trigger is absent, unclear, ambiguous, partially obscured, or unchanged, keep task_done=false and write a concise note about what is visible.",
    ].join(" ")
    : triggerCondition;
  return {
    io_id: cleanText(plan.io_id),
    task_description: taskDescription,
    bot_id: cleanText(plan.bot_id) || BOT_ID,
    monitor_type: monitorType,
    save_note_frames: plan.save_note_frames !== false,
    save_note_videos: plan.save_note_videos !== false,
  };
}

function splitSentences(text) {
  return cleanText(text)
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => cleanText(sentence))
    .filter(Boolean);
}

export function extractRepeatableCondition(text) {
  const raw = cleanText(text);
  const eachMatch = raw.match(/\b(?:each time|every time|whenever)\s+(.+?)(?:,\s*(?:then|add|record|count|tally|log|keep|please)\b|\s+(?:then|add|record|count|tally|log|keep)\b|[.?!]|$)/i);
  if (eachMatch) {
    return sentenceCase(stripLeadIn(eachMatch[1]));
  }
  const sentences = splitSentences(raw);
  const reportOnly = /\b(only\s+report|report\s+when|tell\s+me\s+when\s+i\s+ask|when\s+i\s+ask|when\s+the\s+user\s+asks|total\s+so\s+far)\b/i;
  const candidate = sentences.find((sentence) => !reportOnly.test(sentence) && /\b(watch|monitor|track|count|record|tally)\b/i.test(sentence)) ||
    sentences.find((sentence) => !reportOnly.test(sentence)) ||
    raw;
  return sentenceCase(stripLeadIn(
    candidate
      .replace(/\b(?:add|record|count|tally|log|keep)\s+.+$/i, "")
      .replace(/\b(?:do not|don't|only report|only tell).+$/i, ""),
  ));
}

function inferVisualMemoryMode(text) {
  const lower = cleanText(text).toLowerCase();
  if (/\b(total|sum|add|running|tally|count)\b/.test(lower)) return "numeric_total";
  return "event_log";
}

function inferVisualMemoryLabel(text) {
  const lower = cleanText(text).toLowerCase();
  if (/\bfingers?\b/.test(lower)) return "finger count";
  if (/\bapple|apples\b/.test(lower)) return "apple count";
  if (/\bpeople|persons?\b/.test(lower)) return "people count";
  const target = extractRepeatableCondition(text)
    .replace(/^(the|a|an)\s+/i, "")
    .replace(/[.?!]+$/g, "");
  return target ? target.slice(0, 64) : "visual observations";
}

export function buildVisualMemorySpec(text) {
  const request = cleanText(text);
  const eventCondition = extractRepeatableCondition(request);
  const mode = inferVisualMemoryMode(request);
  const label = inferVisualMemoryLabel(request);
  return {
    mode,
    label,
    event_condition: eventCondition,
    original_request: request,
    extraction_instruction: mode === "numeric_total"
      ? "Extract the numeric amount to add for this single observation. Do not return the running total."
      : "Extract a concise observation to append to the log for this single event.",
  };
}

export function visualMemoryTriggerCondition(spec = {}, previousValue = null) {
  const condition = cleanText(spec.event_condition) || "the requested visual event is clearly visible";
  const previousClause = previousValue !== null && previousValue !== undefined && cleanText(previousValue)
    ? ` The observation should be meaningfully new or changed from the previous extracted value: ${cleanText(previousValue)}.`
    : "";
  return `Complete when this requested visual event is clearly visible: ${condition}. Do not complete when the view is unclear, ambiguous, partially obscured, or unchanged.${previousClause}`;
}

export function parseVisualMemoryObservation(text, spec = {}) {
  const raw = cleanText(text);
  if (!raw) return { observed: false, value: null, confidence: "low", reason: "empty response" };
  const lower = raw.toLowerCase();
  const jsonMatch = raw.match(/\{[\s\S]*\}/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]);
      const rawValue = parsed.value ?? parsed.amount ?? parsed.count ?? parsed.number ?? parsed.finger_count ?? parsed.fingers ?? parsed.observation ?? null;
      const mode = cleanText(spec.mode);
      const value = mode === "numeric_total" ? Number(rawValue) : cleanText(rawValue);
      return {
        observed: parsed.observed !== false && rawValue !== null && rawValue !== undefined && rawValue !== "",
        value: mode === "numeric_total" && Number.isFinite(value) ? value : value || null,
        confidence: cleanText(parsed.confidence) || "medium",
        reason: cleanText(parsed.reason),
        raw: parsed,
      };
    } catch {
      // Fall through to text parsing.
    }
  }
  if (spec.mode === "numeric_total") {
    const digitMatch = lower.match(/\b(?:value|amount|count|number|total|showing|holding up|held up|raised)\s*[:=]?\s*(-?\d+(?:\.\d+)?)\b/) ||
      lower.match(/\b(-?\d+(?:\.\d+)?)\s+(?:raised\s+)?(?:fingers?|items?|objects?|people|apples?)\b/);
    if (digitMatch) {
      return { observed: true, value: Number(digitMatch[1]), confidence: "medium", reason: "parsed numeric text" };
    }
  }
  for (const [word, number] of WORD_NUMBERS.entries()) {
    if (number >= 0 && number <= 12) {
      const pattern = new RegExp(`\\b(?:${word})\\s+(?:raised\\s+)?(?:fingers?|items?|objects?|people|apples?)\\b|\\b(?:showing|holding up|held up|raised|count(?:ed)?)\\s+${word}\\b`, "i");
      if (pattern.test(raw)) {
        return { observed: true, value: number, confidence: "medium", reason: "parsed number word" };
      }
    }
  }
  if (/\b(no|none|null|unclear|ambiguous|not visible|cannot|can't)\b/.test(lower)) {
    return { observed: false, value: null, confidence: "low", reason: raw };
  }
  return spec.mode === "event_log"
    ? { observed: true, value: raw, confidence: "low", reason: "used free-text observation" }
    : { observed: false, value: null, confidence: "low", reason: raw };
}

export function parseFingerCount(text) {
  const parsed = parseVisualMemoryObservation(text, { mode: "numeric_total", label: "finger count" });
  return Number.isFinite(Number(parsed.value)) ? Number(parsed.value) : null;
}

export function summarizeVisualMemory(memory) {
  const observations = Array.isArray(memory?.observations) ? memory.observations : [];
  const mode = cleanText(memory?.mode || memory?.spec?.mode);
  const label = cleanText(memory?.label || memory?.spec?.label) || "visual observations";
  if (observations.length === 0) {
    return `No ${label} have been recorded yet.`;
  }
  if (mode === "numeric_total") {
    const total = Number.isFinite(Number(memory?.total))
      ? Number(memory.total)
      : observations.reduce((sum, entry) => sum + Number(entry.value ?? entry.count ?? 0), 0);
    const sequence = observations.map((entry) => entry.value ?? entry.count).join(" + ");
    return `${sentenceCase(label)} total: ${total}. Observations: ${sequence}.`;
  }
  const rows = observations.map((entry, index) => `${index + 1}. ${entry.value || entry.observation || entry.caption || "observed"}`).join(" ");
  return `${sentenceCase(label)} log: ${rows}`;
}

export function summarizeFingerCounter(counter) {
  return summarizeVisualMemory({ ...counter, mode: "numeric_total", label: "finger count" });
}

export function parseLedgerEntry(text, pending = {}) {
  const raw = cleanText(text);
  const lower = raw.toLowerCase();
  if (!raw) {
    return { complete: false, name: cleanText(pending.name), apple_count: null, missing: ["name", "apple_count"] };
  }

  let name = cleanText(pending.name);
  const explicitName = raw.match(/\b(?:my name is|name is|i am|i'm|this is)\s+([a-z][a-z .'-]{0,48}?)(?:[,.;]|\s+(?:and|with|taking|took|got|bought|grabbed)\b|$)/i);
  const subjectName = raw.match(/^([a-z][a-z.'-]{1,30})\s+(?:took|takes|got|bought|grabbed)\b/i);
  if (explicitName) {
    name = sentenceCase(explicitName[1].replace(/\b(i|we|they|he|she)\b.*$/i, ""));
  } else if (subjectName) {
    name = sentenceCase(subjectName[1]);
  }

  let appleCount = Number.isFinite(Number(pending.apple_count)) ? Number(pending.apple_count) : null;
  const digitMatch = lower.match(/(?:^|\b)(\d{1,2})\s+(?:apple|apples)\b/);
  const tookDigitMatch = lower.match(/\b(?:took|takes|got|bought|grabbed|taking)\s+(\d{1,2})\b/);
  if (digitMatch || tookDigitMatch) {
    appleCount = Number((digitMatch || tookDigitMatch)[1]);
  } else {
    for (const [word, number] of WORD_NUMBERS.entries()) {
      const pattern = new RegExp(`\\b(?:${word})\\s+(?:apple|apples)\\b|\\b(?:took|takes|got|bought|grabbed|taking)\\s+${word}\\b`, "i");
      if (pattern.test(raw)) {
        appleCount = number;
        break;
      }
    }
  }
  if (appleCount === null && /\b(?:an|a)\s+apple\b/i.test(raw)) {
    appleCount = 1;
  }

  const missing = [];
  if (!name) missing.push("name");
  if (!Number.isInteger(appleCount) || appleCount < 1) missing.push("apple_count");
  if (Number.isInteger(appleCount) && appleCount > 50) {
    return {
      complete: false,
      name,
      apple_count: appleCount,
      missing: [],
      error: "Apple count is too high for the demo ledger.",
    };
  }

  return {
    complete: missing.length === 0,
    name,
    apple_count: Number.isInteger(appleCount) ? appleCount : null,
    amount_due: Number.isInteger(appleCount) && appleCount > 0 ? appleCount : null,
    missing,
  };
}

export function summarizeLedger(ledger) {
  const entries = Array.isArray(ledger) ? ledger : [];
  if (entries.length === 0) {
    return "The ledger is empty.";
  }
  const totalApples = entries.reduce((sum, entry) => sum + Number(entry.apple_count || 0), 0);
  const totalDue = entries.reduce((sum, entry) => sum + Number(entry.amount_due || 0), 0);
  const rows = entries
    .map((entry) => `${entry.name}: ${entry.apple_count} apple${Number(entry.apple_count) === 1 ? "" : "s"}, $${entry.amount_due}`)
    .join("; ");
  return `${rows}. Total: ${totalApples} apple${totalApples === 1 ? "" : "s"}, $${totalDue}.`;
}

export function buildWakeupMessage(registryEntry, payload = {}) {
  const note = cleanText(payload.note).replace(/[.?!]+$/g, "");
  if (registryEntry?.persona === "apple_shopkeeper") {
    return note
      ? `I saw activity at the apple stand: ${note}. Hi, welcome. What's your name, and how many apples are you taking? Apples are $1 each.`
      : "I saw activity at the apple stand. Hi, welcome. What's your name, and how many apples are you taking? Apples are $1 each.";
  }
  const action = cleanText(registryEntry?.action_instruction);
  if (/^say\b:?/i.test(action)) {
    return cleanText(action.replace(/^say\b:?\s*/i, ""));
  }
  if (action && action !== "Tell the user that the visual condition happened.") {
    return action;
  }
  const condition = cleanText(registryEntry?.trigger_condition)
    .replace(/\bwhen that happens\b.*$/i, "")
    .replace(/[.?!]+$/g, "");
  return condition
    ? `Detected: ${condition}.`
    : (note ? `VideoMemory woke me up: ${note}` : "VideoMemory woke me up.");
}

export function normalizeEventId(payload) {
  return cleanText(payload?.idempotency_key) || cleanText(payload?.event_id) || "";
}

function drawRect(pixels, width, height, x0, y0, x1, y1, color) {
  const left = Math.max(0, Math.min(width - 1, x0));
  const right = Math.max(0, Math.min(width - 1, x1));
  const top = Math.max(0, Math.min(height - 1, y0));
  const bottom = Math.max(0, Math.min(height - 1, y1));
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const idx = (y * width + x) * 3;
      pixels[idx] = color[0];
      pixels[idx + 1] = color[1];
      pixels[idx + 2] = color[2];
    }
  }
}

function drawCircle(pixels, width, height, cx, cy, radius, color) {
  const radiusSq = radius * radius;
  for (let y = Math.max(0, cy - radius); y <= Math.min(height - 1, cy + radius); y += 1) {
    for (let x = Math.max(0, cx - radius); x <= Math.min(width - 1, cx + radius); x += 1) {
      const dx = x - cx;
      const dy = y - cy;
      if (dx * dx + dy * dy <= radiusSq) {
        const idx = (y * width + x) * 3;
        pixels[idx] = color[0];
        pixels[idx + 1] = color[1];
        pixels[idx + 2] = color[2];
      }
    }
  }
}

export function buildFakeCameraFrame(options = {}) {
  const width = Number(options.width || 480);
  const height = Number(options.height || 270);
  const scene = cleanText(options.scene) || "apple_counter";
  const pulse = Boolean(options.pulse);
  const pixels = Buffer.alloc(width * height * 3, 236);

  drawRect(pixels, width, height, 0, 0, width - 1, height - 1, [235, 238, 241]);
  drawRect(pixels, width, height, 0, Math.floor(height * 0.62), width - 1, height - 1, [144, 106, 68]);
  drawRect(pixels, width, height, 0, Math.floor(height * 0.62), width - 1, Math.floor(height * 0.66), [101, 70, 43]);

  const appleY = Math.floor(height * 0.56);
  const appleXs = [170, 210, 250, 290, 330];
  for (let i = 0; i < appleXs.length; i += 1) {
    drawCircle(pixels, width, height, appleXs[i], appleY + (i % 2) * 8, 22, i % 2 ? [71, 150, 72] : [210, 47, 44]);
    drawRect(pixels, width, height, appleXs[i] - 2, appleY - 30 + (i % 2) * 8, appleXs[i] + 2, appleY - 18 + (i % 2) * 8, [75, 55, 37]);
  }

  if (scene === "customer" || scene === "apple_taken") {
    drawCircle(pixels, width, height, 98, 92, 32, [226, 185, 143]);
    drawRect(pixels, width, height, 62, 126, 134, 238, [45, 88, 145]);
    drawRect(pixels, width, height, 126, 154, 214, 178, [226, 185, 143]);
  }
  if (scene === "apple_taken") {
    drawCircle(pixels, width, height, 220, 146, 19, [210, 47, 44]);
  }

  drawRect(pixels, width, height, 14, 14, 74, 74, pulse ? [0, 132, 196] : [245, 204, 65]);
  const header = Buffer.from(`P6\n${width} ${height}\n255\n`, "ascii");
  return Buffer.concat([header, pixels]);
}

export function fakeCameraPreviewSvg(scene = "apple_counter") {
  const customer = scene === "customer" || scene === "apple_taken";
  const taken = scene === "apple_taken";
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270" viewBox="0 0 480 270">
  <rect width="480" height="270" fill="#edf0f2"/>
  <rect y="168" width="480" height="102" fill="#906a44"/>
  <rect y="168" width="480" height="12" fill="#65462b"/>
  ${[170, 210, 250, 290, 330].map((x, index) => `<circle cx="${x}" cy="${152 + (index % 2) * 8}" r="22" fill="${index % 2 ? "#479648" : "#d22f2c"}"/><rect x="${x - 2}" y="${122 + (index % 2) * 8}" width="4" height="13" fill="#4b3725"/>`).join("")}
  ${customer ? '<circle cx="98" cy="92" r="32" fill="#e2b98f"/><rect x="62" y="126" width="72" height="112" fill="#2d5891"/><rect x="126" y="154" width="88" height="24" fill="#e2b98f"/>' : ""}
  ${taken ? '<circle cx="220" cy="146" r="19" fill="#d22f2c"/>' : ""}
  <text x="20" y="34" fill="#111827" font-family="Arial" font-size="18">Fake VideoMemory camera</text>
</svg>`;
}
