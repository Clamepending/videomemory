"""OpenClaw webhook wake-up notifier for VideoMemory detection events."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger("OpenClawNotifier")
_UNSET = object()


class OpenClawWakeNotifier:
    """POSTs detection events to an OpenClaw gateway hook endpoint.

    This is intentionally best-effort: failures are logged and never raised back
    into the video ingestion pipeline.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = _UNSET,  # type: ignore[assignment]
        bearer_token: Optional[str] = _UNSET,  # type: ignore[assignment]
        timeout_seconds: float = 3.0,
        dedupe_ttl_seconds: float = 30.0,
        min_interval_seconds: float = 0.0,
        enabled: Optional[bool] = None,
        event_recorder: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        if webhook_url is _UNSET:
            webhook_url = os.getenv("VIDEOMEMORY_OPENCLAW_WEBHOOK_URL", "")
        if bearer_token is _UNSET:
            bearer_token = os.getenv("VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN", "")

        self.webhook_url = str(webhook_url or "").strip()
        self.bearer_token = str(bearer_token or "").strip()
        self.timeout_seconds = float(
            timeout_seconds if timeout_seconds is not None else os.getenv("VIDEOMEMORY_OPENCLAW_WEBHOOK_TIMEOUT_S", "3")
        )
        self.dedupe_ttl_seconds = float(
            dedupe_ttl_seconds if dedupe_ttl_seconds is not None else os.getenv("VIDEOMEMORY_OPENCLAW_DEDUPE_TTL_S", "30")
        )
        self.min_interval_seconds = float(
            min_interval_seconds if min_interval_seconds is not None else os.getenv("VIDEOMEMORY_OPENCLAW_MIN_INTERVAL_S", "0")
        )
        self.enabled = bool(self.webhook_url) if enabled is None else bool(enabled)

        self._lock = threading.Lock()
        self._recent_event_times: Dict[str, float] = {}
        self._last_sent_at: float = 0.0
        self._event_recorder = event_recorder

    @classmethod
    def from_env(cls, event_recorder: Optional[Callable[[Dict[str, Any]], None]] = None) -> "OpenClawWakeNotifier":
        """Build from environment variables."""
        return cls(event_recorder=event_recorder)

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.webhook_url)

    def notify_task_update(self, task, note=None) -> bool:
        """Send a wake-up stimulus for a detection event."""
        started = time.perf_counter()
        if not self.is_enabled():
            self._record_debug_event(
                status="disabled",
                payload={
                    "task_id": getattr(task, "task_id", None),
                    "io_id": getattr(task, "io_id", None),
                    "task_description": getattr(task, "task_desc", None),
                },
                duration_ms=self._duration_ms(started),
                result_summary="Webhook disabled or URL not configured",
            )
            return False

        note_content = ""
        note_timestamp = None
        if note is not None:
            note_content = str(getattr(note, "content", "") or "")
            note_timestamp = getattr(note, "timestamp", None)
        if not note_content and getattr(task, "task_note", None):
            latest = task.task_note[-1]
            note_content = str(getattr(latest, "content", "") or "")
            note_timestamp = getattr(latest, "timestamp", None)

        payload = {
            "source": "videomemory",
            "event_type": "task_update",
            "task_id": getattr(task, "task_id", None),
            "task_number": getattr(task, "task_number", None),
            "io_id": getattr(task, "io_id", None),
            "task_description": getattr(task, "task_desc", None),
            "task_done": bool(getattr(task, "done", False)),
            "task_status": getattr(task, "status", None),
            "note": note_content,
            "note_timestamp": note_timestamp,
            "sent_at": time.time(),
        }
        event_key = self._event_key(payload)
        should_send, skip_reason = self._should_send(event_key)
        if not should_send:
            logger.debug("Skipping duplicate/throttled OpenClaw event for task_id=%s", payload.get("task_id"))
            self._record_debug_event(
                status="skipped",
                payload=payload,
                duration_ms=self._duration_ms(started),
                result_summary=f"Suppressed by {skip_reason}",
            )
            return False

        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "OpenClaw webhook returned %s for task_id=%s body=%s",
                    resp.status_code,
                    payload.get("task_id"),
                    (resp.text or "")[:300],
                )
                self._record_debug_event(
                    status="http_error",
                    payload=payload,
                    duration_ms=self._duration_ms(started),
                    result_error=(resp.text or "")[:300] or f"HTTP {resp.status_code}",
                    response_status=resp.status_code,
                )
                return False
            logger.info(
                "OpenClaw wake sent for task_id=%s io_id=%s",
                payload.get("task_id"),
                payload.get("io_id"),
            )
            self._record_debug_event(
                status="ok",
                payload=payload,
                duration_ms=self._duration_ms(started),
                result_summary=f"Webhook delivered (HTTP {resp.status_code})",
                response_status=resp.status_code,
            )
            return True
        except Exception as e:
            logger.warning("OpenClaw webhook send failed: %s", e)
            self._record_debug_event(
                status="send_error",
                payload=payload,
                duration_ms=self._duration_ms(started),
                error=str(e),
            )
            return False

    def _event_key(self, payload: Dict) -> str:
        return json.dumps(
            {
                "task_id": payload.get("task_id"),
                "io_id": payload.get("io_id"),
                "note": payload.get("note"),
                "task_done": payload.get("task_done"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _should_send(self, event_key: str) -> tuple[bool, str]:
        now = time.time()
        with self._lock:
            # Expire old dedupe entries.
            if self.dedupe_ttl_seconds > 0:
                cutoff = now - self.dedupe_ttl_seconds
                self._recent_event_times = {
                    k: t for k, t in self._recent_event_times.items() if t >= cutoff
                }
                if event_key in self._recent_event_times:
                    return False, "dedupe_ttl"

            if self.min_interval_seconds > 0 and (now - self._last_sent_at) < self.min_interval_seconds:
                return False, "min_interval"

            self._recent_event_times[event_key] = now
            self._last_sent_at = now
            return True, ""

    def _duration_ms(self, started: float) -> float:
        return round((time.perf_counter() - started) * 1000.0, 2)

    def _remote_addr(self) -> str:
        if not self.webhook_url:
            return ""
        try:
            parsed = urlparse(self.webhook_url)
            return parsed.netloc or parsed.path
        except Exception:
            return self.webhook_url

    def _record_debug_event(
        self,
        *,
        status: str,
        payload: Dict[str, Any],
        duration_ms: float,
        error: str = "",
        result_error: str = "",
        result_summary: str = "",
        response_status: Optional[int] = None,
    ) -> None:
        if not self._event_recorder:
            return
        try:
            event: Dict[str, Any] = {
                "ts": time.time(),
                "event_source": "webhook",
                "transport": "http",
                "method": "webhook/task_update",
                "status": status,
                "duration_ms": duration_ms,
                "remote_addr": self._remote_addr(),
                "params": {
                    "task_id": payload.get("task_id"),
                    "io_id": payload.get("io_id"),
                    "task_done": payload.get("task_done"),
                    "task_status": payload.get("task_status"),
                    "task_description": payload.get("task_description"),
                },
            }
            if payload.get("note"):
                event["params"]["note"] = payload.get("note")
            if error:
                event["error"] = error
            if result_error:
                event["result_error"] = result_error
            if result_summary:
                event["result_summary"] = result_summary
            if response_status is not None:
                event["response_status"] = response_status
            self._event_recorder(event)
        except Exception:
            logger.debug("Failed to record webhook debug event", exc_info=True)
