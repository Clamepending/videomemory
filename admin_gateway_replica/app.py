#!/usr/bin/env python3
"""OpenClaw-like webhook gateway replica for local testing.

Purpose:
- Accept webhook stimuli from VideoMemory (`/hooks/<path>`)
- Optionally forward them into VideoMemory's existing Google ADK admin agent via `/chat`
- Expose a small event log for smoke testing and debugging

This is not a secure production gateway. It is a test harness to validate the
VideoMemory -> gateway -> agent wakeup loop without running OpenClaw.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, jsonify, request


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def render_template(template: str, values: Dict[str, Any]) -> str:
    """Very small `{{key}}` replacer used by the gateway test harness."""
    out = template
    for key, value in values.items():
        out = out.replace("{{" + str(key) + "}}", str(value))
    return out


class GatewayState:
    def __init__(self):
        self.lock = threading.Lock()
        self.events: List[Dict[str, Any]] = []
        self.last_forward: Optional[Dict[str, Any]] = None
        self.session_id: Optional[str] = os.getenv("VIDEOMEMORY_AGENT_SESSION_ID", "").strip() or None

    def record_event(self, event: Dict[str, Any]) -> None:
        with self.lock:
            self.events.append(event)
            self.events = self.events[-200:]

    def set_last_forward(self, info: Dict[str, Any]) -> None:
        with self.lock:
            self.last_forward = info

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "events": list(self.events),
                "last_forward": dict(self.last_forward) if self.last_forward else None,
                "session_id": self.session_id,
            }


def create_app() -> Flask:
    app = Flask(__name__)
    state = GatewayState()

    hook_path = os.getenv("GATEWAY_HOOK_PATH", "videomemory-alert").strip("/") or "videomemory-alert"
    token = os.getenv("GATEWAY_TOKEN", "").strip()
    videomemory_base = os.getenv("VIDEOMEMORY_BASE_URL", "http://videomemory:5050").rstrip("/")
    forward_enabled = _env_bool("GATEWAY_FORWARD_TO_VIDEOMEMORY_CHAT", True)
    create_session_on_demand = _env_bool("GATEWAY_CREATE_SESSION_ON_DEMAND", True)
    message_template = os.getenv(
        "GATEWAY_MESSAGE_TEMPLATE",
        "VISION ALERT on device {{io_id}} (task {{task_id}}): {{note}}\nTask: {{task_description}}",
    )

    def _unauthorized():
        return jsonify({"status": "error", "error": "unauthorized"}), 401

    def _authorized() -> bool:
        if not token:
            return True
        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        return auth == expected

    def _ensure_session() -> str:
        if state.session_id:
            return state.session_id
        if not create_session_on_demand:
            raise RuntimeError("No session configured and auto-create disabled")
        resp = requests.post(f"{videomemory_base}/api/sessions/new", timeout=10)
        resp.raise_for_status()
        session_id = (resp.json() or {}).get("session_id")
        if not session_id:
            raise RuntimeError("VideoMemory did not return session_id")
        state.session_id = str(session_id)
        return state.session_id

    def _forward_to_admin_agent(message: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = _ensure_session()
        resp = requests.post(
            f"{videomemory_base}/chat",
            json={"message": message, "session_id": session_id},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json() if resp.text else {}
        result = {
            "ok": True,
            "session_id": session_id,
            "message": message,
            "payload": payload,
            "response": (data or {}).get("response"),
            "forwarded_at": time.time(),
        }
        state.set_last_forward(result)
        return result

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify(
            {
                "status": "ok",
                "service": "admin-gateway-replica",
                "hook_path": f"/hooks/{hook_path}",
                "forward_enabled": forward_enabled,
                "videomemory_base_url": videomemory_base,
                "session_id": state.session_id,
            }
        )

    @app.route("/api/events", methods=["GET"])
    def events():
        snap = state.snapshot()
        return jsonify({"status": "ok", **snap})

    @app.route("/api/session/reset", methods=["POST"])
    def reset_session():
        with state.lock:
            state.session_id = None
        return jsonify({"status": "ok", "session_id": None})

    @app.route("/api/trigger", methods=["POST"])
    def manual_trigger():
        """Manual trigger to simulate a hook payload."""
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()
        if not message:
            payload = data.get("payload") or {}
            if not isinstance(payload, dict):
                return jsonify({"status": "error", "error": "payload must be an object"}), 400
            message = render_template(message_template, payload)
        payload = data.get("payload") or {}
        try:
            if forward_enabled:
                result = _forward_to_admin_agent(message, payload if isinstance(payload, dict) else {})
            else:
                result = {"ok": False, "message": "forwarding disabled"}
            state.record_event(
                {
                    "received_at": time.time(),
                    "path": "/api/trigger",
                    "payload": payload,
                    "rendered_message": message,
                    "forwarded": bool(forward_enabled),
                }
            )
            return jsonify({"status": "ok", "result": result})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 502

    @app.route(f"/hooks/{hook_path}", methods=["POST"])
    def hook():
        if not _authorized():
            return _unauthorized()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "error": "Request body must be JSON object"}), 400
        message = render_template(message_template, payload)
        event_record = {
            "received_at": time.time(),
            "path": request.path,
            "payload": payload,
            "rendered_message": message,
            "forwarded": False,
        }
        try:
            forward_result = None
            if forward_enabled:
                forward_result = _forward_to_admin_agent(message, payload)
                event_record["forwarded"] = True
                event_record["agent_response"] = forward_result.get("response")
            state.record_event(event_record)
            return jsonify(
                {
                    "status": "ok",
                    "forwarded": bool(forward_enabled),
                    "session_id": state.session_id,
                    "message": message,
                    "result": forward_result,
                }
            )
        except Exception as e:
            state.record_event({**event_record, "error": str(e)})
            return jsonify({"status": "error", "error": str(e), "message": message}), 502

    return app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "18789"))
    app.run(host=host, port=port, debug=False, threaded=True)
