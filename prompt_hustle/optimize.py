#!/usr/bin/env python3
"""Autonomous prompt optimization loop for VideoMemory instructions.

Runs N optimization steps, each time:
1. Generates a new instructions.md variant using Gemini
2. Commits, runs eval, logs results
3. Keeps improvements, reverts regressions
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types as genai_types

PROJ = Path(__file__).resolve().parent.parent
HUSTLE = PROJ / "prompt_hustle"
INSTRUCTIONS = HUSTLE / "instructions.md"
RESULTS_TSV = HUSTLE / "results.tsv"
PROMPT_LOG = HUSTLE / "prompt_log.jsonl"
LOGS_DIR = HUSTLE / "outputs" / "logs"

OPTIMIZER_MODEL = "gemini-2.5-flash"
NUM_STEPS = 10

EVAL_CMD = [
    sys.executable, "-u", "-m", "prompt_hustle.eval",
    "--instructions", str(INSTRUCTIONS),
    "--model", "qwen3-vl-8b",
    "--no-dedup",
]


def git(*args):
    r = subprocess.run(["git", "-C", str(PROJ)] + list(args),
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def run_eval():
    """Run the eval and parse overall_accuracy + per-task accuracies."""
    print("  Running eval (this takes ~8 min)...")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"run_{ts}.log"
    with open(log_path, "w") as log_f:
        subprocess.run(EVAL_CMD, stdout=log_f, stderr=subprocess.STDOUT, cwd=str(PROJ))
    output = log_path.read_text()
    print(f"  Log saved to {log_path.relative_to(PROJ)}")

    accuracy = None
    total_graded = None
    per_task = {}
    for line in output.splitlines():
        if line.startswith("overall_accuracy:"):
            accuracy = float(line.split(":")[1].strip())
        elif line.startswith("total_graded:"):
            total_graded = int(line.split(":")[1].strip())
        elif line.startswith("task_"):
            parts = line.split(":")
            per_task[parts[0].strip()] = float(parts[1].strip())

    if accuracy is None:
        print(f"  EVAL FAILED - could not parse accuracy")
        print(f"  Last 20 lines of output:")
        for line in output.splitlines()[-20:]:
            print(f"    {line}")
        return None, None, per_task

    return accuracy, total_graded, per_task


def log_result(commit, accuracy, graded, status, description, prompt_text):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(RESULTS_TSV, "a") as f:
        f.write(f"{ts}\t{commit}\t{accuracy:.4f}\t{graded}\t{status}\t{description}\n")
    entry = {"timestamp": ts, "commit": commit, "accuracy": accuracy, "prompt_text": prompt_text}
    with open(PROMPT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def generate_new_instructions(current_text, history, per_task_latest):
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    history_text = "\n".join(
        f"Step {i+1}: {h['description']} -> accuracy={h['accuracy']:.4f} ({'kept' if h['kept'] else 'reverted'})"
        for i, h in enumerate(history)
    )
    if not history_text:
        history_text = "(no previous experiments yet, this is the first optimization step)"

    per_task_text = "\n".join(f"  {k}: {v:.4f}" for k, v in sorted(per_task_latest.items()))
    if not per_task_text:
        per_task_text = "  (no per-task data yet)"

    prompt = f"""You are optimizing the instructions for a video ingestor VLM (Qwen3-VL-8B).
The instructions tell the VLM how to process video frames for various security/monitoring tasks.

Current instructions (this is the file content):
---
{current_text}
---

Previous experiments and their results:
{history_text}

Current per-task accuracies:
{per_task_text}

The overall accuracy is the average of all per-task scores. Your goal is to maximize it.

Focus on the WEAKEST tasks. Think about what specific instruction changes could help those tasks.
Consider:
- Adding more specific examples for weak task types (counting objects, detecting features, describing clothing, room identification)
- Improving clarity of output format instructions
- Adding guidance for edge cases (nothing visible, partial views, ambiguous scenes)
- Being more explicit about what constitutes a good task_note for different task types

IMPORTANT CONSTRAINTS:
- The output must be valid content for instructions.md
- Keep the <instructions> and </instructions> wrapper tags
- The VLM outputs JSON with task_updates array
- Don't make the instructions too long (the VLM has limited context)
- Keep what works, improve what doesn't

