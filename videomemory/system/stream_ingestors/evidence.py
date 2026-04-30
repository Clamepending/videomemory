"""Helpers for building short evidence clips around detections."""

import time
from collections import deque
from typing import Any, List, Optional, Tuple


EvidenceBuffer = deque[Tuple[float, Any]]


def sample_evidence_frame(
    buffer: EvidenceBuffer,
    frame: Any,
    *,
    now: Optional[float] = None,
    last_sample_at: float,
    sample_interval_s: float,
) -> float:
    """Sample a frame into a rolling evidence buffer and return last sample time."""

    if frame is None or getattr(frame, "size", 0) == 0:
        return last_sample_at

    now = time.time() if now is None else now
    if buffer and (now - last_sample_at) < sample_interval_s:
        return last_sample_at

    buffer.append((now, frame.copy()))
    return now


def build_evidence_clip_frames(
    buffer: EvidenceBuffer,
    trigger_frame: Any,
    *,
    fps: float,
    end_hold_seconds: float,
) -> List[Any]:
    """Build a short preroll evidence clip ending on the trigger frame."""

    if trigger_frame is None or getattr(trigger_frame, "size", 0) == 0:
        return []

    clip_frames = [frame.copy() for _, frame in buffer if getattr(frame, "size", 0) > 0]
    clip_frames.append(trigger_frame.copy())

    hold_frames = int(round(fps * end_hold_seconds))
    for _ in range(max(0, hold_frames)):
        clip_frames.append(trigger_frame.copy())

    return clip_frames
