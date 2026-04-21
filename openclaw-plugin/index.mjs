import {
  DEFAULTS,
  getVideomemoryStatus,
  onboardVideomemory,
  relaunchVideomemory,
  summarizeOnboardResult,
} from "./src/shared.mjs";

const PLUGIN_ID = "videomemory";

const statusToolSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    baseUrl: {
      type: "string",
      description: "Optional VideoMemory base URL. Defaults to plugin config or http://127.0.0.1:5050.",
    },
  },
};

const lifecycleToolSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    baseUrl: {
      type: "string",
      description: "Optional VideoMemory base URL. Defaults to plugin config or http://127.0.0.1:5050.",
    },
    repoRef: {
      type: "string",
      description: "Optional VideoMemory git ref. Defaults to plugin config or v0.1.2.",
    },
    repoDir: {
      type: "string",
      description: "Optional host checkout directory.",
    },
    explain: {
      type: "boolean",
      description: "Print the plan without making changes.",
    },
  },
};

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function boolConfig(value, fallback) {
  return typeof value === "boolean" ? value : fallback;
}

function pluginOptions(api, overrides = {}) {
  const config =
    api.pluginConfig && typeof api.pluginConfig === "object" && !Array.isArray(api.pluginConfig)
      ? api.pluginConfig
      : {};
  const safeMode = boolConfig(config.safeMode, true);

  return {
    openclawHome: cleanText(overrides.openclawHome) || cleanText(config.openclawHome),
    repoDir: cleanText(overrides.repoDir) || cleanText(config.repoDir),
    repoRef: cleanText(overrides.repoRef) || cleanText(config.repoRef) || DEFAULTS.repoRef,
    videomemoryBase:
      cleanText(overrides.baseUrl) || cleanText(config.baseUrl) || DEFAULTS.videomemoryBase,
    safe: safeMode,
    dryRun: Boolean(overrides.explain),
    explain: Boolean(overrides.explain),
    skipKeys: safeMode || !boolConfig(config.syncModelKeys, false),
    skipTailscale: safeMode || !boolConfig(config.allowTailscaleSetup, false),
    skipNotify: safeMode || !boolConfig(config.notifyTelegram, false),
  };
}

function jsonToolResult(payload) {
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
    details: payload,
  };
}

