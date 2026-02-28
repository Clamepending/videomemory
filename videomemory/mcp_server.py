"""VideoMemory MCP server (stdio + simple HTTP JSON-RPC transport).

This server wraps the existing Flask API so we can expose VideoMemory as an MCP
tool/resource provider without reworking the application internals.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import requests

LOG_LEVEL = os.getenv("VIDEOMEMORY_MCP_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("videomemory.mcp")


def _shorten(value: Any, max_len: int = 500) -> Any:
    """Return a compact JSON-safe representation for event logging."""
    try:
        if isinstance(value, (str, int, float, bool)) or value is None:
            s = str(value)
            return s if len(s) <= max_len else f"{s[:max_len]}...[truncated]"
        dumped = json.dumps(value, ensure_ascii=True, default=str)
        return dumped if len(dumped) <= max_len else f"{dumped[:max_len]}...[truncated]"
    except Exception:
        s = repr(value)
        return s if len(s) <= max_len else f"{s[:max_len]}...[truncated]"


class McpEventLog:
    """Thread-safe in-memory ring buffer for MCP request/response telemetry."""

    def __init__(self, max_events: int = 500):
        self._events = collections.deque(maxlen=max(10, int(max_events)))
        self._lock = threading.Lock()
        self._seq = 0

    def append(self, event: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, **event}
            self._events.append(entry)
            return entry

    def list(self, limit: int = 200) -> List[Dict[str, Any]]:
        count = max(1, min(int(limit), 1000))
        with self._lock:
            return list(self._events)[-count:]

    def clear(self) -> int:
        with self._lock:
            removed = len(self._events)
            self._events.clear()
            return removed

    def count(self) -> int:
        with self._lock:
            return len(self._events)


class ApiError(Exception):
    """Raised when the VideoMemory HTTP API returns an error."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


