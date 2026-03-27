#!/usr/bin/env python3
"""Run the VideoStreamIngestor on frame sequences without oracle grading.

Uses the same multi-task setup as the eval loop: tasks are loaded from
data/{split}/tasks/{video_name}/*.md. Accepts an --instructions flag to
inject custom instructions into the VLM prompt, so you can qualitatively
compare different prompts side by side.

Usage (from project root):
    uv run python -m prompt_hustle.results.videoingestor_on_frame_sequence house_tour
    uv run python -m prompt_hustle.results.videoingestor_on_frame_sequence house_tour \
        --instructions prompt_hustle/prompt.md
    uv run python -m prompt_hustle.results.videoingestor_on_frame_sequence house_tour \
        --instructions prompt_hustle/prompt.md --split validation --model gemini-2.5-flash
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from eval.common import DATA_DIR, OUTPUT_DIR, load_frames, create_ingestor, process_frames

EXPERIMENT_OUTPUT_DIR = OUTPUT_DIR / "frame_sequence_experiment"
VIDEO_INGESTOR_MODEL = os.getenv("VIDEO_INGESTOR_MODEL")


def load_video_tasks(tasks_dir: Path) -> list[tuple[str, str]]:
    """Load all .md task files from a directory. Returns [(name, desc), ...]."""
    return [
        (p.stem, p.read_text().strip())
        for p in sorted(tasks_dir.glob("*.md"))
        if p.read_text().strip()
    ]


def run_experiment(video_name: str, split: str, instructions_path: str | None,
                   model_name: str | None):
    custom_instructions = None
    if instructions_path:
        inst = Path(instructions_path)
        if not inst.exists():
            sys.exit(f"Instructions file not found: {inst}")
        custom_instructions = inst.read_text().strip()
        if not custom_instructions:
            sys.exit(f"Instructions file is empty: {inst}")

    frames_dir = DATA_DIR / split / "frames" / video_name
    tasks_dir = DATA_DIR / split / "tasks" / video_name

    if not frames_dir.exists():
        sys.exit(f"Frames directory not found: {frames_dir}")
    if not tasks_dir.is_dir():
        sys.exit(f"Tasks directory not found: {tasks_dir}")

    task_descs = load_video_tasks(tasks_dir)
    if not task_descs:
        sys.exit(f"No task .md files found in {tasks_dir}")

    frames = load_frames(frames_dir)
    print(f"Video:  {video_name} ({split})")
    print(f"Frames: {len(frames)}")
    print(f"Tasks:  {len(task_descs)}")
    for name, desc in task_descs:
        print(f"  - {name}: {desc[:80]}")
    if instructions_path:
        print(f"Instructions: {instructions_path}")
    print()

    ingestor, tasks = create_ingestor(
        task_descs, model_name,
        custom_instructions=custom_instructions,
    )
    task_map = {t.task_number: (name, desc)
                for t, (name, desc) in zip(tasks, task_descs)}

    vlm_io = []
    t0 = time.time()

    for r in process_frames(ingestor, tasks, frames):
        filename = r["filename"]
        label = f"[{r['index'] + 1}/{r['total']}] {filename}"

        entry = {"frame_index": r["index"], "filename": filename}

        if r["status"] == "error":
            print(f"{label}  -> error ({r['error']})")
            entry.update(status="error", error=r["error"])
        elif r["status"] == "skipped":
            print(f"{label}  -> skipped (duplicate)")
            entry.update(status="skipped", model_called=False)
        else:
            elapsed_ms = r["processing_time_ms"]
            per_task = {}
            for tn, (tname, _) in task_map.items():
                output = r["per_task_outputs"].get(tn, "(no output)")
                per_task[tname] = output

            summaries = [f"{k}: {v[:60]}" for k, v in per_task.items()]
            print(f"{label}  -> {elapsed_ms}ms")
            for s in summaries:
                print(f"    {s}")

            entry.update(
                status="processed",
                model_called=True,
                processing_time_ms=elapsed_ms,
                per_task_outputs=per_task,
                prompt=r["prompt"],
            )

        vlm_io.append(entry)

    elapsed_s = round(time.time() - t0, 2)
    processed = [e for e in vlm_io if e["status"] == "processed"]
    inference_times = [e["processing_time_ms"] for e in processed]

    metadata = {
        "video": video_name,
        "split": split,
        "instructions_file": instructions_path,
        "tasks": [{"name": n, "description": d} for n, d in task_descs],
        "model_provider": type(ingestor._model_provider).__name__,
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
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = EXPERIMENT_OUTPUT_DIR / f"{video_name}_{ts}.json"

    task_notes_out = {}
    for t, (name, _) in zip(tasks, task_descs):
        task_notes_out[name] = [
            {"timestamp": n.timestamp, "content": n.content}
            for n in t.task_note
        ]

    output = {"metadata": metadata, "task_notes": task_notes_out, "vlm_io": vlm_io}
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print()
    print("=" * 60)
    print("TASK NOTES")
    print("=" * 60)
    for name, notes in task_notes_out.items():
        print(f"\n  [{name}]")
        for n in notes:
            ts_str = time.strftime("%H:%M:%S", time.localtime(n["timestamp"]))
            print(f"    [{ts_str}] {n['content']}")
        if not notes:
            print("    (none)")
    print("=" * 60)
    m = metadata
    print(
        f"Frames: {m['total_frames']} total, {m['processed']} processed, "
        f"{m['skipped']} skipped, {m['errors']} errors"
    )
    if inference_times:
        print(
            f"Inference: avg {m['avg_inference_ms']}ms, "
            f"min {m['min_inference_ms']}ms, max {m['max_inference_ms']}ms"
        )
    print(f"Total time: {m['total_time_s']}s")
    print(f"Output: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run VideoIngestor on frame sequences (qualitative, no oracle grading)",
    )
    parser.add_argument(
        "video_name",
        help="Video directory name under data/{split}/frames/",
    )
    parser.add_argument(
        "--instructions",
        help="Path to prompt.md for the VLM prompt",
    )
    parser.add_argument("--model", default=VIDEO_INGESTOR_MODEL, help="Model name")
    parser.add_argument("--split", default="train", choices=["train", "validation"],
                        help="Data split to use (default: train)")
    args = parser.parse_args()
    run_experiment(args.video_name, args.split, args.instructions, args.model)


if __name__ == "__main__":
    main()
