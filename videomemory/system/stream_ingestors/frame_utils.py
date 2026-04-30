"""Frame encoding and comparison helpers for video ingestion."""

import base64
import logging
from typing import Any

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
