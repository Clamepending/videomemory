#!/usr/bin/env node

import { spawn } from 'node:child_process'
import http from 'node:http'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js'

const HOST = process.env.VIDEOMEMORY_CLAUDE_CHANNEL_HOST || '127.0.0.1'
const PORT = Number(process.env.VIDEOMEMORY_CLAUDE_CHANNEL_PORT || 8791)
const BASE_URL = (process.env.VIDEOMEMORY_BASE_URL || 'http://127.0.0.1:5050').replace(/\/+$/, '')
const TOKEN = cleanText(process.env.VIDEOMEMORY_CLAUDE_CHANNEL_TOKEN)
const PLUGIN_ROOT = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(PLUGIN_ROOT, '..')
const STATE_DIR = join(homedir(), '.claude', 'channels', 'videomemory')
const REPLY_LOG = join(STATE_DIR, 'replies.jsonl')

const clients = new Set()
const seenEventIds = new Map()
let replySeq = 0

function cleanText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function asString(value) {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  return String(value)
}

function sendJson(res, payload, status = 200) {
  const body = JSON.stringify(payload, null, 2)
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  })
  res.end(body)
}

function sseEncode(event, payload) {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
}

function broadcast(event, payload) {
  const chunk = sseEncode(event, payload)
  for (const res of clients) res.write(chunk)
}

function requireAuthorized(req, res) {
  if (!TOKEN) return false
  const header = cleanText(req.headers.authorization)
  if (header === `Bearer ${TOKEN}`) return false
  sendJson(res, { status: 'error', error: 'unauthorized' }, 401)
  return true
}

function pruneSeenEvents() {
  const cutoff = Date.now() - 10 * 60 * 1000
  for (const [eventId, seenAt] of seenEventIds) {
    if (seenAt < cutoff) seenEventIds.delete(eventId)
  }
}

function shouldSuppressDuplicate(eventId) {
  if (!eventId) return false
  pruneSeenEvents()
  if (seenEventIds.has(eventId)) return true
  seenEventIds.set(eventId, Date.now())
  return false
}

function safeMeta(value) {
  return asString(value).slice(0, 500)
}

function normalizeMonitorType(value) {
  const monitorType = cleanText(value || 'general').toLowerCase()
  if (monitorType === 'general' || monitorType === 'binary') return monitorType
  throw new Error('monitor_type must be "general" or "binary"')
}

function normalizeReadinessPayload(payload) {
  if (typeof payload !== 'object' || !payload) {
    return {
      status: 'unknown',
      ready: false,
      warnings: ['VideoMemory returned a non-object readiness payload.'],
    }
  }
  const warnings = Array.isArray(payload.warnings) ? payload.warnings.map(cleanText).filter(Boolean) : []
  return {
    ...payload,
    status: cleanText(payload.status) || (payload.ready ? 'ready' : 'not_ready'),
    ready: Boolean(payload.ready),
    warnings,
  }
}

function metaFromPayload(payload) {
  return {
    event_type: safeMeta(payload.event_type || 'task_update'),
    event_id: safeMeta(payload.event_id),
    bot_id: safeMeta(payload.bot_id),
    io_id: safeMeta(payload.io_id),
    task_id: safeMeta(payload.task_id),
    task_status: safeMeta(payload.task_status),
    task_done: safeMeta(payload.task_done),
    note_id: safeMeta(payload.note_id),
    task_api_url: safeMeta(payload.task_api_url),
    note_frame_api_url: safeMeta(payload.note_frame_api_url),
    note_video_api_url: safeMeta(payload.note_video_api_url),
  }
}

function buildChannelContent(payload) {
  const taskDescription = cleanText(payload.task_description) || 'VideoMemory task'
  const note = cleanText(payload.note) || 'VideoMemory reported a task update.'
  const action =
    cleanText(payload.action_instruction) ||
    cleanText(payload.requested_action) ||
    'If the observation satisfies the trigger, give a short user-facing confirmation.'
  const lines = [
    'VideoMemory camera monitor event.',
    `Task: ${taskDescription}`,
    `Observation: ${note}`,
    `Requested action: ${action}`,
    `Device io_id: ${asString(payload.io_id) || 'unknown'}`,
    `Task id: ${asString(payload.task_id) || 'unknown'}`,
  ]
  const taskApiUrl = cleanText(payload.task_api_url)
  const frameUrl = cleanText(payload.note_frame_api_url)
  const videoUrl = cleanText(payload.note_video_api_url)
  if (taskApiUrl) lines.push(`Task API URL: ${taskApiUrl}`)
  if (frameUrl) lines.push(`Saved triggering frame URL: ${frameUrl}`)
  if (videoUrl) lines.push(`Saved triggering video URL: ${videoUrl}`)
  lines.push('Do not start a polling loop. If responding through this channel test surface, call mcp__videomemory__reply.')
  return lines.join('\n')
}

