"""Runtime deployment mode helpers for VideoMemory."""

from __future__ import annotations

import os

STREAMING_MODE = "streaming"
EVENT_MODE = "event"
DEFAULT_MODE = STREAMING_MODE
VALID_MODES = {STREAMING_MODE, EVENT_MODE}


def normalize_deployment_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in VALID_MODES:
        return mode
    return DEFAULT_MODE


def get_deployment_mode() -> str:
    return normalize_deployment_mode(os.getenv("VIDEOMEMORY_DEPLOYMENT_MODE", DEFAULT_MODE))


def is_streaming_mode() -> bool:
    return get_deployment_mode() == STREAMING_MODE


def is_event_mode() -> bool:
    return get_deployment_mode() == EVENT_MODE
