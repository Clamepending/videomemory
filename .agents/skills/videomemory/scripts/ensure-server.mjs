#!/usr/bin/env node

import { getBaseUrl, maybeRequestJson, parseArgs, requestJson, settingValue } from "./common.mjs";

function settingIsSet(settings, key) {
  if (!key) {
    return true;
  }
  const info = settings?.[key];
  return Boolean(info && typeof info === "object" && info.is_set);
}

function requiredProviderKey(model) {
  if (!model || model === "local-vllm") {
    return "";
  }
  if (model.includes("/")) {
    return "OPENROUTER_API_KEY";
  }
  if (model.startsWith("gpt-")) {
    return "OPENAI_API_KEY";
  }
  if (model.startsWith("claude-")) {
    return "ANTHROPIC_API_KEY";
  }
  if (model.startsWith("gemini-")) {
    return "GOOGLE_API_KEY";
  }
  return "";
}

async function localVllmStatus(settings) {
  const baseUrl = (settingValue(settings, "LOCAL_MODEL_BASE_URL") || "http://localhost:8100").replace(/\/+$/, "");
  const result = await maybeRequestJson(`${baseUrl}/v1/models`);
  return { url: baseUrl, active: result.ok, ...(result.ok ? { payload: result.payload } : { error: result.error }) };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const baseUrl = getBaseUrl(options);
  const health = await requestJson(`${baseUrl}/api/health`);
  const settingsPayload = await requestJson(`${baseUrl}/api/settings`);
  const settings = settingsPayload?.settings || {};
  const model = (settingValue(settings, "VIDEO_INGESTOR_MODEL") || "local-vllm").toLowerCase();
  const requiredKey = requiredProviderKey(model);
  const readiness = {
    base_url: baseUrl,
    server_reachable: true,
    video_ingestor_model: model,
    required_model_api_key: requiredKey || null,
    model_api_key_configured: settingIsSet(settings, requiredKey),
    webhook_configured: settingIsSet(settings, "VIDEOMEMORY_OPENCLAW_WEBHOOK_URL"),
    webhook_url: settingValue(settings, "VIDEOMEMORY_OPENCLAW_WEBHOOK_URL"),
  };
  if (model === "local-vllm") {
    readiness.local_vllm = await localVllmStatus(settings);
    readiness.needs_model_runtime = !readiness.local_vllm.active;
  } else {
    readiness.needs_model_api_key = Boolean(requiredKey && !readiness.model_api_key_configured);
  }

  const output = { status: "ok", health, readiness };
  if (options.json === "true") {
    process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
    return;
  }
  process.stdout.write(`VideoMemory reachable at ${baseUrl}\n`);
  process.stdout.write(`${JSON.stringify(readiness, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({ status: "error", error: error?.message || String(error) }, null, 2)}\n`);
  process.exitCode = 1;
});
