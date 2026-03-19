#!/usr/bin/env python3
"""Run a VideoStreamIngestor on a sequence of frames from disk.

Usage (from project root):
    uv run python -m offline.experiments.videoingestor_on_frame_sequence house_tour "count chairs"
    uv run python -m offline.experiments.videoingestor_on_frame_sequence house_tour "count chairs" --model gemini-2.5-flash
    uv run python -m offline.experiments.videoingestor_on_frame_sequence house_tour "count chairs" --no-dedup

Output: JSON file in offline/outputs/frame_sequence_experiment/ with:
  - vlm_io:      per-frame VLM input/output with processing time (same length as frame count)
  - task_notes:  accumulated task notes history
"""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from videomemory.system.task_types import Task
from videomemory.system.model_providers import get_VLM_provider
from videomemory.system.stream_ingestors.video_stream_ingestor import (
    VideoStreamIngestor,
)


OFFLINE_ROOT = Path(__file__).resolve().parents[1]
FRAMES_DIR = OFFLINE_ROOT / "data" / "frames"
OUTPUT_DIR = OFFLINE_ROOT / "outputs" / "frame_sequence_experiment"


def load_frames(frame_dir: Path) -> list[tuple[str, any]]:
    """Load all jpg frames from a directory, sorted by filename."""
    frame_files = sorted(frame_dir.glob("*.jpg"))
    if not frame_files:
        raise FileNotFoundError(f"No .jpg files found in {frame_dir}")
    frames = []
    for f in frame_files:
        img = cv2.imread(str(f))
        if img is None:
            print(f"  Warning: could not read {f.name}, will still record as error")
            frames.append((f.name, None))
        else:
            frames.append((f.name, img))
    return frames


def run_experiment(frame_dir_name: str, task_desc: str, model_name: str | None, skip_dedup: bool):
    frame_dir = FRAMES_DIR / frame_dir_name
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Load frames ---
    print(f"Loading frames from {frame_dir} ...")
    frames = load_frames(frame_dir)
    print(f"Loaded {len(frames)} frames\n")

    # --- Model provider ---
    model_provider = get_VLM_provider(model_name)
    provider_name = type(model_provider).__name__

    # --- Ingestor (reuse prompt building, dedup, VLM pipeline) ---
    ingestor = VideoStreamIngestor(
        camera_source=-1,
        model_provider=model_provider,
    )

    task = Task(task_number=0, task_desc=task_desc, task_note=[], done=False)
    ingestor._tasks_list.append(task)

    if skip_dedup:
        ingestor._frame_diff_threshold = -1

    # --- Process frames ---
    vlm_io: list[dict] = []
    experiment_t0 = time.time()

    for i, (filename, frame) in enumerate(frames):
        entry: dict = {"frame_index": i, "filename": filename}
        label = f"[{i + 1}/{len(frames)}] {filename}"

        if frame is None:
            print(f"{label}  -> error (unreadable)")
            entry.update(status="error", error="could not read image file")
            vlm_io.append(entry)
            continue

        target = ingestor._target_resolution
        if frame.shape[1] != target[0] or frame.shape[0] != target[1]:
            frame = cv2.resize(frame, target, interpolation=cv2.INTER_LINEAR)

        skipped_before = ingestor._frames_skipped
        result = ingestor._VLM_processing(frame)

        if result is not None:
            elapsed_ms = result.get("processing_time_ms", 0)
            task_updates = result.get("task_updates", [])
            updates_summary = [u["task_note"][:80] for u in task_updates]
            if task_updates:
                print(f"{label}  -> {elapsed_ms}ms  {updates_summary}")
            else:
                print(f"{label}  -> {elapsed_ms}ms  model_returned_empty_updates")
            entry.update(
                status="processed",
                processing_kind="model_response",
                model_called=True,
                model_returned_empty_updates=(len(task_updates) == 0),
                processing_time_ms=elapsed_ms,
                prompt=result.get("prompt", ""),
                vlm_output={"task_updates": task_updates},
            )
        elif ingestor._frames_skipped > skipped_before:
            print(f"{label}  -> skipped (duplicate)")
            entry.update(
                status="skipped",
                processing_kind="programmatic_skip",
                model_called=False,
                model_returned_empty_updates=False,
                reason="duplicate_frame",
            )
        else:
            print(f"{label}  -> no VLM result")
            entry.update(
                status="error",
                processing_kind="inference_error",
                model_called=True,
                model_returned_empty_updates=False,
                error="VLM returned no results",
            )

        vlm_io.append(entry)

    # --- Build output ---
    total_elapsed_s = round(time.time() - experiment_t0, 2)
    processed_entries = [e for e in vlm_io if e["status"] == "processed"]
    inference_times = [e["processing_time_ms"] for e in processed_entries]

    metadata = {
        "frame_dir": frame_dir_name,
        "task_description": task_desc,
        "model_provider": provider_name,
        "target_resolution": list(ingestor._target_resolution),
        "dedup_threshold": ingestor._frame_diff_threshold,
        "total_frames": len(frames),
        "processed": len(processed_entries),
        "processed_with_empty_updates": sum(
            1 for e in processed_entries if e.get("model_returned_empty_updates") is True
        ),
        "processed_with_nonempty_updates": sum(
            1 for e in processed_entries if e.get("model_returned_empty_updates") is False
        ),
        "programmatic_skips": sum(
            1 for e in vlm_io if e.get("processing_kind") == "programmatic_skip"
        ),
        "skipped": sum(1 for e in vlm_io if e["status"] == "skipped"),
        "errors": sum(1 for e in vlm_io if e["status"] == "error"),
        "total_time_s": total_elapsed_s,
        "avg_inference_ms": round(sum(inference_times) / len(inference_times)) if inference_times else None,
        "min_inference_ms": min(inference_times) if inference_times else None,
        "max_inference_ms": max(inference_times) if inference_times else None,
    }

    output = {
        "metadata": metadata,
        "task_notes": [n.to_dict() for n in task.task_note],
        "vlm_io": vlm_io,
    }

    safe_task = task_desc.replace(" ", "_")[:30]
    out_path = OUTPUT_DIR / f"{frame_dir_name}_{safe_task}.json"

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print("TASK NOTES")
    print(f"{'=' * 60}")
    for note in task.task_note:
        ts = time.strftime("%H:%M:%S", time.localtime(note.timestamp))
        print(f"  [{ts}] {note.content}")
    if not task.task_note:
        print("  (none)")
    print(f"{'=' * 60}")
    m = metadata
    print(f"Frames: {m['total_frames']} total, {m['processed']} processed, "
          f"{m['skipped']} skipped, {m['errors']} errors")
    print(f"Output: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run VideoIngestor on a sequence of frames from disk",
    )
    parser.add_argument("frame_dir", help="Directory name under offline/data/frames/")
    parser.add_argument("task", help="Task description, e.g. 'count chairs'")
    parser.add_argument("--model", default=None,
                        help="Model name (default: VIDEO_INGESTOR_MODEL env or local-vllm)")
    parser.add_argument("--no-dedup", action="store_true",
                        help="Disable frame deduplication (process every frame)")
    args = parser.parse_args()

    run_experiment(args.frame_dir, args.task, args.model, args.no_dedup)


if __name__ == "__main__":
    main()
