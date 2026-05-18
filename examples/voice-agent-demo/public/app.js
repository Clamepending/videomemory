const REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls";

const state = {
  useFakeCamera: false,
  lastTaskId: "",
  mediaStream: null,
  frameTimer: null,
  framesPosted: 0,
  pc: null,
  dc: null,
  realtimeReady: false,
  handledToolCalls: new Set(),
  currentAssistantText: "",
  lastImageContextAt: 0,
  responseInProgress: false,
  lastWakeupAt: 0,
  announcedWakeupEventIds: new Set(),
};

const els = {
  statusLine: document.getElementById("statusLine"),
  vmUrl: document.getElementById("vmUrl"),
  webhookUrl: document.getElementById("webhookUrl"),
  taskId: document.getElementById("taskId"),
  readiness: document.getElementById("readiness"),
  wakeState: document.getElementById("wakeState"),
  transcript: document.getElementById("transcript"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  simulateWakeup: document.getElementById("simulateWakeup"),
  registerFakeCamera: document.getElementById("registerFakeCamera"),
  copyDebugSnapshot: document.getElementById("copyDebugSnapshot"),
  fakeScene: document.getElementById("fakeScene"),
  fakePreview: document.getElementById("fakePreview"),
  liveCameraMode: document.getElementById("liveCameraMode"),
  fakeCameraMode: document.getElementById("fakeCameraMode"),
  ledgerBody: document.getElementById("ledgerBody"),
  clearLedger: document.getElementById("clearLedger"),
  events: document.getElementById("events"),
  refreshStatus: document.getElementById("refreshStatus"),
  startLive: document.getElementById("startLive"),
  talkButton: document.getElementById("talkButton"),
  resetDemo: document.getElementById("resetDemo"),
  shopkeeperButton: document.getElementById("shopkeeperButton"),
  liveVideo: document.getElementById("liveVideo"),
  remoteAudio: document.getElementById("remoteAudio"),
  liveCanvas: document.getElementById("liveCanvas"),
  liveStatus: document.getElementById("liveStatus"),
  cameraShell: document.querySelector(".camera-shell"),
};

function appendMessage(role, text) {
  if (!text) return;
  const item = document.createElement("div");
  item.className = `message ${role}`;
  if (role === "system") {
    item.setAttribute("aria-hidden", "true");
  }
  const label = document.createElement("strong");
  label.textContent = role;
  const body = document.createElement("div");
  body.textContent = text;
  item.append(label, body);
  els.transcript.append(item);
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

function clearTranscript() {
  els.transcript.replaceChildren();
}

function appendEvent(event) {
  els.events.textContent = `${new Date().toLocaleTimeString()} ${JSON.stringify(event, null, 2)}\n\n${els.events.textContent}`;
}

function oneLine(value, fallback = "") {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text || fallback;
}

function setWakeState(label, className = "") {
  els.wakeState.textContent = label;
  els.wakeState.className = `pill ${className}`.trim();
}

function setLiveStatus(text) {
  els.liveStatus.textContent = text;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || body.message || `HTTP ${response.status}`);
  }
  return body;
}

async function registerLiveCamera() {
  const body = await api("/api/live-camera/register", { method: "POST", body: "{}" });
  return body.device?.io_id || body.io_id || "browser_facetime";
}

async function postLiveFrame() {
  if (!state.mediaStream || !els.liveVideo.videoWidth || !els.liveVideo.videoHeight) return;
  const width = els.liveVideo.videoWidth;
  const height = els.liveVideo.videoHeight;
  if (width < 64 || height < 64) return;
  const canvas = els.liveCanvas;
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const ctx = canvas.getContext("2d", { alpha: false });
  ctx.drawImage(els.liveVideo, 0, 0, width, height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.78));
  if (!blob) return;
  const response = await fetch("/api/live-camera/frame", {
    method: "POST",
    headers: { "Content-Type": "image/jpeg" },
    body: blob,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || body.message || `Frame post failed: ${response.status}`);
  }
  state.framesPosted += 1;
}

async function startCameraAndFrameRelay() {
  if (state.mediaStream) return state.mediaStream;
  setLiveStatus("Requesting camera and microphone permission...");
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 960 }, height: { ideal: 540 }, facingMode: "user" },
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  state.mediaStream = stream;
  els.liveVideo.srcObject = stream;
  els.cameraShell.classList.add("live");
  await registerLiveCamera();
  state.useFakeCamera = false;
  setCameraMode(false);
  clearInterval(state.frameTimer);
  state.frameTimer = setInterval(() => {
    postLiveFrame().catch((error) => setLiveStatus(error.message));
  }, 700);
  await postLiveFrame();
  return stream;
}