async function readRequestBody(req) {
  const chunks = []
  for await (const chunk of req) chunks.push(chunk)
  return Buffer.concat(chunks).toString('utf8')
}

async function readPayload(req) {
  const body = await readRequestBody(req)
  const contentType = req.headers['content-type'] || ''
  if (String(contentType).includes('application/json')) {
    if (!body.trim()) return {}
    const parsed = JSON.parse(body)
    if (typeof parsed === 'object' && parsed && !Array.isArray(parsed)) return parsed
    return { value: parsed }
  }
  return { note: body }
}

async function deliverVideoMemoryEvent(payload) {
  const eventId = cleanText(payload.event_id) || `vm-channel-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  payload.event_id = eventId
  if (shouldSuppressDuplicate(eventId)) {
    return { delivered: false, duplicate: true, eventId }
  }
  const content = buildChannelContent(payload)
  await mcp.notification({
    method: 'notifications/claude/channel',
    params: {
      content,
      meta: metaFromPayload(payload),
    },
  })
  broadcast('inbound', { event_id: eventId, payload, content })
  return { delivered: true, duplicate: false, eventId }
}

async function requestVideoMemory(path, init = {}) {
  const response = await fetch(`${BASE_URL}${path}`, init)
  const text = await response.text()
  let payload = text
  try {
    payload = text ? JSON.parse(text) : {}
  } catch {
    // Keep text payload.
  }
  if (!response.ok) {
    throw new Error(`VideoMemory HTTP ${response.status}: ${typeof payload === 'string' ? payload : JSON.stringify(payload)}`)
  }
  return payload
}

async function maybeRequestVideoMemory(path, init = {}) {
  try {
    return { ok: true, payload: await requestVideoMemory(path, init) }
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) }
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function waitForVideoMemory(timeoutMs = 25000) {
  const startedAt = Date.now()
  let lastError = ''
  while (Date.now() - startedAt < timeoutMs) {
    const health = await maybeRequestVideoMemory('/api/health')
    if (health.ok) return { ok: true, payload: health.payload }
    lastError = health.error
    await sleep(500)
  }
  return { ok: false, error: lastError || `Timed out waiting for ${BASE_URL}/api/health` }
}

function chooseLocalServerCommand() {
  const venvPython = join(REPO_ROOT, '.venv', 'bin', 'python')
  if (existsSync(venvPython)) {
    return { command: venvPython, args: ['flask_app/app.py'], label: '.venv/bin/python flask_app/app.py' }
  }
  return { command: 'uv', args: ['run', 'flask_app/app.py'], label: 'uv run flask_app/app.py' }
}

async function ensureLocalVideoMemoryServer() {
  const health = await maybeRequestVideoMemory('/api/health')
  if (health.ok) {
    return { started: false, ready: true, base_url: BASE_URL, health: health.payload }
  }
  if (!existsSync(join(REPO_ROOT, 'flask_app', 'app.py'))) {
    return {
      started: false,
      ready: false,
      base_url: BASE_URL,
      error: `Cannot start VideoMemory because flask_app/app.py is missing under ${REPO_ROOT}`,
    }
  }
  const server = chooseLocalServerCommand()
  const logPath = join(homedir(), '.videomemory', 'claude', 'videomemory-server.log')
  mkdirSync(dirname(logPath), { recursive: true })
  const child = spawn(server.command, server.args, {
    cwd: REPO_ROOT,
    detached: true,
    stdio: ['ignore', 'ignore', 'ignore'],
    env: process.env,
  })
  child.unref()
  const ready = await waitForVideoMemory()
  return {
    started: true,
    ready: ready.ok,
    base_url: BASE_URL,
    command: server.label,
    pid: child.pid || 0,
    log_path: logPath,
    ...(ready.ok ? { health: ready.payload } : { error: ready.error }),
  }
}

async function configureVideoMemoryWebhook() {
  const webhookUrl = `http://${HOST}:${PORT}/videomemory-event`
  await requestVideoMemory('/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: webhookUrl }),
  })
  await requestVideoMemory('/api/settings/VIDEOMEMORY_SELF_BASE_URL', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: BASE_URL }),
  })
  if (!TOKEN) {
    await requestVideoMemory('/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: '' }),
    })
  }
  return { configured: true, webhook_url: webhookUrl, token_required: Boolean(TOKEN) }
}

