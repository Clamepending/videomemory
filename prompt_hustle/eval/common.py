"""Shared utilities for running VideoMemory's video ingestor on frame sequences.

Provides path setup, frame loading, ingestor construction, and a frame-processing
generator that both the eval harness and the standalone experiment script reuse.
"""

import os
import sys
from pathlib import Path
from typing import Generator, Optional

import cv2
from dotenv import load_dotenv

PROMPT_HUSTLE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PROMPT_HUSTLE_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROMPT_HUSTLE_ROOT / ".env")

DATA_DIR = PROMPT_HUSTLE_ROOT / "data"
OUTPUT_DIR = PROMPT_HUSTLE_ROOT / "outputs"

from videomemory.system.task_types import Task  # noqa: E402
from videomemory.system.model_providers import get_VLM_provider  # noqa: E402
from videomemory.system.stream_ingestors.video_stream_ingestor import (  # noqa: E402
    VideoStreamIngestor,
)


def load_frames(frame_dir: Path) -> list[tuple[str, object]]:
    """Load all .jpg frames from *frame_dir*, sorted by filename.

    Returns a list of (filename, cv2_image_or_None) tuples.
    """
    frame_files = sorted(frame_dir.glob("*.jpg"))
    if not frame_files:
        raise FileNotFoundError(f"No .jpg files in {frame_dir}")
    frames = []
    for f in frame_files:
        img = cv2.imread(str(f))
        if img is None:
            print(f"  Warning: could not read {f.name}")
        frames.append((f.name, img))
    return frames


def create_ingestor(
    task_desc: str,
    model_name: Optional[str] = None,
    skip_dedup: bool = False,
) -> tuple[VideoStreamIngestor, Task]:
    """Create a VideoStreamIngestor with a single task."""
    model_provider = get_VLM_provider(model_name)
    ingestor = VideoStreamIngestor(camera_source=-1, model_provider=model_provider)
    task = Task(task_number=0, task_desc=task_desc, task_note=[], done=False)
    ingestor._tasks_list.append(task)
    if skip_dedup:
        ingestor._frame_diff_threshold = -1
    return ingestor, task


def process_frames(
    ingestor: VideoStreamIngestor,
    task: Task,
    frames: list[tuple[str, object]],
) -> Generator[dict, None, None]:
    """Run each frame through the ingestor, yielding a result dict per frame.

    Yielded keys always present: ``index``, ``total``, ``filename``, ``frame``,
    ``status`` (one of ``"processed"``, ``"skipped"``, ``"error"``).

    Extra keys for ``status == "processed"``:
        ``vlm_output``, ``produced_update``, ``task_updates``,
        ``processing_time_ms``, ``prompt``.

    Extra key for ``status == "error"``: ``error``.
    """
    total = len(frames)
    for i, (filename, frame) in enumerate(frames):
        base = {"index": i, "total": total, "filename": filename, "frame": frame}

        if frame is None:
            yield {**base, "status": "error", "error": "unreadable"}
            continue

        target = ingestor._target_resolution
        if frame.shape[1] != target[0] or frame.shape[0] != target[1]:
            frame = cv2.resize(frame, target, interpolation=cv2.INTER_LINEAR)
            base["frame"] = frame

        skipped_before = ingestor._frames_skipped
        result = ingestor._VLM_processing(frame)

        if result is None:
            if ingestor._frames_skipped > skipped_before:
                yield {**base, "status": "skipped"}
            else:
                yield {**base, "status": "error", "error": "no VLM result"}
            continue

        task_updates = result.get("task_updates", [])
        if task_updates:
            vlm_output = "; ".join(u["task_note"] for u in task_updates)
            produced_update = True
        else:
            vlm_output = task.task_note[-1].content if task.task_note else "(no observation yet)"
            produced_update = False

        yield {
            **base,
            "status": "processed",
            "vlm_output": vlm_output,
            "produced_update": produced_update,
            "task_updates": task_updates,
            "processing_time_ms": result.get("processing_time_ms", 0),
            "prompt": result.get("prompt", ""),
        }