function captureCameraDataUrl(maxWidth = 640) {
  if (!els.liveVideo.videoWidth || !els.liveVideo.videoHeight) return "";
  const sourceWidth = els.liveVideo.videoWidth;
  const sourceHeight = els.liveVideo.videoHeight;
  const scale = Math.min(1, maxWidth / sourceWidth);
  const width = Math.round(sourceWidth * scale);
  const height = Math.round(sourceHeight * scale);
  const canvas = els.liveCanvas;
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d", { alpha: false });
  ctx.drawImage(els.liveVideo, 0, 0, width, height);
  return canvas.toDataURL("image/jpeg", 0.72);
}

function sendRealtimeEvent(event) {
  if (!state.dc || state.dc.readyState !== "open") return false;
  state.dc.send(JSON.stringify(event));
  return true;
}

function createRealtimeResponse(response = null) {
  const event = { type: "response.create" };
  if (response) event.response = response;
  return sendRealtimeEvent(event);
}

async function injectCameraContext(reason, { force = false } = {}) {
  if (!state.realtimeReady) return false;
  const now = Date.now();
  if (!force && now - state.lastImageContextAt < 2000) return false;
  const imageUrl = captureCameraDataUrl();
  if (!imageUrl) return false;
  state.lastImageContextAt = now;
  return sendRealtimeEvent({
    type: "conversation.item.create",
    item: {
      type: "message",
      role: "user",
      content: [
        {
          type: "input_text",
          text: `${reason} This is visual context only. Do not respond solely because this frame arrived.`,
        },
        {
          type: "input_image",
          image_url: imageUrl,
        },
      ],
    },
  });
}

async function connectRealtime(stream, token) {
  const ephemeralKey = token.value || token.client_secret?.value;
  if (!ephemeralKey) throw new Error("Realtime client secret response did not include a usable token.");

  const pc = new RTCPeerConnection();
  state.pc = pc;
  state.handledToolCalls = new Set();
  state.currentAssistantText = "";
  state.responseInProgress = false;

  pc.ontrack = (event) => {
    els.remoteAudio.srcObject = event.streams[0];
  };

  for (const track of stream.getAudioTracks()) {
    pc.addTrack(track, stream);
  }

  const dc = pc.createDataChannel("oai-events");
  state.dc = dc;

  dc.addEventListener("open", async () => {
    state.realtimeReady = true;
    els.startLive.disabled = true;
    els.talkButton.disabled = false;
    setLiveStatus("Live. Camera, microphone, and speaker are connected. Just speak.");
    await injectCameraContext("Initial camera frame after connecting the live agent.", { force: true });
  });
  dc.addEventListener("message", (message) => {
    try {
      handleRealtimeEvent(JSON.parse(message.data));
    } catch (error) {
      appendMessage("system", error.message);
    }
  });
  dc.addEventListener("close", () => {
    state.realtimeReady = false;
    if (state.mediaStream) setLiveStatus("Realtime connection closed. Camera may still be on.");
  });

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const sdpResponse = await fetch(REALTIME_CALLS_URL, {
    method: "POST",
    body: offer.sdp,
    headers: {
      Authorization: `Bearer ${ephemeralKey}`,
      "Content-Type": "application/sdp",
    },
  });
  if (!sdpResponse.ok) {
    const text = await sdpResponse.text();
    throw new Error(text || `Realtime SDP exchange failed: HTTP ${sdpResponse.status}`);
  }
  await pc.setRemoteDescription({
    type: "answer",
    sdp: await sdpResponse.text(),
  });
}

async function startRealtimeAgent() {
  if (state.realtimeReady) {
    setLiveStatus("Live agent is already running. Just speak.");
    return;
  }
  setLiveStatus("Connecting to the voice model...");
  const token = await api("/api/realtime/client-secret", { method: "POST", body: "{}" });
  setLiveStatus("Starting live camera and microphone...");
  const stream = await startCameraAndFrameRelay();
  await connectRealtime(stream, token);
}

