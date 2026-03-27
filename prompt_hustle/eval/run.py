#!/usr/bin/env python3
"""Evaluate VideoMemory's video ingestor against an oracle model.

Tasks are stored per-video in data/{split}/tasks/{video_name}/*.md.
All tasks for a video run simultaneously in one ingestor (like the real
system), so VLM calls = videos * frames, not tasks * videos * frames.

Usage (from the prompt_hustle/ directory):
    uv run python -m eval \
        --instructions prompt.md --no-dedup
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
from pydantic import BaseModel, Field

from eval.common import DATA_DIR, OUTPUT_DIR, load_frames, create_ingestor, process_frames

EVAL_OUTPUT_DIR = OUTPUT_DIR / "eval"
ORACLE_MODEL = os.getenv("ORACLE_MODEL", "gemini-2.5-flash")
VIDEO_INGESTOR_MODEL = os.getenv("VIDEO_INGESTOR_MODEL")
GRADING_PROMPT_TEMPLATE = (Path(__file__).resolve().parent / "grading_prompt.md").read_text()
SPLITS = ["train", "validation"]


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
    """Grade all tasks for one frame in a single oracle call."""
    from google.genai import types as genai_types

    task_blocks = "\n\n".join(
        f"Task '{tname}':\n  Description: {tdesc}\n  Model output: {vlm_out}"
        for tname, tdesc, vlm_out in task_outputs
    )
    grading_prompt = GRADING_PROMPT_TEMPLATE.format(task_blocks=task_blocks)
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
    return [
        (p.stem, p.read_text().strip())
        for p in sorted(tasks_dir.glob("*.md"))
        if p.read_text().strip()
    ]


def run_eval(args):
    custom_instructions = None
    if args.instructions:
        inst_path = Path(args.instructions)
        if not inst_path.exists():
            sys.exit(f"Instructions file not found: {inst_path}")
        custom_instructions = inst_path.read_text().strip()
        if not custom_instructions:
            sys.exit(f"Instructions file is empty: {inst_path}")

    oracle_client = _build_oracle_client()
    results_by_split = {}

    for split in SPLITS:
        frames_dir = DATA_DIR / split / "frames"
        tasks_dir = DATA_DIR / split / "tasks"
        if not frames_dir.exists() or not tasks_dir.exists():
            continue

        video_dirs = sorted(p.name for p in frames_dir.iterdir() if p.is_dir())
        if not video_dirs:
            continue

        print(f"\n--- {split} ({len(video_dirs)} videos) ---", flush=True)
        all_scores, task_scores, video_results = [], {}, []

        for video_name in video_dirs:
            video_tasks_dir = tasks_dir / video_name
            task_descs = load_video_tasks(video_tasks_dir) if video_tasks_dir.is_dir() else []
            if not task_descs:
                continue

            frames = load_frames(frames_dir / video_name)
            print(
                f"[eval] split={split} video={video_name} tasks={len(task_descs)} frames={len(frames)}",
                flush=True,
            )
            ingestor, tasks = create_ingestor(
                task_descs, VIDEO_INGESTOR_MODEL,
                custom_instructions=custom_instructions,
            )
            task_map = {t.task_number: (name, desc) for t, (name, desc) in zip(tasks, task_descs)}

            per_frame = []
            for frame_index, result in enumerate(process_frames(ingestor, tasks, frames), start=1):
                if result["status"] == "error":
                    print(
                        f"[eval] split={split} video={video_name} frame={frame_index}/{len(frames)} "
                        f"status=error reason={result.get('error', 'unknown')}",
                        flush=True,
                    )
                    per_frame.append({"filename": result["filename"], "status": "error"})
                    continue

                _, buf = cv2.imencode(".jpg", result["frame"])
                batch_input = tuple(
                    (tname, tdesc, result["per_task_outputs"].get(tn, "(no output)"))
                    for tn, (tname, tdesc) in task_map.items()
                )
                try:
                    t0 = time.time()
                    scores_map = oracle_grade_batch(oracle_client, bytes(buf), batch_input)
                    oracle_grading_time_ms = round((time.time() - t0) * 1000)
                except Exception as e:
                    scores_map = {}
                    oracle_grading_time_ms = -1
                    print(
                        f"[eval] split={split} video={video_name} frame={frame_index}/{len(frames)} "
                        f"oracle_error={type(e).__name__}: {e}",
                        flush=True,
                    )

                frame_grades = {}
                for tname, _, vlm_out in batch_input:
                    score = scores_map.get(tname, -1)
                    if score >= 0:
                        all_scores.append(score)
                        task_scores.setdefault(tname, []).append(score)
                    frame_grades[tname] = {"vlm_output": vlm_out, "score": score}

                # print(
                #     f"[eval] split={split} video={video_name} frame={frame_index}/{len(frames)} "
                #     f"status={result['status']} vlm_ms={result['processing_time_ms']} "
                #     f"oracle_ms={oracle_grading_time_ms}",
                #     flush=True,
                # )

                per_frame.append({"filename": result["filename"], "status": result["status"], "per_task": frame_grades, "video_ingestor_processing_time_ms": result["processing_time_ms"], "oracle_grading_time_ms": oracle_grading_time_ms})

            video_results.append({
                "video": video_name,
                "tasks": [n for n, _ in task_descs],
                "total_frames": len(frames),
                "per_frame": per_frame,
            })

        overall = sum(all_scores) / len(all_scores) if all_scores else 0.0
        per_task_acc = {
            name: round(sum(s) / len(s), 4) if s else 0.0
            for name, s in sorted(task_scores.items())
        }
        results_by_split[split] = {
            "overall_accuracy": round(overall, 4),
            "total_graded": len(all_scores),
            "total_correct": sum(all_scores),
            "per_task_accuracy": per_task_acc,
            "per_video": video_results,
            "total_video_ingestor_processing_time_s": sum(f.get("video_ingestor_processing_time_ms", 0) for f in per_frame),
            "total_oracle_grading_time_s": sum(f.get("oracle_grading_time_ms", 0) for f in per_frame),
        }

    EVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EVAL_OUTPUT_DIR / f"eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    output = {
        "model": VIDEO_INGESTOR_MODEL,
        "oracle_model": ORACLE_MODEL,
        "instructions_file": args.instructions,
        "splits": results_by_split,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults JSON: {out_path}", flush=True)

    for split_name, split_data in results_by_split.items():
        acc = split_data["overall_accuracy"]
        graded = split_data["total_graded"]
        correct = split_data["total_correct"]
        ingestor_t = split_data.get("total_video_ingestor_processing_time_s", 0)
        oracle_t = split_data.get("total_oracle_grading_time_s", 0)
        print(f"\n[{split_name}] overall_accuracy={acc:.4f}  graded={graded}  correct={correct}"
              f"  ingestor_time_ms={ingestor_t}  oracle_time_ms={oracle_t}", flush=True)
        for task_name, task_acc in split_data.get("per_task_accuracy", {}).items():
            print(f"  {task_name}: {task_acc:.4f}", flush=True)

    return output


def main():
    parser = argparse.ArgumentParser(description="Eval VideoMemory video ingestor")
    parser.add_argument("--instructions", help="Path to instructions markdown file")
    run_eval(parser.parse_args())

if __name__ == "__main__":
    main()
