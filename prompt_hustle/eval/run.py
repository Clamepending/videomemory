#!/usr/bin/env python3
"""Evaluate VideoMemory's video ingestor against an oracle model.

Runs the video ingestor on every video folder in a data split (train or
validation), then asks an oracle model to grade each (frame, prompt, output)
tuple on a binary rubric (0 = incorrect, 1 = correct).  Reports per-video
and overall accuracy.

Usage (from project root):
    uv run python -m prompt_hustle.eval --prompt-file prompt_hustle/prompts/count_people.md
    uv run python -m prompt_hustle.eval --prompt-file prompt_hustle/prompts/count_people.md --eval
    uv run python -m prompt_hustle.eval --prompt-file prompt_hustle/prompts/count_people.md --eval --model gemini-2.5-flash --no-dedup
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


# ---------------------------------------------------------------------------
# Oracle grading
# ---------------------------------------------------------------------------

class GradingResult(BaseModel):
    reasoning: str = Field(..., description="Brief reasoning for the grade")
    score: int = Field(..., ge=0, le=1, description="0 for incorrect, 1 for correct")


def _build_oracle_client():
    from google import genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY must be set for oracle grading. "
            "Export it or set it via the VideoMemory settings API."
        )
    return genai.Client(api_key=api_key)


def oracle_grade(client, image_bytes: bytes, task_description: str, vlm_output: str) -> GradingResult:
    """Ask the oracle to grade a single VLM output against the image."""
    from google.genai import types as genai_types

    grading_prompt = (
        "You are an evaluator grading a vision-language model's output.\n\n"
        f"Task given to the model:\n{task_description}\n\n"
        f"Model's output:\n{vlm_output}\n\n"
        "Look at the attached image and evaluate whether the model's output "
        "is factually correct with respect to what is visible in the image "
        "and relevant to the task.\n\n"
        "Rubric:\n"
        "  1 - The output accurately describes what is in the image relative to the task.\n"
        "  0 - The output is incorrect or significantly misrepresents the image content.\n\n"
        "Return JSON with 'reasoning' (one sentence) and 'score' (0 or 1)."
    )

    image_part = genai_types.Part(
        inline_data=genai_types.Blob(data=image_bytes, mime_type="image/jpeg")
    )
    response = client.models.generate_content(
        model=ORACLE_MODEL,
        contents=[image_part, genai_types.Part(text=grading_prompt)],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=GradingResult.model_json_schema(),
        ),
    )
    raw = getattr(response, "text", None)
    if not raw:
        raise RuntimeError("Oracle model returned empty response.")
    return GradingResult.model_validate_json(raw)


# ---------------------------------------------------------------------------
# Per-video evaluation
# ---------------------------------------------------------------------------

def evaluate_video(video_name, frames_dir, task_desc, model_name, skip_dedup, oracle_client):
    print(f"\n{'=' * 60}")
    print(f"VIDEO: {video_name}")
    print(f"{'=' * 60}")

    frames = load_frames(frames_dir / video_name)
    print(f"  Loaded {len(frames)} frames")

    ingestor, task = create_ingestor(task_desc, model_name, skip_dedup)

    per_frame: list[dict] = []
    scores: list[int] = []
    vlm_errors = 0
    oracle_errors = 0

    for r in process_frames(ingestor, task, frames):
        filename = r["filename"]
        label = f"  [{r['index'] + 1}/{r['total']}] {filename}"

        if r["status"] == "error":
            per_frame.append({"filename": filename, "status": "error", "error": r["error"]})
            vlm_errors += 1
            print(f"{label}  VLM error ({r['error']})")
            continue

        if r["status"] == "skipped":
            per_frame.append({"filename": filename, "status": "skipped"})
            print(f"{label}  skipped (dup)")
            continue

        vlm_output_text = r["vlm_output"]
        produced_update = r["produced_update"]

        _, buf = cv2.imencode(".jpg", r["frame"])
        try:
            grade = oracle_grade(oracle_client, bytes(buf), task_desc, vlm_output_text)
            score, reasoning = grade.score, grade.reasoning
        except Exception as e:
            print(f"{label}  oracle error: {e}")
            score, reasoning = -1, f"oracle_error: {e}"
            oracle_errors += 1

        if score >= 0:
            scores.append(score)

        tag = "" if produced_update else " (carried)"
        print(f'{label}  vlm="{vlm_output_text[:60]}"{tag}  score={score}')

        per_frame.append({
            "filename": filename, "status": "graded",
            "vlm_output": vlm_output_text, "produced_update": produced_update,
            "oracle_score": score, "oracle_reasoning": reasoning,
        })

    accuracy = sum(scores) / len(scores) if scores else 0.0
    skipped = sum(1 for f in per_frame if f.get("status") == "skipped")
    print(f"  => {video_name} accuracy: {accuracy:.2%} ({sum(scores)}/{len(scores)} graded)")
    if vlm_errors or oracle_errors or skipped:
        print(f"     dropped: {vlm_errors} vlm err, {oracle_errors} oracle err, {skipped} skipped")

    return {
        "video": video_name, "total_frames": len(frames),
        "graded": len(scores), "correct": sum(scores),
        "vlm_errors": vlm_errors, "oracle_errors": oracle_errors,
        "skipped": skipped, "accuracy": round(accuracy, 4),
        "per_frame": per_frame,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_eval(args):
    prompt_path = Path(args.prompt_file)
    if not prompt_path.exists():
        sys.exit(f"Prompt file not found: {prompt_path}")
    task_desc = prompt_path.read_text().strip()
    if not task_desc:
        sys.exit(f"Prompt file is empty: {prompt_path}")

    split = "validation" if args.eval else "train"
    frames_dir = DATA_DIR / split / "frames"
    if not frames_dir.exists():
        sys.exit(f"Frames directory not found: {frames_dir}")

    video_dirs = sorted(p.name for p in frames_dir.iterdir() if p.is_dir())
    if not video_dirs:
        sys.exit(f"No video folders found in {frames_dir}")

    print(f"Split:       {split}")
    print(f"Prompt file: {prompt_path}")
    print(f"Task:        {task_desc[:80]}")
    print(f"Videos:      {video_dirs}")
    print(f"Model:       {args.model or '(default)'}")
    print(f"Oracle:      {ORACLE_MODEL}")
    print(f"Dedup:       {'off' if args.no_dedup else 'on'}")

    oracle_client = _build_oracle_client()
    results: list[dict] = []
    all_scores: list[int] = []

    for video_name in video_dirs:
        vr = evaluate_video(video_name, frames_dir, task_desc, args.model, args.no_dedup, oracle_client)
        results.append(vr)
        all_scores.extend(
            f["oracle_score"] for f in vr["per_frame"] if f.get("oracle_score", -1) >= 0
        )

    overall = sum(all_scores) / len(all_scores) if all_scores else 0.0
    total_frames = sum(r["total_frames"] for r in results)
    total_dropped = sum(r["vlm_errors"] + r["oracle_errors"] + r["skipped"] for r in results)

    EVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_task = task_desc.replace(" ", "_")[:30]
    out_path = EVAL_OUTPUT_DIR / f"eval_{split}_{safe_task}_{ts}.json"

    output = {
        "split": split, "task_description": task_desc,
        "prompt_file": str(prompt_path),
        "model": args.model or "(default)", "oracle_model": ORACLE_MODEL,
        "dedup": not args.no_dedup,
        "overall_accuracy": round(overall, 4),
        "total_frames": total_frames, "total_graded": len(all_scores),
        "total_correct": sum(all_scores), "total_dropped": total_dropped,
        "per_video": results,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'=' * 60}")
    print("EVAL SUMMARY")
    print(f"{'=' * 60}")
    for r in results:
        print(f"  {r['video']:20s}  {r['accuracy']:.2%}  ({r['correct']}/{r['graded']})")
    print(f"  {'OVERALL':20s}  {overall:.2%}  ({sum(all_scores)}/{len(all_scores)})")
    if total_dropped:
        print(f"  WARNING: {total_dropped}/{total_frames} frames not graded")
    print(f"{'=' * 60}")
    print(f"Results saved to {out_path}")

    print(f"\n---")
    print(f"overall_accuracy: {overall:.6f}")
    print(f"total_graded:     {len(all_scores)}")
    print(f"total_correct:    {sum(all_scores)}")
    print(f"total_frames:     {total_frames}")
    print(f"dropped_frames:   {total_dropped}")

    return overall


def main():
    parser = argparse.ArgumentParser(description="Evaluate VideoMemory video ingestor with oracle grading")
    parser.add_argument("--prompt-file", required=True, help="Path to the task description markdown file")
    parser.add_argument("--eval", action="store_true", help="Use the validation split instead of train")
    parser.add_argument("--model", default=None, help="Model name for the video ingestor")
    parser.add_argument("--no-dedup", action="store_true", help="Disable frame deduplication")
    args = parser.parse_args()
    run_eval(args)


if __name__ == "__main__":
    main()