function stopRealtimeAgent() {
  clearInterval(state.frameTimer);
  state.frameTimer = null;
  if (state.dc) state.dc.close();
  if (state.pc) state.pc.close();
  if (state.mediaStream) {
    for (const track of state.mediaStream.getTracks()) track.stop();
  }
  state.mediaStream = null;
  state.pc = null;
  state.dc = null;
  state.realtimeReady = false;
  state.framesPosted = 0;
  els.liveVideo.srcObject = null;
  els.remoteAudio.srcObject = null;
  els.cameraShell.classList.remove("live");
  els.startLive.disabled = false;
  els.talkButton.disabled = true;
  setLiveStatus("Stopped. Nothing is listening or watching through this page.");
}

function findFunctionCalls(event) {
  const output = event.response?.output || [];
  return output.filter((item) => item?.type === "function_call" && item.call_id && item.name);
}

async function handleFunctionCall(call) {
  if (state.handledToolCalls.has(call.call_id)) return;
  state.handledToolCalls.add(call.call_id);
  let args = {};
  try {
    args = call.arguments ? JSON.parse(call.arguments) : {};
  } catch {
    args = {};
  }
  appendEvent({ type: "realtime_tool_call", name: call.name, arguments: args });
  let output;
  try {
    output = await api("/api/realtime/tool", {
      method: "POST",
      body: JSON.stringify({ name: call.name, arguments: args }),
    });
    await refreshStatus();
    await refreshLedger();
  } catch (error) {
    output = { status: "error", error: error.message };
  }
  sendRealtimeEvent({
    type: "conversation.item.create",
    item: {
      type: "function_call_output",
      call_id: call.call_id,
      output: JSON.stringify(output),
    },
  });
  const wakeupJustArrived = state.lastWakeupAt && Date.now() - state.lastWakeupAt < 3000;
  if (call.name === "set_videomemory_monitor" && wakeupJustArrived) {
    appendEvent({
      type: "realtime_tool_response_skipped",
      reason: "VideoMemory woke the agent while the monitor setup tool call was finishing.",
      call_id: call.call_id,
    });
    return;
  }
  createRealtimeResponse();
}

function handleRealtimeEvent(event) {
  if (event.type === "error") {
    appendMessage("system", event.error?.message || event.message || "Realtime error.");
    return;
  }
  if (event.type === "input_audio_buffer.speech_started") {
    injectCameraContext("Camera frame captured as the user started speaking.").catch(() => {});
    setLiveStatus("Listening...");
    return;
  }
  if (event.type === "input_audio_buffer.speech_stopped") {
    setLiveStatus("Thinking...");
    return;
  }
  if (event.type === "response.created") {
    state.responseInProgress = true;
    return;
  }
  if (event.type === "conversation.item.input_audio_transcription.completed" && event.transcript) {
    appendMessage("user", event.transcript);
    return;
  }
  if (event.type === "response.output_text.delta" && event.delta) {
    state.currentAssistantText += event.delta;
    return;
  }
  if ((event.type === "response.audio_transcript.delta" || event.type === "response.output_audio_transcript.delta") && event.delta) {
    state.currentAssistantText += event.delta;
    return;
  }
  if (event.type === "response.audio_transcript.done" || event.type === "response.output_audio_transcript.done") {
    const text = event.transcript || state.currentAssistantText;
    appendMessage("assistant", text);
    state.currentAssistantText = "";
    setLiveStatus("Live. Just speak.");
    return;
  }
  if (event.type === "response.done") {
    state.responseInProgress = false;
    const calls = findFunctionCalls(event);
    for (const call of calls) {
      handleFunctionCall(call).catch((error) => appendMessage("system", error.message));
    }
    if (!calls.length && state.currentAssistantText) {
      appendMessage("assistant", state.currentAssistantText);
      state.currentAssistantText = "";
    }
    setLiveStatus("Live. Just speak.");
  }
}

async function refreshStatus() {
  const status = await api("/api/status");
  els.statusLine.textContent = status.health?.status === "ok"
    ? "VideoMemory is reachable."
    : `VideoMemory status: ${status.health?.error || status.health?.status || "unknown"}`;
  if (!status.realtime?.configured) {
    els.statusLine.textContent += " OpenAI realtime key is missing.";
  }
  if (status.videomemory_settings?.model_key_configured === false) {
    els.statusLine.textContent += " VideoMemory model key is missing.";
  }
  els.vmUrl.textContent = status.videomemory_base_url;
  els.webhookUrl.textContent = status.webhook_url;
  if (status.latest_monitor?.task_id) {
    state.lastTaskId = status.latest_monitor.task_id;
    els.taskId.textContent = status.latest_monitor.task_id;
    els.readiness.textContent = "armed";
    if (!status.pending_sale) setWakeState("armed", "armed");
  } else {
    state.lastTaskId = "";
    els.taskId.textContent = "none";
    els.readiness.textContent = "not armed";
    if (!status.pending_sale) setWakeState("idle");
  }
  if (status.pending_sale) {
    setWakeState("awaiting sale", "wake");
  }
  return status;
}

