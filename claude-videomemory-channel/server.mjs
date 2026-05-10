#!/usr/bin/env node

import http from 'node:http'
import { mkdirSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
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
      'Do not create polling loops after a monitor event.',
    ].join(' '),
  },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
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
