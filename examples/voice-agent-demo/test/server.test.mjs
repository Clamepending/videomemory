import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { createServer } from "node:http";
import { createVoiceDemoServer } from "../server.mjs";

async function listen(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  return `http://127.0.0.1:${port}`;
}

async function close(server) {
  await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  return { response, body };
}

function createFakeVideoMemory(options = {}) {
  const calls = {
    settings: [],
    tasks: [],
    taskRecords: [],
    network: [],
    stops: [],
    captions: [],
    readiness: 0,
  };
  let taskCounter = 0;
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const rawBuffer = Buffer.concat(chunks);
    const raw = rawBuffer.toString("utf8");
    let body = {};
    try {
      body = raw && (req.headers["content-type"] || "").includes("application/json") ? JSON.parse(raw) : {};
    } catch {
      body = {};
    }

    function send(status, payload) {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(payload));
    }

    if (req.method === "GET" && url.pathname === "/api/health") {
      send(200, { status: "ok", active_tasks: calls.taskRecords.filter((task) => task.status === "active").length });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/settings") {
      send(200, {
        settings: {
          GOOGLE_API_KEY: { value: "****fake", is_set: true, source: "test" },
          OPENAI_API_KEY: { value: "", is_set: false, source: "unset" },
          VIDEO_INGESTOR_MODEL: { value: "fake-model", is_set: true, source: "test" },
        },
      });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/devices") {
      send(200, {
        devices: {
          camera: [
            { io_id: "browser_facetime", name: "Browser FaceTime Camera" },
            { io_id: "net_fake", name: "Fake Camera" },
          ],
        },
      });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/tasks") {
      send(200, { tasks: calls.taskRecords });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/browser-camera/facetime/register") {
      send(200, {
        status: "success",
        device: { io_id: "browser_facetime", name: "Browser FaceTime Camera" },
        snapshot_url: "http://127.0.0.1/api/browser-camera/facetime/latest.jpg",
      });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/browser-camera/facetime/status") {
      send(200, { camera_id: "facetime", has_frame: true, has_fresh_frame: true });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/browser-camera/facetime/frame") {
      send(200, { status: "ok", width: 640, height: 480 });
      return;
    }
    if (req.method === "PUT" && url.pathname.startsWith("/api/settings/")) {
      calls.settings.push({ key: decodeURIComponent(url.pathname.split("/").pop()), body });
      send(200, { status: "success" });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/devices/network") {
      calls.network.push(body);
      send(200, { status: "success", device: { io_id: "net_fake", name: body.name, url: body.url } });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/tasks") {
      taskCounter += 1;
      const taskId = `task_${taskCounter}`;
      calls.tasks.push(body);
      calls.taskRecords.push({
        task_id: taskId,
        io_id: body.io_id,
        bot_id: body.bot_id,
        status: "active",
        done: false,
        monitor_type: body.monitor_type,
        task_description: body.task_description,
        notes: [],
        created_at: new Date().toISOString(),
      });
      send(201, { status: "success", task_id: taskId, io_id: body.io_id, task_description: body.task_description });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/caption_frame") {
      calls.captions.push(body);
      send(200, { status: "success", analysis: options.caption || '{"observed": true, "value": 5, "confidence": "high", "reason": "clear hand"}' });
      return;
    }
    if (req.method === "POST" && /^\/api\/task\/[^/]+\/stop$/.test(url.pathname)) {
      const taskId = decodeURIComponent(url.pathname.split("/")[3]);
      calls.stops.push(taskId);
      const taskRecord = calls.taskRecords.find((task) => task.task_id === taskId);
      if (taskRecord) {
        taskRecord.status = "done";
        taskRecord.done = true;
        taskRecord.updated_at = new Date().toISOString();
      }
      send(200, { status: "success" });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/device/net_fake/readiness") {
      calls.readiness += 1;
      if (calls.readiness <= Number(options.notReadyResponses || 0)) {
        send(200, { status: "not_ready", ready: false, warnings: ["warming"], io_id: "net_fake" });
        return;
      }
      send(200, { status: "ready", ready: true, warnings: [], io_id: "net_fake" });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/device/browser_facetime/readiness") {
      send(200, {
        status: "not_ready",
        ready: false,
        warnings: ["Browser camera source has no fresh frames."],
        io_id: "browser_facetime",
      });
      return;
    }
    send(404, { status: "error", error: "not found" });
  });
  return { server, calls };
}