async function refreshLedger() {
  const body = await api("/api/ledger");
  const rows = body.ledger || [];
  if (rows.length === 0) {
    els.ledgerBody.innerHTML = '<tr><td colspan="4">No entries</td></tr>';
    return;
  }
  els.ledgerBody.replaceChildren(...rows.map((entry) => {
    const tr = document.createElement("tr");
    const evidence = entry.evidence_url
      ? `<a href="${entry.evidence_url}" target="_blank" rel="noreferrer">open</a>`
      : "-";
    tr.innerHTML = `<td></td><td></td><td></td><td>${evidence}</td>`;
    tr.children[0].textContent = entry.name;
    tr.children[1].textContent = String(entry.apple_count);
    tr.children[2].textContent = `$${entry.amount_due}`;
    return tr;
  }));
}

function setCameraMode(useFake) {
  state.useFakeCamera = useFake;
  els.fakeCameraMode.classList.toggle("selected", useFake);
  els.liveCameraMode.classList.toggle("selected", !useFake);
}

async function sendFallbackChat(text) {
  appendMessage("user", text);
  const body = await api("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      text,
      use_fake_camera: state.useFakeCamera,
    }),
  });
  if (body.task || body.registry_entry) {
    const taskId = body.registry_entry?.task_id || body.task?.task_id || body.task?.task?.task_id || "";
    state.lastTaskId = taskId;
    els.taskId.textContent = taskId || "created";
    els.readiness.textContent = body.readiness?.ready ? "ready" : (body.readiness?.warnings || ["not ready"]).join(" ");
    setWakeState(body.readiness?.ready ? "armed" : "created", body.readiness?.ready ? "armed" : "");
  }
  appendMessage("assistant", body.reply || "Done.");
  if (body.kind === "ledger_entry" || body.kind === "ledger") {
    await refreshLedger();
  }
}

async function sendChat(text) {
  if (state.realtimeReady) {
    appendMessage("user", text);
    await injectCameraContext("Camera frame captured for the user's typed message.", { force: true });
    sendRealtimeEvent({
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text }],
      },
    });
    createRealtimeResponse();
    return;
  }
  await sendFallbackChat(text);
}

function shouldSpeakWakeup(event) {
  return Boolean(event && !event.silent && !event.registry_entry?.silent_wakeup && oneLine(event.message));
}

function announceWakeupToRealtime(event) {
  if (!state.realtimeReady || !shouldSpeakWakeup(event)) return false;
  const eventId = oneLine(event.event_id, `wakeup-${Date.now()}`);
  if (state.announcedWakeupEventIds.has(eventId)) return true;
  state.announcedWakeupEventIds.add(eventId);
  const message = oneLine(event.message, "The visual condition happened.").slice(0, 600);
  const note = oneLine(event.note).slice(0, 1000);
  state.lastWakeupAt = Date.now();

  if (state.responseInProgress) {
    sendRealtimeEvent({ type: "response.cancel" });
    state.responseInProgress = false;
  }

  const created = sendRealtimeEvent({
    type: "conversation.item.create",
    item: {
      type: "message",
      role: "user",
      content: [{
        type: "input_text",
        text: [
          "External VideoMemory wakeup event received.",
          `Event message: ${message}`,
          note ? `Observation: ${note}` : "",
          "This is authoritative: the monitor already fired. Do not say you have not seen it. Do not set another monitor. Respond out loud now with the event message.",
        ].filter(Boolean).join("\n"),
      }],
    },
  });
  if (!created) return false;

  createRealtimeResponse({
    instructions: `A VideoMemory monitor just fired. Speak exactly this concise notification to the user now: "${message}". Do not say the monitor is only armed, do not say you have not seen it, and do not create another monitor.`,
    metadata: {
      source: "videomemory_wakeup",
      event_id: eventId,
    },
  });
  setLiveStatus("VideoMemory woke the live agent.");
  return true;
}

