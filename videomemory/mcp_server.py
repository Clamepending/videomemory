"""VideoMemory MCP server (stdio + simple HTTP JSON-RPC transport).

This server wraps the existing Flask API so we can expose VideoMemory as an MCP
tool/resource provider without reworking the application internals.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import requests

LOG_LEVEL = os.getenv("VIDEOMEMORY_MCP_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("videomemory.mcp")


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

    def send_telegram(self, message: str) -> Dict[str, Any]:
        return self._request("POST", "/api/actions/telegram", json_body={"message": message})

    def send_discord(self, message: str, username: Optional[str] = None) -> Dict[str, Any]:
        body = {"message": message}
        if username:
            body["username"] = username
        return self._request("POST", "/api/actions/discord", json_body=body)


class VideoMemoryMcpServer:
    """MCP request handler exposing VideoMemory tools/resources."""

    SERVER_NAME = "videomemory-mcp"
    SERVER_VERSION = "0.1.0"
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, api_client: VideoMemoryApiClient):
        self.api = api_client
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
            "create_srt_camera": {
                "description": "Create a network camera entry and return an SRT publish URL (lower latency and more resilient than RTMP). VideoMemory pulls via RTSP automatically.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_name": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.create_srt_camera(
                    device_name=(args or {}).get("device_name"),
                    name=(args or {}).get("name"),
                ),
            },
            "create_whip_camera": {
                "description": "Create a network camera entry and return a WebRTC/WHIP ingest URL for very low-latency phone/web publishers. VideoMemory pulls via RTSP automatically.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "device_name": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.create_whip_camera(
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
            "send_telegram_notification": {
                "description": "Send a Telegram notification using VideoMemory's configured bot.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.send_telegram(message=args["message"]),
            },
            "send_discord_notification": {
                "description": "Send a Discord notification using VideoMemory's configured webhook.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "username": {"type": "string"},
                    },
                    "required": ["message"],
                    "additionalProperties": False,
                },
                "handler": lambda args: self.api.send_discord(message=args["message"], username=args.get("username")),
            },
        }

    def handle_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle a JSON-RPC request or notification."""
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if not method:
            return self._error(msg_id, -32600, "Invalid Request: missing method")

        try:
            if method == "initialize":
                requested_version = (params or {}).get("protocolVersion")
                return self._result(
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
            if method == "notifications/initialized":
                return None
            if method == "ping":
                return self._result(msg_id, {})
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
                return self._result(msg_id, {"tools": tools})
            if method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if name not in self._tools:
                    return self._result(msg_id, self._tool_error(f"Unknown tool: {name}"))
                try:
                    result = self._tools[name]["handler"](arguments)
                    return self._result(msg_id, self._tool_ok(result))
                except ApiError as e:
                    err = {
                        "error": str(e),
                        "status_code": e.status_code,
                        "payload": e.payload,
                    }
                    return self._result(msg_id, self._tool_error(err))
            if method == "resources/list":
                resources = self._list_resources()
                return self._result(msg_id, {"resources": resources})
            if method == "resources/read":
                uri = params.get("uri", "")
                contents = self._read_resource(uri)
                return self._result(msg_id, {"contents": contents})
            if method == "prompts/list":
                return self._result(msg_id, {"prompts": []})
            if method == "completion/complete":
                return self._result(msg_id, {"completion": {"values": []}})
            return self._error(msg_id, -32601, f"Method not found: {method}")
        except Exception as e:
            logger.error("Unhandled MCP server error for method=%s: %s\n%s", method, e, traceback.format_exc())
            return self._error(msg_id, -32603, f"Internal error: {e}")

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
            response = server.handle_message(msg)
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
                    "hint": "POST JSON-RPC requests to /mcp",
                },
            )
            return
        self._send_json(404, {"error": "not found"})

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

        response = self.mcp.handle_message(msg)
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
