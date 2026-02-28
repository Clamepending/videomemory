"""Cloud VideoMemory Server for Event Mode (control plane + MCP HTTP).

This service does not ingest video. It receives edge triggers, stores a command
queue per edge, and exposes an MCP-compatible HTTP endpoint so OpenClaw (or any
MCP client) can enqueue commands and inspect recent state.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional

from flask import Flask, jsonify, request, redirect
import html

logging.basicConfig(level=os.getenv("VIDEOMEMORY_CLOUD_LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("CloudVideoMemoryServer")


class EventControlStore:
    def __init__(self, max_recent: int = 500):
        self.max_recent = max_recent
        self._lock = threading.Lock()
        self._pending_commands: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        self._recent_triggers: Deque[Dict[str, Any]] = deque(maxlen=max_recent)
        self._recent_results: Deque[Dict[str, Any]] = deque(maxlen=max_recent)
        self._edge_seen: Dict[str, float] = {}

    def record_trigger(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        edge_id = str(payload.get("edge_id") or "unknown-edge")
        now = time.time()
        item = dict(payload)
        item.setdefault("received_at", now)
        with self._lock:
            self._edge_seen[edge_id] = now
            self._recent_triggers.append(item)
        return item

    def enqueue_command(self, edge_id: str, command: Dict[str, Any]) -> Dict[str, Any]:
        edge_id = str(edge_id or "").strip() or "unknown-edge"
        now = time.time()
        cmd = dict(command)
        cmd.setdefault("request_id", uuid.uuid4().hex)
        cmd.setdefault("enqueued_at", now)
        with self._lock:
            self._edge_seen[edge_id] = now
            self._pending_commands[edge_id].append(cmd)
        return cmd

    def pull_commands(self, edge_id: str, max_commands: int = 1) -> List[Dict[str, Any]]:
        edge_id = str(edge_id or "").strip() or "unknown-edge"
        count = max(1, int(max_commands or 1))
        out: List[Dict[str, Any]] = []
        now = time.time()
        with self._lock:
            self._edge_seen[edge_id] = now
            q = self._pending_commands[edge_id]
            while q and len(out) < count:
                out.append(q.popleft())
        return out

    def record_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        edge_id = str(payload.get("edge_id") or "unknown-edge")
        now = time.time()
        item = dict(payload)
        item.setdefault("received_at", now)
        with self._lock:
            self._edge_seen[edge_id] = now
            self._recent_results.append(item)
        return item

    def list_edges(self) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            items = []
            for edge_id, last_seen in self._edge_seen.items():
                pending = len(self._pending_commands.get(edge_id, []))
                items.append(
                    {
                        "edge_id": edge_id,
                        "last_seen_at": last_seen,
                        "last_seen_age_s": round(max(0.0, now - last_seen), 3),
                        "pending_commands": pending,
                    }
                )
        items.sort(key=lambda x: x["last_seen_at"], reverse=True)
        return items

    def list_recent_triggers(self, edge_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._recent_triggers)
        if edge_id:
            items = [x for x in items if str(x.get("edge_id")) == str(edge_id)]
        return list(reversed(items[-max(1, limit):]))

    def list_recent_results(self, edge_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._recent_results)
        if edge_id:
            items = [x for x in items if str(x.get("edge_id")) == str(edge_id)]
        return list(reversed(items[-max(1, limit):]))

    def list_pending_commands(self, edge_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows: List[Dict[str, Any]] = []
            if edge_id:
                for cmd in list(self._pending_commands.get(str(edge_id), []))[: max(1, limit)]:
                    rows.append({"edge_id": str(edge_id), "command": cmd})
            else:
                for eid, q in self._pending_commands.items():
                    for cmd in list(q):
                        rows.append({"edge_id": eid, "command": cmd})
                        if len(rows) >= max(1, limit):
                            return rows
        return rows


class CloudVideoMemoryMcpServer:
    SERVER_NAME = "videomemory-cloud-mcp"
    SERVER_VERSION = "0.1"

    def __init__(self, store: EventControlStore):
        self.store = store

    def tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "list_edges",
                "description": "List edge videomemory servers seen by the cloud queue and their pending command counts.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "enqueue_edge_command",
                "description": "Queue a command for an edge videomemory server. The edge will fetch it on the next poll.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "edge_id": {"type": "string"},
                        "action": {"type": "string"},
                        "args": {"type": "object"},
                    },
                    "required": ["edge_id", "action"],
                },
            },
            {
                "name": "list_recent_triggers",
                "description": "List recent triggers emitted by edge videomemory servers.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"edge_id": {"type": "string"}, "limit": {"type": "integer"}},
                },
            },
            {
                "name": "list_recent_results",
                "description": "List recent command execution results posted by edge videomemory servers.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"edge_id": {"type": "string"}, "limit": {"type": "integer"}},
                },
            },
            {
                "name": "list_pending_edge_commands",
                "description": "Inspect pending queued commands that have not yet been fetched by edges.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"edge_id": {"type": "string"}, "limit": {"type": "integer"}},
                },
            },
        ]

    def handle(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            return self._ok(
                msg_id,
                {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "serverInfo": {"name": self.SERVER_NAME, "version": self.SERVER_VERSION},
                    "capabilities": {"tools": {}, "resources": {}},
                },
            )
        if method == "tools/list":
            return self._ok(msg_id, {"tools": self.tools()})
        if method == "tools/call":
            return self._tool_call(msg_id, params)
        if method == "resources/list":
            return self._ok(msg_id, {"resources": []})
        return self._err(msg_id, -32601, f"Method not found: {method}")

    def _tool_call(self, msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        try:
            if name == "list_edges":
                content = {"edges": self.store.list_edges()}
            elif name == "enqueue_edge_command":
                edge_id = str(args.get("edge_id") or "").strip()
                action = str(args.get("action") or "").strip()
                if not edge_id or not action:
                    raise ValueError("edge_id and action are required")
                command = {"action": action, "args": args.get("args") or {}}
                if "request_id" in args:
                    command["request_id"] = args["request_id"]
                if "reply_url" in args:
                    command["reply_url"] = args["reply_url"]
                queued = self.store.enqueue_command(edge_id, command)
                content = {"status": "queued", "edge_id": edge_id, "command": queued}
            elif name == "list_recent_triggers":
                content = {
                    "triggers": self.store.list_recent_triggers(
                        edge_id=args.get("edge_id"),
                        limit=int(args.get("limit", 20) or 20),
                    )
                }
            elif name == "list_recent_results":
                content = {
                    "results": self.store.list_recent_results(
                        edge_id=args.get("edge_id"),
                        limit=int(args.get("limit", 20) or 20),
                    )
                }
            elif name == "list_pending_edge_commands":
                content = {
                    "pending": self.store.list_pending_commands(
                        edge_id=args.get("edge_id"),
                        limit=int(args.get("limit", 20) or 20),
                    )
                }
            else:
                raise ValueError(f"Unknown tool: {name}")
            return self._ok(
                msg_id,
                {
                    "content": [{"type": "text", "text": json.dumps(content, indent=2)}],
                    "structuredContent": content,
                    "isError": False,
                },
            )
        except Exception as e:
            content = {"error": str(e)}
            return self._ok(
                msg_id,
                {
                    "content": [{"type": "text", "text": json.dumps(content)}],
                    "structuredContent": content,
                    "isError": True,
                },
            )

    @staticmethod
    def _ok(msg_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _err(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def create_app() -> Flask:
    app = Flask(__name__)
    store = EventControlStore(max_recent=int(os.getenv("VIDEOMEMORY_CLOUD_MAX_RECENT", "500")))
    mcp = CloudVideoMemoryMcpServer(store)
    token = str(os.getenv("VIDEOMEMORY_CLOUD_TOKEN", "")).strip()

    def _auth_ok() -> bool:
        if not token:
            return True
        auth = request.headers.get("Authorization", "")
        return auth == f"Bearer {token}"

    def _require_auth():
        if not _auth_ok():
            return jsonify({"status": "error", "error": "Unauthorized"}), 401
        return None

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify(
            {
                "status": "ok",
                "service": "cloud-videomemory-server",
                "mode": "event-control",
                "edges": store.list_edges(),
            }
        )

    @app.route("/", methods=["GET"])
    def dashboard():
        edges = store.list_edges()
        triggers = store.list_recent_triggers(limit=20)
        results = store.list_recent_results(limit=20)
        pending = store.list_pending_commands(limit=20)
        status_note = request.args.get("status", "")

        def _rows(items: List[Dict[str, Any]], renderer):
            if not items:
                return "<tr><td colspan='4' style='opacity:.7'>No data yet</td></tr>"
            return "".join(renderer(x) for x in items)

        html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="5">
  <title>Cloud VideoMemory Server (Event Mode)</title>
  <style>
    :root {{
      --bg: #0d141b;
      --panel: #13202a;
      --panel2: #172733;
      --text: #e6f0f4;
      --muted: #9cb2bf;
      --accent: #65d4a3;
      --warn: #ffd166;
      --line: #28404f;
    }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, sans-serif; background:var(--bg); color:var(--text); }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 18px; }}
    .top {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }}
    .badge {{ background:#103b31; color:var(--accent); border:1px solid #245847; padding:4px 10px; border-radius:999px; font-weight:700; font-size:12px; }}
    .sub {{ color:var(--muted); font-size: 13px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:14px; margin-top:14px; }}
    .card {{ background:linear-gradient(180deg, var(--panel), var(--panel2)); border:1px solid var(--line); border-radius:14px; padding:12px; }}
    h2 {{ margin:0 0 8px; font-size:15px; }}
    table {{ width:100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ border-top:1px solid var(--line); padding:6px 4px; text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-weight:600; }}
    code {{ color:#b8e3ff; white-space: pre-wrap; word-break: break-word; }}
    input, textarea, button {{ width:100%; box-sizing:border-box; border-radius:10px; border:1px solid var(--line); background:#0f1a22; color:var(--text); padding:10px; }}
    textarea {{ min-height:80px; resize:vertical; }}
    button {{ background:#173041; cursor:pointer; font-weight:600; }}
    .row {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px; }}
    .row3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-bottom:8px; }}
    .ok {{ color: var(--accent); }}
    .note {{ color: var(--warn); font-size: 12px; }}
    .inline {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .mini {{ width:auto; padding:6px 10px; font-size:12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1 style="margin:0;font-size:22px;">Cloud VideoMemory Server</h1>
        <div class="sub">Minimal queue/control-plane UI for <b>Event Mode</b>. Auto-refreshes every 5s.</div>
      </div>
      <div class="badge">UI Mode: Event</div>
    </div>
    {f'<div class="note" style="margin-top:8px;">{html.escape(status_note)}</div>' if status_note else ''}

    <div class="grid">
      <div class="card">
        <h2>Queue Command (Manual Demo)</h2>
        <form method="post" action="/ui/enqueue">
          <div class="row">
            <input name="edge_id" placeholder="edge_id (e.g. phone-pixel-abc123)" required />
            <input name="action" placeholder="action (e.g. list_devices)" required />
          </div>
          <textarea name="args_json" placeholder='args JSON (optional), e.g. {{ "io_id": "0" }}'></textarea>
          <button type="submit">Queue Command</button>
        </form>
        <div class="note" style="margin-top:8px;">OpenClaw can use MCP at <code>/mcp</code> instead of this form. Mobile edge-server demo actions: <code>ping</code>, <code>show_toast</code>, <code>emit_test_event</code>, <code>list_devices</code>, <code>list_tasks</code>, <code>create_task</code>, <code>update_task</code>, <code>stop_task</code>, <code>delete_task</code>.</div>
      </div>
      <div class="card">
        <h2>Edges</h2>
        <table>
          <tr><th>edge_id</th><th>last seen (s)</th><th>pending</th><th>quick actions</th></tr>
          {_rows(edges, lambda e: f"<tr><td><code>{html.escape(str(e.get('edge_id')))}</code></td><td>{e.get('last_seen_age_s')}</td><td>{e.get('pending_commands')}</td><td><div class='inline'><form method='post' action='/ui/quick-command'><input type='hidden' name='edge_id' value='{html.escape(str(e.get('edge_id')))}'/><input type='hidden' name='action' value='ping'/><button class='mini' type='submit'>Ping</button></form><form method='post' action='/ui/quick-command'><input type='hidden' name='edge_id' value='{html.escape(str(e.get('edge_id')))}'/><input type='hidden' name='action' value='emit_test_event'/><button class='mini' type='submit'>Emit Test Event</button></form><form method='post' action='/ui/quick-command'><input type='hidden' name='edge_id' value='{html.escape(str(e.get('edge_id')))}'/><input type='hidden' name='action' value='show_toast'/><input type='hidden' name='args_json' value='{{&quot;message&quot;:&quot;Hello from cloud&quot;}}'/><button class='mini' type='submit'>Toast</button></form><form method='post' action='/ui/quick-command'><input type='hidden' name='edge_id' value='{html.escape(str(e.get('edge_id')))}'/><input type='hidden' name='action' value='list_tasks'/><button class='mini' type='submit'>List Tasks</button></form><form method='post' action='/ui/quick-command'><input type='hidden' name='edge_id' value='{html.escape(str(e.get('edge_id')))}'/><input type='hidden' name='action' value='create_task'/><input type='hidden' name='args_json' value='{{&quot;io_id&quot;:&quot;phone-camera-0&quot;,&quot;task_description&quot;:&quot;Watch front door for deliveries&quot;}}'/><button class='mini' type='submit'>Create Task</button></form></div></td></tr>")}
        </table>
      </div>
      <div class="card">
        <h2>Recent Triggers (Edge -> Cloud)</h2>
        <table>
          <tr><th>edge_id</th><th>event</th><th>note</th></tr>
          {_rows(triggers, lambda t: f"<tr><td><code>{html.escape(str(t.get('edge_id')))}</code></td><td>{html.escape(str(t.get('event_type')))}</td><td><code>{html.escape(str(t.get('note', ''))[:220])}</code></td></tr>")}
        </table>
      </div>
      <div class="card">
        <h2>Pending Commands</h2>
        <table>
          <tr><th>edge_id</th><th>command</th></tr>
          {_rows(pending, lambda p: f"<tr><td><code>{html.escape(str(p.get('edge_id')))}</code></td><td><code>{html.escape(json.dumps(p.get('command', {})))}</code></td></tr>")}
        </table>
      </div>
      <div class="card" style="grid-column: 1 / -1;">
        <h2>Recent Results (Edge -> Cloud)</h2>
        <table>
          <tr><th>edge_id</th><th>request_id</th><th>status</th><th>result/error</th></tr>
          {_rows(results, lambda r: f"<tr><td><code>{html.escape(str(r.get('edge_id')))}</code></td><td><code>{html.escape(str(r.get('request_id')))}</code></td><td class='ok'>{html.escape(str(r.get('status')))}</td><td><code>{html.escape(json.dumps(r.get('result') if 'result' in r else r.get('error', '')))}</code></td></tr>")}
        </table>
      </div>
    </div>
  </div>
</body>
</html>"""
        return html_doc

    @app.route("/ui/enqueue", methods=["POST"])
    def ui_enqueue():
        edge_id = (request.form.get("edge_id") or "").strip()
        action = (request.form.get("action") or "").strip()
        args_text = (request.form.get("args_json") or "").strip()
        if not edge_id or not action:
            return redirect("/?status=Missing+edge_id+or+action")
        args: Dict[str, Any] = {}
        if args_text:
            try:
                parsed = json.loads(args_text)
                if isinstance(parsed, dict):
                    args = parsed
                else:
                    return redirect("/?status=args_json+must+be+a+JSON+object")
            except Exception as e:
                return redirect(f"/?status=Invalid+args_json:+{html.escape(str(e))}")
        store.enqueue_command(edge_id=edge_id, command={"action": action, "args": args})
        return redirect(f"/?status=Queued+{html.escape(action)}+for+{html.escape(edge_id)}")

    @app.route("/ui/quick-command", methods=["POST"])
    def ui_quick_command():
        edge_id = (request.form.get("edge_id") or "").strip()
        action = (request.form.get("action") or "").strip()
        args_text = (request.form.get("args_json") or "").strip()
        if not edge_id or not action:
            return redirect("/?status=Missing+edge_id+or+action")
        args: Dict[str, Any] = {}
        if args_text:
            try:
                parsed = json.loads(args_text)
                if isinstance(parsed, dict):
                    args = parsed
            except Exception:
                pass
        store.enqueue_command(edge_id=edge_id, command={"action": action, "args": args})
        return redirect(f"/?status=Queued+{html.escape(action)}+for+{html.escape(edge_id)}")

    @app.route("/api/event/triggers", methods=["POST"])
    def ingest_trigger():
        auth_resp = _require_auth()
        if auth_resp:
            return auth_resp
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "error": "JSON object required"}), 400
        item = store.record_trigger(payload)
        logger.info("Trigger received edge_id=%s event_type=%s", item.get("edge_id"), item.get("event_type"))
        return jsonify({"status": "ok", "received": item.get("received_at")})

    @app.route("/api/event/commands", methods=["POST"])
    def enqueue_command_http():
        auth_resp = _require_auth()
        if auth_resp:
            return auth_resp
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "error": "JSON object required"}), 400
        edge_id = str(payload.get("edge_id") or "").strip()
        action = str(payload.get("action") or "").strip()
        if not edge_id or not action:
            return jsonify({"status": "error", "error": "edge_id and action are required"}), 400
        command = {"action": action, "args": payload.get("args") or {}}
        if "request_id" in payload:
            command["request_id"] = payload["request_id"]
        if "reply_url" in payload:
            command["reply_url"] = payload["reply_url"]
        queued = store.enqueue_command(edge_id=edge_id, command=command)
        return jsonify({"status": "queued", "edge_id": edge_id, "command": queued}), 201

    @app.route("/api/event/commands/pull", methods=["POST"])
    def pull_commands():
        auth_resp = _require_auth()
        if auth_resp:
            return auth_resp
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "error": "JSON object required"}), 400
        edge_id = str(payload.get("edge_id") or "").strip()
        if not edge_id:
            return jsonify({"status": "error", "error": "edge_id is required"}), 400
        max_commands = int(payload.get("max_commands", 1) or 1)
        commands = store.pull_commands(edge_id=edge_id, max_commands=max_commands)
        if not commands:
            return ("", 204)
        return jsonify({"commands": commands, "edge_id": edge_id})

    @app.route("/api/event/commands/result", methods=["POST"])
    def command_result():
        auth_resp = _require_auth()
        if auth_resp:
            return auth_resp
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "error": "JSON object required"}), 400
        item = store.record_result(payload)
        return jsonify({"status": "ok", "received": item.get("received_at")})

    @app.route("/api/event/edges", methods=["GET"])
    def list_edges_http():
        auth_resp = _require_auth()
        if auth_resp:
            return auth_resp
        return jsonify({"edges": store.list_edges()})

    @app.route("/api/event/triggers", methods=["GET"])
    def list_triggers_http():
        auth_resp = _require_auth()
        if auth_resp:
            return auth_resp
        edge_id = request.args.get("edge_id") or None
        limit = int(request.args.get("limit", "20") or 20)
        return jsonify({"triggers": store.list_recent_triggers(edge_id=edge_id, limit=limit)})

    @app.route("/api/event/results", methods=["GET"])
    def list_results_http():
        auth_resp = _require_auth()
        if auth_resp:
            return auth_resp
        edge_id = request.args.get("edge_id") or None
        limit = int(request.args.get("limit", "20") or 20)
        return jsonify({"results": store.list_recent_results(edge_id=edge_id, limit=limit)})

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify({"status": "ok", "service": "videomemory-cloud-mcp"})

    @app.route("/mcp", methods=["POST"])
    def mcp_http():
        auth_resp = _require_auth()
        if auth_resp:
            return auth_resp
        msg = request.get_json(silent=True) or {}
        if not isinstance(msg, dict):
            return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON"}}), 400
        return jsonify(mcp.handle(msg))

    return app


def main() -> int:
    app = create_app()
    host = os.getenv("VIDEOMEMORY_CLOUD_HOST", "0.0.0.0")
    port = int(os.getenv("VIDEOMEMORY_CLOUD_PORT", "8785"))
    logger.info("Starting Cloud VideoMemory Server on http://%s:%s", host, port)
    app.run(host=host, port=port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