async function resetDemo() {
  await api("/api/reset", { method: "POST", body: "{}" });
  state.lastTaskId = "";
  state.handledToolCalls = new Set();
  state.lastWakeupAt = 0;
  state.announcedWakeupEventIds = new Set();
  clearTranscript();
  els.events.textContent = "";
  els.taskId.textContent = "none";
  els.readiness.textContent = "not armed";
  setWakeState("idle");
  await refreshLedger();
  await refreshStatus();
  setLiveStatus(state.realtimeReady
    ? "Reset. Live agent is still connected; nothing is armed."
    : "Reset. Nothing is armed.");
}

function connectEvents() {
  const source = new EventSource("/events");
  source.addEventListener("wakeup", async (message) => {
    const event = JSON.parse(message.data);
    appendEvent(event);
    setWakeState("woke up", "wake");
    await refreshStatus();
    appendMessage("system", `VideoMemory wakeup: ${event.message}${event.note ? ` Observation: ${event.note}` : ""}`);
    const announcedToRealtime = announceWakeupToRealtime(event);
    if (shouldSpeakWakeup(event) && !announcedToRealtime) {
      appendMessage("assistant text-only", event.message);
    }
  });
  source.addEventListener("monitor", (message) => appendEvent(JSON.parse(message.data)));
  source.addEventListener("tool_call", (message) => appendEvent(JSON.parse(message.data)));
  source.addEventListener("ledger", async (message) => {
    appendEvent(JSON.parse(message.data));
    await refreshLedger();
  });
  source.addEventListener("ledger_reset", async () => refreshLedger());
  source.addEventListener("reset", async () => {
    await refreshLedger();
    await refreshStatus();
  });
  source.addEventListener("fake_camera", (message) => appendEvent(JSON.parse(message.data)));
}

els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = els.chatInput.value.trim();
  if (!text) return;
  els.chatInput.value = "";
  sendChat(text).catch((error) => appendMessage("system", error.message));
});

els.startLive.addEventListener("click", () => {
  startRealtimeAgent().catch((error) => {
    setLiveStatus(error.message);
    appendMessage("system", error.message);
  });
});

els.talkButton.addEventListener("click", () => stopRealtimeAgent());
els.talkButton.disabled = true;

els.resetDemo.addEventListener("click", () => {
  resetDemo().catch((error) => appendMessage("system", error.message));
});

els.shopkeeperButton.addEventListener("click", () => {
  const prompt = "Be a shopkeeper. Watch these apples. If someone walks up or takes an apple, ask for their name, charge $1 per apple, and keep a ledger.";
  sendChat(prompt).catch((error) => appendMessage("system", error.message));
});

els.liveCameraMode.addEventListener("click", () => setCameraMode(false));
els.fakeCameraMode.addEventListener("click", () => setCameraMode(true));

els.simulateWakeup.addEventListener("click", async () => {
  try {
    const eventId = `browser-sim-${Date.now()}`;
    const body = await api("/api/simulate-event", {
      method: "POST",
      body: JSON.stringify({ task_id: state.lastTaskId, event_id: eventId }),
    });
    appendEvent(body);
  } catch (error) {
    appendMessage("system", error.message);
  }
});

els.registerFakeCamera.addEventListener("click", async () => {
  try {
    const body = await api("/api/fake-camera/register", { method: "POST", body: "{}" });
    appendMessage("system", `Fake camera registered as ${body.io_id || body.device?.io_id}.`);
  } catch (error) {
    appendMessage("system", error.message);
  }
});

els.copyDebugSnapshot.addEventListener("click", async () => {
  try {
    const body = await api("/api/debug");
    const text = JSON.stringify(body, null, 2);
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      appendMessage("system", "Debug snapshot copied.");
    } else {
      els.events.textContent = `${text}\n\n${els.events.textContent}`;
      appendMessage("system", "Debug snapshot added to the Events panel.");
    }
  } catch (error) {
    appendMessage("system", error.message);
  }
});

els.fakeScene.addEventListener("change", async () => {
  try {
    await api("/api/fake-camera/scene", {
      method: "POST",
      body: JSON.stringify({ scene: els.fakeScene.value }),
    });
    els.fakePreview.src = `/fake-camera/preview.svg?t=${Date.now()}`;
  } catch (error) {
    appendMessage("system", error.message);
  }
});

els.clearLedger.addEventListener("click", async () => {
  await api("/api/ledger", { method: "DELETE" });
  await refreshLedger();
});

els.refreshStatus.addEventListener("click", () => refreshStatus().catch((error) => appendMessage("system", error.message)));

connectEvents();
refreshStatus().catch((error) => appendMessage("system", error.message));
refreshLedger().catch((error) => appendMessage("system", error.message));
