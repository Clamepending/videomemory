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
    """Load all .jpg frames from *frame_dir*, sorted by filename."""
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
    task_descs: list[tuple[str, str]],
    model_name: Optional[str] = None,
    skip_dedup: bool = False,
    custom_instructions: Optional[str] = None,
) -> tuple[VideoStreamIngestor, list[Task]]:
    """Create a VideoStreamIngestor with one or more simultaneous tasks.

    Args:
        task_descs: List of (task_name, task_description) pairs.
        custom_instructions: If provided, replaces the built-in <instructions> block.

    Returns:
        (ingestor, tasks) where tasks is a list of Task objects matching task_descs order.
    """
    model_provider = get_VLM_provider(model_name)
    ingestor = VideoStreamIngestor(camera_source=-1, model_provider=model_provider)
    tasks = []
    for i, (name, desc) in enumerate(task_descs):
        task = Task(task_number=i, task_desc=desc, task_note=[], done=False)
        ingestor._tasks_list.append(task)
        tasks.append(task)
    if skip_dedup:
        ingestor._frame_diff_threshold = -1

    if custom_instructions is not None:
        import time as _time
        import types
        from videomemory.system.task_types import NoteEntry

        def _patched_build_prompt(self) -> str:
            lines = ["<tasks>"]
            for t in self._tasks_list:
                lines.append("<task>")
                lines.append(f"<task_number>{t.task_number}</task_number>")
                lines.append(f"<task_desc>{t.task_desc}</task_desc>")
                newest = t.task_note[-1] if t.task_note else NoteEntry(content="None", timestamp=_time.time())
                ts = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(newest.timestamp))
                lines.append(f'<task_newest_note timestamp="{ts}">{newest.content}</task_newest_note>')
                lines.append("</task>")
            lines.append("</tasks>")
            return "\n".join(lines) + "\n\n" + custom_instructions

        ingestor._build_prompt = types.MethodType(_patched_build_prompt, ingestor)

    return ingestor, tasks


def process_frames(
    ingestor: VideoStreamIngestor,
    tasks: list[Task],
    frames: list[tuple[str, object]],
) -> Generator[dict, None, None]:
    """Run each frame through the ingestor, yielding a result dict per frame.

    For multi-task ingestors, task_updates may contain updates for different
    task_number values. The caller is responsible for splitting per-task.
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

        try:
            result = ingestor._VLM_processing(frame)
        except Exception as exc:
            yield {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
            continue

        if result is None:
            yield {**base, "status": "error", "error": "no VLM result"}
            continue

        status = "skipped" if result.get("skipped") else "processed"

        task_updates = result.get("task_updates", [])
        per_task_outputs = {}
        for u in task_updates:
            tn = u.get("task_number", 0)
            per_task_outputs[tn] = u.get("task_note", "")

        for t in tasks:
            if t.task_number not in per_task_outputs:
                if t.task_note:
                    per_task_outputs[t.task_number] = t.task_note[-1].content
                else:
                    per_task_outputs[t.task_number] = "(no observation yet)"

        yield {
            **base,
            "status": status,
            "task_updates": task_updates,
            "per_task_outputs": per_task_outputs,
            "processing_time_ms": result.get("processing_time_ms", 0),
            "prompt": result.get("prompt", ""),
        }
