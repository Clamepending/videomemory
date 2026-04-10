import { Type } from "@sinclair/typebox";
import {
  getVideomemoryStatus,
  onboardVideomemory,
  relaunchVideomemory,
  summarizeOnboardResult,
} from "./shared.mjs";

const onboardSchema = Type.Object({
  repoUrl: Type.Optional(Type.String()),
  repoRef: Type.Optional(Type.String()),
  repoDir: Type.Optional(Type.String()),
  openclawHome: Type.Optional(Type.String()),
  videomemoryBase: Type.Optional(Type.String()),
  botId: Type.Optional(Type.String()),
  tailscaleAuthKey: Type.Optional(Type.String()),
  videoIngestorModel: Type.Optional(Type.String()),
  skipStart: Type.Optional(Type.Boolean()),
  skipKeys: Type.Optional(Type.Boolean()),
  skipTailscale: Type.Optional(Type.Boolean()),
  GOOGLE_API_KEY: Type.Optional(Type.String()),
  GEMINI_API_KEY: Type.Optional(Type.String()),
  OPENAI_API_KEY: Type.Optional(Type.String()),
  OPENROUTER_API_KEY: Type.Optional(Type.String()),
  ANTHROPIC_API_KEY: Type.Optional(Type.String()),
});

const relaunchSchema = Type.Object({
  repoUrl: Type.Optional(Type.String()),
  repoRef: Type.Optional(Type.String()),
  repoDir: Type.Optional(Type.String()),
  videomemoryBase: Type.Optional(Type.String()),
  videoIngestorModel: Type.Optional(Type.String()),
  skipKeys: Type.Optional(Type.Boolean()),
  GOOGLE_API_KEY: Type.Optional(Type.String()),
  GEMINI_API_KEY: Type.Optional(Type.String()),
  OPENAI_API_KEY: Type.Optional(Type.String()),
  OPENROUTER_API_KEY: Type.Optional(Type.String()),
  ANTHROPIC_API_KEY: Type.Optional(Type.String()),
});

const statusSchema = Type.Object({
  videomemoryBase: Type.Optional(Type.String()),
});

const plugin = {
  id: "videomemory",
  name: "VideoMemory",
  description: "VideoMemory onboarding and host-management tools for OpenClaw.",
  configSchema: {
    type: "object",
    additionalProperties: false,
    properties: {
      videomemoryBaseUrl: { type: "string" },
      repoDir: { type: "string" },
      repoRef: { type: "string" },
      botId: { type: "string" },
      tailscaleAuthKeyEnvVar: { type: "string" },
    },
  },
  register(api) {
    const baseConfig =
      api.pluginConfig && typeof api.pluginConfig === "object" ? api.pluginConfig : {};

    api.registerTool({
      name: "videomemory_onboard",
      label: "VideoMemory Onboard",
      description:
        "Install or refresh VideoMemory on the host machine, connect the OpenClaw integration, and return the user-facing UI link.",
      parameters: onboardSchema,
      async execute(_toolCallId, params) {
        const result = await onboardVideomemory({
          ...baseConfig,
          ...params,
        });
        return {
          content: [{ type: "text", text: summarizeOnboardResult(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "videomemory_relaunch",
      label: "VideoMemory Relaunch",
      description:
        "Upgrade and restart the local VideoMemory service, then return the current UI link and repo commit.",
      parameters: relaunchSchema,
      async execute(_toolCallId, params) {
        const result = await relaunchVideomemory({
          ...baseConfig,
          ...params,
        });
        return {
          content: [{ type: "text", text: summarizeOnboardResult(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "videomemory_status",
      label: "VideoMemory Status",
      description:
        "Check whether VideoMemory is healthy at the configured base URL and return the best known UI link.",
      parameters: statusSchema,
      async execute(_toolCallId, params) {
        const result = await getVideomemoryStatus({
          videomemoryBase: params.videomemoryBase || baseConfig.videomemoryBaseUrl,
        });
        return {
          content: [
            {
              type: "text",
              text: `VideoMemory is healthy at ${result.videomemoryBase}. UI: ${result.uiUrl}`,
            },
          ],
          details: result,
        };
      },
    });
  },
};

export default plugin;
