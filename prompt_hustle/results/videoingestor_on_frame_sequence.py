#!/usr/bin/env python3
"""Run a VideoStreamIngestor on a sequence of frames from disk.

Records the full VLM I/O (prompt, output, timing) for each frame without
oracle grading. Useful for inspecting raw ingestor behaviour.

Usage (from project root):
    uv run python prompt_hustle/eval/videoingestor_on_frame_sequence.py house_tour "count chairs"
    uv run python prompt_hustle/eval/videoingestor_on_frame_sequence.py house_tour "count chairs" --model gemini-2.5-flash --no-dedup
"""

import argparse
import json
import time
from pathlib import Path

from eval.common import DATA_DIR, OUTPUT_DIR, load_frames, create_ingestor, process_frames

EXPERIMENT_OUTPUT_DIR = OUTPUT_DIR / "frame_sequence_experiment"


def run_experiment(frame_dir_name, task_desc, model_name, skip_dedup):
    frames_dir = DATA_DIR / "train" / "frames"
    frame_dir = frames_dir / frame_dir_name

    frames = load_frames(frame_dir)
    print(f"Loaded {len(frames)} frames from {frame_dir}")

    ingestor, task = create_ingestor(task_desc, model_name, skip_dedup)
    provider_name = type(ingestor._model_provider).__name__

    vlm_io = []
    t0 = time.time()

    for r in process_frames(ingestor, task, frames):
        filename = r["filename"]
        label = f"[{r['index'] + 1}/{r['total']}] {filename}"

        entry = {"frame_index": r["index"], "filename": filename}

        if r["status"] == "error":
            print(f"{label}  -> error ({r['error']})")
            entry.update(status="error", error=r["error"])

        elif r["status"] == "skipped":
            print(f"{label}  -> skipped (duplicate)")
            entry.update(status="skipped", reason="duplicate_frame", model_called=False)

        else:
            updates = r["task_updates"]
            elapsed_ms = r["processing_time_ms"]
            summaries = [u["task_note"][:80] for u in updates]
            if updates:
                print(f"{label}  -> {elapsed_ms}ms  {summaries}")
            else:
                print(f"{label}  -> {elapsed_ms}ms  model_returned_empty_updates")
            entry.update(
                status="processed",
                model_called=True,
                model_returned_empty_updates=(len(updates) == 0),
                processing_time_ms=elapsed_ms,
                prompt=r["prompt"],
                vlm_output={"task_updates": updates},
            )

        vlm_io.append(entry)

    elapsed_s = round(time.time() - t0, 2)
    processed = [e for e in vlm_io if e["status"] == "processed"]
    inference_times = [e["processing_time_ms"] for e in processed]

    metadata = {
        "frame_dir": frame_dir_name,
        "task_description": task_desc,
        "model_provider": provider_name,
        "target_resolution": list(ingestor._target_resolution),
        "dedup_threshold": ingestor._frame_diff_threshold,
        "total_frames": len(frames),
        "processed": len(processed),
        "skipped": sum(1 for e in vlm_io if e["status"] == "skipped"),
        "errors": sum(1 for e in vlm_io if e["status"] == "error"),
        "total_time_s": elapsed_s,
        "avg_inference_ms": (
            round(sum(inference_times) / len(inference_times))
            if inference_times else None
        ),
        "min_inference_ms": min(inference_times) if inference_times else None,
        "max_inference_ms": max(inference_times) if inference_times else None,
    }

    EXPERIMENT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_task = task_desc.replace(" ", "_")[:30]
    out_path = EXPERIMENT_OUTPUT_DIR / f"{frame_dir_name}_{safe_task}.json"

    output = {
        "metadata": metadata,
        "task_notes": [n.to_dict() for n in task.task_note],
        "vlm_io": vlm_io,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print("")
    print("=" * 60)
    print("TASK NOTES")
    print("=" * 60)
    for note in task.task_note:
        ts = time.strftime("%H:%M:%S", time.localtime(note.timestamp))
        print(f"  [{ts}] {note.content}")
    if not task.task_note:
        print("  (none)")
    print("=" * 60)
    m = metadata
    print(
        f"Frames: {m['total_frames']} total, {m['processed']} processed, "
        f"{m['skipped']} skipped, {m['errors']} errors"
    )
    print(f"Output: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run VideoIngestor on a sequence of frames from disk",
    )
    parser.add_argument(
        "frame_dir",
        help="Directory name under prompt_hustle/data/train/frames/",
    )
    parser.add_argument("task", help="Task description")
    parser.add_argument("--model", default=None, help="Model name")
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable frame deduplication",
    )
    args = parser.parse_args()
    run_experiment(args.frame_dir, args.task, args.model, args.no_dedup)


if __name__ == "__main__":
    main()