async function openBrowserCameraBridge(cameraId = 'facetime') {
  const safeCameraId = cleanText(cameraId) || 'facetime'
  const bridgeUrl = `${BASE_URL}/browser-camera/${encodeURIComponent(safeCameraId)}`
  if (process.platform !== 'darwin') {
    return { opened: false, url: bridgeUrl, reason: 'automatic browser opening is only implemented on macOS' }
  }
  try {
    const child = spawn('open', [bridgeUrl], { detached: true, stdio: 'ignore' })
    child.unref()
    return { opened: true, url: bridgeUrl }
  } catch (error) {
    return { opened: false, url: bridgeUrl, error: error instanceof Error ? error.message : String(error) }
  }
}

async function setupLocalVideoMemory(args = {}) {
  const cameraId = cleanText(args.camera_id) || 'facetime'
  const ioId = cleanText(args.io_id) || `browser_${cameraId}`
  const server = args.start_server === false
    ? { started: false, ready: false, skipped: true, base_url: BASE_URL }
    : await ensureLocalVideoMemoryServer()
  if (!server.ready) {
    return { status: 'not_ready', server, next: server.error || 'Start VideoMemory and retry setup.' }
  }

  const webhook = args.configure_webhook === false
    ? { configured: false, skipped: true }
    : await configureVideoMemoryWebhook()
  const camera = args.open_camera === false
    ? { opened: false, skipped: true, url: `${BASE_URL}/browser-camera/${encodeURIComponent(cameraId)}` }
    : await openBrowserCameraBridge(cameraId)
  const devices = await maybeRequestVideoMemory('/api/devices')
  const readiness = await getDeviceReadiness(ioId)

  return {
    status: readiness.ready ? 'ready' : 'needs_camera',
    server,
    webhook,
    camera,
    devices: devices.ok ? devices.payload : { error: devices.error },
    readiness,
    recommended_io_id: ioId,
    next: readiness.ready
      ? 'Create the requested monitor.'
      : 'Grant camera permission in the opened browser tab and keep it open so VideoMemory receives fresh frames.',
  }
}

async function getDeviceReadiness(ioId) {
  const normalizedIoId = cleanText(ioId) || '0'
  const readiness = await maybeRequestVideoMemory(`/api/device/${encodeURIComponent(normalizedIoId)}/readiness`)
  if (readiness.ok) {
    return normalizeReadinessPayload(readiness.payload)
  }

  const debugStatus = await maybeRequestVideoMemory(
    `/api/device/${encodeURIComponent(normalizedIoId)}/debug/semantic-preview/status`,
  )
  if (!debugStatus.ok) {
    return normalizeReadinessPayload({
      status: 'unknown',
      ready: false,
      io_id: normalizedIoId,
      warnings: [
        `Could not read device readiness: ${readiness.error}`,
        `Could not read debug status: ${debugStatus.error}`,
      ],
    })
  }
  const payload = debugStatus.payload || {}
  return normalizeReadinessPayload({
    status: payload.has_frame ? 'ready' : 'not_ready',
    ready: Boolean(payload.has_frame),
    io_id: normalizedIoId,
    ingestor: {
      exists: Boolean(payload.has_ingestor),
      running: Boolean(payload.running),
      has_frame: Boolean(payload.has_frame),
      frame_age_ms: payload.frame_age_ms ?? null,
    },
    warnings: payload.has_frame ? [] : ['Device has no current frame. Camera permission or stream setup may be required.'],
  })
}

function logReply(entry) {
  mkdirSync(STATE_DIR, { recursive: true })
  writeFileSync(REPLY_LOG, `${JSON.stringify(entry)}\n`, { flag: 'a' })
}