@dataclass
class VideoMemoryApiClient:
    base_url: str = "http://127.0.0.1:5050"
    timeout_seconds: float = 10.0

    def __post_init__(self):
        self.base_url = self.base_url.rstrip("/")
        self.session = requests.Session()

    def _request(self, method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.request(
                method=method,
                url=url,
                json=json_body,
                params=params,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as e:
            raise ApiError(f"request failed to {url}: {e}") from e

        text = resp.text or ""
        try:
            data = resp.json() if text else {}
        except ValueError:
            data = {"raw_text": text}

        if resp.status_code >= 400:
            message = None
            if isinstance(data, dict):
                message = data.get("error") or data.get("message")
            raise ApiError(message or f"HTTP {resp.status_code} from {path}", status_code=resp.status_code, payload=data if isinstance(data, dict) else {})
        return data if isinstance(data, dict) else {"data": data}

    # High-level wrappers
    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/api/health")

    def list_devices(self) -> Dict[str, Any]:
        return self._request("GET", "/api/devices")

    def analyze_feed(self, io_id: str, prompt: str) -> Dict[str, Any]:
        # Newer core API uses /api/caption_frame. Keep fallback for older servers.
        try:
            return self._request("POST", "/api/caption_frame", json_body={"io_id": io_id, "prompt": prompt})
        except ApiError as e:
            # Only fall back when the endpoint itself is missing, not when
            # caption_frame returned a real API error (e.g. no frame available).
            endpoint_missing = (
                e.status_code in (404, 405)
                and isinstance(e.payload, dict)
                and bool(e.payload.get("raw_text"))
            )
            if not endpoint_missing:
                raise
            return self._request(
                "POST",
                f"/api/device/{quote(io_id, safe='')}/analyze",
                json_body={"prompt": prompt},
            )

    def create_rtmp_camera(self, device_name: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if device_name:
            body["device_name"] = device_name
        if name:
            body["name"] = name
        return self._request("POST", "/api/devices/network/rtmp", json_body=body)

    def create_srt_camera(self, device_name: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if device_name:
            body["device_name"] = device_name
        if name:
            body["name"] = name
        return self._request("POST", "/api/devices/network/srt", json_body=body)

    def create_whip_camera(self, device_name: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if device_name:
            body["device_name"] = device_name
        if name:
            body["name"] = name
        return self._request("POST", "/api/devices/network/whip", json_body=body)

    def add_network_camera(self, url: str, name: Optional[str] = None) -> Dict[str, Any]:
        body = {"url": url}
        if name:
            body["name"] = name
        return self._request("POST", "/api/devices/network", json_body=body)

    def remove_network_camera(self, io_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/api/devices/network/{quote(io_id, safe='')}")

    def list_tasks(self, io_id: Optional[str] = None) -> Dict[str, Any]:
        params = {"io_id": io_id} if io_id else None
        return self._request("GET", "/api/tasks", params=params)

    def create_task(self, io_id: str, task_description: str) -> Dict[str, Any]:
        return self._request("POST", "/api/tasks", json_body={"io_id": io_id, "task_description": task_description})

    def get_task(self, task_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/task/{quote(task_id, safe='')}")

    def update_task(self, task_id: str, new_description: str) -> Dict[str, Any]:
        return self._request("PUT", f"/api/task/{quote(task_id, safe='')}", json_body={"new_description": new_description})

    def stop_task(self, task_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/api/task/{quote(task_id, safe='')}/stop", json_body={})

    def delete_task(self, task_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/api/task/{quote(task_id, safe='')}")

    def get_settings(self) -> Dict[str, Any]:
        return self._request("GET", "/api/settings")

    def update_setting(self, key: str, value: str) -> Dict[str, Any]:
        return self._request("PUT", f"/api/settings/{quote(key, safe='')}", json_body={"value": value})


class VideoMemoryMcpServer:
    """MCP request handler exposing VideoMemory tools/resources."""

    SERVER_NAME = "videomemory-mcp"
    SERVER_VERSION = "0.1.0"
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, api_client: VideoMemoryApiClient, event_log: Optional[McpEventLog] = None):
        self.api = api_client
        self.event_log = event_log or McpEventLog(
            max_events=int(os.getenv("VIDEOMEMORY_MCP_EVENT_BUFFER_SIZE", "500"))
        )
        self._tools = self._build_tools()

    def _build_tools(self) -> Dict[str, Dict[str, Any]]:
        return {
            "health_check": {
                "description": "Check VideoMemory health and current device/task counts.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "handler": lambda args: self.api.health(),
            },
            "list_devices": {
                "description": "List available local and network camera devices grouped by category.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "handler": lambda args: self.api.list_devices(),
            },
            "analyze_feed": {
                "description": "Run one-off analysis on the latest frame from a device using a custom prompt (no persistent task required).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "io_id": {"type": "string", "description": "Device id to analyze (camera/network device)."},
                        "prompt": {"type": "string", "description": "Natural-language instruction for what to analyze in the frame."},
                    },
                    "required": ["io_id", "prompt"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.analyze_feed(io_id=args["io_id"], prompt=args["prompt"]),
            },
            "create_rtmp_camera": {
                "description": "Create a network camera entry and return an RTMP push URL for Android phones. VideoMemory will pull via RTSP automatically.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_name": {"type": "string", "description": "Safe Android-friendly stream key name (letters/numbers/_/- only)."},
                        "name": {"type": "string", "description": "Display name if device_name is omitted."},
                    },
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.create_rtmp_camera(
                    device_name=(args or {}).get("device_name"),
                    name=(args or {}).get("name"),
                ),
            },
            "add_network_camera": {
                "description": "Register a network camera URL (RTSP/HTTP/RTMP). RTMP URLs are converted to RTSP pull URLs internally.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.add_network_camera(url=args["url"], name=args.get("name")),
            },
            "remove_network_camera": {
                "description": "Remove a registered network camera by io_id. Active tasks on that device are stopped first.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"io_id": {"type": "string"}},
                    "required": ["io_id"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.remove_network_camera(io_id=args["io_id"]),
            },
            "list_tasks": {
                "description": "List all tasks, optionally filtered by device io_id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"io_id": {"type": "string"}},
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.list_tasks(io_id=(args or {}).get("io_id")),
            },
            "create_task": {
                "description": "Create a monitoring task on a device using a natural-language condition description.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "io_id": {"type": "string"},
                        "task_description": {"type": "string"},
                    },
                    "required": ["io_id", "task_description"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.create_task(io_id=args["io_id"], task_description=args["task_description"]),
            },
            "get_task": {
                "description": "Get full task details including note history and current status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.get_task(task_id=args["task_id"]),
            },
            "update_task": {
                "description": "Update a task's natural-language description.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "new_description": {"type": "string"},
                    },
                    "required": ["task_id", "new_description"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.update_task(task_id=args["task_id"], new_description=args["new_description"]),
            },
            "stop_task": {
                "description": "Stop a task but keep its history (status becomes done).",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.stop_task(task_id=args["task_id"]),
            },
            "delete_task": {
                "description": "Permanently delete a task and its notes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.delete_task(task_id=args["task_id"]),
            },
            "get_settings": {
                "description": "List configured settings/API keys (sensitive values are masked).",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "handler": lambda args: self.api.get_settings(),
            },
            "update_setting": {
                "description": "Set or clear a VideoMemory setting. Pass an empty string value to clear.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.update_setting(key=args["key"], value=args["value"]),
            },
        }

    @staticmethod
    def _validate_tool_arguments(schema: Dict[str, Any], arguments: Any) -> Optional[Dict[str, Any]]:
        """Validate basic JSON-schema-like constraints for tool arguments.

        Supports object type, required keys, additionalProperties=false, and
        primitive type checks used by this server's tool schemas.
        Returns an error payload dict when invalid, otherwise None.
        """
        if not isinstance(arguments, dict):
            return {
                "error": "Invalid arguments: expected an object",
                "details": {"received_type": type(arguments).__name__},
            }

        required = schema.get("required", []) or []
        properties = schema.get("properties", {}) or {}
        additional_allowed = schema.get("additionalProperties", True)

        missing = [k for k in required if k not in arguments]
        if missing:
            return {
                "error": "Invalid arguments: missing required field(s)",
                "details": {"missing": missing},
            }

        if additional_allowed is False:
            unexpected = [k for k in arguments.keys() if k not in properties]
            if unexpected:
                return {
                    "error": "Invalid arguments: unexpected field(s)",
                    "details": {"unexpected": unexpected},
                }

        expected_types = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        for key, value in arguments.items():
            prop = properties.get(key)
            if not isinstance(prop, dict):
                continue
            schema_type = prop.get("type")
            if not schema_type:
                continue
            py_type = expected_types.get(schema_type)
            if py_type is None:
                continue
            if not isinstance(value, py_type):
                return {
                    "error": f"Invalid arguments: field '{key}' must be {schema_type}",
                    "details": {
                        "field": key,
                        "expected_type": schema_type,
                        "received_type": type(value).__name__,
                    },
                }

        return None

    def handle_message(self, msg: Dict[str, Any], *, transport: str = "unknown", remote_addr: str = "") -> Optional[Dict[str, Any]]:
        """Handle a JSON-RPC request or notification."""
        started = time.time()
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if not method:
            result = self._error(msg_id, -32600, "Invalid Request: missing method")
            self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
            return result

        try:
            if method == "initialize":
                requested_version = (params or {}).get("protocolVersion")
                result = self._result(
                    msg_id,
                    {
                        "protocolVersion": requested_version or self.PROTOCOL_VERSION,
                        "capabilities": {
                            "tools": {"listChanged": False},
                            "resources": {"subscribe": False, "listChanged": False},
                        },
                        "serverInfo": {
                            "name": self.SERVER_NAME,
                            "version": self.SERVER_VERSION,
                        },
                    },
                )
                self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                return result
            if method == "notifications/initialized":
                self._record_event(msg, None, started, transport=transport, remote_addr=remote_addr)
                return None
            if method == "ping":
                result = self._result(msg_id, {})
                self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                return result
            if method == "tools/list":
                tools = []
                for name, spec in self._tools.items():
                    tools.append(
                        {
                            "name": name,
                            "description": spec["description"],
                            "inputSchema": spec["inputSchema"],
                        }
                    )
                result = self._result(msg_id, {"tools": tools})
                self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                return result
            if method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if name not in self._tools:
                    result = self._result(msg_id, self._tool_error(f"Unknown tool: {name}"))
                    self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                    return result
                schema = self._tools[name]["inputSchema"]
                validation_error = self._validate_tool_arguments(schema, arguments)
                if validation_error is not None:
                    result = self._result(msg_id, self._tool_error(validation_error))
                    self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                    return result
                try:
                    result = self._tools[name]["handler"](arguments)
                    rpc_result = self._result(msg_id, self._tool_ok(result))
                    self._record_event(msg, rpc_result, started, transport=transport, remote_addr=remote_addr)
                    return rpc_result
                except ApiError as e:
                    err = {
                        "error": str(e),
                        "status_code": e.status_code,
                        "payload": e.payload,
                    }
                    rpc_result = self._result(msg_id, self._tool_error(err))
                    self._record_event(msg, rpc_result, started, transport=transport, remote_addr=remote_addr)
                    return rpc_result
            if method == "resources/list":
                resources = self._list_resources()
                result = self._result(msg_id, {"resources": resources})
                self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                return result
            if method == "resources/read":
                uri = params.get("uri", "")
                contents = self._read_resource(uri)
                result = self._result(msg_id, {"contents": contents})
                self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                return result
            if method == "prompts/list":
                result = self._result(msg_id, {"prompts": []})
                self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                return result
            if method == "completion/complete":
                result = self._result(msg_id, {"completion": {"values": []}})
                self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
                return result
            result = self._error(msg_id, -32601, f"Method not found: {method}")
            self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
            return result
        except Exception as e:
            logger.error("Unhandled MCP server error for method=%s: %s\n%s", method, e, traceback.format_exc())
            result = self._error(msg_id, -32603, f"Internal error: {e}")
            self._record_event(msg, result, started, transport=transport, remote_addr=remote_addr)
            return result

    def _record_event(self, request_msg: Dict[str, Any], response_msg: Optional[Dict[str, Any]], started_at: float, transport: str = "unknown", remote_addr: str = "") -> None:
        """Record request/response telemetry for debugging UI."""
        try:
            method = request_msg.get("method")
            params = request_msg.get("params") or {}
            event: Dict[str, Any] = {
                "ts": time.time(),
                "duration_ms": round((time.time() - started_at) * 1000.0, 2),
                "transport": transport,
                "remote_addr": remote_addr or "",
                "request_id": request_msg.get("id"),
                "method": method,
                "params": {},
                "status": "ok",
            }
            if method == "tools/call":
                event["params"] = {
                    "name": _shorten(params.get("name"), 120),
                    "arguments": _shorten(params.get("arguments"), 500),
                }
            else:
                event["params"] = _shorten(params, 500)

            if isinstance(response_msg, dict):
                if "error" in response_msg:
                    event["status"] = "rpc_error"
                    event["error"] = _shorten(response_msg.get("error"), 500)
                else:
                    result = response_msg.get("result")
                    if isinstance(result, dict):
                        event["is_error_result"] = bool(result.get("isError"))
                        if result.get("isError"):
                            event["status"] = "tool_error"
                            event["result_error"] = _shorten(result.get("structuredContent"), 500)
                        else:
                            event["result_summary"] = _shorten(result.get("structuredContent"), 500)
            self.event_log.append(event)
        except Exception:
            logger.debug("Failed to record MCP event", exc_info=True)

    def _list_resources(self) -> List[Dict[str, Any]]:
        resources = [
            {
                "uri": "videomemory://health",
                "name": "Health",
                "description": "VideoMemory service health and counts.",
                "mimeType": "application/json",
            },
            {
                "uri": "videomemory://devices",
                "name": "Devices",
                "description": "Available devices grouped by category.",
                "mimeType": "application/json",
            },
            {
                "uri": "videomemory://tasks",
                "name": "Tasks",
                "description": "All tasks.",
                "mimeType": "application/json",
            },
            {
                "uri": "videomemory://settings",
                "name": "Settings",
                "description": "Masked VideoMemory settings.",
                "mimeType": "application/json",
            },
        ]
        try:
            task_resp = self.api.list_tasks()
            for task in task_resp.get("tasks", []):
                task_id = str(task.get("task_id"))
                resources.append(
                    {
                        "uri": f"videomemory://task/{task_id}",
                        "name": f"Task {task_id}",
                        "description": str(task.get("task_desc") or "")[:120],
                        "mimeType": "application/json",
                    }
                )
        except Exception as e:
            logger.debug("Could not enumerate task resources: %s", e)
        return resources

    def _read_resource(self, uri: str) -> List[Dict[str, Any]]:
        parsed = urlparse(uri)
        if parsed.scheme != "videomemory":
            raise ApiError(f"Unsupported resource URI: {uri}")
        host = parsed.netloc
        path = parsed.path or ""

        if host == "health":
            data = self.api.health()
        elif host == "devices":
            data = self.api.list_devices()
        elif host == "tasks":
            data = self.api.list_tasks()
        elif host == "settings":
            data = self.api.get_settings()
        elif host == "task":
            task_id = path.lstrip("/")
            if not task_id:
                raise ApiError(f"Missing task id in resource URI: {uri}")
            data = self.api.get_task(task_id)
        else:
            raise ApiError(f"Unknown resource URI: {uri}")

        return [
            {
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(data, indent=2, sort_keys=True, default=str),
            }
        ]

    def _tool_ok(self, data: Any) -> Dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(data, indent=2, sort_keys=True, default=str),
                }
            ],
            "structuredContent": data if isinstance(data, dict) else {"result": data},
            "isError": False,
        }

    def _tool_error(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            data = {"error": str(data)}
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(data, indent=2, sort_keys=True, default=str),
                }
            ],
            "structuredContent": data,
            "isError": True,
        }

    @staticmethod
    def _result(msg_id: Any, result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _read_stdio_message() -> Optional[Dict[str, Any]]:
    """Read one message from stdin.

    Supports MCP's Content-Length framing and falls back to newline-delimited
    JSON for simpler local testing.
    """
    first_line = sys.stdin.buffer.readline()
    if not first_line:
        return None
    if not first_line.strip():
        return _read_stdio_message()

    # Newline-delimited JSON fallback.
    if first_line.lstrip().startswith(b"{"):
        return json.loads(first_line.decode("utf-8"))

    headers: Dict[str, str] = {}
    line = first_line
    while line and line.strip():
        if b":" in line:
            key, value = line.split(b":", 1)
            headers[key.decode("ascii", errors="ignore").strip().lower()] = value.decode("ascii", errors="ignore").strip()
        line = sys.stdin.buffer.readline()

    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        raise ValueError("Invalid Content-Length header")
    if length <= 0:
        raise ValueError("Missing Content-Length header")
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_stdio_message(msg: Dict[str, Any]) -> None:
    body = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header)
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def run_stdio(server: VideoMemoryMcpServer) -> int:
    logger.info("Starting VideoMemory MCP server on stdio (API base: %s)", server.api.base_url)
    while True:
        try:
            msg = _read_stdio_message()
            if msg is None:
                return 0
            response = server.handle_message(msg, transport="stdio")
            if response is not None and msg.get("id") is not None:
                _write_stdio_message(response)
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            logger.error("stdio loop error: %s\n%s", e, traceback.format_exc())
            # If we can't decode request id, emit a generic JSON-RPC parse error.
            try:
                _write_stdio_message({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}})
            except Exception:
                return 1


class _HttpHandler(BaseHTTPRequestHandler):
    server_version = "VideoMemoryMCP/0.1"

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @property
    def mcp(self) -> VideoMemoryMcpServer:
        return self.server.mcp_server  # type: ignore[attr-defined]

    def do_GET(self):  # noqa: N802
        if self.path in ("/healthz", "/"):
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "videomemory-mcp",
                    "api_base_url": self.mcp.api.base_url,
                    "events_count": self.mcp.event_log.count(),
                    "hint": "POST JSON-RPC requests to /mcp",
                },
            )
            return
        if self.path.startswith("/events"):
            try:
                parsed = urlparse(self.path)
                qs = parsed.query or ""
                limit = 200
                if "limit=" in qs:
                    for pair in qs.split("&"):
                        if pair.startswith("limit="):
                            limit = int(pair.split("=", 1)[1] or "200")
                            break
                events = self.mcp.event_log.list(limit=limit)
                self._send_json(200, {"status": "ok", "count": len(events), "events": events})
            except Exception as e:
                self._send_json(500, {"status": "error", "error": str(e)})
            return
        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):  # noqa: N802
        if self.path != "/events":
            self._send_json(404, {"error": "not found"})
            return
        removed = self.mcp.event_log.clear()
        self._send_json(200, {"status": "ok", "cleared": removed})

    def do_POST(self):  # noqa: N802
        if self.path != "/mcp":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "invalid content-length"})
            return
        body = self.rfile.read(length) if length else b""
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"invalid json: {e}"})
            return

        response = self.mcp.handle_message(
            msg,
            transport="http",
            remote_addr=self.client_address[0] if self.client_address else "",
        )
        if response is None or msg.get("id") is None:
            self.send_response(204)
            self.end_headers()
            return
        self._send_json(200, response)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("http %s - %s", self.address_string(), fmt % args)


