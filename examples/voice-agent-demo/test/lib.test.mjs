import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildFakeCameraFrame,
  buildTaskPlan,
  buildVideoMemoryTaskPayload,
  buildWakeupMessage,
  fakeCameraPreviewSvg,
  inferConversationContext,
  inferMonitorLifecycle,
  isSetupCommand,
  parseLedgerEntry,
  parseVisualMemoryObservation,
  summarizeLedger,
  summarizeVisualMemory,
} from "../lib.mjs";

test("shopkeeper prompt compiles to a general VideoMemory task without semantic filter fields", () => {
  const plan = buildTaskPlan(
    "Please be a shopkeeper. Watch these apples and wake up if someone takes one.",
    { ioId: "browser_facetime" },
  );
  const payload = buildVideoMemoryTaskPayload(plan);

  assert.equal(plan.persona, "apple_shopkeeper");
  assert.equal(payload.monitor_type, "general");
  assert.equal(payload.io_id, "browser_facetime");
  assert.equal(payload.save_note_frames, true);
  assert.equal(payload.save_note_videos, true);
  assert.ok(payload.task_description.includes("apple stand"));
  assert.equal(Object.hasOwn(payload, "semantic_filter_keywords"), false);
  assert.equal(Object.hasOwn(payload, "required_keywords"), false);
  assert.equal(Object.hasOwn(payload, "semantic_filter_config"), false);
});

test("generic when/then command compiles to trigger and action", () => {
  const plan = buildTaskPlan("When a blue cup is visible, then say the cup arrived.", { ioId: "net0" });
  assert.equal(plan.io_id, "net0");
  assert.equal(plan.persona, "generic");
  assert.equal(plan.trigger_condition, "A blue cup is visible.");
  assert.equal(plan.action_instruction, "Say the cup arrived.");
});

test("notify-when command keeps the VideoMemory trigger separate from the action", () => {
  const plan = buildTaskPlan(
    "Watch the live camera view and notify the user when a phone is visible in the frame. When a phone is seen, tell the user that a phone is visible.",
    { ioId: "browser_facetime" },
  );
  const payload = buildVideoMemoryTaskPayload(plan);

  assert.equal(plan.trigger_condition, "A phone is visible in the frame.");
  assert.equal(plan.action_instruction, "A phone is visible");
  assert.match(payload.task_description, /Visual trigger: A phone is visible in the frame\./);
  assert.match(payload.task_description, /Set task_done=true/);
});

test("repeated visual-memory prompt compiles to a persistent silent monitor", () => {
  const plan = buildTaskPlan(
    "Watch the live camera for fingers. Each time I hold up fingers, add that number to a running total. Only report when I ask for the total.",
    { ioId: "browser_facetime" },
  );
  const payload = buildVideoMemoryTaskPayload(plan);

  assert.equal(plan.persona, "visual_memory");
  assert.equal(plan.lifecycle, "persistent");
  assert.equal(plan.silent_wakeup, true);
  assert.equal(plan.rearm_on_wakeup, true);
  assert.match(plan.trigger_condition, /hold up fingers/i);
  assert.doesNotMatch(plan.trigger_condition, /asks for the total/i);
  assert.equal(payload.monitor_type, "general");
});

test("monitor type can still be explicitly set to binary", () => {
  const plan = buildTaskPlan("When a blue cup is visible, then say cup.", {
    ioId: "net0",
    monitorType: "binary",
  });
  const payload = buildVideoMemoryTaskPayload(plan);

  assert.equal(payload.monitor_type, "binary");
});

test("monitor lifecycle inference distinguishes one-shot and persistent wording", () => {
  assert.equal(inferMonitorLifecycle("Remind me when you see a bird one time."), "one_shot");
  assert.equal(inferMonitorLifecycle("Count whenever I walk past."), "persistent");
  assert.equal(inferMonitorLifecycle("When a blue cup appears, say cup.", "persistent"), "persistent");
});

test("conversation context carries apple shopkeeper setup into later pronoun monitor", () => {
  const context = inferConversationContext("You are a shopkeeper for these apples.");
  const plan = buildTaskPlan("Wake up if someone takes one.", { ioId: "net0", context });

  assert.equal(plan.persona, "apple_shopkeeper");
  assert.ok(plan.trigger_condition.includes("apple stand"));
  assert.equal(plan.conversation_context.item, "apple");
});