function createFakeOpenAI() {
  const calls = {
    clientSecrets: [],
  };
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const raw = Buffer.concat(chunks).toString("utf8");
    let body = {};
    try {
      body = raw ? JSON.parse(raw) : {};
    } catch {
      body = {};
    }
    function send(status, payload) {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(payload));
    }
    if (req.method === "POST" && url.pathname === "/realtime/client_secrets") {
      calls.clientSecrets.push({ headers: req.headers, body });
      send(201, {
        value: "ek_test",
        expires_at: Math.floor(Date.now() / 1000) + 600,
        session: body.session,
      });
      return;
    }
    send(404, { status: "error", error: "not found" });
  });
  return { server, calls };
}

test("command endpoint creates general fake-camera monitor, configures webhook, and omits semantic filters", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    const { response, body } = await requestJson(`${demoBase}/api/command`, {
      method: "POST",
      body: JSON.stringify({
        text: "Be a shopkeeper and watch these apples.",
        use_fake_camera: true,
      }),
    });

    assert.equal(response.status, 201);
    assert.equal(body.status, "success");
    assert.equal(body.registry_entry.task_id, "task_1");
    assert.equal(body.registry_entry.io_id, "net_fake");
    assert.equal(body.readiness.ready, true);
    assert.equal(vm.calls.network.length, 1);
    assert.equal(vm.calls.network[0].url, `${demoBase}/fake-camera/snapshot.ppm`);
    assert.equal(vm.calls.tasks.length, 1);
    assert.equal(vm.calls.tasks[0].monitor_type, "general");
    assert.equal(Object.hasOwn(vm.calls.tasks[0], "semantic_filter_keywords"), false);
    assert.equal(Object.hasOwn(vm.calls.tasks[0], "semantic_filter_config"), false);
    assert.ok(vm.calls.settings.some((call) => call.key === "VIDEOMEMORY_OPENCLAW_WEBHOOK_URL" && call.body.value === `${demoBase}/videomemory-event`));
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("command endpoint waits through transient fake-camera readiness", async () => {
  const vm = createFakeVideoMemory({ notReadyResponses: 2 });
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    const { response, body } = await requestJson(`${demoBase}/api/command`, {
      method: "POST",
      body: JSON.stringify({
        text: "Be a shopkeeper and watch these apples.",
        use_fake_camera: true,
      }),
    });

    assert.equal(response.status, 201);
    assert.equal(body.readiness.ready, true);
    assert.equal(vm.calls.readiness, 3);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("chat endpoint treats default shopkeeper ledger prompt as monitor setup", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    const { response, body } = await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({
        text: "Be a shopkeeper. Watch these apples. If someone walks up, ask for their name and keep a ledger.",
        use_fake_camera: true,
      }),
    });

    assert.equal(response.status, 200);
    assert.equal(body.kind, "monitor");
    assert.equal(body.registry_entry.task_id, "task_1");
    assert.equal(vm.calls.tasks.length, 1);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("chat endpoint records auditable tool calls for monitor setup", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({
        text: "Be a shopkeeper and watch these apples.",
        use_fake_camera: true,
      }),
    });
    const { body } = await requestJson(`${demoBase}/api/tool-calls`);
    const names = body.tool_calls.map((call) => call.name);

    assert.deepEqual(names, [
      "register_fake_camera",
      "configure_videomemory_webhook",
      "create_videomemory_monitor",
      "read_device_readiness",
    ]);
    const monitorCall = body.tool_calls.find((call) => call.name === "create_videomemory_monitor");
    assert.equal(monitorCall.input.monitor_type, "general");
    assert.equal(Object.hasOwn(monitorCall.input, "semantic_filter_keywords"), false);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("agent remembers apple-shopkeeper context across monitor setup turns", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({
        text: "You are a shopkeeper for these apples.",
        use_fake_camera: true,
      }),
    });
    const second = await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({
        text: "Wake up if someone takes one.",
        use_fake_camera: true,
      }),
    });
    const status = await requestJson(`${demoBase}/api/status`);

    assert.equal(second.body.kind, "monitor");
    assert.equal(second.body.registry_entry.persona, "apple_shopkeeper");
    assert.match(second.body.registry_entry.trigger_condition, /apple stand/);
    assert.equal(status.body.agent_context.item, "apple");
    assert.equal(vm.calls.tasks.length, 2);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("setup command can create a new monitor while a sale is pending", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "Be a shopkeeper and watch these apples.", use_fake_camera: true }),
    });
    await requestJson(`${demoBase}/api/simulate-event`, {
      method: "POST",
      body: JSON.stringify({ event_id: "pending-sale" }),
    });
    const setup = await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "Also wake up if someone takes one.", use_fake_camera: true }),
    });

    assert.equal(setup.body.kind, "monitor");
    assert.equal(setup.body.registry_entry.task_id, "task_2");
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("generic monitor stores action and wakeup speaks action content", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "When a blue cup is visible, then say the cup arrived.", use_fake_camera: true }),
    });
    const wake = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify({
        event_id: "cup-event",
        task_id: "task_1",
        io_id: "net_fake",
        note: "A blue cup is visible.",
      }),
    });

    assert.equal(wake.body.event.message, "the cup arrived.");
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("webhook ignores negative active general VideoMemory notes", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "When a blue cup is visible, then say the cup arrived.", use_fake_camera: true }),
    });
    const ignored = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify({
        event_id: "cup-negative-note",
        task_id: "task_1",
        io_id: "net_fake",
        task_done: false,
        task_status: "active",
        note: "No blue cup is visible in the frames.",
      }),
    });
    const debug = await requestJson(`${demoBase}/api/debug`);
    const toolCallNames = debug.body.recent.tool_calls.map((call) => call.name);

    assert.equal(ignored.response.status, 200);
    assert.equal(ignored.body.status, "ignored");
    assert.equal(ignored.body.reason, "negative_or_unclear_note");
    assert.equal(debug.body.recent.events.length, 0);
    assert.equal(debug.body.recent.ignored_events[0].event_id, "cup-negative-note");
    assert.ok(toolCallNames.includes("ignore_videomemory_task_update"));
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("webhook accepts affirmative active general VideoMemory notes", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "When a blue cup is visible, then say the cup arrived.", use_fake_camera: true }),
    });
    const wake = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify({
        event_id: "cup-positive-note",
        task_id: "task_1",
        io_id: "net_fake",
        task_done: false,
        task_status: "active",
        note: "A blue cup is visible in frame 4.",
      }),
    });
    const debug = await requestJson(`${demoBase}/api/debug`);
    const toolCallNames = debug.body.recent.tool_calls.map((call) => call.name);

    assert.equal(wake.response.status, 202);
    assert.equal(wake.body.event.message, "the cup arrived.");
    assert.equal(wake.body.event.active_general_note.reason, "general_note_satisfies_trigger");
    assert.equal(wake.body.event.stopped_active_task.status, "success");
    assert.equal(vm.calls.stops.length, 1);
    assert.equal(vm.calls.stops[0], "task_1");
    assert.equal(debug.body.recent.events.length, 1);
    assert.equal(debug.body.recent.ignored_events.length, 0);
    assert.ok(toolCallNames.includes("classify_videomemory_note"));
    assert.ok(toolCallNames.includes("accept_active_videomemory_note"));
    assert.ok(toolCallNames.includes("stop_triggered_active_monitor"));
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("webhook does not accept color-only overlap for a specific active general trigger", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "When a blue cup is visible, then say the cup arrived.", use_fake_camera: true }),
    });
    const ignored = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify({
        event_id: "blue-square-note",
        task_id: "task_1",
        io_id: "net_fake",
        task_done: false,
        task_status: "active",
        note: "A blue square object is visible in the frame.",
      }),
    });
    const debug = await requestJson(`${demoBase}/api/debug`);

    assert.equal(ignored.response.status, 200);
    assert.equal(ignored.body.status, "ignored");
    assert.equal(ignored.body.reason, "general_note_lacks_trigger_overlap");
    assert.equal(debug.body.recent.events.length, 0);
    assert.equal(vm.calls.stops.length, 0);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("webhook ignores unregistered foreign bot events instead of using latest monitor", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "When a phone is visible, tell the user that a phone is visible.", use_fake_camera: true }),
    });
    const ignored = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify({
        event_id: "foreign-binary-note",
        task_id: "foreign_task",
        bot_id: "binary-monitor-demo",
        io_id: "net_fake",
        task_done: true,
        task_status: "done",
        note: "Binary criterion met: a cup is visible.",
      }),
    });
    const debug = await requestJson(`${demoBase}/api/debug`);

    assert.equal(ignored.response.status, 200);
    assert.equal(ignored.body.status, "ignored");
    assert.equal(ignored.body.reason, "foreign_bot_event");
    assert.equal(debug.body.recent.events.length, 0);
    assert.equal(debug.body.recent.ignored_events[0].event_id, "foreign-binary-note");
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("webhook endpoint broadcasts one wakeup and deduplicates repeated event ids", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/command`, {
      method: "POST",
      body: JSON.stringify({ text: "Be a shopkeeper and watch these apples.", use_fake_camera: true }),
    });

    const payload = {
      event_id: "evt-1",
      idempotency_key: "evt-1",
      task_id: "task_1",
      io_id: "net_fake",
      note: "A customer picked up an apple.",
    };
    const first = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const second = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    assert.equal(first.response.status, 202);
    assert.equal(first.body.status, "success");
    assert.match(first.body.event.message, /What's your name/);
    assert.equal(second.response.status, 200);
    assert.equal(second.body.status, "duplicate");
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("chat endpoint records pending shopkeeper sale and summarizes ledger", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/command`, {
      method: "POST",
      body: JSON.stringify({ text: "Be a shopkeeper and watch these apples.", use_fake_camera: true }),
    });
    await requestJson(`${demoBase}/api/simulate-event`, {
      method: "POST",
      body: JSON.stringify({ event_id: "sale-1" }),
    });
    const sale = await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "My name is Sam and I took two apples." }),
    });
    const summary = await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "What is the ledger total?" }),
    });

    assert.equal(sale.body.kind, "ledger_entry");
    assert.equal(sale.body.entry.name, "Sam");
    assert.equal(sale.body.entry.apple_count, 2);
    assert.match(summary.body.reply, /Total: 2 apples, \$2/);
    const tools = await requestJson(`${demoBase}/api/tool-calls`);
    assert.ok(tools.body.tool_calls.some((call) => call.name === "handle_videomemory_wakeup"));
    assert.ok(tools.body.tool_calls.some((call) => call.name === "record_ledger_entry"));
    assert.ok(tools.body.tool_calls.some((call) => call.name === "answer_ledger"));
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("fake camera endpoint returns a PPM snapshot", async () => {
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: "http://127.0.0.1:1", stateDir });
  const demoBase = await listen(demo);
  try {
    const response = await fetch(`${demoBase}/fake-camera/snapshot.ppm`);
    const bytes = Buffer.from(await response.arrayBuffer());
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-type"), "image/x-portable-pixmap");
    assert.equal(bytes.subarray(0, 2).toString("ascii"), "P6");
  } finally {
    await close(demo);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("realtime client secret endpoint configures voice, tools, and image-capable model", async () => {
  const openai = createFakeOpenAI();
  const openaiBase = await listen(openai.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({
    videomemoryBaseUrl: "http://127.0.0.1:1",
    openaiApiKey: "sk-test",
    openaiBaseUrl: openaiBase,
    stateDir,
  });
  const demoBase = await listen(demo);

  try {
    const { response, body } = await requestJson(`${demoBase}/api/realtime/client-secret`, {
      method: "POST",
      body: "{}",
    });

    assert.equal(response.status, 201);
    assert.equal(body.value, "ek_test");
    assert.equal(openai.calls.clientSecrets.length, 1);
    assert.equal(openai.calls.clientSecrets[0].body.session.type, "realtime");
    assert.equal(openai.calls.clientSecrets[0].body.session.model, "gpt-realtime-2");
    assert.ok(openai.calls.clientSecrets[0].body.session.tools.some((tool) => tool.name === "set_videomemory_monitor"));
    assert.ok(openai.calls.clientSecrets[0].body.session.tools.some((tool) => tool.name === "record_ledger_entry"));
  } finally {
    await close(demo);
    await close(openai.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("realtime client secret endpoint reports missing OpenAI key clearly", async () => {
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: "http://127.0.0.1:1", stateDir });
  const demoBase = await listen(demo);

  try {
    const { response, body } = await requestJson(`${demoBase}/api/realtime/client-secret`, {
      method: "POST",
      body: "{}",
    });

    assert.equal(response.status, 428);
    assert.match(body.error, /OPENAI_API_KEY/);
  } finally {
    await close(demo);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("realtime tool can arm a live VideoMemory monitor", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    const { response, body } = await requestJson(`${demoBase}/api/realtime/tool`, {
      method: "POST",
      body: JSON.stringify({
        name: "set_videomemory_monitor",
        arguments: { instruction: "Be a shopkeeper and watch these apples." },
      }),
    });
    const status = await requestJson(`${demoBase}/api/status`);

    assert.equal(response.status, 200);
    assert.equal(body.tool, "set_videomemory_monitor");
    assert.equal(body.registry_entry.io_id, "browser_facetime");
    assert.equal(status.body.latest_monitor.task_id, "task_1");
    assert.equal(vm.calls.tasks.length, 1);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("debug endpoint returns monitor, task, readiness, and tool-call state", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/realtime/tool`, {
      method: "POST",
      body: JSON.stringify({
        name: "set_videomemory_monitor",
        arguments: { instruction: "Tell me when I hold up one finger." },
      }),
    });
    const { response, body } = await requestJson(`${demoBase}/api/debug`);
    const warningCodes = body.warnings.map((warning) => warning.code);
    const toolCallNames = body.recent.tool_calls.map((call) => call.name);

    assert.equal(response.status, 200);
    assert.equal(body.status, "success");
    assert.equal(body.current.latest_monitor.task_id, "task_1");
    assert.equal(body.current.registry_count, 1);
    assert.equal(body.browser_camera.readiness.ready, false);
    assert.equal(body.videomemory.voice_agent_tasks[0].task_id, "task_1");
    assert.equal(body.videomemory.voice_agent_tasks[0].status, "active");
    assert.ok(warningCodes.includes("browser_camera_not_ready"));
    assert.ok(warningCodes.includes("realtime_key_missing"));
    assert.ok(toolCallNames.includes("create_videomemory_monitor"));
    assert.ok(toolCallNames.includes("read_device_readiness"));
    assert.match(body.debug_urls.debug, /\/api\/debug$/);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("persistent lifecycle can be explicitly requested for a generic one-shot-shaped monitor", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    const { response, body } = await requestJson(`${demoBase}/api/realtime/tool`, {
      method: "POST",
      body: JSON.stringify({
        name: "set_videomemory_monitor",
        arguments: {
          instruction: "When you see a bird, say bird.",
          lifecycle: "persistent",
        },
      }),
    });

    assert.equal(response.status, 200);
    assert.equal(body.registry_entry.lifecycle, "persistent");
    assert.equal(body.registry_entry.rearm_on_wakeup, true);
    assert.equal(body.registry_entry.silent_wakeup, false);
    assert.equal(vm.calls.tasks.length, 1);
    assert.match(vm.calls.tasks[0].task_description, /bird/i);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("visual-memory setup creates a persistent silent monitor with the extracted visual condition", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    const { response, body } = await requestJson(`${demoBase}/api/realtime/tool`, {
      method: "POST",
      body: JSON.stringify({
        name: "set_videomemory_monitor",
        arguments: {
          instruction: "Watch the live camera for fingers. Each time I hold up fingers, add that number to a running total. Only report when I ask for the total.",
          lifecycle: "persistent",
        },
      }),
    });
    const status = await requestJson(`${demoBase}/api/status`);

    assert.equal(response.status, 200);
    assert.equal(body.registry_entry.persona, "visual_memory");
    assert.equal(body.registry_entry.lifecycle, "persistent");
    assert.equal(body.registry_entry.silent_wakeup, true);
    assert.match(vm.calls.tasks[0].task_description, /hold up fingers/i);
    assert.doesNotMatch(vm.calls.tasks[0].task_description, /asks for the total/i);
    assert.equal(status.body.visual_memory.total, 0);
    assert.equal(status.body.visual_memory.active_task_id, "task_1");
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("visual-memory wakeup captions the frame, records total, and re-arms silently", async () => {
  const vm = createFakeVideoMemory({ caption: '{"observed": true, "value": 5, "confidence": "high"}' });
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/realtime/tool`, {
      method: "POST",
      body: JSON.stringify({
        name: "set_videomemory_monitor",
        arguments: {
          instruction: "Watch the live camera for fingers. Each time I hold up fingers, add that number to a running total. Only report when I ask for the total.",
          lifecycle: "persistent",
        },
      }),
    });
    const wake = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify({
        event_id: "finger-evt-1",
        task_id: "task_1",
        io_id: "browser_facetime",
        note: "Binary criterion met.",
      }),
    });
    const total = await requestJson(`${demoBase}/api/realtime/tool`, {
      method: "POST",
      body: JSON.stringify({ name: "answer_visual_memory", arguments: {} }),
    });

    assert.equal(wake.response.status, 202);
    assert.equal(wake.body.event.silent, true);
    assert.equal(wake.body.event.visual_memory.value, 5);
    assert.equal(wake.body.event.visual_memory.total, 5);
    assert.equal(wake.body.event.visual_memory.rearmed_task_id, "task_2");
    assert.equal(vm.calls.captions.length, 1);
    assert.equal(vm.calls.tasks.length, 2);
    assert.match(vm.calls.tasks[1].task_description, /previous extracted value: 5/);
    assert.equal(total.body.summary, "Finger count total: 5. Observations: 5.");
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("generic persistent monitor re-arms after each wakeup without becoming a visual-memory counter", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/realtime/tool`, {
      method: "POST",
      body: JSON.stringify({
        name: "set_videomemory_monitor",
        arguments: {
          instruction: "When you see a bird, say bird.",
          lifecycle: "persistent",
        },
      }),
    });
    const wake = await requestJson(`${demoBase}/videomemory-event`, {
      method: "POST",
      body: JSON.stringify({
        event_id: "bird-evt-1",
        task_id: "task_1",
        io_id: "browser_facetime",
        note: "A bird is visible.",
      }),
    });

    assert.equal(wake.response.status, 202);
    assert.equal(wake.body.event.silent, false);
    assert.equal(wake.body.event.visual_memory, null);
    assert.equal(vm.calls.tasks.length, 2);
    assert.match(vm.calls.tasks[1].task_description, /new occurrence/i);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("reset endpoint clears stale monitor state and stops remembered VideoMemory tasks", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    await requestJson(`${demoBase}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ text: "Be a shopkeeper and watch these apples.", use_fake_camera: true }),
    });
    await requestJson(`${demoBase}/api/simulate-event`, {
      method: "POST",
      body: JSON.stringify({ event_id: "reset-sale" }),
    });
    const reset = await requestJson(`${demoBase}/api/reset`, { method: "POST", body: "{}" });
    const status = await requestJson(`${demoBase}/api/status`);

    assert.equal(reset.response.status, 200);
    assert.deepEqual(reset.body.stopped_task_ids, ["task_1"]);
    assert.equal(vm.calls.stops[0], "task_1");
    assert.equal(status.body.latest_monitor, null);
    assert.equal(status.body.pending_sale, null);
    assert.equal(status.body.ledger_count, 0);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});

test("live camera proxy registers, forwards frame bytes, and reports status", async () => {
  const vm = createFakeVideoMemory();
  const vmBase = await listen(vm.server);
  const stateDir = await mkdtemp(join(tmpdir(), "voice-demo-"));
  const demo = createVoiceDemoServer({ videomemoryBaseUrl: vmBase, stateDir });
  const demoBase = await listen(demo);

  try {
    const registered = await requestJson(`${demoBase}/api/live-camera/register`, { method: "POST", body: "{}" });
    const frame = await fetch(`${demoBase}/api/live-camera/frame`, {
      method: "POST",
      headers: { "Content-Type": "image/jpeg" },
      body: Buffer.from("fake-jpeg"),
    });
    const frameBody = await frame.json();
    const status = await requestJson(`${demoBase}/api/live-camera/status`);

    assert.equal(registered.body.device.io_id, "browser_facetime");
    assert.equal(frame.status, 200);
    assert.equal(frameBody.status, "ok");
    assert.equal(status.body.camera.has_fresh_frame, true);
  } finally {
    await close(demo);
    await close(vm.server);
    await rm(stateDir, { recursive: true, force: true });
  }
});
