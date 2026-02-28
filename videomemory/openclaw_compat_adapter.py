"""OpenClaw compatibility adapter for VideoMemory webhook events.

Purpose:
- Provide a stable ingest endpoint for VideoMemory (`/videomemory-alert`)
- Forward to one or more OpenClaw targets (which may drift across releases)
- Keep VideoMemory unchanged while OpenClaw integration details evolve
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from typing import Any, Deque, Dict, List, Tuple

import requests
from flask import Flask, jsonify, request

logging.basicConfig(level=os.getenv("VIDEOMEMORY_OPENCLAW_ADAPTER_LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("OpenClawCompatAdapter")


def _parse_targets() -> List[str]:
    raw = os.getenv(
        "OPENCLAW_COMPAT_TARGETS",
        "http://openclaw:18789/hooks/videomemory-alert,http://openclaw:18789/webhooks/videomemory-alert",
    )
    return [x.strip() for x in raw.split(",") if x.strip()]


class CompatForwarder:
    def __init__(self):
        self.targets = _parse_targets()
        self.timeout_s = float(os.getenv("OPENCLAW_COMPAT_TIMEOUT_S", "3"))
        self.target_token = str(os.getenv("OPENCLAW_COMPAT_TARGET_TOKEN", "")).strip()
        self.max_recent = int(os.getenv("OPENCLAW_COMPAT_MAX_RECENT", "500"))
        self.recent: Deque[Dict[str, Any]] = deque(maxlen=max(50, self.max_recent))

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.target_token:
            h["Authorization"] = f"Bearer {self.target_token}"
        return h

    def forward(self, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        attempts: List[Dict[str, Any]] = []
        for target in self.targets:
            started = time.time()
            try:
                resp = requests.post(target, json=payload, headers=self._headers(), timeout=self.timeout_s)
                elapsed_ms = int((time.time() - started) * 1000)
                attempts.append(
                    {
                        "target": target,
                        "status_code": int(resp.status_code),
                        "elapsed_ms": elapsed_ms,
                        "ok": resp.status_code < 400,
                        "body_excerpt": (resp.text or "")[:200],
                    }
                )
                if resp.status_code < 400:
                    outcome = {"forwarded": True, "target": target, "attempts": attempts}
                    self._record(payload, outcome)
                    return True, outcome
            except Exception as e:
                attempts.append({"target": target, "ok": False, "error": str(e)})

        outcome = {"forwarded": False, "attempts": attempts}
        self._record(payload, outcome)
        return False, outcome

    def _record(self, payload: Dict[str, Any], outcome: Dict[str, Any]) -> None:
        self.recent.appendleft(
            {
                "received_at": time.time(),
                "edge_id": payload.get("edge_id"),
                "event_type": payload.get("event_type"),
                "task_id": payload.get("task_id"),
                "note": str(payload.get("note", ""))[:180],
                "outcome": outcome,
            }
        )

    def snapshot(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.recent)[: max(1, int(limit))]


def create_app() -> Flask:
    app = Flask(__name__)
    forwarder = CompatForwarder()

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify(
            {
                "status": "ok",
                "service": "openclaw-compat-adapter",
                "targets": forwarder.targets,
                "recent_count": len(forwarder.recent),
            }
        )

    @app.route("/recent", methods=["GET"])
    def recent():
        limit = int(request.args.get("limit", "50") or 50)
        return jsonify({"items": forwarder.snapshot(limit=limit)})

    @app.route("/videomemory-alert", methods=["POST"])
    def videomemory_alert():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "error": "JSON object required"}), 400

        ok, outcome = forwarder.forward(payload)
        if ok:
            logger.info(
                "Forwarded event edge_id=%s task_id=%s target=%s",
                payload.get("edge_id"),
                payload.get("task_id"),
                outcome.get("target"),
            )
            return jsonify({"status": "forwarded", "target": outcome.get("target"), "attempts": outcome.get("attempts")})

        # Important: return success-like code so VideoMemory doesn't fail hard while
        # OpenClaw endpoints are being upgraded/migrated.
        logger.warning(
            "Buffered event; no OpenClaw target accepted edge_id=%s task_id=%s attempts=%s",
            payload.get("edge_id"),
            payload.get("task_id"),
            json.dumps(outcome.get("attempts", [])),
        )
        return jsonify({"status": "accepted_unforwarded", "attempts": outcome.get("attempts", [])}), 202

    return app


def main() -> int:
    app = create_app()
    host = os.getenv("OPENCLAW_COMPAT_HOST", "0.0.0.0")
    port = int(os.getenv("OPENCLAW_COMPAT_PORT", "8091"))
    logger.info("Starting OpenClaw compat adapter on http://%s:%s", host, port)
    app.run(host=host, port=port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
