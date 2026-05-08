"""Helpers for building short evidence clips around detections."""

import time
from collections import deque
from typing import Any, Iterable, List, Optional, Tuple


EvidenceFrameRecord = Tuple[float, Any]
EvidenceBuffer = deque[EvidenceFrameRecord]


def snapshot_evidence_buffer(buffer: Iterable[EvidenceFrameRecord]) -> List[EvidenceFrameRecord]:
    """Copy evidence-buffer frames so queued chunks keep their own time context."""

    return [
        (timestamp, frame.copy())
        for timestamp, frame in buffer
        if frame is not None and getattr(frame, "size", 0) > 0
    ]


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
    buffer: Iterable[EvidenceFrameRecord],
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


def build_evidence_clip_from_frames(
    frames: Iterable[Any],
    *,
    fps: float,
    end_hold_seconds: float,
) -> List[Any]:
    """Build an evidence clip from the exact frames sent to the VLM."""

    clip_frames = [
        frame.copy()
        for frame in frames
        if frame is not None and getattr(frame, "size", 0) > 0
    ]
    if not clip_frames:
        return []

    trigger_frame = clip_frames[-1]
    hold_frames = int(round(fps * end_hold_seconds))
    for _ in range(max(0, hold_frames)):
        clip_frames.append(trigger_frame.copy())

    return clip_frames