def run_http(server: VideoMemoryMcpServer, host: str, port: int) -> int:
    httpd = ThreadingHTTPServer((host, port), _HttpHandler)
    httpd.mcp_server = server  # type: ignore[attr-defined]
    logger.info("Starting VideoMemory MCP HTTP server on %s:%s (API base: %s)", host, port, server.api.base_url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VideoMemory MCP server")
    p.add_argument("--api-base-url", default=os.getenv("VIDEOMEMORY_API_BASE_URL", "http://127.0.0.1:5050"))
    p.add_argument("--api-timeout", type=float, default=float(os.getenv("VIDEOMEMORY_MCP_API_TIMEOUT_S", "10")))
    p.add_argument("--transport", choices=["stdio", "http"], default=os.getenv("VIDEOMEMORY_MCP_TRANSPORT", "stdio"))
    p.add_argument("--host", default=os.getenv("VIDEOMEMORY_MCP_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("VIDEOMEMORY_MCP_PORT", "8765")))
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    api = VideoMemoryApiClient(base_url=args.api_base_url, timeout_seconds=args.api_timeout)
    server = VideoMemoryMcpServer(api)
    if args.transport == "http":
        return run_http(server, args.host, args.port)
    return run_stdio(server)


if __name__ == "__main__":
    raise SystemExit(main())