test("explicit new object is not incorrectly pulled into apple context", () => {
  const context = inferConversationContext("You are a shopkeeper for these apples.");
  const plan = buildTaskPlan("When a blue cup is visible, then say the cup arrived.", { ioId: "net0", context });

  assert.equal(plan.persona, "generic");
  assert.equal(plan.trigger_condition, "A blue cup is visible.");
});

test("non wakeup chat is rejected as setup", () => {
  assert.equal(isSetupCommand("hello there"), false);
  assert.throws(() => buildTaskPlan("hello there"), /does not look like a wakeup/);
});

test("ledger parser handles name and digit count", () => {
  const parsed = parseLedgerEntry("My name is Sam, I took 2 apples.");
  assert.equal(parsed.complete, true);
  assert.equal(parsed.name, "Sam");
  assert.equal(parsed.apple_count, 2);
  assert.equal(parsed.amount_due, 2);
});

test("ledger parser handles spoken count words and pending name", () => {
  const parsed = parseLedgerEntry("I took two apples", { name: "Ava" });
  assert.equal(parsed.complete, true);
  assert.equal(parsed.name, "Ava");
  assert.equal(parsed.apple_count, 2);
});

test("ledger parser rejects impossible demo counts", () => {
  const parsed = parseLedgerEntry("My name is Sam and I took 99 apples");
  assert.equal(parsed.complete, false);
  assert.match(parsed.error, /too high/);
});

test("ledger summary includes totals", () => {
  assert.equal(summarizeLedger([]), "The ledger is empty.");
  assert.equal(
    summarizeLedger([
      { name: "Sam", apple_count: 2, amount_due: 2 },
      { name: "Ava", apple_count: 1, amount_due: 1 },
    ]),
    "Sam: 2 apples, $2; Ava: 1 apple, $1. Total: 3 apples, $3.",
  );
});

test("visual-memory parser and summary handle numeric totals and logs", () => {
  assert.deepEqual(
    parseVisualMemoryObservation('{"observed":true,"value":5,"confidence":"high"}', { mode: "numeric_total" }).value,
    5,
  );
  assert.equal(parseVisualMemoryObservation("The user is holding up four raised fingers.", { mode: "numeric_total" }).value, 4);
  assert.equal(parseVisualMemoryObservation('{"observed":false,"value":null,"confidence":"low"}', { mode: "numeric_total" }).observed, false);
  assert.equal(
    summarizeVisualMemory({ mode: "numeric_total", label: "finger count", observations: [{ value: 5 }, { value: 4 }] }),
    "Finger count total: 9. Observations: 5 + 4.",
  );
  assert.match(
    summarizeVisualMemory({ mode: "event_log", label: "bird sightings", observations: [{ value: "small bird on window" }] }),
    /Bird sightings log/,
  );
});

test("wakeup message uses shopkeeper persona", () => {
  const message = buildWakeupMessage(
    { persona: "apple_shopkeeper" },
    { note: "A customer reached toward the apples." },
  );
  assert.match(message, /apple stand/);
  assert.match(message, /What's your name/);
});

test("generic say action speaks the requested content", () => {
  const message = buildWakeupMessage(
    { persona: "generic", action_instruction: "Say the cup arrived." },
    { note: "A cup is visible." },
  );
  assert.equal(message, "the cup arrived.");
});

test("generic notify action produces useful text-only wakeup content", () => {
  const plan = buildTaskPlan("When the user holds up a single finger, notify me that a finger is held up.");
  assert.equal(plan.action_instruction, "A finger is held up");
  assert.equal(buildWakeupMessage(plan, { note: "Binary criterion met." }), "A finger is held up");
});

test("fake camera produces decodable PPM and SVG preview", () => {
  const frame = buildFakeCameraFrame({ scene: "apple_taken", pulse: true, width: 32, height: 24 });
  assert.equal(frame.subarray(0, 2).toString("ascii"), "P6");
  assert.ok(frame.length > 32 * 24 * 3);
  assert.match(fakeCameraPreviewSvg("apple_taken"), /Fake VideoMemory camera/);
});
