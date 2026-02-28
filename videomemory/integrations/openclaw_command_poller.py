"""Edge-initiated OpenClaw command poller for Event Mode deployments."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

logger = logging.getLogger("OpenClawCommandPoller")


class OpenClawCommandPoller:
    """Poll cloud commands and execute them against local VideoMemory APIs."""

    def __init__(
        self,
        *,
        pull_url: Optional[str],
        result_url: Optional[str] = None,
        bearer_token: Optional[str] = None,
        edge_id: Optional[str] = None,
        local_api_base_url: str = "http://127.0.0.1:5050",
        enabled: bool = True,
        timeout_seconds: float = 10.0,
        max_commands: int = 1,
    ):
        self.pull_url = (pull_url or "").strip()
        self.result_url = (result_url or "").strip()
        self.bearer_token = (bearer_token or "").strip()
        self.edge_id = (
            edge_id
            or os.getenv("VIDEOMEMORY_OPENCLAW_EDGE_ID")
            or "edge-default"
        ).strip()
        self.local_api_base_url = local_api_base_url.rstrip("/")
        self.enabled = bool(enabled)
        self.timeout_seconds = float(timeout_seconds)
        self.max_commands = max(1, int(max_commands))

    def _deployment_mode(self) -> str:
        return (os.getenv("VIDEOMEMORY_DEPLOYMENT_MODE") or "streaming").strip().lower()

    def is_enabled(self) -> bool:
        if not self.enabled:
            return False
        if not self.pull_url:
            return False
        return self._deployment_mode() != "streaming"

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    def _map_action(
        self, action: str, args: Dict[str, Any]
    ) -> Tuple[str, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        normalized = action.strip().lower()
        if normalized == "health":
            return "GET", "/api/health", None, None
        if normalized == "list_devices":
            return "GET", "/api/devices", None, None
        if normalized == "list_tasks":
            io_id = (args.get("io_id") or "").strip()
            return "GET", "/api/tasks", None, {"io_id": io_id} if io_id else None
        if normalized == "get_task":
            task_id = str(args.get("task_id") or "").strip()
            if not task_id:
                raise ValueError("task_id is required")
            return "GET", f"/api/task/{task_id}", None, None
        if normalized == "create_task":
            io_id = str(args.get("io_id") or "").strip()
            task_description = str(args.get("task_description") or "").strip()
            if not io_id or not task_description:
                raise ValueError("io_id and task_description are required")
            return "POST", "/api/tasks", {"io_id": io_id, "task_description": task_description}, None
        if normalized in {"edit_task", "update_task"}:
            task_id = str(args.get("task_id") or "").strip()
            new_description = str(args.get("new_description") or "").strip()
            if not task_id or not new_description:
                raise ValueError("task_id and new_description are required")
            return "PUT", f"/api/task/{task_id}", {"new_description": new_description}, None
        if normalized == "stop_task":
            task_id = str(args.get("task_id") or "").strip()
            if not task_id:
                raise ValueError("task_id is required")
            return "POST", f"/api/task/{task_id}/stop", {}, None
        if normalized == "delete_task":
            task_id = str(args.get("task_id") or "").strip()
            if not task_id:
                raise ValueError("task_id is required")
            return "DELETE", f"/api/task/{task_id}", None, None
        if normalized in {"caption_frame", "analyze_feed"}:
            io_id = str(args.get("io_id") or "").strip()
            prompt = str(args.get("prompt") or "").strip()
            if not io_id or not prompt:
                raise ValueError("io_id and prompt are required")
            return "POST", "/api/caption_frame", {"io_id": io_id, "prompt": prompt}, None

        raise ValueError(f"Unsupported action: {action}")

    def _pull_commands(self) -> List[Dict[str, Any]]:
        response = requests.post(
            self.pull_url,
            headers=self._headers(),
            json={"edge_id": self.edge_id, "max_commands": self.max_commands},
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Command pull failed: HTTP {response.status_code} {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        commands = payload.get("commands")
        if isinstance(commands, list):
            return [item for item in commands if isinstance(item, dict)]
        if payload.get("request_id") and payload.get("action"):
            return [payload]
        return []

    def _post_result(self, result_payload: Dict[str, Any]) -> None:
        if not self.result_url:
            return
        response = requests.post(
            self.result_url,
            headers=self._headers(),
            json=result_payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Result callback failed: HTTP {response.status_code} {response.text}"
            )

    def _request_local(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Dict[str, Any]],
        query: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        url = urljoin(f"{self.local_api_base_url}/", path.lstrip("/"))
        response = requests.request(
            method=method,
            url=url,
            json=body,
            params=query,
            timeout=self.timeout_seconds,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text}
        if response.status_code >= 400:
            raise RuntimeError(
                f"Local API failed: {method} {path} -> HTTP {response.status_code}: {payload}"
            )
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def _handle_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        request_id = str(command.get("request_id") or "").strip()
        action = str(command.get("action") or "").strip()
        args = command.get("args")
        if not isinstance(args, dict):
            args = {}

        if not request_id:
            return {
                "edge_id": self.edge_id,
                "request_id": "",
                "status": "error",
                "error": "Missing request_id",
            }

        try:
            method, path, body, query = self._map_action(action, args)
            result = self._request_local(method, path, body=body, query=query)
            return {
                "edge_id": self.edge_id,
                "request_id": request_id,
                "status": "success",
                "result": result,
            }
        except Exception as error:
            logger.warning(
                "Failed command request_id=%s action=%s: %s", request_id, action, error
            )
            return {
                "edge_id": self.edge_id,
                "request_id": request_id,
                "status": "error",
                "error": str(error),
            }

    def poll_once(self) -> int:
        if not self.is_enabled():
            return 0
        commands = self._pull_commands()
        for command in commands:
            result = self._handle_command(command)
            self._post_result(result)
        return len(commands)
