# prompt_hustle

Autonomous prompt engineering for VideoMemory video ingestor.

## Context

VideoMemory is a video monitoring system. A VLM analyses video frames and produces structured observations. The VLM prompt has two parts:

1. **Task XML** - injected per-task, same format as the real system (task_number, task_desc, task_newest_note).
2. **Universal instructions** - the instructions block that tells the VLM how to process any task. This is what you optimise.

The evaluation runs many different tasks (count people, detect luggage, describe clothing, etc.) across multiple videos. The overall metric is **overall_accuracy** (oracle-graded, 0/1 per frame) averaged across all tasks and videos. Higher is better.

**Your job**: craft universal instructions that work well across ALL tasks and videos, not just one.

## Setup

1. Agree on a run tag (e.g. codex_mar25_3pm). Branch prompt_hustle/tag must not already exist.
2. Create the branch.
3. Read in-scope files: program.md, instructions.md (only file you edit), data/train/tasks/<video name>/*.md (fixed test cases), eval/run.py (do not modify).
4. Verify data exists in data/train/frames/ and data/validation/frames/.
5. Initialize results/results.tsv and results/prompt_log.jsonl.

## What you CAN and CANNOT do

CAN: Modify prompt_hustle/instructions.md. This content replaces the instructions block in the VLM prompt.

CANNOT: Modify prompts/*.md, eval/run.py, or any VideoMemory source code.

## Running an evaluation

```
uv run python -m prompt_hustle.eval --instructions prompt_hustle/instructions.md > prompt_hustle/outputs/logs/run.log 2>&1
```

Extract metrics from outputs/logs/run.log:
- Use `overall_accuracy` as the optimization target (training metric only).
- Record `validation_overall_accuracy` for human tracking only (do not consider this at all. This is just for another agent).
- Do not use validation accuracy to decide keep/revert.

## Logging results

results/results.tsv: tab-separated with columns timestamp, commit, train_accuracy, validation_accuracy, graded, status, description.

results/prompt_log.jsonl: one JSON line per experiment with full instructions.md text as the prompt field.

## The experiment loop

LOOP FOREVER:

1. Edit prompt_hustle/instructions.md with a new idea.
2. Commit: git add prompt_hustle/instructions.md && git commit -m 'prompt: description'
3. Run eval (see above). Redirect to outputs/logs/run.log.
4. Read results from outputs/logs/run.log.
5. Log to results/results.tsv and results/prompt_log.jsonl, commit logs.
6. If training overall_accuracy improved, keep.
7. If equal or worse, revert: git checkout HEAD~2 -- prompt_hustle/instructions.md && git commit -m 'revert: description'

CRITICAL: Never use git reset --hard. All experiments must remain in results/results.tsv.

NEVER STOP: Run autonomously until manually interrupted.

## Strategies to try

The instructions must work across counting, detection, description, and scene understanding tasks:

- Add examples for description tasks (Describe X -> detailed notes)
- Add examples for detection tasks (Is there X? -> yes/no with details)
- Improve no-change logic (when to emit updates vs return empty)
- Add structured observation strategies
- Tune level of detail in task_note responses
- Handle 'nothing found' tasks properly
- Try chain-of-thought reasoning before JSON output
- Vary example diversity across task categories
- Combine improvements that helped individual categories
