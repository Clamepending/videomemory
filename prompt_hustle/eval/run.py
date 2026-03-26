#!/usr/bin/env python3
"""Evaluate VideoMemory's video ingestor against an oracle model.

Tasks are stored per-video in data/{split}/tasks/{video_name}/*.md.
All tasks for a video run simultaneously in one ingestor (like the real
system), so VLM calls = videos * frames, not tasks * videos * frames.

Usage:
    uv run python -m prompt_hustle.eval \
        --instructions prompt_hustle/instructions.md \
        --model qwen3-vl-8b --no-dedup
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
from pydantic import BaseModel, Field

from .common import DATA_DIR, OUTPUT_DIR, load_frames, create_ingestor, process_frames

EVAL_OUTPUT_DIR = OUTPUT_DIR / "eval"
ORACLE_MODEL = "gemini-2.5-flash"


class TaskGrade(BaseModel):
    task_name: str = Field(..., description="Name of the task being graded")
    reasoning: str = Field(..., description="Brief reasoning for the grade")
    score: int = Field(..., ge=0, le=1, description="0 for incorrect, 1 for correct")


class BatchGradingResult(BaseModel):
    grades: list[TaskGrade] = Field(..., description="One grade per task")


def _build_oracle_client():
    from google import genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY must be set for oracle grading.")
    return genai.Client(api_key=api_key)


def oracle_grade_batch(client, image_bytes, task_outputs):
    """Grade all tasks for one frame in a single oracle call.

    Args:
        task_outputs: list of (task_name, task_description, vlm_output)

    Returns:
        dict mapping task_name -> score (0 or 1), or -1 on error.
    """
    from google.genai import types as genai_types

    task_blocks = []
    for tname, tdesc, vlm_out in task_outputs:
        task_blocks.append(
            f"Task '{tname}':\n  Description: {tdesc}\n  Model output: {vlm_out}"
        )

    grading_prompt = (
        "You are an evaluator grading a vision-language model's outputs on multiple tasks.\n\n"
        + "\n\n".join(task_blocks)
        + "\n\nLook at the attached image. For EACH task, evaluate whether the "
        "model's output is factually correct with respect to what is visible.\n\n"
        "Rubric per task:\n"
        "  1 - The output accurately describes what is in the image relative to the task.\n"
        "  0 - The output is incorrect or significantly misrepresents the image content.\n\n"
        "Return JSON with a 'grades' array containing one object per task, each with "
        "'task_name', 'reasoning' (one sentence), and 'score' (0 or 1)."
    )
    image_part = genai_types.Part(
        inline_data=genai_types.Blob(data=image_bytes, mime_type="image/jpeg")
    )
    response = client.models.generate_content(
        model=ORACLE_MODEL,
        contents=[image_part, genai_types.Part(text=grading_prompt)],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=BatchGradingResult.model_json_schema(),
        ),
    )
    raw = getattr(response, "text", None)
    if not raw:
        raise RuntimeError("Oracle model returned empty response.")
    result = BatchGradingResult.model_validate_json(raw)
    return {g.task_name: g.score for g in result.grades}


def load_video_tasks(tasks_dir):
    """Load all .md task files from a directory. Returns [(name, desc), ...]."""
    tasks = []
    for p in sorted(tasks_dir.glob("*.md")):
        desc = p.read_text().strip()
        if desc:
            tasks.append((p.stem, desc))
    return tasks


def run_eval_for_split(args, split: str, quiet: bool = False):
    custom_instructions = None
    if args.instructions:
        inst_path = Path(args.instructions)
        if not inst_path.exists():
            sys.exit(f"Instructions file not found: {inst_path}")
        custom_instructions = inst_path.read_text().strip()
        if not custom_instructions:
            sys.exit(f"Instructions file is empty: {inst_path}")

    frames_dir = DATA_DIR / split / "frames"
    tasks_dir = DATA_DIR / split / "tasks"
    if not frames_dir.exists():
        sys.exit(f"Frames directory not found: {frames_dir}")
    if not tasks_dir.exists():
        sys.exit(f"Tasks directory not found: {tasks_dir}")

    video_dirs = sorted(p.name for p in frames_dir.iterdir() if p.is_dir())
    if not video_dirs:
        sys.exit(f"No video folders found in {frames_dir}")

    mode = "custom instructions" if custom_instructions else "built-in instructions"
    if not quiet:
        print(f"Split:        {split}")
        print(f"Videos:       {video_dirs}")
        print(f"Model:        {args.model or '(default)'}")
        print(f"Oracle:       {ORACLE_MODEL}")
        print(f"Dedup:        {'off' if args.no_dedup else 'on'}")
        print(f"Instructions: {mode}")

    oracle_client = _build_oracle_client()
    all_video_results = []
    grand_scores = []
    all_task_scores = {}

    for video_name in video_dirs:
        video_tasks_dir = tasks_dir / video_name
        if not video_tasks_dir.is_dir():
            print(f"\nWARNING: No tasks dir for {video_name}, skipping")
            continue

        task_descs = load_video_tasks(video_tasks_dir)
        if not task_descs:
            print(f"\nWARNING: No tasks for {video_name}, skipping")
            continue

        if not quiet:
            print(f"\n{'=' * 60}")
            print(f"VIDEO: {video_name}")
            print(f"  Tasks: {', '.join(n for n, _ in task_descs)}")
            print(f"{'=' * 60}")

        frames = load_frames(frames_dir / video_name)
        if not quiet:
            print(f"  Loaded {len(frames)} frames")

        ingestor, tasks = create_ingestor(
            task_descs, args.model, args.no_dedup,
            custom_instructions=custom_instructions,
        )
        task_map = {t.task_number: (name, desc) for t, (name, desc) in zip(tasks, task_descs)}

        per_frame = []
        vlm_errors = 0

        for r in process_frames(ingestor, tasks, frames):
            filename = r["filename"]
            label = f"  [{r['index'] + 1}/{r['total']}] {filename}"

            if r["status"] == "error":
                per_frame.append({"filename": filename, "status": "error", "error": r["error"]})
                vlm_errors += 1
                if not quiet:
                    print(f"{label}  VLM error ({r['error']})")
                continue

            if r["status"] == "skipped":
                per_frame.append({"filename": filename, "status": "skipped"})
                if not quiet:
                    print(f"{label}  skipped (dup)")
                continue

            per_task_outputs = r["per_task_outputs"]
            _, buf = cv2.imencode(".jpg", r["frame"])
            image_bytes = bytes(buf)

            batch_input = []
            for tn, (tname, tdesc) in task_map.items():
                vlm_out = per_task_outputs.get(tn, "(no output)")
                batch_input.append((tname, tdesc, vlm_out))

            try:
                scores_map = oracle_grade_batch(oracle_client, image_bytes, batch_input)
            except Exception:
                scores_map = {}

            frame_grades = {}
            for tname, tdesc, vlm_out in batch_input:
                score = scores_map.get(tname, -1)
                if score >= 0:
                    grand_scores.append(score)
                    all_task_scores.setdefault(tname, []).append(score)
                frame_grades[tname] = {"vlm_output": vlm_out, "score": score}

            summary_parts = [f"{t}={g['score']}" for t, g in frame_grades.items()]
            if not quiet:
                print(f"{label}  {' '.join(summary_parts)}")

            per_frame.append({
                "filename": filename, "status": "graded",
                "per_task": frame_grades,
            })

        skipped = sum(1 for f in per_frame if f.get("status") == "skipped")
        if not quiet:
            print(f"  => {video_name}: {len(per_frame)} frames, {vlm_errors} errors, {skipped} skipped")

        all_video_results.append({
            "video": video_name,
            "tasks": [n for n, _ in task_descs],
            "total_frames": len(frames),
            "vlm_errors": vlm_errors,
            "skipped": skipped,
            "per_frame": per_frame,
        })

    overall = sum(grand_scores) / len(grand_scores) if grand_scores else 0.0
    total_frames = sum(r["total_frames"] for r in all_video_results)

    EVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = EVAL_OUTPUT_DIR / f"eval_{split}_{ts}.json"

    output = {
        "split": split,
        "model": args.model or "(default)", "oracle_model": ORACLE_MODEL,
        "dedup": not args.no_dedup,
        "instructions_file": args.instructions,
        "overall_accuracy": round(overall, 4),
        "total_frames": total_frames,
        "total_graded": len(grand_scores),
        "total_correct": sum(grand_scores),
        "per_task_accuracy": {
            name: round(sum(scores) / len(scores), 4) if scores else 0.0
            for name, scores in sorted(all_task_scores.items())
        },
        "per_video": all_video_results,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    if not quiet:
        print(f"\n{'=' * 60}")
        print("EVAL SUMMARY")
        print(f"{'=' * 60}")
        for name, scores in sorted(all_task_scores.items()):
            acc = sum(scores) / len(scores) if scores else 0.0
            print(f"  {name:30s}  {acc:.2%}  ({sum(scores)}/{len(scores)})")
        print(f"  {'OVERALL':30s}  {overall:.2%}  ({sum(grand_scores)}/{len(grand_scores)})")
        print(f"{'=' * 60}")
        print(f"Results saved to {out_path}")

        print(f"\n---")
        print(f"overall_accuracy: {overall:.6f}")
        print(f"total_graded:     {len(grand_scores)}")
        print(f"total_correct:    {sum(grand_scores)}")
        print(f"total_frames:     {total_frames}")
        for name, scores in sorted(all_task_scores.items()):
            acc = sum(scores) / len(scores) if scores else 0.0
            print(f"task_{name}: {acc:.6f}")

    return {
        "split": split,
        "overall_accuracy": overall,
        "total_graded": len(grand_scores),
        "total_correct": sum(grand_scores),
        "total_frames": total_frames,
        "per_task_accuracy": {
            name: (sum(scores) / len(scores) if scores else 0.0)
            for name, scores in sorted(all_task_scores.items())
        },
        "out_path": str(out_path),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate VideoMemory video ingestor with oracle grading",
    )
    parser.add_argument(
        "--instructions",
        help="Path to universal instructions markdown file (agent-tunable).",
    )
    parser.add_argument(
        "--eval", action="store_true",
        help="Use the validation split instead of train",
    )
    parser.add_argument("--model", default=None, help="Model name for the video ingestor")
    parser.add_argument("--no-dedup", action="store_true", help="Disable frame deduplication")
    args = parser.parse_args()
    if args.eval:
        run_eval_for_split(args, split="validation", quiet=False)
        return

    run_eval_for_split(args, split="train", quiet=False)
    val_result = run_eval_for_split(args, split="validation", quiet=True)
    print("\n---")
    print(f"validation_overall_accuracy: {val_result['overall_accuracy']:.6f}")
    print(f"validation_total_graded:     {val_result['total_graded']}")
    print(f"validation_total_correct:    {val_result['total_correct']}")
    print(f"validation_total_frames:     {val_result['total_frames']}")


if __name__ == "__main__":
    main()