const mcp = new Server(
  { name: 'videomemory', version: '0.1.0' },
  {
    capabilities: {
      experimental: { 'claude/channel': {} },
      tools: {},
    },
    instructions: [
      'VideoMemory events arrive as <channel source="videomemory" ...> messages.',
      'They are camera monitor task updates, not ordinary user prompts.',
      'Use the observation and task fields to decide whether the requested visual trigger happened.',
      'If the event asks for a user-visible alert during testing, call mcp__videomemory__reply with a concise message.',
      'When the user asks to download, install, set up, or use VideoMemory, call mcp__videomemory__setup_local first.',
      'When the user asks to start watching for a visual condition, call mcp__videomemory__create_monitor.',
      'Use monitor_type "binary" for simple local true/false done conditions such as person visible, phone visible, or door open.',
      'After creating a monitor, inspect the returned readiness. If readiness.ready is false, report the blocker instead of saying the monitor is fully armed.',
      'Do not create polling loops after a monitor event.',
    ].join(' '),
  },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'setup_local',
      description: 'Start/check local VideoMemory, wire this Claude channel as its webhook, and open the browser FaceTime camera bridge.',
      inputSchema: {
        type: 'object',
        properties: {
          camera_id: { type: 'string', description: 'Browser camera bridge id. Defaults to facetime.' },
          io_id: { type: 'string', description: 'VideoMemory device id to inspect. Defaults to browser_<camera_id>.' },
          start_server: { type: 'boolean', description: 'Start VideoMemory if not already running. Defaults to true.' },
          configure_webhook: { type: 'boolean', description: 'Point VideoMemory webhooks at this Claude channel. Defaults to true.' },
          open_camera: { type: 'boolean', description: 'Open the browser camera bridge. Defaults to true.' },
        },
      },
    },
    {
      name: 'reply',
      description: 'Emit a user-visible reply on the VideoMemory channel test surface.',
      inputSchema: {
        type: 'object',
        properties: {
          text: { type: 'string', description: 'Reply text.' },
          task_id: { type: 'string', description: 'Optional VideoMemory task id.' },
          event_id: { type: 'string', description: 'Optional VideoMemory event id.' },
        },
        required: ['text'],
      },
    },
    {
      name: 'inspect_task',
      description: 'Fetch the current VideoMemory task payload by task id.',
      inputSchema: {
        type: 'object',
        properties: {
          task_id: { type: 'string' },
        },
        required: ['task_id'],
      },
    },
    {
      name: 'list_devices',
      description: 'List VideoMemory input devices.',
      inputSchema: {
        type: 'object',
        properties: {},
      },
    },
    {
      name: 'list_monitors',
      description: 'List VideoMemory monitor tasks.',
      inputSchema: {
        type: 'object',
        properties: {
          io_id: { type: 'string' },
        },
      },
    },
    {
      name: 'inspect_device',
      description: 'Return machine-readable readiness for a VideoMemory device before or after monitor creation.',
      inputSchema: {
        type: 'object',
        properties: {
          io_id: { type: 'string', description: 'VideoMemory device io_id. Defaults to 0.' },
        },
      },
    },
    {
      name: 'create_monitor',
      description: 'Create a VideoMemory camera monitor task for a visual condition.',
      inputSchema: {
        type: 'object',
        properties: {
          task_description: { type: 'string', description: 'Natural-language visual condition to monitor.' },
          io_id: { type: 'string', description: 'VideoMemory device io_id. Defaults to 0.' },
          monitor_type: {
            type: 'string',
            enum: ['general', 'binary'],
            description: 'general uses the chunked VLM monitor; binary uses the local FastVLM true/false done monitor. Defaults to general.',
          },
          semantic_filter_keywords: { type: 'string', description: 'Optional keywords for semantic frame filtering.' },
          bot_id: { type: 'string', description: 'Optional creator id. Defaults to claude.' },
          save_note_frames: { type: 'boolean', description: 'Save trigger frames. Defaults to true.' },
          save_note_videos: { type: 'boolean', description: 'Save trigger videos. Defaults to true.' },
        },
        required: ['task_description'],
      },
    },
    {
      name: 'configure_channel_webhook',
      description: 'Point VideoMemory task-update webhooks at this Claude channel.',
      inputSchema: {
        type: 'object',
        properties: {
          webhook_url: { type: 'string', description: 'Optional override. Defaults to this channel endpoint.' },
          clear_token: { type: 'boolean', description: 'Clear the saved VideoMemory webhook token. Defaults to true.' },
        },
      },
    },
  ],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
  const args = req.params.arguments || {}
  try {
    switch (req.params.name) {
      case 'reply': {
        const text = cleanText(args.text)
        if (!text) throw new Error('text is required')
        const entry = {
          id: `r${Date.now()}-${++replySeq}`,
          text,
          task_id: asString(args.task_id),
          event_id: asString(args.event_id),
          ts: new Date().toISOString(),
        }
        logReply(entry)
        broadcast('reply', entry)
        return { content: [{ type: 'text', text: `sent ${entry.id}` }] }
      }
      case 'setup_local': {
        const payload = await setupLocalVideoMemory(args)
        return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] }
      }
      case 'inspect_task': {
        const taskId = cleanText(args.task_id)
        if (!taskId) throw new Error('task_id is required')
        const payload = await requestVideoMemory(`/api/task/${encodeURIComponent(taskId)}`)
        return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] }
      }
      case 'list_devices': {
        const payload = await requestVideoMemory('/api/devices')
        return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] }
      }
      case 'list_monitors': {
        const ioId = cleanText(args.io_id)
        const suffix = ioId ? `?io_id=${encodeURIComponent(ioId)}` : ''
        const payload = await requestVideoMemory(`/api/tasks${suffix}`)
        return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] }
      }
      case 'inspect_device': {
        const payload = await getDeviceReadiness(cleanText(args.io_id) || '0')
        return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] }
      }
      case 'create_monitor': {
        const taskDescription = cleanText(args.task_description)
        if (!taskDescription) throw new Error('task_description is required')
        const ioId = cleanText(args.io_id) || '0'
        const monitorType = normalizeMonitorType(args.monitor_type)
        const payload = await requestVideoMemory('/api/tasks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            io_id: ioId,
            task_description: taskDescription,
            monitor_type: monitorType,
            bot_id: cleanText(args.bot_id) || 'claude',
            semantic_filter_keywords: cleanText(args.semantic_filter_keywords),
            save_note_frames: args.save_note_frames !== false,
            save_note_videos: args.save_note_videos !== false,
          }),
        })
        const readiness = await getDeviceReadiness(payload.io_id || ioId)
        const response = {
          ...payload,
          monitor_type: payload.monitor_type || monitorType,
          readiness,
          warning: readiness.ready
            ? ''
            : `Monitor was created, but device is not ready: ${readiness.warnings.join(' ') || readiness.status}`,
        }
        return { content: [{ type: 'text', text: JSON.stringify(response, null, 2) }] }
      }
      case 'configure_channel_webhook': {
        const webhookUrl = cleanText(args.webhook_url) || `http://${HOST}:${PORT}/videomemory-event`
        await requestVideoMemory('/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: webhookUrl }),
        })
        await requestVideoMemory('/api/settings/VIDEOMEMORY_SELF_BASE_URL', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: BASE_URL }),
        })
        if (args.clear_token !== false) {
          await requestVideoMemory('/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: '' }),
          })
        }
        return { content: [{ type: 'text', text: `configured ${webhookUrl}` }] }
      }
      default:
        return { content: [{ type: 'text', text: `unknown tool: ${req.params.name}` }], isError: true }
    }
  } catch (error) {
    return {
      content: [{ type: 'text', text: error instanceof Error ? error.message : String(error) }],
      isError: true,
    }
  }
})

