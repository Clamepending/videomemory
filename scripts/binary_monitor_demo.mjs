#!/usr/bin/env node
import { createServer } from "node:http";
import { Readable } from "node:stream";
import { URL } from "node:url";

const DEFAULT_PORT = 8766;
const DEFAULT_BASE_URL = "http://127.0.0.1:5050";

function parseArgs(argv) {
  const options = {
    port: DEFAULT_PORT,
    baseUrl: DEFAULT_BASE_URL,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--port") {
      options.port = Number(argv[++i] || DEFAULT_PORT);
    } else if (token === "--base-url") {
      options.baseUrl = String(argv[++i] || DEFAULT_BASE_URL).replace(/\/+$/, "");
    } else if (token === "--help" || token === "-h") {
      options.help = true;
    } else {
      throw new Error(`Unknown argument: ${token}`);
    }
  }
  return options;
}

function usage() {
  return [
    "Usage:",
    "  node scripts/binary_monitor_demo.mjs [--port 8766] [--base-url http://127.0.0.1:5050]",
    "",
    "Open the printed URL, choose a device, type a binary criterion, and start the monitor.",
  ].join("\n");
}

function send(res, status, contentType, body, headers = {}) {
  res.writeHead(status, {
    "Content-Type": contentType,
    "Cache-Control": "no-store",
    ...headers,
  });
  res.end(body);
}