function formatResult(result) {
  if (result?.dryRun && result?.stdout) {
    return result.stdout.trim();
  }
  if (result?.uiUrl) {
    return summarizeOnboardResult(result);
  }
  return JSON.stringify(result, null, 2);
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

async function commandText(work) {
  try {
    return formatResult(await work());
  } catch (error) {
    return `VideoMemory error: ${errorMessage(error)}`;
  }
}

async function writeCliResult(work, options = {}) {
  try {
    const result = await work();
    const text = options.rawJson ? JSON.stringify(result, null, 2) : formatResult(result);
    process.stdout.write(`${text}\n`);
  } catch (error) {
    process.stderr.write(
      `${JSON.stringify({ success: false, error: errorMessage(error) }, null, 2)}\n`,
    );
    process.exitCode = 1;
  }
}

function parseCommandArgs(args = "") {
  const normalized = cleanText(args).toLowerCase();
  return {
    explain: normalized.includes("--explain") || normalized.includes("dry-run"),
  };
}

async function runStatus(api, overrides = {}) {
  return getVideomemoryStatus(pluginOptions(api, overrides));
}

async function runOnboard(api, overrides = {}) {
  return onboardVideomemory(pluginOptions(api, overrides));
}

async function runRelaunch(api, overrides = {}) {
  return relaunchVideomemory(pluginOptions(api, overrides));
}

const videomemoryPlugin = {
  id: PLUGIN_ID,
  name: "VideoMemory",
  description: "Camera monitoring, one-off frame questions, and host onboarding.",
  configSchema: {
    parse(value) {
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    },
  },
  register(api) {
    api.registerTool({
      name: "videomemory_status",
      label: "VideoMemory Status",
      description: "Check whether VideoMemory is reachable and return its UI link.",
      parameters: statusToolSchema,
      async execute(_toolCallId, params = {}) {
        return jsonToolResult(await runStatus(api, params));
      },
    });

    api.registerTool({
      name: "videomemory_onboard",
      label: "VideoMemory Onboard",
      description:
        "Safely start or install VideoMemory on the OpenClaw host and return the UI link. Use explain=true before making changes when requested from chat.",
      parameters: lifecycleToolSchema,
      async execute(_toolCallId, params = {}) {
        return jsonToolResult(await runOnboard(api, params));
      },
    });

    api.registerTool({
      name: "videomemory_relaunch",
      label: "VideoMemory Relaunch",
      description: "Relaunch or update an existing VideoMemory host install and return the UI link.",
      parameters: lifecycleToolSchema,
      async execute(_toolCallId, params = {}) {
        return jsonToolResult(await runRelaunch(api, params));
      },
    });

    api.registerGatewayMethod("videomemory.status", async ({ params, respond }) => {
      try {
        respond(true, await runStatus(api, params || {}));
      } catch (error) {
        respond(false, { error: errorMessage(error) });
      }
    });

    api.registerGatewayMethod("videomemory.onboard", async ({ params, respond }) => {
      try {
        respond(true, await runOnboard(api, params || {}));
      } catch (error) {
        respond(false, { error: errorMessage(error) });
      }
    });

    api.registerGatewayMethod("videomemory.relaunch", async ({ params, respond }) => {
      try {
        respond(true, await runRelaunch(api, params || {}));
      } catch (error) {
        respond(false, { error: errorMessage(error) });
      }
    });

    api.registerCommand({
      name: "videomemory-status",
      description: "Check VideoMemory status.",
      requireAuth: true,
      handler: async () => ({ text: await commandText(() => runStatus(api)) }),
    });

    api.registerCommand({
      name: "videomemory-onboard",
      description: "Start or install VideoMemory and return the UI link.",
      acceptsArgs: true,
      requireAuth: true,
      handler: async (ctx) => ({
        text: await commandText(() => runOnboard(api, parseCommandArgs(ctx.args))),
      }),
    });

    api.registerCommand({
      name: "videomemory-relaunch",
      description: "Relaunch or update VideoMemory and return the UI link.",
      acceptsArgs: true,
      requireAuth: true,
      handler: async (ctx) => ({
        text: await commandText(() => runRelaunch(api, parseCommandArgs(ctx.args))),
      }),
    });

    api.registerCli(
      ({ program }) => {
        const command = program
          .command("videomemory")
          .description("Manage VideoMemory from OpenClaw");

        command
          .command("status")
          .description("Check VideoMemory health")
          .option("--base-url <url>", "VideoMemory base URL")
          .action(async (options) => {
            await writeCliResult(() => runStatus(api, options), { rawJson: true });
          });

        command
          .command("onboard")
          .description("Start or install VideoMemory on this host")
          .option("--base-url <url>", "VideoMemory base URL")
          .option("--repo-ref <ref>", "VideoMemory git ref")
          .option("--repo-dir <dir>", "VideoMemory checkout directory")
          .option("--explain", "Print the plan without making changes")
          .action(async (options) => {
            await writeCliResult(() => runOnboard(api, options));
          });

        command
          .command("relaunch")
          .description("Relaunch or update VideoMemory")
          .option("--base-url <url>", "VideoMemory base URL")
          .option("--repo-ref <ref>", "VideoMemory git ref")
          .option("--repo-dir <dir>", "VideoMemory checkout directory")
          .option("--explain", "Print the plan without making changes")
          .action(async (options) => {
            await writeCliResult(() => runRelaunch(api, options));
          });
      },
      { commands: ["videomemory"] },
    );

    api.registerService({
      id: "videomemory-autostart",
      start() {
        const config =
          api.pluginConfig && typeof api.pluginConfig === "object" && !Array.isArray(api.pluginConfig)
            ? api.pluginConfig
            : {};
        if (!boolConfig(config.autoStart, false)) {
          api.logger.info("[videomemory] autoStart is disabled; use /videomemory-onboard when ready.");
          return;
        }

        void runOnboard(api)
          .then((result) => {
            api.logger.info(`[videomemory] ${formatResult(result)}`);
          })
          .catch((error) => {
            api.logger.warn(`[videomemory] autoStart failed: ${errorMessage(error)}`);
          });
      },
    });
  },
};

export default videomemoryPlugin;
