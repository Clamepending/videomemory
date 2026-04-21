import {
  DEFAULTS,
  getVideomemoryStatus,
  onboardVideomemory,
  summarizeOnboardResult,
} from "../../src/shared.mjs";

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function truthy(value) {
  return value === true || value === "true" || value === "1" || value === 1;
}

function hookConfig(event) {
  const entries = event?.context?.cfg?.hooks?.internal?.entries;
  const entry = entries?.["videomemory-startup"];
  return entry && typeof entry === "object" && !Array.isArray(entry) ? entry : {};
}

function buildOptions(event) {
  const config = hookConfig(event);
  return {
    videomemoryBase:
      cleanText(config.baseUrl) ||
      cleanText(process.env.VIDEOMEMORY_BASE_URL) ||
      DEFAULTS.videomemoryBase,
    repoRef:
      cleanText(config.repoRef) ||
      cleanText(process.env.VIDEOMEMORY_REPO_REF) ||
      DEFAULTS.repoRef,
    repoDir: cleanText(config.repoDir) || cleanText(process.env.VIDEOMEMORY_REPO_DIR),
    openclawHome: cleanText(config.openclawHome) || cleanText(process.env.OPENCLAW_HOME),
    safe: true,
    skipKeys: true,
    skipTailscale: true,
    skipNotify: true,
  };
}

function shouldAutoStart(event) {
  const config = hookConfig(event);
  return truthy(config.autoStart) || truthy(process.env.VIDEOMEMORY_OPENCLAW_AUTOSTART);
}

export default async function videomemoryStartupHook(event) {
  if (event?.type !== "gateway" || event?.action !== "startup") {
    return;
  }

  const options = buildOptions(event);
  try {
    const status = await getVideomemoryStatus(options);
    console.log(`[videomemory-startup] VideoMemory is reachable: ${status.uiUrl}`);
    return;
  } catch (error) {
    console.warn(
      `[videomemory-startup] VideoMemory is not reachable at ${options.videomemoryBase}: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }

  if (!shouldAutoStart(event)) {
    console.warn(
      "[videomemory-startup] autoStart is disabled. Set VIDEOMEMORY_OPENCLAW_AUTOSTART=1 or hook config autoStart=true to start it automatically.",
    );
    return;
  }

  void onboardVideomemory(options)
    .then((result) => {
      console.log(`[videomemory-startup] ${summarizeOnboardResult(result)}`);
    })
    .catch((error) => {
      console.warn(
        `[videomemory-startup] onboarding failed: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    });
}