function sendJson(res, status, payload) {
  send(res, status, "application/json", JSON.stringify(payload));
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

function headerEntries(headers) {
  const out = {};
  for (const [key, value] of headers.entries()) {
    const lower = key.toLowerCase();
    if (
      lower === "content-encoding" ||
      lower === "content-length" ||
      lower === "connection" ||
      lower === "keep-alive" ||
      lower === "transfer-encoding"
    ) {
      continue;
    }
    out[key] = value;
  }
  return out;
}

async function proxyRequest(req, res, baseUrl) {
  const incoming = new URL(req.url, "http://127.0.0.1");
  const targetPath = incoming.pathname.replace(/^\/vm/, "") || "/";
  const targetUrl = `${baseUrl}${targetPath}${incoming.search}`;
  const body = req.method === "GET" || req.method === "HEAD" ? undefined : await readBody(req);
  const headers = {};
  for (const [key, value] of Object.entries(req.headers)) {
    const lower = key.toLowerCase();
    if (lower === "host" || lower === "content-length" || lower === "connection") continue;
    headers[key] = value;
  }

  try {
    const upstream = await fetch(targetUrl, {
      method: req.method,
      headers,
      body,
    });
    res.writeHead(upstream.status, headerEntries(upstream.headers));
    if (upstream.body) {
      Readable.fromWeb(upstream.body).pipe(res);
    } else {
      res.end();
    }
  } catch (error) {
    sendJson(res, 502, { status: "error", error: error?.message || String(error), targetUrl });
  }
}

const pageHtml = String.raw`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Binary Monitor Tester</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: #151515;
      color: #eeeeee;
      font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button, input, select, textarea {
      font: inherit;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(420px, 1.35fr) minmax(360px, 0.65fr);
    }
    .stage {
      padding: 18px;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      gap: 14px;
      border-right: 1px solid #2e2e2e;
      min-height: 100vh;
    }
    .topline {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 650;
      letter-spacing: 0;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border: 1px solid #3e3e3e;
      border-radius: 999px;
      color: #bdbdbd;
      background: #202020;
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #777;
    }
    .status.ready .dot { background: #19c37d; }
    .status.triggered .dot { background: #ffb020; }
    .status.error .dot { background: #f25f5c; }
    .videoBox {
      position: relative;
      min-height: 360px;
      border: 1px solid #2f2f2f;
      border-radius: 8px;
      overflow: hidden;
      background: #090909;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .videoBox img,
    .videoBox video {
      width: 100%;
      height: 100%;
      max-height: calc(100vh - 170px);
      object-fit: contain;
      display: block;
    }
    .videoBox video {
      display: none;
    }
    .videoBox.browser-live img {
      display: none;
    }
    .videoBox.browser-live video {
      display: block;
    }
    .empty {
      color: #777;
      padding: 24px;
      text-align: center;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      background: #202020;
      border: 1px solid #303030;
      border-radius: 8px;
      padding: 10px;
      min-width: 0;
    }
    .metric label {
      display: block;
      color: #888;
      font-size: 11px;
      text-transform: uppercase;
      margin-bottom: 4px;
    }
    .metric strong {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 15px;
      color: #f4f4f4;
    }
    .side {
      padding: 18px;
      overflow-y: auto;
      min-height: 100vh;
    }
    .panel {
      border: 1px solid #303030;
      border-radius: 8px;
      background: #1d1d1d;
      padding: 14px;
      margin-bottom: 14px;
    }
    .panel h2 {
      margin: 0 0 10px;
      font-size: 14px;
      font-weight: 650;
      color: #d9d9d9;
    }
    label {
      display: block;
      color: #aaaaaa;
      font-size: 12px;
      margin: 10px 0 5px;
    }
    select, textarea, input[type="number"], input[type="text"] {
      width: 100%;
      color: #eeeeee;
      background: #111111;
      border: 1px solid #3a3a3a;
      border-radius: 6px;
      padding: 9px;
      outline: none;
    }
    textarea {
      resize: vertical;
      min-height: 98px;
    }
    select:focus, textarea:focus, input:focus {
      border-color: #19c37d;
    }
    .row {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    button {
      border: 0;
      border-radius: 6px;
      padding: 9px 12px;
      color: #eeeeee;
      background: #383838;
      cursor: pointer;
    }
    button:hover { background: #474747; }
    button.primary {
      color: #06150f;
      background: #19c37d;
      font-weight: 700;
    }
    button.primary:hover { background: #26d88f; }
    button.danger { background: #633; }
    button.danger:hover { background: #744; }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
    .prob {
      display: grid;
      gap: 10px;
    }
    .barLine {
      display: grid;
      gap: 5px;
    }
    .barHead {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 10px;
      color: #cfcfcf;
    }
    .bar {
      position: relative;
      height: 16px;
      border-radius: 999px;
      overflow: hidden;
      background: #101010;
      border: 1px solid #333;
    }
    .fill {
      height: 100%;
      width: 0%;
      border-radius: inherit;
      background: #19c37d;
      transition: width 0.18s ease;
    }
    .fill.false { background: #f25f5c; }
    .thresholdMarker {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 2px;
      background: #ffb020;
      box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.75);
      transition: left 0.18s ease;
    }
    .thresholdStats {
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid #303030;
    }
    .triggerBox {
      border-radius: 8px;
      padding: 14px;
      background: #151515;
      border: 1px solid #333;
    }
    .triggerBox.on {
      border-color: #ffb020;
      background: rgba(255, 176, 32, 0.11);
    }
    .triggerBox strong {
      display: block;
      font-size: 22px;
      margin-bottom: 4px;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      color: #bfbfbf;
      word-break: break-word;
    }
    .log {
      max-height: 190px;
      overflow: auto;
      white-space: pre-wrap;
      color: #bfbfbf;
      background: #111;
      border: 1px solid #303030;
      border-radius: 6px;
      padding: 10px;
    }
    .hint {
      color: #888;
      font-size: 12px;
      margin-top: 8px;
    }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      .stage { min-height: auto; border-right: 0; border-bottom: 1px solid #2e2e2e; }
      .side { min-height: auto; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <main class="app">
    <section class="stage">
      <div class="topline">
        <h1>Binary Monitor Tester</h1>
        <div id="statusPill" class="status"><span class="dot"></span><span id="statusText">Connecting</span></div>
      </div>
      <div id="videoBox" class="videoBox">
        <div id="emptyFrame" class="empty">Choose a device and start a binary monitor.</div>
        <img id="preview" alt="Selected device preview">
        <video id="browserVideo" autoplay playsinline muted></video>
        <canvas id="browserCanvas" hidden></canvas>
      </div>
      <div class="metrics">
        <div class="metric"><label>Answer</label><strong id="answer">-</strong></div>
        <div class="metric"><label>Hits</label><strong id="hits">-</strong></div>
        <div class="metric"><label>Inference</label><strong id="inference">-</strong></div>
        <div class="metric"><label>Frame age</label><strong id="frameAge">-</strong></div>
      </div>
    </section>
    <aside class="side">
      <section class="panel">
        <h2>Prompt</h2>
        <label for="device">Device</label>
        <select id="device"></select>
        <label for="criterion">Binary criterion</label>
        <textarea id="criterion" spellcheck="true">A blue cup is visible.</textarea>
        <div class="row">
          <div>
            <label for="threshold">Warmup threshold</label>
            <input id="threshold" type="number" min="0" max="1" step="0.01" value="0.70">
          </div>
          <div>
            <label for="adaptiveZ">Std devs</label>
            <input id="adaptiveZ" type="number" min="0" max="10" step="0.1" value="3.0">
          </div>
          <div>
            <label for="adaptiveMinSamples">Calibration frames</label>
            <input id="adaptiveMinSamples" type="number" min="2" max="1000" step="1" value="10">
          </div>
        </div>
        <div class="row">
          <div>
            <label for="adaptiveFloor">Adaptive floor</label>
            <input id="adaptiveFloor" type="number" min="0" max="1" step="0.01" value="0.50">
          </div>
          <div>
            <label for="requiredHits">Hits</label>
            <input id="requiredHits" type="number" min="1" max="30" step="1" value="4">
          </div>
          <div>
            <label for="windowSize">Window</label>
            <input id="windowSize" type="number" min="1" max="30" step="1" value="5">
          </div>
        </div>
        <div class="buttons">
          <button id="start" class="primary" type="button">Start monitor</button>
          <button id="stop" class="danger" type="button">Stop</button>
          <button id="refresh" type="button">Refresh devices</button>
        </div>
        <div class="buttons">
          <button id="startBrowserCamera" type="button">Start browser camera</button>
          <button id="stopBrowserCamera" type="button">Stop browser camera</button>
        </div>
        <div class="hint">For the FaceTime browser source, start browser camera first and allow camera permission in this browser. Fake/network devices do not need it.</div>
      </section>
      <section class="panel">
        <h2>Probabilities</h2>
        <div class="prob">
          <div class="barLine">
            <div class="barHead"><span>True</span><span id="pTrueLabel">-</span></div>
            <div class="bar"><div id="pTrueFill" class="fill"></div><div id="thresholdMarker" class="thresholdMarker" hidden></div></div>
          </div>
          <div class="barLine">
            <div class="barHead"><span>False</span><span id="pFalseLabel">-</span></div>
            <div class="bar"><div id="pFalseFill" class="fill false"></div></div>
          </div>
        </div>
        <div id="thresholdStats" class="mono thresholdStats">adaptive threshold pending</div>
      </section>
      <section id="triggerBox" class="panel triggerBox">
        <strong id="triggerState">Not triggered</strong>
        <div id="triggerDetail" class="mono">No active task yet.</div>
      </section>
      <section class="panel">
        <h2>Runtime</h2>
        <div id="runtime" class="mono">-</div>
      </section>
      <section class="panel">
        <h2>Events</h2>
        <div id="log" class="log"></div>
      </section>
    </aside>
  </main>
  <script>
    const BOT_ID = "binary-monitor-demo";
    const BROWSER_IO_ID = "browser_facetime";
    const els = Object.fromEntries([
      "statusPill", "statusText", "device", "criterion", "threshold", "adaptiveZ",
      "adaptiveMinSamples", "adaptiveFloor", "requiredHits", "windowSize",
      "start", "stop", "refresh", "preview", "emptyFrame", "answer", "hits", "inference", "frameAge",
      "pTrueLabel", "pFalseLabel", "pTrueFill", "pFalseFill", "thresholdMarker", "thresholdStats",
      "triggerBox", "triggerState",
      "triggerDetail", "runtime", "log", "startBrowserCamera", "stopBrowserCamera", "browserVideo",
      "browserCanvas", "videoBox"
    ].map(id => [id, document.getElementById(id)]));

    let currentTaskId = "";
    let currentIoId = "";
    let pollTimer = null;
    let frameTimer = null;
    let mediaStream = null;

    function log(message, data) {
      const line = "[" + new Date().toLocaleTimeString() + "] " + message + (data ? " " + JSON.stringify(data) : "");
      els.log.textContent = (line + "\n" + els.log.textContent).slice(0, 6000);
    }

    function setStatus(text, mode = "") {
      els.statusText.textContent = text;
      els.statusPill.className = ("status " + mode).trim();
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });
      const contentType = response.headers.get("content-type") || "";
      const body = contentType.includes("application/json") ? await response.json() : await response.text();
      if (!response.ok) {
        throw new Error((body && body.error) || (body && body.message) || ("HTTP " + response.status));
      }
      return body;
    }

    function selectedDevice() {
      return els.device.value || BROWSER_IO_ID;
    }

    function updatePreview(ioId) {
      if (!ioId) return;
      currentIoId = ioId;
      if (mediaStream && ioId === BROWSER_IO_ID) {
        els.videoBox.classList.add("browser-live");
        els.emptyFrame.hidden = true;
        return;
      }
      els.videoBox.classList.remove("browser-live");
      els.emptyFrame.hidden = true;
      els.preview.src = "/vm/api/device/" + encodeURIComponent(ioId) + "/preview/stream?t=" + Date.now();
    }

    async function loadSettings() {
      const data = await api("/vm/api/settings");
      const settings = data.settings || {};
      const set = (id, key, fallback) => {
        const value = settings[key] && settings[key].value ? settings[key].value : fallback;
        els[id].value = value;
      };
      set("threshold", "VIDEOMEMORY_FASTVLM_THRESHOLD", "0.70");
      set("adaptiveZ", "VIDEOMEMORY_FASTVLM_ADAPTIVE_Z", "3.0");
      set("adaptiveMinSamples", "VIDEOMEMORY_FASTVLM_ADAPTIVE_MIN_SAMPLES", "10");
      set("adaptiveFloor", "VIDEOMEMORY_FASTVLM_ADAPTIVE_FLOOR", "0.50");
      set("requiredHits", "VIDEOMEMORY_FASTVLM_REQUIRED_HITS", "4");
      set("windowSize", "VIDEOMEMORY_FASTVLM_WINDOW", "5");
    }

    async function loadDevices() {
      const data = await api("/vm/api/devices");
      const devices = [];
      for (const group of Object.values(data.devices || {})) {
        for (const device of group) devices.push(device);
      }
      els.device.innerHTML = "";
      for (const device of devices) {
        const option = document.createElement("option");
        option.value = device.io_id;
        option.textContent = (device.name || device.io_id) + " (" + device.io_id + ")";
        els.device.append(option);
      }
      const preferred = devices.find(d => d.io_id === BROWSER_IO_ID) || devices.find(d => d.io_id === "net0") || devices[0];
      if (preferred) {
        els.device.value = preferred.io_id;
        updatePreview(preferred.io_id);
      }
      setStatus("Ready", "ready");
    }

    async function stopDemoTasks() {
      const data = await api("/vm/api/tasks");
      const tasks = data.tasks || [];
      const stops = tasks
        .filter(task => task.bot_id === BOT_ID && !task.done)
        .map(task => api("/vm/api/task/" + encodeURIComponent(task.task_id) + "/stop", { method: "POST", body: "{}" }).catch(error => ({ error: error.message })));
      if (stops.length) await Promise.all(stops);
    }

    async function saveBinarySettings() {
      const threshold = Math.max(0, Math.min(1, Number(els.threshold.value || 0.7)));
      const adaptiveZ = Math.max(0, Math.min(10, Number(els.adaptiveZ.value || 3.0)));
      const adaptiveMinSamples = Math.max(2, Math.round(Number(els.adaptiveMinSamples.value || 10)));
      const adaptiveFloor = Math.max(0, Math.min(1, Number(els.adaptiveFloor.value || 0.5)));
      const requiredHits = Math.max(1, Math.round(Number(els.requiredHits.value || 4)));
      const windowSize = Math.max(requiredHits, Math.round(Number(els.windowSize.value || 5)));
      els.threshold.value = threshold.toFixed(2);
      els.adaptiveZ.value = adaptiveZ.toFixed(1);
      els.adaptiveMinSamples.value = String(adaptiveMinSamples);
      els.adaptiveFloor.value = adaptiveFloor.toFixed(2);
      els.requiredHits.value = String(requiredHits);
      els.windowSize.value = String(windowSize);
      await Promise.all([
        api("/vm/api/settings/VIDEOMEMORY_FASTVLM_THRESHOLD_MODE", { method: "PUT", body: JSON.stringify({ value: "adaptive" }) }),
        api("/vm/api/settings/VIDEOMEMORY_FASTVLM_THRESHOLD", { method: "PUT", body: JSON.stringify({ value: String(threshold) }) }),
        api("/vm/api/settings/VIDEOMEMORY_FASTVLM_REQUIRED_HITS", { method: "PUT", body: JSON.stringify({ value: String(requiredHits) }) }),
        api("/vm/api/settings/VIDEOMEMORY_FASTVLM_WINDOW", { method: "PUT", body: JSON.stringify({ value: String(windowSize) }) }),
        api("/vm/api/settings/VIDEOMEMORY_FASTVLM_ADAPTIVE_Z", { method: "PUT", body: JSON.stringify({ value: String(adaptiveZ) }) }),
        api("/vm/api/settings/VIDEOMEMORY_FASTVLM_ADAPTIVE_MIN_SAMPLES", { method: "PUT", body: JSON.stringify({ value: String(adaptiveMinSamples) }) }),
        api("/vm/api/settings/VIDEOMEMORY_FASTVLM_ADAPTIVE_WINDOW", { method: "PUT", body: JSON.stringify({ value: String(adaptiveMinSamples) }) }),
        api("/vm/api/settings/VIDEOMEMORY_FASTVLM_ADAPTIVE_FLOOR", { method: "PUT", body: JSON.stringify({ value: String(adaptiveFloor) }) }),
      ]);
    }

    async function startMonitor() {
      const ioId = selectedDevice();
      const criterion = els.criterion.value.trim();
      if (!criterion) {
        throw new Error("Enter a binary criterion.");
      }
      setStatus("Starting");
      await saveBinarySettings();
      await api("/vm/api/device/" + encodeURIComponent(ioId) + "/debug/frame-skip-threshold", {
        method: "PUT",
        body: JSON.stringify({ value: 0 }),
      });
      await stopDemoTasks();
      const task = await api("/vm/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          io_id: ioId,
          task_description: criterion,
          bot_id: BOT_ID,
          monitor_type: "binary",
          save_note_frames: true,
          save_note_videos: false,
        }),
      });
      currentTaskId = String(task.task_id || "");
      updatePreview(ioId);
      log("Started binary monitor", { task_id: currentTaskId, io_id: ioId, criterion });
      setStatus("Monitoring", "ready");
      await pollNow();
      startPolling();
    }

    async function stopMonitor() {
      if (currentTaskId) {
        await api("/vm/api/task/" + encodeURIComponent(currentTaskId) + "/stop", { method: "POST", body: "{}" });
        log("Stopped monitor", { task_id: currentTaskId });
      }
      currentTaskId = "";
      setStatus("Stopped");
      renderEmpty();
    }

    function pct(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return 0;
      return Math.max(0, Math.min(100, number * 100));
    }

    function renderEmpty() {
      els.answer.textContent = "-";
      els.hits.textContent = "-";
      els.inference.textContent = "-";
      els.frameAge.textContent = "-";
      els.pTrueLabel.textContent = "-";
      els.pFalseLabel.textContent = "-";
      els.pTrueFill.style.width = "0%";
      els.pFalseFill.style.width = "0%";
      els.thresholdMarker.hidden = true;
      els.thresholdStats.textContent = "adaptive threshold pending";
      els.triggerBox.classList.remove("on");
      els.triggerState.textContent = "Not triggered";
      els.triggerDetail.textContent = currentTaskId ? "Task " + currentTaskId + " is waiting for evaluations." : "No active task yet.";
      els.runtime.textContent = "-";
    }

    function fmt(value, digits = 3) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(digits) : "-";
    }

    function renderStatus(status, task) {
      const binary = status.binary_monitor || {};
      const latestTaskId = String(binary.last_task_id || "");
      const hasCurrentTask = Boolean(currentTaskId);
      const activeTaskMatches = hasCurrentTask && latestTaskId === String(currentTaskId);
      const currentBinary = activeTaskMatches ? binary : {};
      const pTrue = pct(currentBinary.last_p_true);
      const pFalse = pct(currentBinary.last_p_false);
      const effectiveThreshold = Number(
        currentBinary.last_effective_threshold ?? binary.last_effective_threshold ?? binary.threshold ?? els.threshold.value
      );
      const thresholdPct = pct(effectiveThreshold);
      const done = Boolean((task && task.done) || currentBinary.last_done);
      const ingestorRunning = Boolean((status.ingestor && status.ingestor.running) || status.running);
      const deviceReady = status.ready === true || (Boolean(status.has_ingestor) && ingestorRunning && Boolean(status.has_frame));

      if (!hasCurrentTask) {
        renderEmpty();
        els.frameAge.textContent = status.frame_age_ms != null ? Number(status.frame_age_ms).toFixed(0) + " ms" : "-";
        els.runtime.textContent = [
          "device_ready=" + deviceReady,
          "ingestor_running=" + ingestorRunning,
          "binary_enabled=" + Boolean(binary.enabled),
          "active_tasks=" + (binary.active_tasks ?? 0),
          "latest_task=" + (latestTaskId || "-"),
        ].join("\n");
        setStatus(deviceReady ? "Ready" : "Waiting", deviceReady ? "ready" : "");
        return;
      }

      els.answer.textContent = currentBinary.last_answer || (activeTaskMatches ? "-" : "waiting");
      els.hits.textContent = currentBinary.last_hits != null ? currentBinary.last_hits + "/" + (binary.required_hits || "?") : "-";
      els.inference.textContent = currentBinary.last_inference_ms != null ? Number(currentBinary.last_inference_ms).toFixed(1) + " ms" : "-";
      els.frameAge.textContent = status.frame_age_ms != null ? Number(status.frame_age_ms).toFixed(0) + " ms" : "-";
      els.pTrueLabel.textContent = pTrue.toFixed(1) + "%";
      els.pFalseLabel.textContent = pFalse.toFixed(1) + "%";
      els.pTrueFill.style.width = pTrue + "%";
      els.pFalseFill.style.width = pFalse + "%";
      els.thresholdMarker.hidden = !Number.isFinite(effectiveThreshold);
      els.thresholdMarker.style.left = thresholdPct + "%";
      els.thresholdStats.textContent = [
        "effective_threshold=" + fmt(effectiveThreshold),
        "mode=" + (currentBinary.last_threshold_mode || binary.threshold_mode || "adaptive"),
        "calibration=" + (currentBinary.last_adaptive_ready ? "complete" : (currentBinary.last_calibrating ? "collecting" : "-")),
        "baseline_mean=" + fmt(currentBinary.last_baseline_mean),
        "baseline_stddev=" + fmt(currentBinary.last_baseline_stddev),
        "baseline_samples=" + (currentBinary.last_baseline_samples ?? 0) + "/" + (binary.adaptive_min_samples ?? els.adaptiveMinSamples.value),
        "z=" + fmt(binary.adaptive_z ?? els.adaptiveZ.value, 1),
        "floor=" + fmt(binary.adaptive_floor ?? els.adaptiveFloor.value, 2),
      ].join("\n");
      els.triggerBox.classList.toggle("on", done);
      els.triggerState.textContent = done ? "Triggered" : "Not triggered";
      els.triggerDetail.textContent = [
        "task=" + (currentTaskId || binary.last_task_id || "-"),
        "criterion=" + (currentBinary.last_criterion || els.criterion.value.trim() || "-"),
        "effective_threshold=" + fmt(effectiveThreshold),
        "warmup_threshold=" + (binary.threshold ?? "-"),
        "calibration=" + (currentBinary.last_adaptive_ready ? "complete" : (currentBinary.last_calibrating ? "collecting" : "-")),
        "baseline_mean=" + fmt(currentBinary.last_baseline_mean),
        "baseline_stddev=" + fmt(currentBinary.last_baseline_stddev),
        "baseline_samples=" + (currentBinary.last_baseline_samples ?? 0),
        "window=" + (binary.window ?? "-"),
        "evaluations=" + (binary.evaluations ?? 0),
        "latest_evaluated_task=" + (latestTaskId || "-"),
      ].join("\n");
      els.runtime.textContent = [
        "device_ready=" + deviceReady,
        "ingestor_running=" + ingestorRunning,
        "binary_enabled=" + Boolean(binary.enabled),
        "active_tasks=" + (binary.active_tasks ?? 0),
        "threshold_mode=" + (binary.threshold_mode || "-"),
        "adaptive_z=" + (binary.adaptive_z ?? "-"),
        "adaptive_floor=" + (binary.adaptive_floor ?? "-"),
        "model=" + (currentBinary.last_model || "-"),
        "last_error=" + (currentBinary.last_error || binary.latest_error || "-"),
        "task_status=" + (task ? task.status : "-"),
        "matching_latest_task=" + activeTaskMatches,
      ].join("\n");

      if (done) {
        setStatus("Triggered", "triggered");
      } else if (deviceReady) {
        setStatus("Monitoring", "ready");
      } else {
        setStatus("Waiting");
      }
    }

    async function pollNow() {
      const ioId = selectedDevice();
      const status = await api("/vm/api/device/" + encodeURIComponent(ioId) + "/debug/semantic-preview/status");
      let task = null;
      if (currentTaskId) {
        try {
          const taskPayload = await api("/vm/api/task/" + encodeURIComponent(currentTaskId));
          task = taskPayload.task;
        } catch (error) {
          log("Task read failed", { error: error.message });
        }
      }
      renderStatus(status, task);
      if (task && task.done) {
        log("Monitor triggered", { task_id: currentTaskId, note_count: (task.task_note || []).length });
      }
    }

    function startPolling() {
      clearInterval(pollTimer);
      pollTimer = setInterval(() => {
        pollNow().catch(error => {
          setStatus("Error", "error");
          log("Poll failed", { error: error.message });
        });
      }, 700);
    }

    async function registerBrowserCamera() {
      await api("/vm/api/browser-camera/facetime/register?client=binary-monitor-demo", {
        method: "POST",
        body: "{}",
      });
      await loadDevices();
      els.device.value = BROWSER_IO_ID;
      updatePreview(BROWSER_IO_ID);
    }

    async function postBrowserFrame() {
      if (!mediaStream || !els.browserVideo.videoWidth || !els.browserVideo.videoHeight) return;
      const canvas = els.browserCanvas;
      canvas.width = els.browserVideo.videoWidth;
      canvas.height = els.browserVideo.videoHeight;
      const ctx = canvas.getContext("2d", { alpha: false });
      ctx.drawImage(els.browserVideo, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.78));
      if (!blob) return;
      const response = await fetch("/vm/api/browser-camera/facetime/frame", {
        method: "POST",
        headers: { "Content-Type": "image/jpeg" },
        body: blob,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || ("frame post failed: HTTP " + response.status));
      }
    }

    async function startBrowserCamera() {
      setStatus("Requesting camera");
      await registerBrowserCamera();
      mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 960 }, height: { ideal: 540 }, facingMode: "user" },
        audio: false,
      });
      els.browserVideo.srcObject = mediaStream;
      els.videoBox.classList.add("browser-live");
      clearInterval(frameTimer);
      frameTimer = setInterval(() => {
        postBrowserFrame().catch(error => log("Frame post failed", { error: error.message }));
      }, 650);
      await postBrowserFrame();
      log("Browser camera started", { io_id: BROWSER_IO_ID });
      setStatus("Camera live", "ready");
    }

    function stopBrowserCamera() {
      clearInterval(frameTimer);
      frameTimer = null;
      if (mediaStream) {
        for (const track of mediaStream.getTracks()) track.stop();
      }
      mediaStream = null;
      els.videoBox.classList.remove("browser-live");
      updatePreview(selectedDevice());
      log("Browser camera stopped");
    }

    els.device.addEventListener("change", () => {
      updatePreview(selectedDevice());
      renderEmpty();
    });
    els.start.addEventListener("click", () => startMonitor().catch(error => {
      setStatus("Error", "error");
      log("Start failed", { error: error.message });
    }));
    els.stop.addEventListener("click", () => stopMonitor().catch(error => log("Stop failed", { error: error.message })));
    els.refresh.addEventListener("click", () => loadDevices().catch(error => log("Refresh failed", { error: error.message })));
    els.startBrowserCamera.addEventListener("click", () => startBrowserCamera().catch(error => {
      setStatus("Camera error", "error");
      log("Browser camera failed", { error: error.message });
    }));
    els.stopBrowserCamera.addEventListener("click", stopBrowserCamera);

    Promise.all([loadSettings(), loadDevices()])
      .then(() => {
        renderEmpty();
        startPolling();
        log("Demo ready");
      })
      .catch(error => {
        setStatus("Error", "error");
        log("Initialization failed", { error: error.message });
      });
  </script>
</body>
</html>`;

function createApp(baseUrl) {
  return createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (url.pathname === "/" && req.method === "GET") {
      send(res, 200, "text/html; charset=utf-8", pageHtml);
      return;
    }
    if (url.pathname.startsWith("/vm/")) {
      proxyRequest(req, res, baseUrl);
      return;
    }
    sendJson(res, 404, { status: "error", error: "not found" });
  });
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  if (!Number.isFinite(options.port) || options.port <= 0) {
    throw new Error("--port must be a positive number");
  }
  const app = createApp(options.baseUrl);
  await new Promise((resolve, reject) => {
    app.once("error", reject);
    app.listen(options.port, "127.0.0.1", resolve);
  });
  process.stdout.write(`Binary monitor tester: http://127.0.0.1:${options.port}\n`);
  process.stdout.write(`VideoMemory base: ${options.baseUrl}\n`);
}

main().catch(error => {
  process.stderr.write(`${error?.stack || error?.message || String(error)}\n`);
  process.exitCode = 1;
});
