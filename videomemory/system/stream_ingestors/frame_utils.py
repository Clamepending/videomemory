"""Frame encoding and comparison helpers for video ingestion."""

import base64
import logging
import math
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np


logger = logging.getLogger("VideoStreamIngestor")


def frame_to_jpeg_bytes(frame: Any, quality: int = 85) -> bytes:
    """Convert an OpenCV frame to JPEG bytes."""

    if frame is None:
        return b""
    success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        return b""
    return buffer.tobytes()


def frame_to_base64(frame: Any, quality: int = 85) -> str:
    """Convert an OpenCV frame to a base64-encoded JPEG string."""

    try:
        frame_bytes = frame_to_jpeg_bytes(frame, quality=quality)
        if not frame_bytes:
            return ""
        return base64.b64encode(frame_bytes).decode("utf-8")
    except Exception as e:
        logger.error("Error encoding frame: %s", e)
        return ""


def mean_absolute_frame_difference(frame: Any, previous_frame: Any) -> float:
    """Return the mean absolute pixel difference on the 0-255 pixel scale."""

    return float(np.abs(frame.astype(np.int16) - previous_frame.astype(np.int16)).mean())


def normalize_frames(frame_or_frames: Any) -> List[Any]:
    """Return non-empty OpenCV frames from a frame or frame sequence."""

    frames = list(frame_or_frames) if isinstance(frame_or_frames, (list, tuple)) else [frame_or_frames]
    return [frame for frame in frames if frame is not None and getattr(frame, "size", 0) > 0]


def subsample_frames(frames: List[Any], max_frames: int) -> List[Any]:
    """Return up to max_frames evenly spaced frames from a sequence."""

    valid_frames = [frame for frame in frames if frame is not None and getattr(frame, "size", 0) > 0]
    if max_frames <= 0 or len(valid_frames) <= max_frames:
        return [frame.copy() for frame in valid_frames]

    if max_frames == 1:
        return [valid_frames[-1].copy()]

    last_index = len(valid_frames) - 1
    indices = [round(i * last_index / (max_frames - 1)) for i in range(max_frames)]
    return [valid_frames[index].copy() for index in indices]


def build_frame_contact_sheet(frames: List[Any], output_size: Optional[Tuple[int, int]] = None) -> Any:
    """Pack frames into one chronological image for providers that accept one image."""

    valid_frames = [frame for frame in frames if frame is not None and getattr(frame, "size", 0) > 0]
    if not valid_frames:
        return None
    if len(valid_frames) == 1:
        return valid_frames[0].copy()

    first_frame = valid_frames[0]
    sheet_width, sheet_height = output_size or (first_frame.shape[1], first_frame.shape[0])
    sheet_width = max(1, int(sheet_width))
    sheet_height = max(1, int(sheet_height))
    cols = max(1, math.ceil(math.sqrt(len(valid_frames))))
    rows = max(1, math.ceil(len(valid_frames) / cols))
    cell_width = max(1, sheet_width // cols)
    cell_height = max(1, sheet_height // rows)

    sheet = np.zeros((sheet_height, sheet_width, first_frame.shape[2]), dtype=first_frame.dtype)
    for index, frame in enumerate(valid_frames):
        row = index // cols
        col = index % cols
        scale = min(cell_width / frame.shape[1], cell_height / frame.shape[0])
        thumb_width = max(1, int(frame.shape[1] * scale))
        thumb_height = max(1, int(frame.shape[0] * scale))
        thumb = cv2.resize(frame, (thumb_width, thumb_height), interpolation=cv2.INTER_AREA)

        x0 = col * cell_width + (cell_width - thumb_width) // 2
        y0 = row * cell_height + (cell_height - thumb_height) // 2
        sheet[y0:y0 + thumb_height, x0:x0 + thumb_width] = thumb

        label = f"{index + 1}"
        cv2.putText(
            sheet,
            label,
            (col * cell_width + 8, row * cell_height + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    return sheet


def build_subsampled_contact_sheet(
    frames: List[Any],
    *,
    max_frames: int,
    output_size: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[List[Any], Any]]:
    """Subsample frames and build the single image sent to model providers."""

    sampled_frames = subsample_frames(frames, max_frames)
    model_frame = build_frame_contact_sheet(sampled_frames, output_size=output_size)
    if model_frame is None:
        return None
    return sampled_frames, model_frame


def is_chunk_complete(chunk_start_monotonic: float, now_monotonic: float, chunk_seconds: float) -> bool:
    """Return True when a capture chunk has reached its target duration."""

    return now_monotonic - chunk_start_monotonic >= chunk_seconds


def build_chunk_metadata(
    *,
    duration_seconds: float,
    sampled_frame_count: int,
    raw_frame_count: int,
) -> dict[str, Any]:
    """Build debug metadata for a chunk sent to the model provider."""

    return {
        "duration_seconds": float(duration_seconds),
        "sampled_frame_count": int(sampled_frame_count),
        "raw_frame_count": int(raw_frame_count),
    }
