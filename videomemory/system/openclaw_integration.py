"""OpenClaw webhook delivery helpers for VideoMemory task updates."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import requests

from .task_types import NoteEntry, Task

logger = logging.getLogger("OpenClawIntegration")


@dataclass
class OpenClawWebhookConfig:
    url: str
    token: str
    timeout_s: float
    dedupe_ttl_s: float
    min_interval_s: float
    default_bot_id: str


class OpenClawWebhookDispatcher:
    """Dispatch task note changes to an OpenClaw-compatible webhook."""

    def __init__(
        self,
        *,
        config_loader: Optional[Callable[[], OpenClawWebhookConfig]] = None,
        http_client: Any = requests,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config_loader = config_loader or self._load_config_from_env
        self._http_client = http_client
        self._clock = clock
        self._lock = threading.Lock()
        self._recent_successes: Dict[str, float] = {}
        self._last_delivery_at = 0.0

    @staticmethod
    def _load_config_from_env() -> OpenClawWebhookConfig:
        def _float_env(name: str, default: float, minimum: float) -> float:
            raw = str(os.getenv(name, "")).strip()
            if not raw:
                return default
            try:
                return max(minimum, float(raw))
            except ValueError:
                logger.warning("Invalid float for %s=%r; using default %s", name, raw, default)
                return default

        return OpenClawWebhookConfig(
            url=str(os.getenv("VIDEOMEMORY_OPENCLAW_WEBHOOK_URL", "")).strip(),
            token=str(os.getenv("VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN", "")).strip(),
            timeout_s=_float_env("VIDEOMEMORY_OPENCLAW_WEBHOOK_TIMEOUT_S", 3.0, 0.1),
            dedupe_ttl_s=_float_env("VIDEOMEMORY_OPENCLAW_DEDUPE_TTL_S", 30.0, 0.0),
            min_interval_s=_float_env("VIDEOMEMORY_OPENCLAW_MIN_INTERVAL_S", 0.0, 0.0),
            default_bot_id=str(os.getenv("VIDEOMEMORY_OPENCLAW_BOT_ID", "")).strip(),
        )

    @staticmethod
    def _isoformat(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _latest_note(task: Task, new_note: Optional[NoteEntry]) -> Optional[NoteEntry]:
        if new_note is not None:
            return new_note
        if getattr(task, "task_note", None):
            candidate = task.task_note[-1]
            if isinstance(candidate, NoteEntry):
                return candidate
            if isinstance(candidate, dict):
                return NoteEntry(
                    content=str(candidate.get("content", "")),
                    timestamp=float(candidate.get("timestamp", time.time())),
                )
        return None

    def _build_payload(
        self,
        *,
        task: Task,
        note: Optional[NoteEntry],
        bot_id: str,
        now_ts: float,
    ) -> Dict[str, Any]:
        note_content = note.content if note is not None else ""
        note_ts = float(note.timestamp) if note is not None else now_ts
        event_basis = "|".join(
            [
                str(bot_id),
                str(getattr(task, "io_id", "") or ""),
                str(getattr(task, "task_id", "") or ""),
                str(getattr(task, "status", "") or ""),
                str(int(bool(getattr(task, "done", False)))),
                note_content,
                f"{note_ts:.6f}",
            ]
        )
        event_hash = hashlib.sha256(event_basis.encode("utf-8")).hexdigest()
        event_id = f"vm-{event_hash[:20]}"
        note_entries = getattr(task, "task_note", []) or []
        return {
            "service": "videomemory",
            "event_type": "task_update",
            "event_id": event_id,
            "idempotency_key": event_id,
            "bot_id": bot_id,
            "io_id": str(getattr(task, "io_id", "") or ""),
            "task_id": str(getattr(task, "task_id", "") or ""),
            "task_number": getattr(task, "task_number", None),
            "task_description": str(getattr(task, "task_desc", "") or ""),
            "task_status": str(getattr(task, "status", "") or ""),
            "task_done": bool(getattr(task, "done", False)),
            "note": note_content,
            "note_timestamp": note_ts,
            "note_timestamp_iso": self._isoformat(note_ts),
            "notes_count": len(note_entries),
            "observed_at": self._isoformat(now_ts),
        }

    @staticmethod
    def _dedupe_key(payload: Dict[str, Any]) -> str:
        return "|".join(
            [
                str(payload.get("bot_id", "")),
                str(payload.get("io_id", "")),
                str(payload.get("task_id", "")),
                str(payload.get("task_status", "")),
                str(int(bool(payload.get("task_done", False)))),
                str(payload.get("note", "")),
            ]
        )

    def dispatch_task_update(self, task: Task, new_note: Optional[NoteEntry] = None) -> Dict[str, Any]:
        """Send a task-note change to the configured OpenClaw webhook."""
        config = self._config_loader()
        if not config.url:
            return {"status": "disabled", "reason": "missing webhook url"}

        bot_id = str(getattr(task, "bot_id", "") or "").strip() or config.default_bot_id
        if not bot_id:
            logger.info(
                "Skipping OpenClaw webhook for task %s because bot_id is not available",
                getattr(task, "task_id", None),
            )
            return {"status": "skipped", "reason": "missing bot_id"}

        if new_note is None and not bool(getattr(task, "done", False)):
            return {"status": "skipped", "reason": "no note change"}

        now_ts = self._clock()
        note = self._latest_note(task, new_note)
        payload = self._build_payload(task=task, note=note, bot_id=bot_id, now_ts=now_ts)
        dedupe_key = self._dedupe_key(payload)

        with self._lock:
            if config.dedupe_ttl_s > 0:
                cutoff = now_ts - config.dedupe_ttl_s
                stale = [key for key, seen_at in self._recent_successes.items() if seen_at < cutoff]
                for key in stale:
                    self._recent_successes.pop(key, None)
                seen_at = self._recent_successes.get(dedupe_key)
                if seen_at is not None and (now_ts - seen_at) < config.dedupe_ttl_s:
                    return {"status": "suppressed", "reason": "duplicate"}

            if config.min_interval_s > 0 and (now_ts - self._last_delivery_at) < config.min_interval_s:
                return {"status": "suppressed", "reason": "rate_limited"}

        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": str(payload["idempotency_key"]),
        }
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"

        response = self._http_client.post(
            config.url,
            json=payload,
            headers=headers,
            timeout=config.timeout_s,
        )
        response.raise_for_status()

        response_payload: Any
        try:
            response_payload = response.json() if getattr(response, "text", "") else {}
        except Exception:
            response_payload = {"text": (getattr(response, "text", "") or "").strip()}

        with self._lock:
            self._recent_successes[dedupe_key] = now_ts
            self._last_delivery_at = now_ts

        logger.info(
            "Delivered OpenClaw webhook for task_id=%s io_id=%s bot_id=%s",
            payload["task_id"],
            payload["io_id"],
            bot_id,
        )
        return {
            "status": "sent",
            "event_id": payload["event_id"],
            "bot_id": bot_id,
            "response_status": getattr(response, "status_code", None),
            "response": response_payload,
        }