await mcp.connect(new StdioServerTransport())

const httpServer = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${HOST}:${PORT}`)
  if (req.method === 'GET' && url.pathname === '/health') {
    sendJson(res, {
      status: 'ok',
      channel: 'videomemory',
      host: HOST,
      port: PORT,
      videomemory_base_url: BASE_URL,
      token_required: Boolean(TOKEN),
    })
    return
  }
  if (req.method === 'GET' && url.pathname === '/events') {
    res.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
    })
    res.write(': connected\n\n')
    clients.add(res)
    req.on('close', () => clients.delete(res))
    return
  }
  if (req.method === 'POST' && (url.pathname === '/' || url.pathname === '/videomemory-event')) {
    if (requireAuthorized(req, res)) return
    try {
      const payload = await readPayload(req)
      const delivery = await deliverVideoMemoryEvent(payload)
      sendJson(res, { status: 'ok', ...delivery }, delivery.duplicate ? 200 : 202)
    } catch (error) {
      sendJson(res, { status: 'error', error: error instanceof Error ? error.message : String(error) }, 500)
    }
    return
  }
  sendJson(res, { status: 'error', error: 'not found' }, 404)
})

httpServer.listen(PORT, HOST, () => {
  process.stderr.write(`videomemory-channel: http://${HOST}:${PORT}/videomemory-event\n`)
})
