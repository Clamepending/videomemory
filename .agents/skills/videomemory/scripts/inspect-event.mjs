#!/usr/bin/env node

import { cleanText, getBaseUrl, parseArgs, requestJson, summarizeTask } from "./common.mjs";

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const taskId = cleanText(options["task-id"]);
  if (!taskId) {
    throw new Error("Missing required --task-id");
  }
  const baseUrl = getBaseUrl(options);
  const taskPayload = await requestJson(`${baseUrl}/api/task/${encodeURIComponent(taskId)}`);
  const summary = summarizeTask(taskPayload);
  const output = { status: "ok", base_url: baseUrl, summary, raw: taskPayload };
  if (options.json === "true") {
    process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
    return;
  }
  process.stdout.write(`${JSON.stringify({ status: output.status, base_url: baseUrl, summary }, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({ status: "error", error: error?.message || String(error) }, null, 2)}\n`);
  process.exitCode = 1;
});