Return ONLY the new instructions.md content (including <instructions> tags), nothing else."""

    response = client.models.generate_content(
        model=OPTIMIZER_MODEL,
        contents=[genai_types.Part(text=prompt)],
        config=genai_types.GenerateContentConfig(temperature=0.8),
    )
    return response.text.strip()


def main():
    from dotenv import load_dotenv
    load_dotenv(HUSTLE / ".env")

    if not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("GOOGLE_API_KEY not set")
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("OPENROUTER_API_KEY not set")

    best_accuracy = 0.4848
    best_instructions = INSTRUCTIONS.read_text()
    history = []
    per_task_latest = {
        "task_count_chairs": 0.2333, "task_count_people": 0.6000,
        "task_count_tables": 0.3000, "task_describe_people_clothing": 0.7500,
        "task_detect_electronics": 0.3333, "task_doors_open_or_closed": 0.7000,
        "task_floor_obstructions": 0.4000, "task_identify_room_type": 0.5000,
        "task_items_on_surfaces": 0.5714,
    }

    print(f"Starting optimization: {NUM_STEPS} steps, baseline={best_accuracy:.4f}")
    print(f"=" * 60)

    for step in range(1, NUM_STEPS + 1):
        print(f"\n{'=' * 60}")
        print(f"STEP {step}/{NUM_STEPS}")
        print(f"{'=' * 60}")

        current_text = INSTRUCTIONS.read_text()
        print("  Generating new instructions with Gemini...")
        try:
            new_text = generate_new_instructions(current_text, history, per_task_latest)
        except Exception as e:
            print(f"  Generation failed: {e}")
            history.append({"description": "generation failed", "accuracy": 0.0, "kept": False})
            continue

        if not new_text or "<instructions>" not in new_text:
            print("  Generated text invalid (missing <instructions> tags), skipping")
            history.append({"description": "invalid generation", "accuracy": 0.0, "kept": False})
            continue

        desc = f"step{step}"
        first_diff_line = ""
        for old_line, new_line in zip(current_text.splitlines(), new_text.splitlines()):
            if old_line != new_line:
                first_diff_line = new_line[:60]
                break
        if first_diff_line:
            desc = f"step{step}: {first_diff_line}"

        INSTRUCTIONS.write_text(new_text)
        git("add", str(INSTRUCTIONS))
        git("commit", "-m", f"prompt: {desc[:72]}")
        commit = git("rev-parse", "--short", "HEAD").stdout.strip()

        accuracy, graded, per_task = run_eval()

        if accuracy is None:
            log_result(commit, 0.0, 0, "error", desc, new_text)
            git("add", str(RESULTS_TSV), str(PROMPT_LOG))
            git("commit", "-m", f"log: {desc[:50]} -> error")
            INSTRUCTIONS.write_text(best_instructions)
            git("add", str(INSTRUCTIONS))
            git("commit", "-m", f"revert: {desc[:50]} (eval error)")
            history.append({"description": desc, "accuracy": 0.0, "kept": False})
            continue

        graded = graded or 0
        per_task_latest = per_task if per_task else per_task_latest
        kept = accuracy > best_accuracy

        status = "kept" if kept else "reverted"
        log_result(commit, accuracy, graded, status, desc, new_text)
        git("add", str(RESULTS_TSV), str(PROMPT_LOG))
        git("commit", "-m", f"log: {desc[:50]} -> {accuracy:.4f}")

        if kept:
            print(f"  IMPROVED: {accuracy:.4f} > {best_accuracy:.4f} -> keeping")
            best_accuracy = accuracy
            best_instructions = new_text
        else:
            print(f"  NO IMPROVEMENT: {accuracy:.4f} <= {best_accuracy:.4f} -> reverting")
            INSTRUCTIONS.write_text(best_instructions)
            git("add", str(INSTRUCTIONS))
            git("commit", "-m", f"revert: {desc[:50]}")

        history.append({"description": desc, "accuracy": accuracy, "kept": kept})

        print(f"\n  Step {step} summary: accuracy={accuracy:.4f}, best={best_accuracy:.4f}, {status}")
        for k, v in sorted(per_task.items()):
            print(f"    {k}: {v:.4f}")

    print(f"\n{'=' * 60}")
    print("OPTIMIZATION COMPLETE")
    print(f"{'=' * 60}")
    print(f"Best accuracy: {best_accuracy:.4f}")
    print(f"\nAll experiments:")
    for i, h in enumerate(history):
        print(f"  Step {i+1}: {h['description'][:60]} -> {h['accuracy']:.4f} ({'kept' if h['kept'] else 'reverted'})")


if __name__ == "__main__":
    main()
