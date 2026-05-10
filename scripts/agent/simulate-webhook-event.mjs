#!/usr/bin/env node

import {
  cleanText,
  getBaseUrl,
  inferOpenClawWebhook,
  parseArgs,
  requestJson,
  summarizeTask,
  truthy,
} from "./common.mjs";

function buildSyntheticPayload(options, taskSummary, baseUrl) {
  const now = new Date();
  const taskId = cleanText(options["task-id"]) || cleanText(taskSummary.task_id);
  const ioId = cleanText(options["io-id"]) || cleanText(taskSummary.io_id);
  const botId = cleanText(options["bot-id"]) || cleanText(taskSummary.bot_id) || "agent";
  const eventId = cleanText(options["event-id"]) || `vm-sim-${Date.now()}`;
  return {
    service: "videomemory",
    event_type: "task_update",
    event_id: eventId,
    idempotency_key: eventId,
    bot_id: botId,
    videomemory_base_url: baseUrl,
    io_id: ioId,
    task_id: taskId,
    task_number: null,
    task_description:
      cleanText(options["task-description"]) ||
      cleanText(taskSummary.task_description) ||
      "Synthetic VideoMemory test task",
    task_status: cleanText(options["task-status"]) || cleanText(taskSummary.status) || "active",
    task_done: truthy(options["task-done"]),
    task_api_url: `${baseUrl}/api/task/${encodeURIComponent(taskId)}`,
    note: cleanText(options.note) || "Synthetic VideoMemory note for webhook path testing.",
    note_id: cleanText(options["note-id"]) || `sim-${Date.now()}`,
    note_timestamp: now.getTime() / 1000,
    note_timestamp_iso: now.toISOString(),
    note_has_frame: false,
    note_frame_api_path: "",
    note_frame_api_url: "",
    note_has_video: false,
    note_video_api_path: "",
    note_video_api_url: "",
    notes_count: Number(taskSummary.notes_count || 0),
    observed_at: now.toISOString(),
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (!truthy(options.confirm)) {
    throw new Error("Pass --confirm true to send a synthetic webhook event.");
  }

  const taskId = cleanText(options["task-id"]);
  if (!taskId) {
    throw new Error("Missing required --task-id");
  }

  const baseUrl = getBaseUrl(options);
  let taskSummary = {};
  try {
    const taskPayload = await requestJson(`${baseUrl}/api/task/${encodeURIComponent(taskId)}`);
    taskSummary = summarizeTask(taskPayload);
  } catch {
    taskSummary = { task_id: taskId };
  }

  const webhook = await inferOpenClawWebhook(options);
  const payload = buildSyntheticPayload(options, taskSummary, baseUrl);
  const response = await fetch(webhook.url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": payload.idempotency_key,
      ...(webhook.token ? { Authorization: `Bearer ${webhook.token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  const responseText = await response.text();
  let responsePayload = responseText;
  try {
    responsePayload = responseText ? JSON.parse(responseText) : {};
  } catch {
    // Keep the raw text response.
  }
  const output = {
    status: response.ok ? "ok" : "error",
    webhook_url: webhook.url,
    response_status: response.status,
    response: responsePayload,
    payload,
  };
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
  if (!response.ok) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({ status: "error", error: error?.message || String(error) }, null, 2)}\n`);
  process.exitCode = 1;
});
